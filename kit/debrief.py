"""Debrief: a proposal swarm that learns from losing.

Run from the root of a specialist-swarm checkout, after setup_environment.py,
create_specialists.py and upload_skills.py.

    python debrief.py setup [--solo]                 # coordinator + memory store
    python debrief.py calibrate --buyer acme         # bad must lose, good must win
    python debrief.py round --rfp acme --buyer acme --label acme-cold --learn
    python debrief.py round --rfp vandelay --buyer vandelay --label vandelay-cold
    python debrief.py round --rfp vandelay --buyer vandelay --label vandelay-warm --use-memory
    python debrief.py score                          # scoreboard + leak check
    python debrief.py lessons                        # what the swarm remembered
    python debrief.py collect                        # platform cost/usage per agent into verdicts
    python debrief.py manifest                       # outputs/deployment.json: agents, models, Skills
    python debrief.py report                         # outputs/report.html, the proof screen
    python debrief.py serve                          # http://127.0.0.1:8765/war-room.html (live/replay)

Add --backend local to round/lessons/score if the memory store isn't available.
The API key is read from ANTHROPIC_API_KEY only.
"""

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from anthropic import Anthropic

BETA = "managed-agents-2026-04-01"
COORDINATOR_MODEL = os.environ.get("COORDINATOR_MODEL", "claude-opus-5-5")
BUYER_MODEL = os.environ.get("BUYER_MODEL", "claude-sonnet-5-5")  # never the coordinator's model
SPECIALIST_WORDS = os.environ.get("SPECIALIST_WORDS", "300")
WIN_AT = 4  # criteria passed (of 5) to win

OUT = Path("outputs")
RFPS = {"acme": "synthetic-data/rfp-acme-corp.md", "vandelay": "synthetic-data/rfp-vandelay.md"}
SUPPORTING = ["synthetic-data/past-wins.json", "synthetic-data/product-overview.md"]
START, END = "=== PROPOSAL START ===", "=== PROPOSAL END ==="


def need(path: str) -> str:
    p = Path(path)
    if not p.exists():
        sys.exit(f"Missing {path}. Follow README.md in order.")
    return p.read_text().strip()


def client() -> Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY first: put it in build/.env, then run `source env.sh` (README step 3).")
    if os.environ.get("ANTHROPIC_BASE_URL"):
        print("WARNING: ANTHROPIC_BASE_URL is set, so calls go to a gateway, not the workspace API. "
              "Run `unset ANTHROPIC_BASE_URL` for Managed Agents.", file=sys.stderr)
    return Anthropic()


# --------------------------------------------------------------------------- setup

def cmd_setup(args) -> None:
    c = client()
    ma = Anthropic(default_headers={"anthropic-beta": BETA})
    specialist_ids = json.loads(need(".specialist_ids.json"))
    need(".environment_id")

    kwargs = dict(
        name="Debrief Coordinator",
        model=COORDINATOR_MODEL,
        system=need("coordinator_system.md"),
        tools=[{"type": "agent_toolset_20260401"}],
        metadata={"hackathon": "partner-basecamp-2026", "project": "debrief"},
    )
    if not args.solo:
        kwargs["multiagent"] = {
            "type": "coordinator",
            "agents": [{"type": "agent", "id": i} for i in specialist_ids.values()],
        }
    coordinator = ma.beta.agents.create(**kwargs)
    Path(".coordinator_id").write_text(coordinator.id)
    print(f"Coordinator ({'solo' if args.solo else 'swarm'}, {COORDINATOR_MODEL}): {coordinator.id}")

    if Path(".memory_store_id").exists():
        print(f"Memory store reused: {need('.memory_store_id')}")
    else:
        store = c.beta.memory_stores.create(
            name="Debrief lessons",
            description="General lessons from lost and won proposals. No customer names or deal figures.",
        )
        Path(".memory_store_id").write_text(store.id)
        print(f"Memory store: {store.id}")
    print("Next: python debrief.py calibrate --buyer acme")


# --------------------------------------------------------------------------- buyer judge

VERDICT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["PASS", "FAIL"]},
            "reason": {"type": "string", "description": "One sentence, quoting the proposal where possible."},
        },
        "required": ["verdict", "reason"],
        "additionalProperties": False,
    },
}


def judge_one(c: Anthropic, buyer: dict, crit: dict, proposal: str) -> dict:
    response = c.messages.create(
        model=BUYER_MODEL,
        max_tokens=1024,
        system=(
            f"{buyer['persona']}\n\nYou are scoring ONE vendor proposal against ONE of your private "
            "evaluation criteria. Judge only that criterion, not overall quality. "
            "If the criterion is only partly met, the verdict is FAIL."
        ),
        messages=[{
            "role": "user",
            "content": f"<proposal>\n{proposal}\n</proposal>\n\n<criterion>\n{crit['test']}\n</criterion>\n\n"
                       "Does the proposal meet this criterion?",
        }],
        output_config={"format": VERDICT_SCHEMA},
    )
    texts = [b.text for b in response.content if b.type == "text"]
    if response.stop_reason != "end_turn" or not texts:  # grader error, not a lost criterion
        raise RuntimeError(f"buyer judge returned no verdict (stop_reason={response.stop_reason})")
    data = json.loads(texts[0])
    return {"id": crit["id"], "name": crit["name"], **data}


