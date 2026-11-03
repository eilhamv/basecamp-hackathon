"""Debrief: one-click local app.

    python app.py            # then open http://127.0.0.1:8765 and click "Run everything"

It prepares the workspace (clones the starter swarm into build/ and copies kit/ into it), deploys the
agents to Claude Platform, calibrates the AI buyers, runs the three bids, and builds the report.
Steps that are already done are skipped, so you can click again safely.

The API key is read from ANTHROPIC_API_KEY or from a .env file in this folder. It is never shown or logged.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KIT, BUILD = ROOT / "kit", ROOT / "build"
OUT, LOGS = BUILD / "outputs", BUILD / "outputs" / "logs"
STARTER = "https://github.com/rosscrooke/specialist-swarm.git"
PORT = int(os.environ.get("PORT", "8765"))

STEPS = [
    ("prepare", "Prepare the workspace", "Clone the starter swarm into build/ and add the Debrief kit"),
    ("deploy", "Deploy agents to Claude Platform", "Environment, 4 specialists, Skills, coordinator, memory store"),
    ("calibrate", "Calibrate the AI buyers", "A weak proposal must lose and a strong one must win, twice"),
    ("wave1", "Bid on Acme, then learn  ∥  bid on Vandelay without lessons", "Two bids in parallel, about 7 min"),
    ("wave2", "Bid on Vandelay with lessons", "The test: same unseen customer, now with memory, about 7 min"),
    ("report", "Collect platform evidence and build the report", "Cost and model per agent, report.html"),
]
LIVE = {"wave1": ["acme-cold", "vandelay-cold"], "wave2": ["vandelay-warm"]}
state = {k: {"status": "pending", "secs": None, "note": ""} for k, _, _ in STEPS}
runner = {"busy": False, "current": None, "error": ""}


# --------------------------------------------------------------------------- environment

def api_key() -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    for env_file in (ROOT / ".env", BUILD / ".env"):
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.strip().startswith("ANTHROPIC_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def child_env() -> dict:
    env = dict(os.environ, ANTHROPIC_API_KEY=api_key(), PYTHONUNBUFFERED="1")
    env.pop("ANTHROPIC_BASE_URL", None)  # Managed Agents calls must go to the Claude API directly
    return env


def run(args: list, log: str) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(LOGS / f"{log}.log", "a") as f:
        f.write(f"\n$ {' '.join(args)}\n")
        f.flush()
        rc = subprocess.run([sys.executable, *args], cwd=BUILD, env=child_env(), stdout=f, stderr=subprocess.STDOUT).returncode
    if rc != 0:
        raise RuntimeError(f"`{' '.join(args)}` failed (exit {rc}). See the log below.")


def parallel(jobs: list) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    procs = []
    for args, log in jobs:
        f = open(LOGS / f"{log}.log", "a")
        procs.append((args, f, subprocess.Popen([sys.executable, *args], cwd=BUILD, env=child_env(),
                                                stdout=f, stderr=subprocess.STDOUT)))
    failed = []
    for args, f, p in procs:
        if p.wait() != 0:
            failed.append(args)
        f.close()
    if failed:
        raise RuntimeError(f"{len(failed)} bid(s) failed. See the logs below.")


# --------------------------------------------------------------------------- steps

def step_prepare() -> str:
    if not (BUILD / "create_specialists.py").exists():
        if shutil.which("git") is None:
            raise RuntimeError("git is not installed")
        tmp = ROOT / "_starter_tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        subprocess.run(["git", "clone", "-q", STARTER, str(tmp)], check=True)
        shutil.copytree(tmp, BUILD, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git"))
        shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(KIT, BUILD, dirs_exist_ok=True)  # refresh the kit every time
    OUT.mkdir(exist_ok=True)
    shutil.copy(KIT / "war-room.html", OUT / "war-room.html")
    return "starter cloned, kit copied"


def step_deploy() -> str:
    if all((BUILD / f).exists() for f in (".coordinator_id", ".memory_store_id", ".skill_ids.json")):
        return "skip"
    if not (BUILD / ".environment_id").exists():
        run(["setup_environment.py"], "deploy")
    if not (BUILD / ".specialist_ids.json").exists():
        run(["create_specialists.py"], "deploy")
    run(["upload_skills.py"], "deploy")
    solo = ["--solo"] if os.environ.get("SOLO") == "1" else []  # workspaces without multi-agent
    run(["debrief.py", "setup", *solo], "deploy")  # coordinator after Skills, so its roster sees them
    return "deployed"


def step_calibrate() -> str:
    done = 0
    for buyer in ("acme", "vandelay"):
        f = OUT / f"calibration-{buyer}.json"
        if f.exists() and json.loads(f.read_text()).get("passed"):
            done += 1
            continue
        run(["debrief.py", "calibrate", "--buyer", buyer], "calibrate")
    return "skip" if done == 2 else "both buyers trusted"


def bid(label: str, rfp: str, *flags: str) -> tuple:
    return ["debrief.py", "round", "--rfp", rfp, "--buyer", rfp, "--label", label, "--quiet", *flags], label


def step_wave1() -> str:
    jobs = [j for j in (bid("acme-cold", "acme", "--learn"), bid("vandelay-cold", "vandelay"))
            if not (OUT / f"{j[1]}.verdict.json").exists()]
    if not jobs:
        return "skip"
    parallel(jobs)
    return "two bids done, lessons written"


def step_wave2() -> str:
    if (OUT / "vandelay-warm.verdict.json").exists():
        return "skip"
    run(bid("vandelay-warm", "vandelay", "--use-memory")[0], "vandelay-warm")
    return "bid done"


def step_report() -> str:
    for args in (["debrief.py", "collect"], ["debrief.py", "manifest"], ["debrief.py", "report"]):
        run(args, "report")
    shutil.copy(KIT / "war-room.html", OUT / "war-room.html")
    return "report.html ready"


FUNCS = {"prepare": step_prepare, "deploy": step_deploy, "calibrate": step_calibrate,
         "wave1": step_wave1, "wave2": step_wave2, "report": step_report}


def run_steps(keys: list) -> None:
    runner.update(busy=True, error="")
    for k in keys:
        runner["current"] = k
        state[k].update(status="running", secs=None, note="")
        t0 = time.time()
        try:
            note = FUNCS[k]()
            state[k].update(status="skipped" if note == "skip" else "done",
                            note="already done" if note == "skip" else note)
        except Exception as e:
            state[k].update(status="failed", note=str(e))
            runner["error"] = f"{dict((a, b) for a, b, _ in STEPS)[k]}: {e}"
            break
        finally:
            state[k]["secs"] = round(time.time() - t0)
    runner.update(busy=False, current=None)


# --------------------------------------------------------------------------- status for the UI

def results() -> list:
    rows = []
    for label in ("acme-cold", "vandelay-cold", "vandelay-warm"):
        f = OUT / f"{label}.verdict.json"
        if f.exists():
            v = json.loads(f.read_text())
            rows.append({"label": label, "won": v["won"], "passed": v["passed"], "total": v["total"],
                         "cost": (v.get("usage") or {}).get("cost"), "seconds": v.get("seconds")})
    return rows


def log_tail() -> dict:
    cur = runner["current"] or next((k for k, _, _ in reversed(STEPS) if state[k]["status"] in ("failed", "done")), None)
    names = {"deploy": ["deploy"], "calibrate": ["calibrate"], "wave1": ["acme-cold", "vandelay-cold"],
             "wave2": ["vandelay-warm"], "report": ["report"]}.get(cur, [])
    tails = {}
    for n in names:
        f = LOGS / f"{n}.log"
        if f.exists():
            tails[n] = "\n".join(f.read_text(errors="replace").splitlines()[-18:])
    return tails


def status() -> dict:
    return {"has_key": bool(api_key()), "busy": runner["busy"], "current": runner["current"], "error": runner["error"],
            "steps": [{"key": k, "title": t, "desc": d, **state[k],
                       "live": LIVE.get(k, []) if state[k]["status"] == "running" else []} for k, t, d in STEPS],
            "results": results(), "report": (OUT / "report.html").exists(), "logs": log_tail()}


# --------------------------------------------------------------------------- web server

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(BUILD), **k)

    def log_message(self, *a):  # keep the terminal quiet
        pass

    def send_json(self, data: dict, code: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/status"):
            self.send_json(status())
        elif self.path.startswith("/outputs/"):  # only run outputs are served, never keys or IDs
            super().do_GET()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/api/run":
            return self.send_error(404)
        length = int(self.headers.get("Content-Length", 0) or 0)
        action = json.loads(self.rfile.read(length) or b"{}").get("action", "all")
        if runner["busy"]:
            return self.send_json({"ok": False, "error": "already running"}, 409)
        if not api_key():
            return self.send_json({"ok": False, "error": "no API key"}, 400)
        keys = ["prepare", "report"] if action == "report" else [k for k, _, _ in STEPS]
        for k in keys:
            state[k].update(status="pending", secs=None, note="")
        threading.Thread(target=run_steps, args=(keys,), daemon=True).start()
        self.send_json({"ok": True})


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Debrief</title><style>
*{box-sizing:border-box}body{margin:0;font:16px/1.45 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;background:#f6f5f2;color:#1d1d1f}
main{max-width:980px;margin:0 auto;padding:30px 28px 60px}h1{font-size:40px;margin:0}.tag{color:#666;font-size:19px;margin:2px 0 20px}
.bar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:18px}
button{font-weight:600;font-size:16px;padding:12px 22px;border-radius:10px;border:0;cursor:pointer;background:#1d1d1f;color:#fff}
button.sec{background:#fff;color:#1d1d1f;border:1px solid #d6d3cc}button:disabled{opacity:.4;cursor:default}
.chip{padding:5px 12px;border-radius:99px;font-size:13px;font-weight:600}.ok{background:#e3f4e9;color:#14663a}.no{background:#fde8e6;color:#9b2c1f}
.steps{background:#fff;border:1px solid #e6e3dc;border-radius:14px;overflow:hidden}
.step{display:grid;grid-template-columns:36px 1fr auto;gap:12px;padding:14px 18px;border-top:1px solid #eee;align-items:center}
.step:first-child{border-top:0}.ic{font-size:20px;text-align:center}.t{font-weight:650}.d{color:#777;font-size:14px}
.note{font-size:13px;color:#555}.running{background:#f3f6ff}.failed{background:#fff3f1}.links a{margin-right:12px;font-size:14px}
.res{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:22px 0}.card{background:#fff;border:2px solid #e6e3dc;border-radius:14px;padding:14px 16px}
.card.w{border-color:#1f8a4c}.big{font-size:34px;font-weight:800}.won{color:#1f8a4c}.lost{color:#c0392b}.small{color:#777;font-size:13px}
pre{background:#14161b;color:#d7d4cc;padding:14px;border-radius:12px;font-size:12px;max-height:300px;overflow:auto;white-space:pre-wrap}
.screens a{display:inline-block;margin:6px 10px 6px 0;padding:10px 16px;border-radius:10px;background:#fff;border:1px solid #d6d3cc;color:#1d1d1f;text-decoration:none;font-weight:600}
.err{background:#fde8e6;color:#9b2c1f;padding:10px 14px;border-radius:10px;margin-bottom:14px}
</style></head><body><main>
<h1>Debrief</h1><p class="tag">Lose once. Win the next one. A proposal team of Claude agents that learns from the buyer's debrief.</p>
<div class="bar"><button id="all" onclick="go('all')">▶ Run everything</button>
<button class="sec" id="rep" onclick="go('report')">Rebuild report</button><span id="key" class="chip"></span>
<span class="small">First full run: about 20 minutes and about $5 at list price. Finished steps are skipped.</span></div>
<div id="err"></div><div class="steps" id="steps"></div>
<div id="res"></div><div class="screens" id="screens"></div><div id="logs"></div>
</main><script>
const ICON={pending:"○",running:"⏳",done:"✅",skipped:"✔️",failed:"❌"};
const NAMES={"acme-cold":"Acme · no lessons","vandelay-cold":"Vandelay · no lessons","vandelay-warm":"Vandelay · with lessons"};
async function go(a){const r=await fetch("/api/run",{method:"POST",body:JSON.stringify({action:a})});const j=await r.json();if(!j.ok)alert(j.error);tick();}
async function tick(){const s=await (await fetch("/api/status")).json();
 document.getElementById("key").className="chip "+(s.has_key?"ok":"no");
 document.getElementById("key").textContent=s.has_key?"API key loaded":"No API key: add ANTHROPIC_API_KEY to .env and restart";
 document.getElementById("all").disabled=s.busy||!s.has_key;document.getElementById("rep").disabled=s.busy||!s.has_key;
 document.getElementById("err").innerHTML=s.error?`<div class="err">${s.error}</div>`:"";
 document.getElementById("steps").innerHTML=s.steps.map(x=>`<div class="step ${x.status}"><div class="ic">${ICON[x.status]}</div>
  <div><div class="t">${x.title}</div><div class="d">${x.desc}</div>${x.note?`<div class="note">${x.note}</div>`:""}
  ${x.live.length?`<div class="links">Watch live: ${x.live.map(l=>`<a target="_blank" href="/outputs/war-room.html?live=${l}">${NAMES[l]}</a>`).join("")}</div>`:""}</div>
  <div class="small">${x.secs!=null?x.secs+"s":""}</div></div>`).join("");
 document.getElementById("res").innerHTML=s.results.length?`<div class="res">${s.results.map(r=>`<div class="card ${r.won?"w":""}">
  <div class="small">${NAMES[r.label]}</div><div class="big ${r.won?"won":"lost"}">${r.won?"WON":"LOST"} ${r.passed}/${r.total}</div>
  <div class="small">${r.seconds||"?"}s${r.cost!=null?" · $"+r.cost.toFixed(2):""}</div></div>`).join("")}</div>`:"";
 const done=new Set(s.results.map(r=>r.label));
 document.getElementById("screens").innerHTML=(s.report||done.size)?`<h3>Demo screens</h3>`+
  (s.report?`<a target="_blank" href="/outputs/report.html">📊 Report: the proof</a>`:"")+
  ["acme-cold","vandelay-cold","vandelay-warm"].filter(l=>done.has(l)).map(l=>`<a target="_blank" href="/outputs/war-room.html?bid=${l}&speed=15">🎬 War room: ${NAMES[l]}</a>`).join(""):"";
 document.getElementById("logs").innerHTML=Object.entries(s.logs).map(([n,t])=>`<h4 style="margin:18px 0 6px">Log · ${n}</h4><pre>${t.replace(/[<&]/g,c=>c=="<"?"&lt;":"&amp;")}</pre>`).join("");
}
tick();setInterval(tick,1500);
</script></body></html>"""


def main() -> None:
    if not KIT.exists():
        sys.exit("Run app.py from the repo folder (kit/ not found).")
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Debrief is running at {url}  (API key {'loaded' if api_key() else 'MISSING: add it to .env'})\nCtrl-C to stop.")
    if os.environ.get("NO_BROWSER") != "1":
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
