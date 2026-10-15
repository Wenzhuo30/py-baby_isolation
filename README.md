# SCSE '26 – Agentic Software Engineering: Robot Navigation

This project builds a complete agentic software-engineering pipeline for a mobile
robot navigation component. A natural-language project brief (`brief.txt`) is
turned into validated requirements, a navigation plan, generated navigation code,
generated tests, a scenario simulation, a benchmark in realistic IR-SIM worlds and
two independent reviews — and, when a problem is found, the Developer Agent
revises the navigation logic and the whole pipeline is re-run.

Everything is orchestrated from one central location: **`main.py`**, which records
every step in **`trace.log`**.

## Pipeline

```
brief.txt
  │
  ├─ 1. Analyst Agent          analyst_agent.py            -> artifacts/requirements.json
  ├─ 2. Planner Agent          planner_agent.py            -> artifacts/plan.json
  ├─ 3. Developer Agent        developer_agent.py          -> generated/navigation_logic.py
  ├─ 4. Test Agent             test_agent.py               -> generated/test_navigation_logic.py
  ├─ 5. Simulation runner      runner.py                   -> artifacts/simulation_report.json
  ├─ 6. Reviewer Agent         reviewer_agent.py           -> artifacts/simulation_review.json
  ├─ 7. IR-SIM benchmark       benchmark_irsim.py          -> artifacts/irsim_benchmark_report.json
  ├─ 8. Benchmark Reviewer     reviewer_benchmark_agent.py -> artifacts/irsim_benchmark_review.json
  └─ 9. Developer revision     developer_agent.py          -> generated/navigation_logic_revised.py
        (re-tests and re-runs steps 3-8 with the revised logic)
```

## Project structure

The layout follows the "Overall Structure" diagram of the Requirements
Engineering instructions: every file the instructions name stays at the
repository root, and only the folders the instructions mandate (`artifacts/`,
`generated/`, `irsim_worlds/`) plus two folders added here (`tools/`, `docs/`)
are used.

```
scse_agentic_se_baby_isolation/
│
│  ── root: exactly what the instructions name ────────────────────────────
├── brief.txt                     # Customer's natural-language brief (input)
├── robot_requirements.txt        # brief_to_req.py output (RE p3)
├── main.py                       # Orchestrator: runs the whole pipeline, writes trace.log
├── analyst_agent.py              # Analyst Agent: run_analyst() + validate_requirements()
├── planner_agent.py              # Planner Agent: run_planner() + validate_plan()
├── developer_agent.py            # Developer Agent: run_developer() + run_developer_revision()
├── test_agent.py                 # Test Agent: run_test_agent() + generated pytest tests
├── runner.py                     # Simulation over all 64 perception scenarios
├── reviewer_agent.py             # Reviewer Agent for the simulation report
├── benchmark_irsim.py            # IR-SIM benchmark over every world file
├── reviewer_benchmark_agent.py   # Reviewer Agent for the benchmark report
├── test_irsim_with_agent.py      # Single-world IR-SIM entry point (given, unmodified)
├── run_visual.sh                 # ./run_visual.sh irsim_worlds/world_easy.yaml (given)
├── brief_to_req.py, run_*.py     # Step-by-step runners for the individual agents
├── test_analyst.py, test_planner.py, test_developer.py   # Level-1 agent smoke tests
├── test_generated_navigation_logic.py                    # Level-2 behavioral tests
├── experiment_bug_injection.py   # Proves the tests detect an injected fault (Testing p9)
├── requirements.txt, .env.example, .gitignore, README.md
│
│  ── generated (safe to delete; the pipeline recreates them) ─────────────
├── artifacts/                    # requirements.json, plan.json, reports, reviews
├── generated/                    # navigation_logic.py + generated test modules
├── trace.log                     # Full orchestration log
├── visuals/                      # PNG snapshots of the head-less visual run
├── irsim_worlds/                 # world_easy / medium / difficult / custom (+ hard)
│
│  ── added on top of the assignment ─────────────────────────────────────
├── tools/                        # helpers, none of them named by the instructions
│   ├── llm_client.py             #   one place resolving backend/model/credentials
│   ├── check_llm.py              #   credential + JSON-mode pre-flight check
│   ├── run_visual.py             #   same worlds; --show for the window, else PNGs
│   ├── run_visual.cmd            #   Windows equivalent of run_visual.sh
│   ├── compare_navigation_logic.py  # A/B benchmark of two navigation logics
│   └── _pdf_tool.py              #   dependency-free PDF text extractor
├── docs/                         # the course PDFs and the duplicate brief
└── scratch/                      # development leftovers (git-ignored)
```

