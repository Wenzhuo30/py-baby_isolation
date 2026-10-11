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

```
agentic_se/
├── main.py                       # Orchestrator: runs the whole pipeline, writes trace.log
├── brief.txt                     # Customer's natural-language brief (input)
├── analyst_agent.py              # Analyst Agent: run_analyst() + validate_requirements()
├── planner_agent.py              # Planner Agent: run_planner() + validate_plan()
├── developer_agent.py            # Developer Agent: run_developer() + run_developer_revision()
├── test_agent.py                 # Test Agent: run_test_agent() + generated pytest tests
├── runner.py                     # Simulation over all 64 perception scenarios
├── reviewer_agent.py             # Reviewer Agent for the simulation report
├── benchmark_irsim.py            # IR-SIM benchmark over every world file
├── reviewer_benchmark_agent.py   # Reviewer Agent for the benchmark report
├── test_irsim_with_agent.py      # Single-world IR-SIM entry point (visual run)
├── _irsim_runner.py              # Headless bridge used by the benchmark
├── run_visual.sh                 # ./run_visual.sh irsim_worlds/world_easy.yaml
├── irsim_worlds/                 # world_easy / world_medium / world_difficult / world_custom / world_hard
├── generated/                    # Navigation logic + generated tests (generated)
├── artifacts/                    # Requirements, plan, reports, reviews (generated)
├── trace.log                     # Full orchestration log (generated)
├── brief_to_req.py, run_*.py     # Step-by-step runners for the individual agents
├── test_analyst.py, test_planner.py, test_developer.py   # Level-1 smoke tests
├── requirements.txt, .env.example, .gitignore
└── robot_requirements.txt
```

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

## Reports and reviews

| File | Produced by | Content |
| --- | --- | --- |
| `artifacts/simulation_report.json` | `runner.py` | 64 scenarios, passed/failed, success rate, safety violations, per-scenario results |
| `artifacts/simulation_review.json` | `reviewer_agent.py` | `issue`, `likely_cause`, `recommendation`, `needs_revision` |
| `artifacts/irsim_benchmark_report.json` | `benchmark_irsim.py` | success rate, efficiency rate, average steps, per-world results |
| `artifacts/irsim_benchmark_review.json` | `reviewer_benchmark_agent.py` | `issue`, `likely_cause`, `recommendation`, `safety_passed`, `goal_completion_passed`, `efficiency_passed`, `needs_revision` |
| `trace.log` | `main.py` | every pipeline event, including the failing stages |

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