def judge(c: Anthropic, buyer_key: str, proposal: str) -> dict:
    buyer = json.loads(need(f"buyers/{buyer_key}.json"))
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda cr: judge_one(c, buyer, cr, proposal), buyer["criteria"]))
    passed = sum(r["verdict"] == "PASS" for r in results)
    return {"buyer": buyer_key, "passed": passed, "total": len(results),
            "won": passed >= WIN_AT, "criteria": results}


def print_verdict(v: dict, label: str) -> None:
    status = "WON " if v["won"] else "LOST"
    print(f"\n  BUYER VERDICT [{label}]: {status} {v['passed']}/{v['total']}")
    for r in v["criteria"]:
        mark = "✓" if r["verdict"] == "PASS" else "✗"
        print(f"   {mark} {r['name']:<22} {r['reason']}")


def cmd_calibrate(args) -> None:
    c = client()
    ok = True
    record = {"buyer": args.buyer, "model": BUYER_MODEL, "runs": []}
    for kind, should_win in (("bad", False), ("good", True)):
        proposal = need(f"calibration/{args.buyer}-{kind}.md")
        outcomes = []
        for attempt in (1, 2):
            v = judge(c, args.buyer, proposal)
            print_verdict(v, f"{kind} proposal, try {attempt}")
            outcomes.append((v["won"], v["passed"]))
            record["runs"].append({"kind": kind, "try": attempt, "won": v["won"], "passed": v["passed"]})
        stable = outcomes[0] == outcomes[1]
        right = all(won == should_win for won, _ in outcomes)
        print(f"  -> {kind}: {'OK' if right and stable else 'PROBLEM'} (expected {'WIN' if should_win else 'LOSS'}, stable={stable})")
        ok &= right and stable
    record["passed"] = ok
    OUT.mkdir(exist_ok=True)
    (OUT / f"calibration-{args.buyer}.json").write_text(json.dumps(record, indent=2))
    print("\nCALIBRATION " + ("PASSED: the buyer can be trusted." if ok else "FAILED: fix buyers/*.json before bidding."))
    sys.exit(0 if ok else 1)


# --------------------------------------------------------------------------- sessions

def stream_session(c: Anthropic, session_id: str, text: str, quiet: bool = False,
                   live_path: Path | None = None, live_meta: dict | None = None) -> tuple[str, list]:
    """Send one user message and stream until the session goes idle.

    Returns the agent's text and a trace of timed events ({t, kind, agent}) for the report's
    fan-out timeline.
    """
    parts: list[str] = []
    trace: list[dict] = []
    t0 = time.time()

    def mark(kind: str, agent: str, label: str) -> None:
        t = round(time.time() - t0, 1)
        trace.append({"t": t, "kind": kind, "agent": agent})
        print(f"  {t:>6.1f}s  [{label}] {agent}", flush=True)
        if live_path:  # the war room polls this file in live mode
            live_path.write_text(json.dumps({**(live_meta or {}), "status": "done" if kind == "done" else "running",
                                             "session_id": session_id, "trace": trace}))

    with c.beta.sessions.events.stream(session_id) as stream:
        c.beta.sessions.events.send(
            session_id,
            events=[{"type": "user.message", "content": [{"type": "text", "text": text}]}],
        )
        for event in stream:
            t = event.type
            if t == "session.thread_created":
                mark("spawned", getattr(event, "agent_name", "?"), "thread spawned")
            elif t == "agent.thread_message_sent":
                mark("delegated", getattr(event, "to_agent_name", "?"), "delegate →   ")
            elif t == "agent.thread_message_received":
                mark("replied", getattr(event, "from_agent_name", "?"), "reply ←      ")
            elif t == "agent.tool_use":
                inp = getattr(event, "input", {}) or {}
                target = str(inp.get("path") or inp.get("file_path") or inp.get("command") or "")
                if "/mnt/memory" in target:
                    mark("memory", target[:60], "memory read  ")
                else:
                    print(f"  [tool: {getattr(event, 'name', '?')}]", flush=True)
            elif t == "agent.message":
                for block in event.content:
                    if getattr(block, "type", None) == "text":
                        parts.append(block.text)
                        if not quiet:
                            print(block.text, end="", flush=True)
            elif t == "session.status_idle":
                mark("done", "Coordinator", "finished     ")
                break
    return "".join(parts), trace


def memory_resource(instructions: str) -> list:
    return [{
        "type": "memory_store",
        "memory_store_id": need(".memory_store_id"),
        "access": "read_write",
        "instructions": instructions,
    }]