Why the agents are **not** in an `agents/` subfolder: the instructions' structure
diagram shows `analyst_agent.py` / `run_analyst.py` at the root, the Integration
instructions say "Only the `developer_agent.py` file must be updated. Everything
else is new", and the Testing checklist names the test files without a folder.
Graders match those names, so moving them would break the expected layout.


## Setup

```bash
uv venv .venv
uv pip install -r requirements.txt        # openai (Qwen / DashScope client)
uv pip install pytest                     # used by the Test Agent to run its tests
uv pip install ir-sim                     # IR-SIM world simulation
```

Configure the Qwen API key (only needed for the LLM-backed agents) using **one**
of these methods:

- Copy `.env.example` to `.env` and paste the key:
  ```
  DASHSCOPE_API_KEY=sk-xxxxxxxx
  ```
- Or set an environment variable:
  ```bash
  # PowerShell
  $env:DASHSCOPE_API_KEY = "sk-xxxxxxxx"
  # bash
  export DASHSCOPE_API_KEY="sk-xxxxxxxx"
  ```

Without a key the pipeline still runs end to end: every agent falls back to a
deterministic implementation that follows the same contract (each fallback is
recorded in `trace.log`).

> **The graded run must have the key configured.** The Requirements Engineering
> instructions are explicit that the requirements JSON "MUST come from Qwen and
> not your Python program", so `artifacts/requirements.json` and
> `artifacts/plan.json` have to be produced by Qwen, not by the offline fallback.
>
> Check the key **before** a scored run - this one request also verifies that the
> model supports the JSON mode every agent depends on:
>
> ```bash
> python tools/check_llm.py                       # or: python tools/check_llm.py --model qwen-max
> ```
>
> It prints exactly where the key was found (environment variable or `.env`) and,
> on failure, what to do about it (401 invalid key, 404 unknown model, 400 model
> without JSON mode, network/timeout, 429 quota).
>
> `main.py` also refuses to report success when the two Qwen stages fell back:
>
> | exit code | meaning |
> | --- | --- |
> | `0` | every stage ran, `requirements.json`/`plan.json` are Qwen's output |
> | `2` | **the Analyst/Planner stages fell back** - those artifacts are NOT Qwen's output (also logged as `ATTENTION` + `error` in `trace.log`) |
> | `1` | the pipeline itself crashed |
>
> So a scoring run is only valid when `python main.py` exits `0` and
> `trace.log` shows `AnalystAgent`/`PlannerAgent` as `ok` rather than `degraded`.

### Optional: run against a local OpenAI-compatible model (Ollama)

The "Ollama and Qwen installation" practice sheet runs `qwen3:8b` on your own
machine. Two environment variables point every agent at that server instead of
DashScope, so no DashScope key is needed:

```bash
# .env
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
QWEN_MODEL=qwen3:8b
```

Then confirm the backend before relying on it, because a local model must support
the JSON mode all six agents use:

```bash
python tools/check_llm.py
```

No agent code changes: `llm_client.py` resolves the endpoint, model and credential
in exactly one place. Notes:

- **Unset `LLM_BASE_URL` to return to DashScope** - that is the default and the
  configuration the project instructions describe. `check_llm.py` prints a
  reminder whenever a local/custom backend is active.
- Expect **~1 minute per agent call** on CPU (thinking models emit a reasoning
  block first), so a full pipeline takes 10-25 minutes rather than seconds.
- Keep the model resident, otherwise Ollama unloads it between stages and a slow
  in-flight request is left hanging. Recommended for a full local run:

  ```bash
  OLLAMA_KEEP_ALIVE=-1        # or: ollama run qwen3:8b --keepalive -1
  ```

- Each request has a finite timeout (`LLM_TIMEOUT`, default 300s locally / 60s on
  DashScope). Without one, a stalled local request hangs the pipeline forever
  with no error and no progress.
- A thinking model can return an *empty* message when `max_tokens` is small,
  because its reasoning consumes the whole budget. `check_llm.py` retries with a
  larger budget instead of reporting a false failure.
- `artifacts/requirements.json` and `plan.json` are then authored by the **local**
  model. Still Qwen-family output, but the instructions describe the hosted Qwen -
  confirm before submitting such a run.

## Run the whole pipeline

```bash
python main.py                  # full pipeline + one revision round (trace.log)
python main.py --offline        # never call the LLM (deterministic fallbacks)
python main.py --rounds 0       # no revision round
python main.py --skip-irsim     # skip the slow IR-SIM stages
python main.py --quiet          # do not echo the IR-SIM sub-process output
```

`main.py` logs a line for every event (agent, action, status, duration) and ends
with a summary table. Example trace lines:

