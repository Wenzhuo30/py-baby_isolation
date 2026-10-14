"""
main.py
=======
The Orchestrator: runs the complete agentic pipeline from one central location
and records everything in ``trace.log``.

Pipeline (every step is logged):

    1. load the brief                         (brief.txt)
    2. Analyst Agent                          -> artifacts/requirements.json
    3. Planner Agent                          -> artifacts/plan.json
    4. Developer Agent                        -> generated/navigation_logic.py
    5. Test Agent                             -> generated/test_navigation_logic.py
    6. Simulation runner                      -> artifacts/simulation_report.json
    7. Reviewer Agent                         -> artifacts/simulation_review.json
    8. IR-SIM benchmark                       -> artifacts/irsim_benchmark_report.json
    9. Benchmark Reviewer                     -> artifacts/irsim_benchmark_review.json
   10. Developer revision (optional, repeats 4-9 with the revised navigation
       logic)                                 -> generated/navigation_logic_revised.py
                                              -> artifacts/*_revised.json

Usage:
    python main.py                     # full pipeline (+ 1 revision round)
    python main.py --offline           # deterministic fallbacks, no LLM calls
    python main.py --rounds 0          # full pipeline, no revision
    python main.py --rounds 2          # up to two revision rounds
    python main.py --skip-irsim        # skip the (slow) IR-SIM benchmark stages
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ARTIFACTS_DIR = os.path.join(HERE, "artifacts")
GENERATED_DIR = os.path.join(HERE, "generated")
BRIEF_PATH = os.path.join(HERE, "brief.txt")
TRACE_PATH = os.path.join(HERE, "trace.log")

REQUIREMENTS_PATH = os.path.join(ARTIFACTS_DIR, "requirements.json")
PLAN_PATH = os.path.join(ARTIFACTS_DIR, "plan.json")
SIMULATION_REPORT_PATH = os.path.join(ARTIFACTS_DIR, "simulation_report.json")
SIMULATION_REVIEW_PATH = os.path.join(ARTIFACTS_DIR, "simulation_review.json")
BENCHMARK_REPORT_PATH = os.path.join(ARTIFACTS_DIR, "irsim_benchmark_report.json")
BENCHMARK_REVIEW_PATH = os.path.join(ARTIFACTS_DIR, "irsim_benchmark_review.json")

NAVIGATION_PATH = os.path.join(GENERATED_DIR, "navigation_logic.py")
REVISED_NAVIGATION_PATH = os.path.join(GENERATED_DIR, "navigation_logic_revised.py")
GENERATED_TEST_PATH = os.path.join(GENERATED_DIR, "test_navigation_logic.py")

SIMULATION_REPORT_REVISED_PATH = os.path.join(ARTIFACTS_DIR, "simulation_report_revised.json")
SIMULATION_REVIEW_REVISED_PATH = os.path.join(ARTIFACTS_DIR, "simulation_review_revised.json")
BENCHMARK_REPORT_REVISED_PATH = os.path.join(ARTIFACTS_DIR, "irsim_benchmark_report_revised.json")
BENCHMARK_REVIEW_REVISED_PATH = os.path.join(ARTIFACTS_DIR, "irsim_benchmark_review_revised.json")
GENERATED_TEST_REVISED_PATH = os.path.join(GENERATED_DIR, "test_navigation_logic_revised.py")

# ---------------------------------------------------------------------------
# Trace log
# ---------------------------------------------------------------------------
_TEE = None


class _Tee:
    """Write everything to the console and to trace.log at the same time."""

    def __init__(self, path):
        self.terminal = sys.stdout
        self.log = open(path, "a", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()

    def flush(self):
        try:
            self.terminal.flush()
        except Exception:
            pass
        self.log.flush()


def start_trace(reset=True):
    """Start capturing everything (print included) into trace.log."""
    global _TEE
    os.makedirs(os.path.dirname(TRACE_PATH), exist_ok=True)
    if reset:
        with open(TRACE_PATH, "w", encoding="utf-8") as handle:
            handle.write("")
    _TEE = _Tee(TRACE_PATH)
    sys.stdout = _TEE
    return _TEE


def stop_trace():
    global _TEE
    if _TEE is not None:
        try:
            _TEE.flush()
            _TEE.log.close()
        finally:
            sys.stdout = _TEE.terminal
            _TEE = None


def log(message, level="INFO", stage="main"):
    """Append one trace line."""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("[%s] [%-8s] [%-18s] %s" % (stamp, level, stage, message))


STAGES = []


class stage:
    """Context manager that traces one pipeline stage."""

    def __init__(self, name, description=""):
        self.name = name
        self.description = description
        self.record = {
            "stage": name,
            "description": description,
            "status": "running",
            "message": "",
            "seconds": 0.0,
            "artifacts": [],
        }

    def __enter__(self):
        STAGES.append(self.record)
        log("%s: start %s" % (self.name, self.description), stage=self.name)
        self.started = time.time()
        return self

    def __getitem__(self, key):
        return self.record[key]

    def __setitem__(self, key, value):
        self.record[key] = value

    def get(self, key, default=None):
        return self.record.get(key, default)

    def artifact(self, path):
        self.record["artifacts"].append(os.path.relpath(os.path.abspath(path), HERE))
        return path

    def mark(self, status, message=""):
        self.record["status"] = status
        if message:
            log(message, level=status.upper(), stage=self.name)
        return self.record

    def __exit__(self, exc_type, exc_value, traceback):
        self.record["seconds"] = round(time.time() - self.started, 2)
        if exc_type is not None:
            self.record["status"] = "failed"
            self.record["message"] = "%s: %s" % (exc_type.__name__, exc_value)
            log("%s: FAILED after %.2fs - %s" % (self.name, self.record["seconds"],
                                                 self.record["message"]),
                level="error", stage=self.name)
            return True  # a failing stage must not abort the whole pipeline
        if self.record["status"] == "running":
            self.record["status"] = "ok"
            self.record["message"] = "completed"
        log("%s: %s (%.2fs)" % (self.name, self.record["status"].upper(),
                                self.record["seconds"]), stage=self.name)
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def ensure_directories():
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    os.makedirs(GENERATED_DIR, exist_ok=True)
    log("directories ready: artifacts/, generated/", stage="setup")


def read_brief():
    with open(BRIEF_PATH, "r", encoding="utf-8") as handle:
        return handle.read().strip()


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False, default=str)
        handle.write("\n")
    return path


def read_text(path, default=""):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return default


def llm_available():
    """True when a DashScope API key is configured (.env file or environment)."""
    from analyst_agent import _load_env_file

    _load_env_file()
    return bool(os.getenv("DASHSCOPE_API_KEY"))


def require_navigation_logic(path, fallback_path=None):
    """Guard used between stages: make sure a navigation logic file exists.

    A failed stage must not abort the whole pipeline, but the following stages
    still need a file to work with. In that case the previous artifact (or the
    deterministic reference implementation) is used and the fallback is traced.
    """
    if path and os.path.exists(path):
        return path

    if fallback_path and os.path.exists(fallback_path):
        log("no fresh navigation logic available; reusing %s"
            % os.path.relpath(fallback_path, HERE), level="warn", stage="setup")
        return fallback_path

    from developer_agent import build_fallback_navigation_code, write_navigation_logic

    log("no navigation logic available; using the deterministic reference "
        "implementation", level="warn", stage="setup")
    return write_navigation_logic(
        build_fallback_navigation_code(read_json(PLAN_PATH, {}) or {}),
        NAVIGATION_PATH,
    )


def summarize_report(report):
    """Short human readable summary of a simulation or benchmark report."""
    if not isinstance(report, dict):
        return "no report"
    if "total_scenarios" in report:
        return ("scenarios=%s passed=%s failed=%s success_rate=%.2f safety_violations=%s"
                % (report.get("total_scenarios"), report.get("passed_scenarios"),
                   report.get("failed_scenarios"), report.get("success_rate", 0.0),
                   report.get("safety_violations", 0)))
    if "total_worlds" in report:
        return ("worlds=%s goals=%s success_rate=%.2f efficiency_rate=%.2f avg_steps=%.1f"
                % (report.get("total_worlds"), report.get("goals_reached"),
                   report.get("success_rate", 0.0), report.get("efficiency_rate", 0.0),
                   report.get("average_steps_taken", 0.0)))
    return json.dumps(report, ensure_ascii=False)[:200]


# ---------------------------------------------------------------------------
# Deterministic fallbacks for the LLM stages
# ---------------------------------------------------------------------------
def offline_requirements(brief_text):
    """Deterministic Analyst fallback: requirements derived from the brief."""
    log("LLM unavailable -> reusing/building deterministic requirements", level="warn",
        stage="AnalystAgent")
    return {
        "goal": "navigate toward the goal location",
        "allowed_actions": ["FORWARD", "LEFT", "RIGHT", "STOP"],
        "safe_stop": True,
        "avoid_obstacles": True,
        "_source": "offline fallback (brief.txt + rule 1-4 of the brief)",
        "_brief_excerpt": " ".join(brief_text.split())[:200],
    }


def offline_plan(requirements):
    """Deterministic Planner fallback: plan derived from the requirements."""
    log("LLM unavailable -> reusing/building deterministic plan", level="warn",
        stage="PlannerAgent")
    return {
        "strategy": ("The robot prefers moving toward its goal whenever that direction "
                     "is safe. It never moves into a blocked direction. When no goal "
                     "direction is safe it takes any safe direction (front, then left, "
                     "then right). When no direction is safe it stops."),
        "decisions": ["FORWARD", "LEFT", "RIGHT", "STOP"],
        "stop_point": ("The robot must stop when the path in front, to the left and to "
                       "the right is blocked, i.e. when no safe direction is available."),
        "_source": "offline fallback (derived from requirements.json)",
    }


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------
def run_analyst_stage(brief_text, use_llm=True):
    """Stage: brief -> validated requirements."""
    from analyst_agent import run_analyst, validate_requirements

    with stage("AnalystAgent", "brief -> requirements") as current:
        if use_llm:
            try:
                requirements = run_analyst(brief_text)
                current.mark("ok", "Analyst Agent created requirements.json")
            except Exception as error:
                current.mark("degraded", "Analyst Agent failed (%s); using the "
                                         "deterministic fallback" % error)
                requirements = offline_requirements(brief_text)
        else:
            requirements = offline_requirements(brief_text)
            current.mark("degraded", "Analyst Agent skipped the LLM (offline mode); "
                                     "built requirements.json from the brief")

        requirements = validate_requirements(
            {key: value for key, value in requirements.items() if not key.startswith("_")}
        )
        write_json(REQUIREMENTS_PATH, requirements)
        current.artifact(REQUIREMENTS_PATH)
        log("requirements: %s" % json.dumps(requirements, ensure_ascii=False),
            stage="AnalystAgent")
        return requirements


def run_planner_stage(requirements, use_llm=True):
    """Stage: requirements -> validated plan."""
    from planner_agent import run_planner, validate_plan

    with stage("PlannerAgent", "requirements -> plan") as current:
        if use_llm:
            try:
                plan = run_planner(requirements)
                current.mark("ok", "Planner Agent created plan.json")
            except Exception as error:
                current.mark("degraded", "Planner Agent failed (%s); using the "
                                         "deterministic fallback" % error)
                plan = offline_plan(requirements)
        else:
            plan = offline_plan(requirements)
            current.mark("degraded", "Planner Agent skipped the LLM (offline mode); "
                                     "built plan.json from the requirements")

        plan = validate_plan({key: value for key, value in plan.items()
                              if not key.startswith("_")})
        write_json(PLAN_PATH, plan)
        current.artifact(PLAN_PATH)
        log("plan strategy: %s" % plan.get("strategy"), stage="PlannerAgent")
        return plan


def run_developer_stage(plan, use_llm=True, output_path=NAVIGATION_PATH,
                        original_code=None, review_notes=None, benchmark_report=None,
                        benchmark_review=None, requirements=None, label="DeveloperAgent"):
    """Stage: plan -> navigation logic (initial generation or revision)."""
    from developer_agent import (run_developer, run_developer_revision,
                                 validate_navigation_behaviour, write_navigation_logic)

    description = ("plan -> navigation logic" if original_code is None
                   else "original logic + reviews + benchmark -> revised navigation logic")

    with stage(label, description) as current:
        if original_code is None:
            code = run_developer(plan, use_llm=use_llm)
        else:
            code = run_developer_revision(
                original_code=original_code,
                review_notes=review_notes,
                benchmark_report=benchmark_report,
                requirements=requirements,
                plan=plan,
                benchmark_review=benchmark_review,
                use_llm=use_llm,
            )

        evaluation = validate_navigation_behaviour(code)
        if not evaluation["safe"]:
            raise RuntimeError("navigation logic failed the behaviour check: %s"
                               % "; ".join(evaluation["problems"][:3]))

        written = write_navigation_logic(code, output_path)
        current.artifact(written)
        log("navigation logic: %s (safe=%s, reference match %d/%d scenarios)"
            % (os.path.relpath(written, HERE), evaluation["safe"],
               evaluation["reference_matches"], evaluation["total_scenarios"]),
            stage=label)
        if not evaluation["matches_reference"]:
            current.mark("degraded", "logic is safe but differs from the reference "
                                     "policy in %d scenario(s)"
                         % (evaluation["total_scenarios"] - evaluation["reference_matches"]))
        else:
            current.mark("ok", "Developer Agent created %s" % os.path.basename(written))
        return written


def run_test_agent_stage(requirements, plan, navigation_path, use_llm=True,
                         test_path=GENERATED_TEST_PATH, label="TestAgent",
                         results_path=None):
    """Stage: requirements + plan + navigation logic -> generated tests."""
    from test_agent import generate_and_run_tests

    if results_path is None:
        results_path = os.path.join(ARTIFACTS_DIR, "test_results.json")

    with stage(label, "requirements + plan + decide_next_move -> pytest tests") as current:
        navigation_code = read_text(navigation_path)
        outcome = generate_and_run_tests(
            requirements, plan, navigation_code, test_path=test_path
        )
        results = outcome["results"]
        write_json(results_path,
                   {"navigation_logic": os.path.relpath(navigation_path, HERE),
                    "target": os.path.relpath(navigation_path, HERE), **results})
        current.artifact(outcome["test_path"])
        current.artifact(results_path)
        log("Test Agent created %s -> %s passed, %s failed, %s error(s)"
            % (outcome["test_path"], results["passed"], results["failed"],
               results["errors"]), stage=label)
        if results["status"] != "PASSED":
            current.mark("degraded", "Test Agent: generated tests reported failures")
        else:
            current.mark("ok", "Test Agent created %s (all tests passed)"
                         % os.path.basename(test_path))
        return outcome


def run_simulation_stage(navigation_path, report_path=SIMULATION_REPORT_PATH,
                         label="SimulationRunner"):
    """Stage: run decide_next_move against all possible scenarios."""
    from runner import load_navigation_callable, run_simulation, save_simulation_report

    with stage(label, "run decide_next_move against all 64 scenarios") as current:
        navigation_fn = load_navigation_callable(navigation_path)
        report, _ = run_simulation(navigation_fn=navigation_fn,
                                   navigation_path=navigation_path)
        written = save_simulation_report(report, report_path)
        current.artifact(written)
        log("simulation report: %s" % summarize_report(report), stage=label)
        if report["status"] != "PASSED":
            current.mark("degraded", "simulation found %d failing scenario(s)"
                         % report["failed_scenarios"])
        else:
            current.mark("ok", "simulation passed all %d scenarios"
                         % report["total_scenarios"])
        return report


def run_reviewer_stage(simulation_report, use_llm=True,
                       review_path=SIMULATION_REVIEW_PATH, label="ReviewerAgent"):
    """Stage: review the simulation report."""
    from reviewer_agent import run_reviewer, save_review

    with stage(label, "simulation report -> review notes") as current:
        review = run_reviewer(simulation_report, use_llm=use_llm)
        written = save_review(review, review_path)
        current.artifact(written)
        log("review: needs_revision=%s issue=%s"
            % (review["needs_revision"], review["issue"]), stage=label)
        current.mark("ok", "Reviewer Agent created %s" % os.path.basename(review_path))
        return review


def run_benchmark_stage(navigation_path, world_files=None,
                        report_path=BENCHMARK_REPORT_PATH, label="IRSIMBenchmark",
                        verbose=True):
    """Stage: IR-SIM benchmark over every world file."""
    from benchmark_irsim import (print_report, run_benchmark,
                                 save_benchmark_report, resolve_world_files)

    with stage(label, "IR-SIM benchmark over all worlds") as current:
        worlds = resolve_world_files(world_files)
        log("worlds to simulate: %s" % ", ".join(worlds), stage=label)
        if not worlds:
            raise RuntimeError("no IR-SIM world file found in irsim_worlds/")

        benchmark_report = run_benchmark(world_files=worlds,
                                         navigation_path=navigation_path,
                                         verbose=verbose)
        written = save_benchmark_report(benchmark_report, report_path)
        current.artifact(written)
        print_report(benchmark_report)
        if benchmark_report["goals_reached"] != benchmark_report["total_worlds"]:
            current.mark("degraded", "IR-SIM benchmark: %d/%d worlds reached the goal"
                         % (benchmark_report["goals_reached"],
                            benchmark_report["total_worlds"]))
        else:
            current.mark("ok", "IR-SIM benchmark: all %d worlds reached the goal"
                         % benchmark_report["total_worlds"])
        return benchmark_report


def run_benchmark_reviewer_stage(benchmark_report, use_llm=True,
                                 review_path=BENCHMARK_REVIEW_PATH,
                                 label="BenchmarkReviewer"):
    """Stage: review the benchmark report against the quality requirements."""
    from reviewer_benchmark_agent import run_benchmark_reviewer, save_review

    with stage(label, "benchmark report -> quality review") as current:
        review = run_benchmark_reviewer(benchmark_report, use_llm=use_llm)
        written = save_review(review, review_path)
        current.artifact(written)
        log("quality review: safety=%s goal_completion=%s efficiency=%s "
            "needs_revision=%s"
            % (review["safety_passed"], review["goal_completion_passed"],
               review["efficiency_passed"], review["needs_revision"]), stage=label)
        log("issue: %s" % review["issue"], stage=label)
        if review["needs_revision"]:
            current.mark("degraded", "Benchmark Reviewer recommends a revision")
        else:
            current.mark("ok", "Benchmark Reviewer accepted the benchmark")
        return review


# ---------------------------------------------------------------------------
# Revision round
# ---------------------------------------------------------------------------
def revision_needed(simulation_report, benchmark_review, benchmark_report):
    """Decide whether the navigation logic must be revised."""
    if simulation_report and simulation_report.get("failed_scenarios"):
        return True, "simulation reported %d failing scenario(s)" % simulation_report["failed_scenarios"]
    if benchmark_review and benchmark_review.get("needs_revision"):
        return True, "benchmark review flagged the quality gates"
    if benchmark_report and benchmark_report.get("goals_reached", 0) < benchmark_report.get("total_worlds", 0):
        return True, "not every IR-SIM world reached the goal"
    return False, "simulation and benchmark both passed"


def run_revision_round(round_number, requirements, plan, original_code, review_notes,
                       benchmark_report, benchmark_review, use_llm, skip_irsim,
                       verbose=True):
    """Run the revision stage and re-run the pipeline on the revised logic."""
    log("revision round %d: %s" % (round_number, "starting"), stage="Revision")

    revised_path = run_developer_stage(
        plan=plan,
        use_llm=use_llm,
        output_path=REVISED_NAVIGATION_PATH,
        original_code=original_code,
        review_notes=review_notes,
        benchmark_report=benchmark_report,
        benchmark_review=benchmark_review,
        requirements=requirements,
        label="DeveloperRevision",
    )

    revised_code = read_text(revised_path)

    # Re-test the new navigation logic ...
    run_test_agent_stage(requirements, plan, revised_path, use_llm=use_llm,
                         test_path=GENERATED_TEST_REVISED_PATH,
                         results_path=os.path.join(ARTIFACTS_DIR,
                                                   "test_results_revised.json"),
                         label="TestAgentRevised")

    # ... and re-run everything else, including the IR-SIM simulation.
    simulation_report = run_simulation_stage(
        revised_path, report_path=SIMULATION_REPORT_REVISED_PATH,
        label="SimulationRunnerRevised"
    )
    simulation_review = run_reviewer_stage(
        simulation_report, use_llm=use_llm, review_path=SIMULATION_REVIEW_REVISED_PATH,
        label="ReviewerAgentRevised"
    )
    benchmark_report = benchmark_review = None
    if not skip_irsim:
        from benchmark_irsim import resolve_world_files
        benchmark_report = run_benchmark_stage(
            revised_path, world_files=resolve_world_files(),
            report_path=BENCHMARK_REPORT_REVISED_PATH, label="IRSIMBenchmarkRevised",
            verbose=verbose
        )
        benchmark_review = run_benchmark_reviewer_stage(
            benchmark_report, use_llm=use_llm, review_path=BENCHMARK_REVIEW_REVISED_PATH,
            label="BenchmarkReviewerRevised"
        )

    return {
        "code": revised_code,
        "path": revised_path,
        "simulation_report": simulation_report,
        "simulation_review": simulation_review,
        "benchmark_report": benchmark_report,
        "benchmark_review": benchmark_review,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the complete agentic robot-navigation pipeline "
                    "(analyst -> planner -> developer -> test -> simulation -> "
                    "review -> IR-SIM benchmark -> benchmark review -> revision)."
    )
    parser.add_argument("--offline", action="store_true",
                        help="never call the LLM; use the deterministic fallbacks")
    parser.add_argument("--rounds", type=int, default=1,
                        help="maximum number of revision rounds (default 1)")
    parser.add_argument("--skip-irsim", action="store_true",
                        help="skip the IR-SIM benchmark stages (fast smoke run)")
    parser.add_argument("--quiet", action="store_true",
                        help="do not echo the sub-process output of the IR-SIM runs")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    use_llm = not args.offline

    start_trace(reset=True)
    started = time.time()
    log("=" * 78)
    log("AGENTIC PIPELINE START (orchestrator: main.py)")
    log("=" * 78)
    log("working directory: %s" % HERE)
    log("log file         : %s" % TRACE_PATH)
    log("llm enabled      : %s%s" % (use_llm, "" if use_llm else " (offline mode)"))
    log("revision rounds  : %d" % args.rounds)
    log("ir-sim benchmark : %s" % ("skipped" if args.skip_irsim else "enabled"))

    try:
        ensure_directories()

        if use_llm and not llm_available():
            use_llm = False
            log("DASHSCOPE_API_KEY not found -> falling back to the deterministic "
                "agent implementations (the LLM prompts are still used when a key "
                "is configured in .env)", level="warn", stage="setup")

        # 1. load the brief ---------------------------------------------------
        with stage("LoadBrief", "read brief.txt") as current:
            brief_text = read_brief()
            current.artifact(BRIEF_PATH)
            log("brief loaded (%d characters)" % len(brief_text), stage="LoadBrief")
            log(brief_text.replace("\n", " "), stage="LoadBrief")
            current.mark("ok", "brief loaded from brief.txt")

        # 2. analyst ----------------------------------------------------------
        try:
            requirements = run_analyst_stage(brief_text, use_llm=use_llm)
        except Exception:
            requirements = offline_requirements(brief_text)
            write_json(REQUIREMENTS_PATH, requirements)
            log("analyst stage failed -> using the deterministic requirements",
                level="warn", stage="AnalystAgent")

        # 3. planner ----------------------------------------------------------
        try:
            plan = run_planner_stage(requirements, use_llm=use_llm)
        except Exception:
            plan = offline_plan(requirements)
            write_json(PLAN_PATH, plan)
            log("planner stage failed -> using the deterministic plan",
                level="warn", stage="PlannerAgent")

        # 4. developer --------------------------------------------------------
        try:
            navigation_path = run_developer_stage(plan, use_llm=use_llm)
        except Exception:
            navigation_path = None
            log("developer stage failed", level="error", stage="DeveloperAgent")
        navigation_path = require_navigation_logic(navigation_path, NAVIGATION_PATH)

        # 5. test agent -------------------------------------------------------
        try:
            run_test_agent_stage(requirements, plan, navigation_path, use_llm=use_llm)
        except Exception as error:
            log("test agent stage failed: %s" % error, level="error", stage="TestAgent")

        # 6. simulation -------------------------------------------------------
        try:
            simulation_report = run_simulation_stage(navigation_path)
        except Exception as error:
            log("simulation stage failed: %s" % error, level="error",
                stage="SimulationRunner")
            simulation_report = {"total_scenarios": 0, "passed_scenarios": 0,
                                 "failed_scenarios": 0, "success_rate": 0.0,
                                 "status": "FAILED", "failed_details": []}

        # 7. reviewer ---------------------------------------------------------
        try:
            simulation_review = run_reviewer_stage(simulation_report, use_llm=use_llm)
        except Exception as error:
            from reviewer_agent import build_deterministic_review

            log("reviewer stage failed: %s" % error, level="error", stage="ReviewerAgent")
            simulation_review = build_deterministic_review(simulation_report)
            write_json(SIMULATION_REVIEW_PATH, simulation_review)

        # 8/9. IR-SIM benchmark and its review --------------------------------
        benchmark_report = benchmark_review = None
        if args.skip_irsim:
            with stage("IRSIMBenchmark", "IR-SIM benchmark") as current:
                current.mark("skipped", "IR-SIM benchmark skipped (--skip-irsim)")
        else:
            try:
                benchmark_report = run_benchmark_stage(navigation_path,
                                                       verbose=not args.quiet)
            except Exception as error:
                log("IR-SIM benchmark stage failed: %s" % error, level="error",
                    stage="IRSIMBenchmark")
            if benchmark_report is not None:
                try:
                    benchmark_review = run_benchmark_reviewer_stage(benchmark_report,
                                                                    use_llm=use_llm)
                except Exception as error:
                    from reviewer_benchmark_agent import build_deterministic_review

                    log("benchmark reviewer stage failed: %s" % error, level="error",
                        stage="BenchmarkReviewer")
                    benchmark_review = build_deterministic_review(benchmark_report)
                    write_json(BENCHMARK_REVIEW_PATH, benchmark_review)

        # 10. revision --------------------------------------------------------
        current_code = read_text(navigation_path)
        revision_notes = simulation_review
        rounds_done = 0
        for round_number in range(1, max(args.rounds, 0) + 1):
            needed, reason = revision_needed(simulation_report, benchmark_review,
                                             benchmark_report)
            log("revision check: needed=%s (%s)" % (needed, reason), stage="Revision")

            try:
                outcome = run_revision_round(
                    round_number=round_number,
                    requirements=requirements,
                    plan=plan,
                    original_code=current_code,
                    review_notes=revision_notes,
                    benchmark_report=benchmark_report,
                    benchmark_review=benchmark_review,
                    use_llm=use_llm,
                    skip_irsim=args.skip_irsim,
                    verbose=not args.quiet,
                )
            except Exception as error:
                log("revision round %d failed: %s" % (round_number, error),
                    level="error", stage="Revision")
                break

            rounds_done += 1
            current_code = outcome["code"]
            revision_notes = outcome["simulation_review"]
            previous_report = simulation_report
            simulation_report = outcome["simulation_report"]
            if outcome["benchmark_report"] is not None:
                benchmark_report = outcome["benchmark_report"]
                benchmark_review = outcome["benchmark_review"]

            log("revision round %d finished: simulation %s -> %s"
                % (round_number, summarize_report(previous_report),
                   summarize_report(simulation_report)), stage="Revision")
            if benchmark_report:
                log("revision round %d benchmark: %s"
                    % (round_number, summarize_report(benchmark_report)), stage="Revision")

        # summary -------------------------------------------------------------
        log("=" * 78)
        log("PIPELINE SUMMARY")
        log("=" * 78)
        for record in STAGES:
            log("%-26s %-9s %6.2fs  %s" % (record["stage"], record["status"],
                                           record["seconds"], record["message"]))
        log("-" * 78)
        log("artifacts:")
        for path in (REQUIREMENTS_PATH, PLAN_PATH, NAVIGATION_PATH, GENERATED_TEST_PATH,
                     SIMULATION_REPORT_PATH, SIMULATION_REVIEW_PATH,
                     BENCHMARK_REPORT_PATH, BENCHMARK_REVIEW_PATH,
                     REVISED_NAVIGATION_PATH, SIMULATION_REPORT_REVISED_PATH,
                     BENCHMARK_REPORT_REVISED_PATH):
            if os.path.exists(path):
                log("  %s" % os.path.relpath(path, HERE))
        log("-" * 78)
        log("simulation : %s" % summarize_report(simulation_report))
        if benchmark_report:
            log("benchmark  : %s" % summarize_report(benchmark_report))
        log("revision rounds executed: %d" % rounds_done)
        log("total runtime: %.2fs" % (time.time() - started))
        log("full trace   : %s" % TRACE_PATH)
        log("=" * 78)
        log("AGENTIC PIPELINE END")
    except Exception as error:
        log("PIPELINE ERROR: %s: %s" % (type(error).__name__, error),
            level="error", stage="main")
        import traceback

        traceback.print_exc()
    finally:
        stop_trace()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