def extract_proposal(text: str) -> str:
    m = re.search(re.escape(START) + r"(.*?)" + re.escape(END), text, re.S)
    return (m.group(1) if m else text).strip()


def read_lessons(c: Anthropic, backend: str) -> str:
    if backend == "local":
        p = OUT / "lessons.md"
        return p.read_text() if p.exists() else ""
    store_id = need(".memory_store_id")
    chunks = []
    for item in sorted(c.beta.memory_stores.memories.list(store_id, path_prefix="/").data, key=lambda i: i.path):
        if item.type == "memory":
            got = c.beta.memory_stores.memories.retrieve(item.id, memory_store_id=store_id)
            chunks.append(f"--- {item.path}\n{got.content or ''}")
    return "\n".join(chunks)


def cmd_round(args) -> None:
    c = client()
    OUT.mkdir(exist_ok=True)
    coordinator_id, environment_id = need(".coordinator_id"), need(".environment_id")
    rfp_path = RFPS.get(args.rfp, args.rfp)

    docs = "\n\n".join(f"=====  DOCUMENT: {Path(p).name}  =====\n{need(p)}" for p in [rfp_path, *SUPPORTING])
    lessons_note = ""
    resources = []
    if args.use_memory:
        if args.backend == "store":
            resources = memory_resource("Lessons from past bids. Read them before delegating. Do not modify them in a bid.")
            lessons_note = "Lessons from past bids are in /mnt/memory/. Read them first and apply them.\n\n"
        else:
            lessons_note = f"LESSONS FROM PAST BIDS (apply them):\n{read_lessons(c, 'local')}\n\n"

    message = (
        f"{lessons_note}An RFP has just landed. Run the Deal Desk process: read the RFP, delegate to all "
        f"specialists in parallel in a single message (each answers in ~{SPECIALIST_WORDS} words), synthesise, "
        f"and output the full proposal as markdown between the lines {START} and {END}.\n\n{docs}"
    )

    session = c.beta.sessions.create(agent=coordinator_id, environment_id=environment_id,
                                     title=f"Debrief bid: {args.label}", resources=resources)
    print(f"Bid {args.label}: session {session.id}  (memory: {'on' if args.use_memory else 'off'})\n")
    live = OUT / f"{args.label}.live.json"
    live.write_text(json.dumps({"status": "running", "session_id": session.id, "memory": bool(args.use_memory),
                                "trace": []}))
    t0 = time.time()
    text, trace = stream_session(c, session.id, message, quiet=args.quiet, live_path=live,
                                 live_meta={"memory": bool(args.use_memory)})
    seconds = round(time.time() - t0)
    proposal = extract_proposal(text)
    (OUT / f"{args.label}.md").write_text(proposal)
    print(f"\n\n  proposal saved: outputs/{args.label}.md  ({len(proposal.split())} words, {seconds}s)")

    verdict = judge(c, args.buyer, proposal)
    verdict.update(label=args.label, rfp=args.rfp, memory=bool(args.use_memory), seconds=seconds,
                   words=len(proposal.split()), session_id=session.id, trace=trace)
    verdict.update(collect_usage(c, session.id))
    (OUT / f"{args.label}.verdict.json").write_text(json.dumps(verdict, indent=2))
    print_verdict(verdict, args.label)

    if args.learn:
        debrief(c, verdict, args.backend, environment_id, coordinator_id)


# --------------------------------------------------------------------------- platform evidence

def _usage_dict(u) -> dict:
    if u is None:
        return {}
    cc = getattr(u, "cache_creation", None)
    cost = getattr(u, "list_cost", None)
    return {
        "cost": int(cost.amount) / 100 if cost is not None else None,  # amount is in minor units (cents)
        "currency": str(getattr(cost, "currency", "")) if cost is not None else "",
        "input_tokens": getattr(u, "input_tokens", None) or 0,
        "output_tokens": getattr(u, "output_tokens", None) or 0,
        "cache_read_tokens": getattr(u, "cache_read_input_tokens", None) or 0,
        "cache_write_tokens": ((getattr(cc, "ephemeral_5m_input_tokens", 0) or 0) +
                               (getattr(cc, "ephemeral_1h_input_tokens", 0) or 0)) if cc else 0,
        "active_seconds": getattr(u, "active_seconds", None),
    }


def _skill_names() -> dict:
    p = Path(".skill_ids.json")
    return {v: k for k, v in json.loads(p.read_text()).items()} if p.exists() else {}


