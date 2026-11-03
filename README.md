# Debrief: build guide (45 minutes)

**Lose once. Win the next one.** A proposal swarm loses a bid, reads the buyer's debrief, stores general lessons in memory, and then wins a customer it has never seen.
- [PLAN.md](PLAN.md): the claim, what the audience sees, the run of show, and risks.
- This page: what to type, in order, with a pass/fail gate at each step.

![Demo screen, sample data](docs/demo-screen.png)
*The demo screen (`debrief.py report`), shown here with sample data.*

## What's in the kit

| File | Purpose |
|---|---|
| `kit/debrief.py` | One CLI: `setup` · `calibrate` · `round` · `score` · `lessons` · `report` |
| `kit/env.sh` | Source in every terminal: venv + key from `.env` + gateway URL removed |
| `kit/coordinator_system.md` | Starter coordinator prompt + "read lessons first" + markdown output + debrief mode. **No hidden criteria** |
| `kit/buyers/acme.json`, `vandelay.json` | Hidden scorecards, 5 PASS/FAIL criteria each. Vandelay #5 is the **control** |
| `kit/synthetic-data/rfp-vandelay.md` | The unseen test RFP: different customer, industry, currency and term |
| `kit/calibration/{acme,vandelay}-{bad,good}.md` | Known-bad and known-good proposals that prove each buyer can be trusted |

## Before the clock starts
- [ ] **Workspace API key** from the hackathon Console, saved to `build/.env`. That file is git-ignored; never paste the key into chat or commit it:
  ```bash
  printf 'ANTHROPIC_API_KEY=%s\n' 'PASTE-KEY-HERE' > build/.env
  ```
- [ ] Ask the organisers whether **multi-agent** (research preview) is enabled on the workspace. If not, use `--solo` at minute 5.
- [ ] Open **two terminals** and run `cd build && source env.sh` in each.
- [ ] Check that pre-written code is allowed under the hackathon rules. If not, use the kit as a reference only.

---

## Minute 0–5: set up *(clone, install and copy are already done on this laptop)*

```bash
git clone https://github.com/rosscrooke/specialist-swarm.git build && cd build
```

```bash
python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt && .venv/bin/pip install -q -U anthropic
```

```bash
cp -R ../kit/* . && source env.sh
```

```bash
python setup_environment.py
```

**Gate:** it prints `Environment created`.

## Minute 5–10: deploy the agents

```bash
python create_specialists.py && python upload_skills.py && python debrief.py setup
```

**Gate:** it prints `Coordinator (swarm, …)` and `Memory store: …`.

| If it fails on… | Do this |
|---|---|
| `multiagent` | `python debrief.py setup --solo`. The coordinator covers all four specialist roles itself |
| the coordinator model | `export COORDINATOR_MODEL=claude-opus-4-7` (the model the starter repo shipped with), then rerun `setup` |
| the memory store | Add `--backend local` to every later `round`, `score` and `lessons` command |

Skip the starter's `create_coordinator.py` and `run_deal_desk.py`. `debrief.py` replaces them.

## Minute 10–12: calibrate the buyers (never skip)

```bash
python debrief.py calibrate --buyer acme && python debrief.py calibrate --buyer vandelay
```

**Gate:** `CALIBRATION PASSED` appears twice. For each buyer, the weak proposal **lost** and the strong one **won**, with the same result on two tries (40 judge calls, about a minute).
- **If it fails,** read the ✗ reason, tighten that criterion's wording in `buyers/<buyer>.json`, and rerun.

## Minute 12–24: wave 1, two terminals at once

**Terminal 1** runs the training deal, then the debrief, which writes the lessons:
```bash
python debrief.py round --rfp acme --buyer acme --label acme-cold --learn --quiet
```

**Terminal 2** runs the baseline on the unseen customer:
```bash
python debrief.py round --rfp vandelay --buyer vandelay --label vandelay-cold --quiet
```

**Gate:** Terminal 1 ends with `=== LESSONS NOW IN MEMORY ===` and a short list of general rules. Both terminals print a `BUYER VERDICT`.
- **If wave 1 takes longer than 12 minutes,** run `export SPECIALIST_WORDS=150` before wave 2.

## Minute 24–34: wave 2, the test

```bash
python debrief.py round --rfp vandelay --buyer vandelay --label vandelay-warm --use-memory --quiet
```

**Gate:** a `[memory read] /mnt/memory/…` line appears **before** the `thread spawned` lines, and the run ends with a `BUYER VERDICT`.

## Minute 34–38: the proof

```bash
python debrief.py score && python debrief.py report && open outputs/report.html
```

What a good `score` looks like:
```
UNSEEN CUSTOMER: cold 0/5 -> warm 4/5 (+4)
CONTROL (criterion 5, not taught): cold FAIL / warm FAIL -> flat, as expected
LEAK CHECK on lessons: PASS (general lessons only)
```

If the result is different, see "If the result isn't what we hoped" in [PLAN.md](PLAN.md) §7. Every outcome there has an honest line to say.

## Minute 38–45: rehearse

1. In Terminal 1, have this ready for the live opening, but don't run it yet:
   ```bash
   python debrief.py round --rfp vandelay --buyer vandelay --label live --use-memory --quiet
   ```
2. Walk through the run of show in [PLAN.md](PLAN.md) §2 twice, using `outputs/report.html`.
3. Keep the Console session links from the bottom of the report open in a tab. They show the agents are deployed on Claude Platform.

**Backup:** if anything stalls on stage, `report.html` is offline and already has every number.

---

## Command reference

| Command | Does |
|---|---|
| `debrief.py setup [--solo]` | Creates the coordinator (multi-agent roster unless `--solo`) and the memory store |
| `debrief.py calibrate --buyer B` | Weak and strong proposals ×2 → `outputs/calibration-B.json` |
| `debrief.py round --rfp R --buyer B --label L [--use-memory] [--learn] [--quiet] [--backend local]` | One bid → `outputs/L.md`, `outputs/L.verdict.json` (verdict + timed trace). `--learn` adds the debrief |
| `debrief.py score [--backend local]` | Terminal scoreboard, control check, leak check |
| `debrief.py lessons [--backend local]` | Prints what the swarm remembered |
| `debrief.py report [--banner TEXT]` | Writes `outputs/report.html`, the demo screen. Works offline |

**Environment variables:**
- `COORDINATOR_MODEL`: default `claude-opus-5-5`.
- `BUYER_MODEL`: default `claude-sonnet-5-5`. Must differ from the coordinator's model.
- `SPECIALIST_WORDS`: default `300`.

## What this shows from Basecamp
- **Managed Agents multi-agent + Skills:** a coordinator plus four specialists, each with its own Skill.
- **Memory stores:** the agent curates its own lessons across sessions.
- **Evals:**
  - an LLM judge on a different model, with structured output, one claim per call, and a `stop_reason` check
  - calibration on known-bad and known-good proposals
  - a held-out customer and a control criterion
- **Train/test discipline:** Acme is the training deal; Vandelay is the unseen test deal.
