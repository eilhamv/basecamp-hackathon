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
        sys.exit("Set ANTHROPIC_API_KEY first.")
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
    for kind, should_win in (("bad", False), ("good", True)):
        proposal = need(f"calibration/{args.buyer}-{kind}.md")
        outcomes = []
        for attempt in (1, 2):
            v = judge(c, args.buyer, proposal)
            print_verdict(v, f"{kind} proposal, try {attempt}")
            outcomes.append((v["won"], v["passed"]))
        stable = outcomes[0] == outcomes[1]
        right = all(won == should_win for won, _ in outcomes)
        print(f"  -> {kind}: {'OK' if right and stable else 'PROBLEM'} (expected {'WIN' if should_win else 'LOSS'}, stable={stable})")
        ok &= right and stable
    print("\nCALIBRATION " + ("PASSED: the buyer can be trusted." if ok else "FAILED: fix buyers/*.json before bidding."))
    sys.exit(0 if ok else 1)


# --------------------------------------------------------------------------- sessions

def stream_session(c: Anthropic, session_id: str, text: str, quiet: bool = False) -> str:
    """Send one user message and stream until the session goes idle. Returns the agent's text."""
    parts: list[str] = []
    with c.beta.sessions.events.stream(session_id) as stream:
        c.beta.sessions.events.send(
            session_id,
            events=[{"type": "user.message", "content": [{"type": "text", "text": text}]}],
        )
        for event in stream:
            t = event.type
            if t == "session.thread_created":
                print(f"  [thread spawned]  {getattr(event, 'agent_name', '?')}", flush=True)
            elif t == "agent.thread_message_sent":
                print(f"  [delegate →]      {getattr(event, 'to_agent_name', '?')}", flush=True)
            elif t == "agent.thread_message_received":
                print(f"  [reply ←]         {getattr(event, 'from_agent_name', '?')}", flush=True)
            elif t == "agent.tool_use":
                inp = getattr(event, "input", {}) or {}
                target = str(inp.get("path") or inp.get("file_path") or inp.get("command") or "")
                tag = "memory" if "/mnt/memory" in target else "tool"
                print(f"  [{tag}: {getattr(event, 'name', '?')}] {target[:80]}", flush=True)
            elif t == "agent.message":
                for block in event.content:
                    if getattr(block, "type", None) == "text":
                        parts.append(block.text)
                        if not quiet:
                            print(block.text, end="", flush=True)
            elif t == "session.status_idle":
                break
    return "".join(parts)


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
    t0 = time.time()
    text = stream_session(c, session.id, message, quiet=args.quiet)
    seconds = round(time.time() - t0)
    proposal = extract_proposal(text)
    (OUT / f"{args.label}.md").write_text(proposal)
    print(f"\n\n  proposal saved: outputs/{args.label}.md  ({len(proposal.split())} words, {seconds}s)")

    verdict = judge(c, args.buyer, proposal)
    verdict.update(label=args.label, memory=bool(args.use_memory), seconds=seconds, session_id=session.id)
    (OUT / f"{args.label}.verdict.json").write_text(json.dumps(verdict, indent=2))
    print_verdict(verdict, args.label)

    if args.learn:
        debrief(c, verdict, args.backend, environment_id, coordinator_id)


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
        stream_session(c, session.id, (
            "DEBRIEF MODE. Do not delegate to any specialist. The buyer scored our last proposal:\n"
            f"Result: {'WON' if verdict['won'] else 'LOST'} {verdict['passed']}/{verdict['total']}\n{findings}\n\n"
            f"Update /mnt/memory/lessons.md. {DEBRIEF_RULES} Then print the final file."
        ))
    print("\n\n=== LESSONS NOW IN MEMORY ===\n" + read_lessons(c, backend))


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
    print(read_lessons(client(), args.backend) or "(no lessons yet)")


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
    args = ap.parse_args()
    {"setup": cmd_setup, "calibrate": cmd_calibrate, "round": cmd_round,
     "score": cmd_score, "lessons": cmd_lessons}[args.cmd](args)


if __name__ == "__main__":
    main()