def collect_usage(c: Anthropic, session_id: str) -> dict:
    """Session + per-thread usage from the platform: real list cost, model and Skills per agent."""
    try:
        s = c.beta.sessions.retrieve(session_id)
        names = _skill_names()
        threads = []
        for t in c.beta.sessions.threads.list(session_id=session_id):
            a = t.agent
            model = getattr(getattr(a, "model", None), "id", None) or getattr(a, "model", None)
            skills = [names.get(getattr(k, "skill_id", ""), getattr(k, "skill_id", "")) for k in (getattr(a, "skills", None) or [])]
            threads.append({"agent": getattr(a, "name", "?"), "model": str(model), "skills": skills,
                            "parent": t.parent_thread_id, **_usage_dict(t.usage)})
        return {"usage": _usage_dict(s.usage), "threads": threads}
    except Exception as e:  # evidence is a bonus; never lose a bid over it
        print(f"  (usage not collected: {type(e).__name__}: {e})", file=sys.stderr)
        return {}


def cmd_collect(args) -> None:
    c = client()
    for p in sorted(OUT.glob("*.verdict.json")):
        v = json.loads(p.read_text())
        if args.label and v["label"] != args.label:
            continue
        v.update(collect_usage(c, v["session_id"]))
        p.write_text(json.dumps(v, indent=2))
        u = v.get("usage", {})
        print(f"{v['label']:<16} ${u.get('cost') or 0:.2f}  threads={len(v.get('threads', []))}  "
              f"cache_read={u.get('cache_read_tokens', 0):,}")


def cmd_manifest(args) -> None:
    """What is deployed on Claude Platform: agents, models, Skills, memory store. For the war room."""
    c = client()
    ma = Anthropic(default_headers={"anthropic-beta": BETA})
    names = _skill_names()

    def agent_info(agent_id: str) -> dict:
        a = ma.beta.agents.retrieve(agent_id)
        model = getattr(getattr(a, "model", None), "id", None) or getattr(a, "model", None)
        return {"id": a.id, "name": a.name, "model": str(model), "version": a.version,
                "skills": [names.get(getattr(k, "skill_id", ""), getattr(k, "skill_id", "")) for k in (a.skills or [])]}

    specialists = json.loads(need(".specialist_ids.json"))
    manifest = {
        "coordinator": agent_info(need(".coordinator_id")),
        "specialists": [agent_info(i) for i in specialists.values()],
        "memory_store_id": need(".memory_store_id"),
        "environment_id": need(".environment_id"),
        "buyer_model": BUYER_MODEL,
    }
    OUT.mkdir(exist_ok=True)
    (OUT / "deployment.json").write_text(json.dumps(manifest, indent=2))
    for a in [manifest["coordinator"], *manifest["specialists"]]:
        print(f"  {a['name']:<28} {a['model']:<26} skills={a['skills'] or '-'}")
    print(f"  memory store {manifest['memory_store_id']} · buyer {BUYER_MODEL}\nWrote outputs/deployment.json")


def cmd_serve(args) -> None:
    """Serve outputs/ on localhost so the war room can read the run files."""
    import http.server
    import shutil
    import socketserver
    OUT.mkdir(exist_ok=True)
    shutil.copy("war-room.html", OUT / "war-room.html")
    os.chdir(OUT)
    base = f"http://127.0.0.1:{args.port}"
    print(f"War room (replay):  {base}/war-room.html?bid=vandelay-warm&speed=15\n"
          f"War room (live):    {base}/war-room.html?live=<label>\n"
          f"Report:             {base}/report.html\nCtrl-C to stop.")
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=".", **k)
    with socketserver.TCPServer(("127.0.0.1", args.port), handler) as httpd:
        httpd.serve_forever()


DEBRIEF_RULES = (
    "Write at most 6 lessons as general rules that would improve a proposal to ANY future customer. "
    "Never include customer names, prices, percentages or dates from this deal. "
    "Merge with lessons already there instead of duplicating them."
)


def debrief(c: Anthropic, verdict: dict, backend: str, environment_id: str, coordinator_id: str) -> None:
    findings = "\n".join(f"- {r['verdict']}: {r['name']}: {r['reason']}" for r in verdict["criteria"])
    print("\n=== DEBRIEF: writing lessons ===")
    if backend == "local":
        existing = read_lessons(c, "local")
        r = c.messages.create(
            model=COORDINATOR_MODEL, max_tokens=2048,
            messages=[{"role": "user", "content":
                       f"Existing lessons:\n{existing or '(none)'}\n\nBuyer debrief on our last proposal:\n{findings}\n\n"
                       f"{DEBRIEF_RULES} Output only the updated lessons as a markdown list."}],
        )
        (OUT / "lessons.md").write_text("".join(b.text for b in r.content if b.type == "text"))
    else:
        session = c.beta.sessions.create(
            agent=coordinator_id, environment_id=environment_id, title=f"Debrief: {verdict['label']}",
            resources=memory_resource("Your lessons from past bids. Keep them general and current."),
        )
        _, _trace = stream_session(c, session.id, (
            "DEBRIEF MODE. Do not delegate to any specialist. The buyer scored our last proposal:\n"
            f"Result: {'WON' if verdict['won'] else 'LOST'} {verdict['passed']}/{verdict['total']}\n{findings}\n\n"
            f"Update /mnt/memory/lessons.md. {DEBRIEF_RULES} Then print the final file."
        ))
    lessons = read_lessons(c, backend)
    (OUT / "lessons-snapshot.md").write_text(lessons)  # lets `report` run offline
    print("\n\n=== LESSONS NOW IN MEMORY ===\n" + lessons)