```
[2026-01-01 12:00:00] [INFO    ] [AnalystAgent      ] Analyst Agent created requirements.json
[2026-01-01 12:00:02] [INFO    ] [SimulationRunner  ] simulation report: scenarios=64 passed=64 failed=0 success_rate=1.00 safety_violations=0
[2026-01-01 12:00:20] [INFO    ] [IRSIMBenchmark    ] IR-SIM benchmark: all 5 worlds reached the goal
```

## Run the parts individually

```bash
python run_analyst.py          # brief.txt        -> artifacts/requirements.json
python run_planner.py          # requirements     -> artifacts/plan.json
python run_developer.py        # plan             -> generated/navigation_logic.py
python test_agent.py           # plan + code      -> generated/test_navigation_logic.py (+ pytest run)
python runner.py               # code             -> artifacts/simulation_report.json
python reviewer_agent.py       # simulation report-> artifacts/simulation_review.json
python benchmark_irsim.py      # all worlds       -> artifacts/irsim_benchmark_report.json
python reviewer_benchmark_agent.py   # benchmark  -> artifacts/irsim_benchmark_review.json
python tools/run_visual.py           # 4 worlds, headless -> visuals/*.png + visual_run_report.json
python experiment_bug_injection.py   # proves the tests detect an injected fault
```

## The navigation contract

Every component shares one canonical state contract.
`decide_next_move(state)` receives a dictionary with exactly six boolean keys:

```json
{
  "blocked_front": true,
  "blocked_left": false,
  "blocked_right": false,
  "goal_front": false,
  "goal_left": true,
  "goal_right": false
}
```

and returns exactly one of `"FORWARD"`, `"LEFT"`, `"RIGHT"`, `"STOP"`.
The descriptive aliases `front_blocked`, `left_blocked`, `right_blocked`,
`goal_ahead`, `goal_on_left`, `goal_on_right` are accepted as well.

The required behaviour (from the brief):

1. Never move into a blocked direction.
2. Prefer the goal direction whenever it is safe.
3. Otherwise take any safe direction (reference priority: front, left, right).
4. If no safe direction is available, `STOP`.

## Visual IR-SIM inspection

The IR-SIM worlds are simulated one after another; if the navigation logic is
correct the robot drives to its destination while avoiding the obstacles:

```bash
./run_visual.sh irsim_worlds/world_easy.yaml
./run_visual.sh irsim_worlds/world_medium.yaml
./run_visual.sh irsim_worlds/world_difficult.yaml
./run_visual.sh irsim_worlds/world_custom.yaml
```

Under WSL/Git-Bash use `bash run_visual.sh <world>`; on Windows the venv must be
active (`python` must resolve to the interpreter that has `ir-sim` installed).

**On Windows `run_visual.sh` cannot run at all** (`python3` and `bash` are not
present). Use the `.cmd` wrapper, which runs the same worlds with this venv:

```bat
tools\run_visual.cmd                :: world_easy (the .sh default)
tools\run_visual.cmd world_medium   :: one named world
tools\run_visual.cmd all            :: all four worlds, one window each
tools\run_visual.cmd all hold 5     :: ...each window auto-closed after 5s
```

Each run opens the interactive IR-SIM window and the robot drives to its goal.
Close the window to continue.

`run_visual.sh` opens the interactive matplotlib window, which cannot be looked at
from a head-less session (CI, a remote shell, an automated agent).
`run_visual.py` covers both cases:

```bash
python tools/run_visual.py                # head-less: one PNG per world, no window
python tools/run_visual.py --show         # the interactive window, like run_visual.sh
python tools/run_visual.py --hold 5       # a window per world, auto-closed after 5s
```

- `--show` / `--hold` open the **same** window the provided script does. Note that
  `test_irsim_with_agent.py` calls `env.end()` (which closes the figure) *before*
  its own `plt.show()`, so that `show()` normally has nothing left to display.
  Both flags keep the figure alive across `end()` so the popup really appears.
- Head-less mode (`python tools/run_visual.py`, no flags) writes
  `visuals/world_easy.png` … and is what the automated benchmark uses, because a
  batch or CI run must not block on a window.

Neither `run_visual.sh` nor `test_irsim_with_agent.py` is modified: `run_visual.py`
only wraps `irsim.make`/`env.end` for the duration of the call. `visuals/` is
regenerable build output and is git-ignored, like the other reports.

## Reports and reviews

