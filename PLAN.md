# Debrief: plan

> **Lose once. Win the next one.**
> A proposal team of Claude agents loses a bid, reads the buyer's debrief, keeps general lessons in memory, and then wins a customer it has never seen.

| | |
|---|---|
| **The claim** | On an unseen customer (Vandelay), the same swarm **with** lessons scores higher than **without** them, while a control criterion that no lesson covers stays flat |
| **Time box** | 45 minutes to build, deploy and run; 3 minutes to demo |
| **Built on** | [rosscrooke/specialist-swarm](https://github.com/rosscrooke/specialist-swarm) (coordinator + specialists + Skills) and the memory-store pattern from [rosscrooke/institutional-memory](https://github.com/rosscrooke/institutional-memory) |
| **Deployed on** | Claude Platform: Managed Agents (coordinator + 4 specialists, multi-agent), Skills, a memory store, one environment |
| **Repo** | [eilhamv/basecamp-hackathon](https://github.com/eilhamv/basecamp-hackathon) |

---

## 1. Results from the real runs (2026-11-03)

| Run | Memory | Verdict | Time | Words | Platform list cost |
|---|---|---|---|---|---|
| Calibration, Acme buyer | — | weak LOST 1/5 ×2 · strong WON 5/5 ×2 → **trusted** | | | |
| Calibration, Vandelay buyer | — | weak LOST 0/5 ×2 · strong WON 5/5 ×2 → **trusted** | | | |
| `acme-cold` (training) | off → writes lessons | **LOST 3/5**: missed calendar dates and a named reference | 446s | 2,202 | $1.28 |
| `vandelay-cold` (baseline) | off | **LOST 2/5**: missed full-term total, calendar months and a named reference. Control ✓ | 351s | 2,069 | $1.06 |
| `vandelay-warm` (test) | reads lessons (at 2.8s and 4.7s, before delegating) | **WON 5/5**: calendar milestone dates, one €-total for the term, three named references + dated PoC. Control ✓ | 369s | 2,447 | $1.16 |
| **Headline** | | **Unseen customer: 2/5 → 5/5 (+3). Control flat (✓/✓). Leak check PASS.** | | | |

**What the runs already proved:**
- **Parallel fan-out:** all 4 specialists were spawned within **0.7s** of each other in both runs (`outputs/*.verdict.json` → `trace`).
- **Agent-written memory:** after the Acme loss, the coordinator wrote **6 general lessons** to the memory store. The leak check **passes**: no customer names, figures or legacy-system names.
  - Lessons 1–2 target exactly what it lost on.
  - Lessons 3–5 reinforce what it got right.
  - Lesson 6 is one we never asked for: *"map each evaluation criterion to the exact proposal text"*.
- **Model routing and caching, from the platform's own usage API:**
  - Opus 5.5 coordinator **$0.52**, Sonnet 4.6 specialists **$0.12–$0.21**, Haiku 4.5 analyst **$0.04** (Vandelay cold).
  - Of all input tokens, **373K were read from cache** against 79K written and 87 uncached.
- **The baselines are stronger than planned.** The starter swarm already gives a full-term total (Acme) and an exit plan. So the room for gain on Vandelay was the **3** failed criteria. The warm run flipped **all 3**.
- **Honest caveats:**
  - The warm proposal is 18% longer (2,447 vs. 2,069 words). The control criterion stayed flat, and each flip is a specific, quoted fix, not just more text.
  - n = 1 per arm.

---

## 2. Capability review: is each capability *visible* in the demo?

A capability only counts in a demo if the audience can **see** it happen. This table lists every capability we're claiming, where it lives in the build, and the exact moment it shows on screen.

| # | Capability (Basecamp topic) | Where it lives | What the audience sees | Evidence |
|---|---|---|---|---|
| 1 | **Managed Agents**: hosted agents, environment, sessions | `create_specialists.py`, `debrief.py setup`; every bid is a session | Console session page, with all threads; session link on every screen | ✅ real |
| 2 | **Multi-agent coordinator + parallel fan-out** | Coordinator with `multiagent` roster; delegates in one message | War room: 4 specialist cards light up **within 0.7s**; timers run in parallel | ✅ real trace |
| 3 | **Agent Skills** | `upload_skills.py` attaches a Skill to Pricing, Legal and Competitive | War room: purple `skill:` badges per card, read from the agents API (`debrief.py manifest`); report: the Skill each **thread actually ran with** | ✅ 3 of 4. Technical Fit has no Skill: the starter ships none for it, and its product doc is passed in the message. Say so |
| 4 | **Memory stores** (Managed Agents) | `/mnt/memory/lessons.md`, mounted only on the warm run | War room: the memory card is grey "not mounted" on cold runs and **pulses "read at 2.8s"** on the warm run, before any delegation. Console memory-store page shows the file | ✅ real |
| 5 | **Context engineering**: the agent decides what to remember | Debrief session: "general rules, merge, ≤ 6, no names or figures" | Console memory store / report: 6 rules with keywords; leak check PASS | ✅ real |
| 6 | **Evals: LLM-as-judge** | `buyers/*.json`, `judge()` | War room: buyer card with **5 sealed criteria** that flip one by one with quoted reasons | ✅ real |
| 7 | **Structured outputs** | `output_config.format` JSON schema `{verdict: PASS/FAIL, reason}` | Buyer card badge: "5 PASS/FAIL calls · structured output" | ✅ |
| 8 | **Eval rigour**: calibration, held-out customer, control | `calibrate`, Vandelay test, control criterion 5 | Report: "Can we trust the buyer?" panel; highlighted control row | ✅ real |
| 9 | **Hill-climbing / train–test discipline** | Acme = train, Vandelay = test | Report cards: Acme → Vandelay cold → Vandelay warm | ✅ |
| 10 | **Inference optimisation**: model routing, prompt caching, parallelism | Opus coordinator, Sonnet and Haiku specialists; automatic platform caching | War room cost panel and report table: **cost per agent and model**, % of input from cache | ✅ real platform numbers |
| 11 | **Observability** | Event stream, session/thread usage API | War room event stream; Console traces | ✅ |
| 12 | Human in the loop | — | Not shown. The proposal is a draft; say "a partner approves before it goes out" | ⚠️ gap, mention only |

**Gaps found in review, and what was done about each:**
- **Cold runs probed `/mnt/memory` too,** because of the prompt's "check if mounted". Nothing was there to find. Both screens now show memory activity only for runs with memory mounted.
- **The live war room showed "not mounted" on the warm run,** because the live file dropped the flag. **Fixed** in `debrief.py`, with a fallback in the page.
- **Platform cost is in cents** (`amount` is in minor units). **Fixed**: $1.06, not $106.
- **The war room is a replay, not live:** a bid takes 6–7 minutes, more than the 3-minute slot. The screen is labelled `REPLAY 15× · recorded run`. That's honest, and it's the real trace.
- **n = 1 per arm.** State it, and show the per-criterion quotes so the difference is concrete, not a single number.

---

## 3. The demo: five screens, five acts

The audience never just watches a terminal. Each act has its own screen, and each screen proves specific capabilities from §2.

### Screens (browser tabs, in this order)

| Tab | URL | Proves |
|---|---|---|
| **A · War room: Acme** | `http://127.0.0.1:8765/outputs/war-room.html?bid=acme-cold&speed=15` | 1, 2, 3, 6, 7, 10 |
| **B · Console: memory store** | `https://platform.claude.com/memory-stores/<memory_store_id>` | 4, 5 |
| **C · War room: Vandelay with lessons** | `http://127.0.0.1:8765/outputs/war-room.html?bid=vandelay-warm&speed=15` | 4 (pulse), 2, 6 |
| **D · Report** | `http://127.0.0.1:8765/outputs/report.html` | 8, 9, 10 |
| **E · Console: the warm session** | `https://platform.claude.com/sessions/<vandelay-warm session_id>` | 1, 11 |
| *(optional)* **F · Live bid** | `http://127.0.0.1:8765/outputs/war-room.html?live=live` | 1, 2 live: "this one is running right now" |

The IDs come from `outputs/deployment.json` and `outputs/*.verdict.json`. The report's footer links to every session.

### What each war-room moment looks like
```
┌ DEBRIEF · WAR ROOM   Vandelay · unseen customer · WITH lessons   [REPLAY 15×]  [Reading lessons]   4.7s ┐
│ ┌ MEMORY STORE ──────┐   ┌──────── COORDINATOR · claude-opus-5-5 ────────┐   ┌ BUYER · claude-sonnet-5-5 ─┐ │
│ │ /mnt/memory/       │   │  reading the RFP → waiting for specialists     │   │ 🔒 Criterion 1 · sealed    │ │
│ │ lessons.md         │   └───────┬───────────┬───────────┬───────────┬────┘   │ 🔒 Criterion 2 · sealed    │ │
│ │ ● read at 2.8s     │   ┌ Pricing ┐ ┌ Legal ───┐ ┌ Tech Fit ┐ ┌ Competitive┐  │ …                          │ │
│ └────────────────────┘   │ sonnet  │ │ sonnet   │ │ sonnet   │ │ haiku      │  │ ✓ Full-term total cost     │ │
│                          │ skill:  │ │ skill:   │ │          │ │ skill:     │  │   "…€X for the 4-year term"│ │
│                          │ pricing │ │ legal    │ │          │ │ competitive│  │        WON 5/5             │ │
│                          │ working │ │ working  │ │ ✓ 108s   │ │ ✓ 62s      │  └────────────────────────────┘ │
│ EVENT STREAM  69.0s delegate → Pricing …        COST PER AGENT  Opus $0.52 ▇▇▇▇  Sonnet $0.21 ▇▇  Haiku $0.04 ▏│
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Run of show (3:00)

| Time | Tab | On screen | Say | Capabilities |
|---|---|---|---|---|
| 0:00 | A | Org chart, sealed buyer | "Proposal teams lose deals and never learn why. This is a team of Claude agents that does. Each card is an agent deployed on Claude Platform, with its own model and Skill." | 1, 3, 10 |
| 0:15 | A | Four cards light up together | "The coordinator, on Opus, delegates to four specialists **in parallel**: under a second between them. Sonnet for the heavy lanes, Haiku for the quick lookup." | 2, 10 |
| 0:35 | A | Buyer flips the criteria → **LOST 3/5** | "The buyer is a separate model with a scorecard the swarm never sees. One structured pass/fail call per criterion. It lost on calendar dates and a named reference." | 6, 7 |
| 0:55 | B | `lessons.md` in the Console | "After the debrief, the agent decided what to remember. Six rules, no customer names, no figures. Rule 6, 'map each criterion to the exact proposal text', is one it came up with itself." | 4, 5 |
| 1:20 | C | Memory card pulses first, then fan-out, then buyer flips → **WON** | "New customer, new industry. Before it delegates anything, it reads its lessons. Same swarm. This time it wins." | 4, 2, 6 |
| 1:55 | D | Cards + scorecard grid + buyer quotes | "Without lessons: 'only weeks from contract'. With lessons: calendar months. Three criteria flipped. The control, which no lesson covered, didn't move." | 8, 9 |
| 2:20 | D | Trust panel + cost table | "Before any bid, the buyer had to reject a weak proposal and accept a strong one, twice. About a dollar a bid, most of the input served from prompt cache, according to the platform's own usage numbers." | 8, 10 |
| 2:40 | E | Console session threads | "All of it is a real session on Claude Platform. **Lose once. Win the next one.**" | 1, 11 |

**At speed 15**, one replay takes about 30s plus about 7s for the verdict flips. Two replays fit. If time gets tight, use `speed=25`.

### How to run the demo

**Ten minutes before:**
1. Run this from the repo folder:
   ```bash
   .venv/bin/python app.py
   ```
2. Click **Rebuild report**. It pulls fresh cost data and builds the screens.
3. Open the **Demo screens** buttons on the app page in tabs A, C and D, and log in to the Console for tabs B and E.
4. Set the browser to full screen at 1440×900 or larger.

**Optional live moment:** about 3 minutes before you go on, start a fresh bid from `build/` in a terminal:
```bash
cd build && source env.sh && python debrief.py round --rfp vandelay --buyer vandelay --label live --use-memory --quiet
```
Then open `http://127.0.0.1:8765/outputs/war-room.html?live=live` as tab F.

**Before each act,** reload the war-room tab so its replay starts from zero.

**Backup:** everything except the Console tabs is served from `build/outputs/` by the local app, so it works offline. If the network fails, skip B and E: the report's lessons panel and session IDs cover them.

---

## 4. How it works

```
 ROUND (one bid)                                                       Managed Agents session
   message = RFP + past-wins + product-overview  [+ "read /mnt/memory" when --use-memory]
   Coordinator (claude-opus-5-5)
     ├─ reads /mnt/memory/lessons.md first (warm runs only)
     ├─ delegates in ONE message, in parallel → Pricing · Legal · Technical Fit · Competitive
     │                                          (Sonnet 4.6 ×3, Haiku 4.5; Skills on 3 of 4)
     └─ writes the markdown proposal between === PROPOSAL START/END ===
   writes outputs/<label>.live.json on every event (the live war room polls it)
 JUDGE                                                                 Messages API
   buyers/<buyer>.json: persona + 5 hidden criteria
   5 parallel calls on claude-sonnet-5-5 (never the coordinator's model)
   structured output {verdict: PASS|FAIL, reason}, stop_reason checked
 EVIDENCE                                                              Managed Agents usage API
   session + per-thread usage: list cost (cents), cache reads/writes, model, Skills → verdict.json
 DEBRIEF (--learn only)                                                Managed Agents session
   Coordinator in "DEBRIEF MODE" (no delegation) gets the verdict
   updates /mnt/memory/lessons.md: ≤ 6 general rules, merged; a snapshot is saved for offline use
 SCREENS                                                               local, offline-capable
   war-room.html (replay or live) · report.html · deployment.json, via `debrief.py serve`
```

### The buyers' hidden scorecards
| # | Acme (training) | Vandelay (test) | Taught by Acme? |
|---|---|---|---|
| 1 | One total contract value for 5 years, net | One total for the 4-year term, net | ✅ |
| 2 | Dated phases incl. Teradata decommission | Dated phases incl. Exadata/SAP BW switch-off | ✅ |
| 3 | Exit: format, timeline, who pays | Exit: format, speed, who pays | ✅ |
| 4 | Named reference + reference call or PoC | Named comparable customer + pilot or call | ✅ |
| 5 | Power BI integration | **CONTROL:** 24/7 with P1 response ≤ 30 min | ❌, should stay flat |

The coordinator prompt (`kit/coordinator_system.md`) contains **none** of these criteria.

---

## 5. Why the result can be trusted

| Concern | How it's handled |
|---|---|
| A lenient judge | Calibration for both buyers: weak LOST and strong WON, stable over 2 tries ✅ |
| The model grades itself | Buyer: Sonnet 5.5. Coordinator: Opus 5.5 |
| A vague score | One PASS/FAIL per criterion, each with a quoted reason; a cut-off answer is a grader error |
| Memorising Acme | A different customer, industry, currency, term and legacy stack. Leak check on the stored lessons: PASS ✅ |
| "Better" just means more words | The control row, plus word counts shown per bid |
| Prompt tuned to the test | The coordinator prompt has no criteria; the Vandelay scorecard was written before the lessons existed |

---

## 6. Build timeline (actual)

| Step | Planned | Actual |
|---|---|---|
| Set up + environment | 0–5 min | ✅ |
| Deploy agents, Skills, coordinator, memory | 5–10 min | ✅. One fix: SDK 2.x renamed the Skills field (`display_title` → `display_name`), now patched in `kit/upload_skills.py`. The coordinator was recreated after the Skills were attached |
| Calibrate both buyers | 10–12 min | ✅ both trusted |
| Wave 1 (parallel) | 12–24 min | ✅ Acme 446s, Vandelay 351s |
| Wave 2 | 24–34 min | ✅ 369s, WON 5/5 |
| Proof + screens | 34–38 min | ✅ Now one click: `python app.py` → **Run everything** (skips finished steps) |

---

## 7. If the result isn't what we hoped

| Outcome | What to say |
|---|---|
| Warm > cold, control flat | The headline |
| Warm > cold, control moved | "Part of the gain is general effort. The control is how we can tell." |
| Warm = cold | "It read the lessons (the memory pulse shows it) but didn't apply them. Here's where in the transcript." An honest eval beats a cherry-picked one |
| Warm < cold | Show it. n = 1; rerun both arms if time allows (about $1 and 7 minutes each) |

## 8. Questions to expect from judges
- **"Isn't the debrief just giving it the answers?"** Real debriefs tell you why you lost. The test is whether that transfers to a different customer and wording, and the leak check shows no answers were copied.
- **"n = 1?"** Yes. That shows direction, not a rate. The scripts already support 3 runs per arm.
- **"Why not just write better instructions?"** You could, once you know what to write. Here the system **found** the rules itself, from a loss. Lesson 6 wasn't in any rubric.
- **"Cost?"** About $1–1.30 per bid at list price, from the platform's usage API, with most input tokens served from prompt cache.

## 9. Rules
- Synthetic data only. The key lives in `build/.env`, which is git-ignored, and is never printed or committed.
- `build/` and `outputs/` are git-ignored. Commit only the kit, the docs and a final report you've chosen to share.