# --------------------------------------------------------------------------- score

def leak_check(lessons: str) -> list[str]:
    hits = []
    for name in ("acme", "vandelay", "teradata", "exadata"):
        if name in lessons.lower():
            hits.append(name)
    hits += re.findall(r"[$€]\s?\d[\d,.]*\s?[kKmM]?", lessons)
    return hits


def cmd_score(args) -> None:
    rows = [json.loads(p.read_text()) for p in sorted(OUT.glob("*.verdict.json"))]
    if not rows:
        sys.exit("No verdicts yet. Run a round first.")
    names = [r["name"] for r in rows[-1]["criteria"]]  # legend from the last (test) buyer
    print(f"\n{'bid':<16}{'memory':<8}{'result':<12}" + "".join(f"{i + 1:<4}" for i in range(len(names))) + "time")
    for v in rows:
        marks = "".join(f"{'✓' if r['verdict'] == 'PASS' else '✗':<4}" for r in v["criteria"])
        result = f"{'WON' if v['won'] else 'LOST'} {v['passed']}/{v['total']}"
        print(f"{v['label']:<16}{'on' if v.get('memory') else 'off':<8}{result:<12}{marks}{v.get('seconds', '?')}s")
    print("\ncriteria (per buyer file): " + " · ".join(f"{i + 1}={n}" for i, n in enumerate(names)))

    cold = next((v for v in rows if v["label"] == "vandelay-cold"), None)
    warm = next((v for v in rows if v["label"] == "vandelay-warm"), None)
    if cold and warm:
        print(f"\nUNSEEN CUSTOMER: cold {cold['passed']}/5 -> warm {warm['passed']}/5 "
              f"({warm['passed'] - cold['passed']:+d})")
        ctl_c, ctl_w = cold["criteria"][-1]["verdict"], warm["criteria"][-1]["verdict"]
        print(f"CONTROL (criterion 5, not taught): cold {ctl_c} / warm {ctl_w} "
              f"-> {'flat, as expected' if ctl_c == ctl_w else 'moved: report it'}")
    try:
        hits = leak_check(read_lessons(None if args.backend == "local" else client(), args.backend))
        print(f"LEAK CHECK on lessons: {'PASS (general lessons only)' if not hits else 'FAIL ' + str(hits)}")
    except SystemExit:
        print("LEAK CHECK skipped (no key or memory store).")


def cmd_lessons(args) -> None:
    print(read_lessons(None if args.backend == "local" else client(), args.backend) or "(no lessons yet)")


# --------------------------------------------------------------------------- report (the demo screen)

REPORT_CSS = """
*{box-sizing:border-box}body{margin:0;font:17px/1.45 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;
color:#1d1d1f;background:#f6f5f2}main{max-width:1180px;margin:0 auto;padding:28px 32px 60px}
h1{font-size:44px;margin:0;letter-spacing:-.02em}.tag{color:#6b6b6b;font-size:20px;margin:2px 0 18px}
h2{font-size:22px;margin:34px 0 12px}.banner{background:#fff3cd;border:1px solid #e0c060;padding:8px 14px;
border-radius:8px;font-weight:600;margin-bottom:14px}.cards{display:grid;grid-template-columns:1fr 40px 1fr 40px 1fr;
align-items:stretch}.arrow{display:flex;align-items:center;justify-content:center;font-size:28px;color:#999}
.card{background:#fff;border-radius:14px;padding:18px 20px;border:2px solid #e6e3dc}.card .k{font-size:13px;
text-transform:uppercase;letter-spacing:.06em;color:#777}.card .who{font-size:21px;font-weight:650;margin:2px 0 10px}
.res{font-size:46px;font-weight:800;line-height:1}.res small{font-size:24px;font-weight:600;color:#555}
.won{border-color:#1f8a4c}.won .res{color:#1f8a4c}.lost .res{color:#c0392b}.meta{color:#666;font-size:14px;margin-top:8px}
.delta{margin:16px 0 0;font-size:22px;font-weight:650}.delta b{color:#1f8a4c}
table{border-collapse:collapse;width:100%;background:#fff;border-radius:12px;overflow:hidden}
th,td{padding:10px 14px;border-bottom:1px solid #eee;text-align:left}th{background:#faf9f6;font-size:14px;color:#555}
td.c{text-align:center;font-size:22px;font-weight:700}.p{color:#1f8a4c}.f{color:#c0392b}.na{color:#bbb}
tr.ctl td{background:#f3f1ff}.pill{display:inline-block;font-size:12px;padding:2px 8px;border-radius:99px;
background:#e9e6ff;color:#4b3fb3;margin-left:6px;font-weight:600}.two{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.box{background:#fff;border-radius:12px;padding:16px 20px;border:1px solid #e6e3dc}.box ul{margin:6px 0 0;padding-left:20px}
.ok{color:#1f8a4c;font-weight:700}.bad{color:#c0392b;font-weight:700}.why{display:grid;grid-template-columns:200px 1fr 1fr;
gap:0;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #e6e3dc}.why div{padding:10px 14px;
border-bottom:1px solid #eee;font-size:15px}.why .h{background:#faf9f6;font-weight:650;font-size:14px;color:#555}
.why .cold{color:#8a2a1f}.why .warm{color:#14663a}.lane{display:grid;grid-template-columns:190px 1fr 60px;align-items:center;
gap:10px;margin:5px 0;font-size:14px}.track{position:relative;height:18px;background:#efede8;border-radius:5px}
.bar{position:absolute;top:0;height:18px;border-radius:5px;background:#5b7cfa}.bar.coord{background:#2d2d2d}
.tick{position:absolute;top:-3px;width:4px;height:24px;background:#e67e22;border-radius:2px}.small{color:#777;font-size:13px}
a{color:#3b5bdb}
"""