| File | Produced by | Content |
| --- | --- | --- |
| `artifacts/simulation_report.json` | `runner.py` | 64 scenarios, passed/failed, success rate, safety violations, per-scenario results |
| `artifacts/simulation_review.json` | `reviewer_agent.py` | `issue`, `likely_cause`, `recommendation`, `needs_revision` |
| `artifacts/irsim_benchmark_report.json` | `benchmark_irsim.py` | success rate, efficiency rate, average steps, per-world results |
| `artifacts/irsim_benchmark_review.json` | `reviewer_benchmark_agent.py` | `issue`, `likely_cause`, `recommendation`, `safety_passed`, `goal_completion_passed`, `efficiency_passed`, `needs_revision` |
| `artifacts/test_results.json` | `test_agent.py` | passed/failed/errors of the generated pytest run + the exact pytest command |
| `artifacts/bug_injection_experiment.json` | `experiment_bug_injection.py` | evidence that the tests detect an injected fault (see below) |
| `artifacts/navigation_logic.py` | `test_developer.py` | the documented `artifacts/` copy of the generated logic, kept byte-identical by `developer_agent.refresh_artifact_copy()` |
| `trace.log` | `main.py` | every pipeline event, including the failing stages |

### The requirements artifact

`artifacts/requirements.json` uses exactly the four keys the instructions specify,
and `allowed_actions` holds only the four valid actions and nothing extra:

```json
{
  "goal": "navigate toward the goal location",
  "allowed_actions": ["FORWARD", "LEFT", "RIGHT", "STOP"],
  "safe_stop": true,
  "avoid_obstacles": true
}
```

`analyst_agent.validate_requirements()` rejects both missing keys and any key that
Qwen invents, so the artifact cannot silently drift away from this structure.

### Testing strategy

Two levels, as required:

- **Level 1 – agent/pipeline smoke tests** (`test_analyst.py`, `test_planner.py`,
  `test_developer.py`): run the real agents on the real artifacts and let each
  agent's own validation accept or reject the output. The tests use real
  assertions, so a broken agent fails the test instead of only printing text.
  These three need `DASHSCOPE_API_KEY`; without it they are reported as **skipped**
  (loudly, with the reason) because the agents cannot run at all. The pipeline
  itself still runs offline through the deterministic fallbacks in `main.py`.
- **Level 2 – behavioral tests** (`test_generated_navigation_logic.py`): calls
  `decide_next_move(state)` with known states and checks both that the action is
  valid and that it is the expected move. The same cases work as a printed
  PASS/FAIL report (`python test_generated_navigation_logic.py`) and as pytest
  tests.
- The Test Agent additionally generates `generated/test_navigation_logic.py`,
  which sweeps all 64 perception states.

```bash
python -m pytest test_analyst.py test_planner.py test_developer.py \
                  test_generated_navigation_logic.py generated/test_navigation_logic.py -v
```

Each root-level test file also still runs on its own as a script
(`python test_developer.py`), which prints everything and exits non-zero on
failure, so both ways of running them agree.

### Do the tests actually catch bugs?

Yes — this is verified automatically instead of being asserted in prose
(Testing instructions, page 9). `experiment_bug_injection.py` runs the tests on
the correct logic, injects a realistic fault into `generated/navigation_logic.py`
(the "goal is to the left and the left path is clear" branch returns `STOP`
instead of `LEFT`), shows the tests failing, removes the fault and shows them
passing again:

```bash
python experiment_bug_injection.py
```

The injected fault is deliberately **safe** — stopping never moves into a blocked
direction, so the final safety guard inside `decide_next_move` accepts it. It can
only be caught by comparing the returned action against the expected one, which is
exactly what the behavioral tests do. (An earlier attempt injected `RIGHT` instead
of `LEFT` and the guard rejected it and re-picked a safe direction, which is why
the experiment records the safety-guard behaviour as well.) The full record of
every step, including the pytest summaries, is written to
`artifacts/bug_injection_experiment.json`.

### Benchmark metrics

- **Success rate** = goals reached / total worlds
- **Efficiency rate** = efficient worlds / total worlds
  (a world above the efficient step limit of 200 steps counts as
  *successful but inefficient*; 300 steps is the hard limit)
- **Average steps** = total steps / total worlds

### Revision loop

`run_developer_revision()` in `developer_agent.py` receives the original
navigation code, the simulation review notes, the benchmark report, the
requirements **and** the plan, asks the LLM for new navigation logic, validates it
against all 64 scenarios and saves it as `generated/navigation_logic_revised.py`.
`main.py` then re-runs the Test Agent, the simulation, the Reviewer Agent and the
complete IR-SIM benchmark on the revised logic.

## Notes

- `test_irsim_with_agent.py` is the provided single-world visual entry point; the
  automated benchmark calls it through `_irsim_runner.py`, which only forces the
  non-interactive matplotlib backend so the five worlds can be measured in a batch.
- A stray `__pycache__/navigation_logic.cpython-*.pyc` from an earlier run can be
  ignored; the generated sources are always re-imported by path.

.\.venv\Scripts\python.exe tools\run_visual.py --show