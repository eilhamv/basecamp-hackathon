# Debrief: build guide (45 minutes)

**Lose once. Win the next one.** A proposal swarm loses a bid, reads the buyer's debrief, stores general lessons in memory, and then wins a customer it has never seen. See [PLAN.md](PLAN.md) for the why and the risks. This page covers what to type and when.

## What's in the kit

| File | Purpose |
|---|---|
| `kit/debrief.py` | One CLI: `setup`, `calibrate`, `round`, `score`, `lessons` |
| `kit/coordinator_system.md` | The coordinator prompt: the starter's prompt plus a "read lessons first" rule, markdown output and debrief mode. No hidden criteria |
| `kit/buyers/acme.json`, `vandelay.json` | The buyers' **hidden** scorecards, 5 PASS/FAIL criteria each. Vandelay #5 is the control |
| `kit/synthetic-data/rfp-vandelay.md` | The unseen test RFP. Different customer, industry and wording |
| `kit/calibration/{acme,vandelay}-{bad,good}.md` | Known-bad and known-good proposals that prove each buyer can be trusted |

## Before the clock starts (5 minutes, no code)
- [ ] A workspace API key from the hackathon Console. You'll export it in a terminal; never paste it into a file.
- [ ] Python 3.10+ and `git`.
- [ ] Two terminal tabs open side by side. Wave 1 runs in both.
- [ ] Ask the organisers whether **multi-agent** (research preview) is enabled on your workspace. If not, use `--solo` at minute 5.
- [ ] Confirm the kit is allowed under the hackathon rules. If pre-written code isn't allowed, use this kit only as a reference and type it in.

---

## Minute 0–5: set up

```bash
git clone https://github.com/rosscrooke/specialist-swarm.git build && cd build
```

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

```bash
cp -R ../kit/* .
```

> Run inside `build/` (the clone). `build/` is git-ignored: it holds the starter swarm plus the kit, and is where every command below runs.

```bash
export ANTHROPIC_API_KEY=...   # type it in the shell, never into a file
```

```bash
python setup_environment.py
```

**Gate:** it prints `Environment created`.

## Minute 5–10: deploy the agents

```bash
python create_specialists.py && python upload_skills.py && python debrief.py setup
```

**Gate:** it prints the coordinator and memory store IDs.
- **If `setup` fails on `multiagent`,** run `python debrief.py setup --solo`. The coordinator then covers all four specialist roles itself; the story is unchanged.
- **If the memory store fails,** add `--backend local` to every later `round`, `score` and `lessons` command.

Skip the starter's `create_coordinator.py` and `run_deal_desk.py`. `debrief.py` replaces them.

## Minute 10–12: calibrate the buyer (never skip)

```bash
python debrief.py calibrate --buyer acme && python debrief.py calibrate --buyer vandelay
```

**Gate:** `CALIBRATION PASSED` appears twice. That means, for each buyer, the bad proposal **lost** and the good one **won**, with the same result twice. This takes 40 judge calls, about a minute.
- **If it fails,** read the ✗ reason, tighten the wording of that criterion in `buyers/acme.json`, and rerun. Without this gate the scoreboard means nothing.

## Minute 12–24: wave 1, two terminals at once

**Terminal 1** runs the Acme bid, then the debrief that writes the lessons:
```bash
python debrief.py round --rfp acme --buyer acme --label acme-cold --learn
```

**Terminal 2** runs the cold baseline on the unseen customer:
```bash
python debrief.py round --rfp vandelay --buyer vandelay --label vandelay-cold --quiet
```

**Gate:** Terminal 1 ends with `LESSONS NOW IN MEMORY`.
- **Expected:** Acme **LOST** at about 1–2/5; Power BI passes, the rest mostly fail.
- **If Acme wins,** the swarm is already good at this. Say so honestly and still run wave 2: the comparison that counts is Vandelay cold vs. warm.
- **If wave 1 takes longer than 12 minutes,** set `export SPECIALIST_WORDS=150` before wave 2.

## Minute 24–34: wave 2, the test

```bash
python debrief.py round --rfp vandelay --buyer vandelay --label vandelay-warm --use-memory
```

Watch for `[memory: ...] /mnt/memory/...` before the delegations start. That line is the agent reading its lessons.

## Minute 34–38: the proof

```bash
python debrief.py score
```

```bash
python debrief.py lessons
```

**What good looks like:**
```
UNSEEN CUSTOMER: cold 1/5 -> warm 4/5 (+3)
CONTROL (criterion 5, not taught): cold FAIL / warm FAIL -> flat, as expected
LEAK CHECK on lessons: PASS (general lessons only)
```

Open `outputs/vandelay-cold.md` and `outputs/vandelay-warm.md` side by side, and find the paragraphs that changed: the total-cost line, the dated plan, the exit section.

## Minute 38–45: rehearse

Open the Console link for each bid session: `https://platform.claude.com/sessions/<id>`. The IDs are in `outputs/*.verdict.json`. That's the "deployed" proof: the agents, memory and sessions are live on the platform.

---

## The 3-minute demo

| Time | Show | Say |
|---|---|---|
| 0:00 | Title | "Proposal teams lose deals and never learn why. Ours does." |
| 0:20 | Terminal 1 replay: `[thread spawned]` ×4 | "A coordinator fans out to four specialists in parallel. Each has its own Skill." |
| 0:50 | The Acme verdict, **LOST 1/5** | "The buyer is a separate model with a scorecard the swarm never sees. One pass/fail call per criterion, calibrated before we trusted it." |
| 1:20 | `debrief.py lessons` | "After the debrief, the agent decided what to remember. General rules, no customer names. Our leak check confirms it." |
| 1:50 | `score`, Vandelay cold vs. warm | "A different customer and industry. Same swarm: without memory 1/5, with memory 4/5." |
| 2:20 | The CONTROL row | "The one criterion the lessons never covered didn't move. So it's learning, not a lenient judge." |
| 2:40 | Side-by-side proposals | "Lose once. Win the next one." |

**Backup plan:** everything is saved in `outputs/`, and `python debrief.py score` works offline. If a live run stalls, present from the saved results.

## Workshop concepts this shows (for the judges)

- **Managed Agents multi-agent + Skills:** coordinator + specialists ([specialist-swarm](https://github.com/rosscrooke/specialist-swarm)).
- **Memory stores:** the agent curates its own lessons ([institutional-memory](https://github.com/rosscrooke/institutional-memory)).
- **Evals:**
  - an LLM judge on a different model, with structured output, one claim per call, and a `stop_reason` check
  - calibration against known-bad and known-good answers
  - a held-out customer and a control criterion

  Source: the Basecamp Day 2 evals lab.
- **Train/test discipline:** Acme is the training deal; Vandelay is the unseen test deal.

## Known limits (say them before a judge asks)

- **One run per arm.** That shows direction; it isn't a measured rate. Next step: 3 runs per arm and pass^3.
- **The debrief tells the swarm why it lost,** as real procurement debriefs do. The test is whether that **transfers** to a customer with different wording, industry and terms.
- **Cost per bid isn't on the scoreboard.** Read it from the Console usage page.