def _lanes(trace: list, seconds: float) -> str:
    """Swimlanes: one bar per specialist (delegated → replied), coordinator end to end, memory reads as ticks."""
    import html
    total = max([seconds or 0] + [e["t"] for e in trace]) or 1
    pct = lambda t: f"{100 * t / total:.2f}%"
    rows = []
    done = next((e["t"] for e in trace if e["kind"] == "done"), total)
    ticks = "".join(f'<span class="tick" style="left:{pct(e["t"])}" title="memory read"></span>'
                    for e in trace if e["kind"] == "memory")
    rows.append(f'<div class="lane"><div><b>Coordinator</b></div><div class="track">'
                f'<span class="bar coord" style="left:0;width:{pct(done)}"></span>{ticks}</div>'
                f'<div class="small">{done:.0f}s</div></div>')
    agents = []
    for e in trace:
        if e["kind"] in ("spawned", "delegated") and e["agent"] not in agents and e["agent"] != "Coordinator":
            agents.append(e["agent"])
    for a in agents:
        start = min(e["t"] for e in trace if e["agent"] == a and e["kind"] in ("spawned", "delegated"))
        end = next((e["t"] for e in trace if e["agent"] == a and e["kind"] == "replied" and e["t"] >= start), done)
        rows.append(f'<div class="lane"><div>{html.escape(a)}</div><div class="track"><span class="bar" '
                    f'style="left:{pct(start)};width:{pct(max(end - start, total * 0.01))}"></span></div>'
                    f'<div class="small">{end - start:.0f}s</div></div>')
    return "".join(rows)


