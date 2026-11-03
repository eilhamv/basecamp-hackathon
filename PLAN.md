# Debrief: 45-minute plan

**Debrief: *lose once, win the next one.*** An AI proposal team that loses a bid, reads the buyer's debrief, keeps general lessons in memory, and wins a **different** customer's deal.

**The one claim the demo must prove:** on an unseen customer (Vandelay), the swarm **with** lessons scores higher than the same swarm **without** them. A control criterion that the lessons don't cover stays flat.

**Deployed means:**
- The coordinator, 4 specialists, their Skills and the memory store are live on Claude Platform (Managed Agents).
- Every bid is a session you can open in the Console.
- The demo is driven from one CLI, `debrief.py`.

---

## Scope

| In: 45 minutes | Out: after the hackathon |
|---|---|
| Starter swarm: coordinator + 4 specialists + 3 Skills ([specialist-swarm](https://github.com/rosscrooke/specialist-swarm)) | Critic sub-agent, firm-voice skill |
| Managed Agents memory store, the pattern from [institutional-memory](https://github.com/rosscrooke/institutional-memory) | Curator sub-agent (the debrief prompt does the curating) |
| Buyer judge: hidden 5-criterion scorecard, one PASS/FAIL call per criterion | Multi-turn buyer Q&A |
| 3 bids: Acme cold (learn), Vandelay cold, Vandelay warm | ×3 runs per arm, pass^3 |
| Markdown proposal | docx deliverable, which is slow and adds nothing to the proof |
| Scoreboard + leak check in the terminal | Web UI, $ per bid (read it from the Console instead) |

## Architecture

```
 bid  (session)        RFP + past-wins + product-overview  [+ /mnt/memory lessons if warm]
   └─ Coordinator ── fan-out in parallel ─> Pricing · Legal · Technical Fit · Competitive (Skills)
        └─ markdown proposal between PROPOSAL markers
 judge (Messages API)  5 hidden criteria → 5 parallel PASS/FAIL calls (different model) → verdict.json
 debrief (session)     verdict → Coordinator (no delegation) → writes /mnt/memory/lessons.md
                       rule: general lessons only, no customer names or figures
 score                 verdicts table + leak check on the lessons
```

## Why the evidence holds up

| Concern | How it's handled |
|---|---|
| The judge is lenient | Calibration: a deliberately bad proposal must **lose** and a good one must **win**, with the same result twice (`debrief.py calibrate`) |
| The model grades itself | The buyer runs on a different model from the coordinator (`BUYER_MODEL` vs `COORDINATOR_MODEL`) |
| A vague 1–5 score | One PASS/FAIL per criterion, a reason for each, `stop_reason` checked. A cut-off answer is a grader error, not a loss |
| The swarm memorises Acme | The test deal is a different customer, industry and wording. The leak check fails if the lessons mention Acme or Acme's numbers |
| A general improvement looks like learning | Vandelay criterion 5 (24/7 support with a P1 response under 30 minutes) is **not** taught by Acme. It should be the same in the cold and warm runs |
| The coordinator prompt was tuned to the test | The coordinator prompt has **no** hidden criteria. It only says "apply lessons from memory" |

## Timeline (critical path)

| Minutes | Step | Gate |
|---|---|---|
| 0–5 | Clone the swarm, install, export the key, copy the kit, `setup_environment.py` | `.environment_id` exists |
| 5–10 | `create_specialists.py` → `upload_skills.py` → `debrief.py setup` | `.coordinator_id` and `.memory_store_id` exist. **If multi-agent is rejected → `setup --solo`** |
| 10–12 | `debrief.py calibrate --buyer acme` | Bad proposal LOST, good proposal WON, stable |
| 12–24 | **Wave 1, in 2 terminals:** `acme-cold --learn` ∥ `vandelay-cold` | Both have verdicts; lessons written |
| 24–34 | **Wave 2:** `vandelay-warm --use-memory` | Verdict exists |
| 34–38 | `debrief.py score` + `debrief.py lessons` | Warm beats cold, the control is flat, no leak |
| 38–45 | Rehearse the pitch; open the Console session links | — |

**If wave 1 runs longer than 12 minutes,** set `SPECIALIST_WORDS=150` before wave 2. Never cut calibration: without it, the scoreboard proves nothing.

## Risks and fallbacks

| Risk | Detected at | Fallback |
|---|---|---|
| Multi-agent not enabled on the workspace key | Minute 10, `setup` error | `debrief.py setup --solo`: one coordinator with no roster. The memory and judge story is unchanged |
| The memory store can't be created or attached | Minute 10, or the debrief error | `--backend local`: lessons go to `outputs/lessons.md` and are added to the warm bid's message |
| The warm run doesn't beat the cold run | Minute 34 | Show it honestly: "lessons applied: X/4". Then show which lesson the coordinator ignored, from the session trace. One prompt fix is out of time; say so |
| A live run fails on stage | Demo | Results from wave 1 and 2 are saved in `outputs/`; `score` runs offline |

## Out of bounds
- Synthetic data only. The API key comes from the environment, never a file.
- Keep this local. Basecamp material may be partner-confidential.