def cmd_report(args) -> None:
    import html
    esc = html.escape
    verdicts = {json.loads(p.read_text())["label"]: json.loads(p.read_text()) for p in OUT.glob("*.verdict.json")}
    if not verdicts:
        sys.exit("No verdicts yet. Run the rounds first.")
    order = [l for l in ("acme-cold", "vandelay-cold", "vandelay-warm") if l in verdicts] + \
            sorted(l for l in verdicts if l not in ("acme-cold", "vandelay-cold", "vandelay-warm"))
    titles = {"acme-cold": ("Training deal", "Acme · no lessons"),
              "vandelay-cold": ("Unseen customer", "Vandelay · no lessons"),
              "vandelay-warm": ("Unseen customer", "Vandelay · with lessons")}

    cards = []
    for i, label in enumerate(order[:3]):
        v = verdicts[label]
        k, who = titles.get(label, ("Bid", label))
        cls = "won" if v["won"] else "lost"
        cards.append(f'<div class="card {cls}"><div class="k">{k}</div><div class="who">{esc(who)}</div>'
                     f'<div class="res">{"WON" if v["won"] else "LOST"} <small>{v["passed"]}/{v["total"]}</small></div>'
                     f'<div class="meta">memory {"on" if v.get("memory") else "off"} · {v.get("seconds", "?")}s · '
                     f'{v.get("words", "?")} words</div></div>')
        if i < min(len(order), 3) - 1:
            cards.append('<div class="arrow">→</div>')
    cold, warm = verdicts.get("vandelay-cold"), verdicts.get("vandelay-warm")
    delta = ""
    if cold and warm:
        d = warm["passed"] - cold["passed"]
        delta = (f'<p class="delta">Same swarm, same customer it had never seen: <b>{d:+d} criteria</b> '
                 f'once it had lessons from losing a different deal.</p>')

    # criteria grid, by criterion id, across bids
    ids, names = [], {}
    for label in order:
        for r in verdicts[label]["criteria"]:
            if r["id"] not in ids:
                ids.append(r["id"])
            names.setdefault(r["id"], r["name"])
    head = "".join(f"<th>{esc(titles.get(l, ('', l))[1])}</th>" for l in order)
    grid = []
    for cid in ids:
        ctl = names[cid].startswith("CONTROL")
        cells = []
        for label in order:
            r = next((x for x in verdicts[label]["criteria"] if x["id"] == cid), None)
            cells.append('<td class="c na">–</td>' if r is None else
                         f'<td class="c {"p" if r["verdict"] == "PASS" else "f"}" title="{esc(r["reason"])}">'
                         f'{"✓" if r["verdict"] == "PASS" else "✗"}</td>')
        name = esc(names[cid].replace("CONTROL: ", ""))
        pill = '<span class="pill">control: not taught, should stay flat</span>' if ctl else ""
        grid.append(f'<tr class="{"ctl" if ctl else ""}"><td>{name}{pill}</td>{"".join(cells)}</tr>')

    # lessons + leak check
    snap = OUT / "lessons-snapshot.md"
    lessons = snap.read_text() if snap.exists() else ((OUT / "lessons.md").read_text() if (OUT / "lessons.md").exists() else "")
    items = [re.sub(r"^(\s*[-*]|\s*\d+[.)])\s*", "", ln).strip() for ln in lessons.splitlines()
             if re.match(r"^\s*([-*]|\d+[.)])\s+", ln)]
    hits = leak_check(lessons)
    leak = (f'<p class="ok">Leak check: PASS. No customer names or deal figures.</p>' if lessons and not hits else
            f'<p class="bad">Leak check: FAIL {esc(str(hits))}</p>' if hits else '<p class="small">No lessons yet.</p>')
    lessons_html = "<ul>" + "".join(f"<li>{esc(re.sub(r'[*_`]', '', x))}</li>" for x in items) + "</ul>" if items else \
        f"<pre>{esc(lessons)}</pre>"

    # calibration
    cal_rows = []
    for p in sorted(OUT.glob("calibration-*.json")):
        cal = json.loads(p.read_text())
        def summ(kind):
            runs = [r for r in cal["runs"] if r["kind"] == kind]
            return " / ".join(f'{"WON" if r["won"] else "LOST"} {r["passed"]}/5' for r in runs)
        cal_rows.append(f'<li><b>{esc(cal["buyer"].title())} buyer</b>: weak proposal {summ("bad")} · '
                        f'strong proposal {summ("good")} → '
                        f'{"<span class=ok>trusted</span>" if cal["passed"] else "<span class=bad>not trusted</span>"}</li>')
    cal_html = "<ul>" + "".join(cal_rows) + "</ul>" if cal_rows else '<p class="small">Run calibrate first.</p>'

    # why the warm bid won: the buyer's own words, cold vs warm
    why = []
    if cold and warm:
        for cid in ids:
            rc = next((x for x in cold["criteria"] if x["id"] == cid), None)
            rw = next((x for x in warm["criteria"] if x["id"] == cid), None)
            if rc and rw and rc["verdict"] != rw["verdict"]:
                why.append(f'<div><b>{esc(names[cid])}</b></div><div class="cold">✗ {esc(rc["reason"])}</div>'
                           f'<div class="warm">✓ {esc(rw["reason"])}</div>')
    why_html = ('<div class="why"><div class="h">Criterion</div><div class="h">Without lessons</div>'
                '<div class="h">With lessons</div>' + "".join(why) + "</div>") if why else \
        '<p class="small">No criterion changed between the cold and warm bids.</p>'

    def shown_trace(v):  # cold runs also probe /mnt/memory but nothing is mounted: don't draw a tick
        return [e for e in v.get("trace", []) if e["kind"] != "memory" or v.get("memory")]
    lanes = "".join(f'<h3 style="margin:18px 0 6px;font-size:16px">{esc(titles.get(l, ("", l))[1])}</h3>'
                    f'{_lanes(shown_trace(verdicts[l]), verdicts[l].get("seconds", 0))}'
                    for l in order if verdicts[l].get("trace"))
    links = " · ".join(f'<a href="https://platform.claude.com/sessions/{esc(verdicts[l]["session_id"])}">'
                       f'{esc(l)}</a>' for l in order if verdicts[l].get("session_id"))
    banner = f'<div class="banner">{esc(args.banner)}</div>' if args.banner else ""

    # platform evidence: real cost, model and Skills per agent (from `collect`)
    ev_rows = []
    for l in order:
        v = verdicts[l]
        u = v.get("usage") or {}
        if not v.get("threads"):
            continue
        cache_share = (u.get("cache_read_tokens", 0) /
                       max(1, u.get("cache_read_tokens", 0) + u.get("input_tokens", 0) + u.get("cache_write_tokens", 0)))
        ev_rows.append(f'<tr><td colspan="5" style="background:#faf9f6"><b>{esc(titles.get(l, ("", l))[1])}</b> · '
                       f'total ${u.get("cost") or 0:.2f} · {cache_share:.0%} of input tokens served from prompt cache</td></tr>')
        for t in sorted(v["threads"], key=lambda t: (t.get("parent") is not None, t["agent"])):
            ev_rows.append(f'<tr><td>{esc(t["agent"])}</td><td><code>{esc(t["model"])}</code></td>'
                           f'<td>{esc(", ".join(t["skills"]) or "–")}</td><td>${t.get("cost") or 0:.3f}</td>'
                           f'<td>{(t.get("active_seconds") or 0):.0f}s</td></tr>')
    evidence = ('<table><tr><th>Agent (thread)</th><th>Model</th><th>Skill</th><th>List cost</th><th>Active</th></tr>'
                + "".join(ev_rows) + "</table>") if ev_rows else \
        '<p class="small">Run <code>debrief.py collect</code> to pull cost and model per agent from the platform.</p>'

    # both proposals, side by side
    side = ""
    if cold and warm and (OUT / "vandelay-cold.md").exists() and (OUT / "vandelay-warm.md").exists():
        side = ('<details><summary style="cursor:pointer;font-weight:650">Read both Vandelay proposals side by side</summary>'
                '<div class="two" style="margin-top:10px">'
                f'<div class="box"><b>Without lessons</b><pre style="white-space:pre-wrap;font-size:13px">{esc((OUT / "vandelay-cold.md").read_text())}</pre></div>'
                f'<div class="box"><b>With lessons</b><pre style="white-space:pre-wrap;font-size:13px">{esc((OUT / "vandelay-warm.md").read_text())}</pre></div>'
                '</div></details>')

    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Debrief</title>
<style>{REPORT_CSS}</style></head><body><main>{banner}
<h1>Debrief</h1><p class="tag">Lose once. Win the next one. A proposal swarm that learns from the buyer's debrief.</p>
<div class="cards">{"".join(cards)}</div>{delta}
<h2>The buyer's hidden scorecard</h2>
<table><tr><th>Criterion (never shown to the swarm)</th>{head}</tr>{"".join(grid)}</table>
<div class="two"><div><h2>What it learned from losing</h2><div class="box">{lessons_html}{leak}</div></div>
<div><h2>Can we trust the buyer?</h2><div class="box">{cal_html}
<p class="small">The buyer runs on {esc(BUYER_MODEL)} with one PASS/FAIL call per criterion. The swarm's coordinator runs on {esc(COORDINATOR_MODEL)}.</p></div></div></div>
<h2>Why the second bid won, in the buyer's words</h2>{why_html}
<h2>Four specialists, in parallel</h2><div class="box">{lanes or '<p class="small">No trace recorded.</p>'}
<p class="small">Bars: delegated → reply. Orange ticks: the coordinator reading its lessons from memory.</p></div>
<h2>Running on Claude Platform: cost, models and Skills per agent</h2>{evidence}
<p class="small">From the Managed Agents session and thread usage API: list cost, prompt-cache reads, and the model and Skill each agent actually ran with.</p>
{side}
<p class="small" style="margin-top:24px">Live sessions on Claude Platform: {links or "n/a"}</p>
</main></body></html>"""
    out = OUT / "report.html"
    out.write_text(page)
    print(f"Report: {out.resolve()}")


# --------------------------------------------------------------------------- cli

def main() -> None:
    ap = argparse.ArgumentParser(description="Debrief: lose once, win the next one.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup"); s.add_argument("--solo", action="store_true", help="no multi-agent roster")
    s = sub.add_parser("calibrate"); s.add_argument("--buyer", required=True)
    s = sub.add_parser("round")
    s.add_argument("--rfp", required=True, help="acme | vandelay | path")
    s.add_argument("--buyer", required=True)
    s.add_argument("--label", required=True)
    s.add_argument("--use-memory", action="store_true")
    s.add_argument("--learn", action="store_true", help="debrief after the verdict and write lessons")
    s.add_argument("--quiet", action="store_true", help="hide proposal text while streaming")
    for name in ("round", "score", "lessons"):
        p = s if name == "round" else sub.add_parser(name)
        p.add_argument("--backend", choices=["store", "local"], default="store")
    s = sub.add_parser("report", help="write outputs/report.html, the demo screen (offline)")
    s.add_argument("--banner", default="", help="optional notice at the top, e.g. SAMPLE DATA")
    s = sub.add_parser("collect", help="add platform usage/cost per agent to saved verdicts")
    s.add_argument("--label", default="")
    sub.add_parser("manifest", help="write outputs/deployment.json: agents, models, Skills")
    s = sub.add_parser("serve", help="serve outputs/ for the war room and report")
    s.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    {"setup": cmd_setup, "calibrate": cmd_calibrate, "round": cmd_round, "score": cmd_score,
     "lessons": cmd_lessons, "report": cmd_report, "collect": cmd_collect, "manifest": cmd_manifest,
     "serve": cmd_serve}[args.cmd](args)


if __name__ == "__main__":
    main()
