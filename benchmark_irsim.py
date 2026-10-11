"""
benchmark_irsim.py
==================
Automated IR-SIM benchmark for the navigation logic produced by the Developer
Agent.

Every world file in ``irsim_worlds/`` is loaded one by one by calling
``test_irsim_with_agent.py`` (through ``_irsim_runner.py``, which only forces
the non-interactive matplotlib backend). The per-world IR-SIM report is
extracted from that run and aggregated into a benchmark report:

    total_worlds
    goals_reached                     -> Success Rate
    success_rate                      = goals_reached / total_worlds
    efficient_worlds                  -> Efficiency Rate
    inefficient_success_worlds
    failed_worlds
    efficiency_rate                   = efficient_worlds / total_worlds
    average_steps_taken               = total steps / total_worlds
    results                           -> per-world reports

The summary is saved to ``artifacts/irsim_benchmark_report.json`` and printed
in a readable format.

Public API:
    resolve_world_files(...)        -> list of existing world files
    run_single_world(world_file)    -> (report dict, raw output)
    run_benchmark(...)              -> benchmark report (dict)
    save_benchmark_report(report)   -> path
"""

import ast
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ARTIFACTS_DIR = os.path.join(HERE, "artifacts")
BENCHMARK_REPORT_PATH = os.path.join(ARTIFACTS_DIR, "irsim_benchmark_report.json")

# The world a single run writes its per-world report to (test_irsim_with_agent.py).
PER_WORLD_REPORT_PATH = os.path.join(ARTIFACTS_DIR, "irsim_report.json")

IRSIM_TEST_SCRIPT = "test_irsim_with_agent.py"
IRSIM_RUNNER = "_irsim_runner.py"
NAVIGATION_LOGIC = os.path.join("generated", "navigation_logic.py")

# The four difficulty levels of the brief, one after another, followed by the
# extra "hard" world shipped with the template repository.
WORLD_FILES = (
    os.path.join("irsim_worlds", "world_easy.yaml"),
    os.path.join("irsim_worlds", "world_medium.yaml"),
    os.path.join("irsim_worlds", "world_difficult.yaml"),
    os.path.join("irsim_worlds", "world_custom.yaml"),
    os.path.join("irsim_worlds", "world_hard.yaml"),
)

MAX_STEPS_ALLOWED = 300
EFFICIENT_STEP_LIMIT = 200


# ---------------------------------------------------------------------------
# World files
# ---------------------------------------------------------------------------
def resolve_world_files(world_files=None, on_missing="skip"):
    """Return the list of world files that actually exist.

    ``on_missing`` is "skip" (default) or "error". Missing worlds are reported
    so a typo in a world name cannot silently shrink the benchmark.
    """
    if world_files is None:
        world_files = WORLD_FILES

    found = []
    for world in world_files:
        path = world if os.path.isabs(world) else os.path.join(HERE, world)
        if os.path.exists(path):
            found.append(os.path.relpath(path, HERE))
        elif on_missing == "error":
            raise FileNotFoundError("IR-SIM world file not found: %s" % world)
        else:
            print("[benchmark_irsim] WARNING: world file not found, skipped: %s" % world)
    return found


# ---------------------------------------------------------------------------
# Single world run
# ---------------------------------------------------------------------------
def extract_report(output):
    """Extract the per-world IR-SIM report from the captured console output.

    ``test_irsim_with_agent.py`` prints the report as a Python dict right after
    the marker ``IR-SIM report:``; it also saves it as JSON. Both fallbacks are
    used so the benchmark keeps working if the print format changes.
    """
    if not output:
        return None

    marker = "IR-SIM report:"
    index = output.find(marker)
    if index != -1:
        tail = output[index + len(marker):]
        start = tail.find("{")
        if start != -1:
            depth = 0
            for position in range(start, len(tail)):
                char = tail[position]
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        literal = tail[start:position + 1]
                        try:
                            return ast.literal_eval(literal)
                        except (ValueError, SyntaxError):
                            break
    return None


def _read_per_world_report():
    if not os.path.exists(PER_WORLD_REPORT_PATH):
        return None
    try:
        with open(PER_WORLD_REPORT_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def run_single_world(world_file, navigation_path=None, use_subprocess=True):
    """Run one IR-SIM world and return ``(report, output)``.

    The simulation is executed by ``test_irsim_with_agent.py`` (through the
    non-interactive bridge) with the world file as its argument.
    """
    world_rel = world_file if not os.path.isabs(world_file) else os.path.relpath(world_file, HERE)
    environment = dict(os.environ)
    environment.setdefault("MPLCONFIGDIR", os.path.join(HERE, ".mplconfig"))
    environment["MPLBACKEND"] = "Agg"

    logic_rel = None
    if navigation_path:
        logic_rel = os.path.relpath(os.path.abspath(navigation_path), HERE)

    command = [sys.executable, IRSIM_RUNNER, world_rel]
    if logic_rel:
        command.append(logic_rel)

    # The previous run's report must never be mistaken for this one's.
    try:
        if os.path.exists(PER_WORLD_REPORT_PATH):
            os.remove(PER_WORLD_REPORT_PATH)
    except OSError:
        pass

    output = ""
    returncode = None
    if use_subprocess:
        completed = subprocess.run(
            command, cwd=HERE, capture_output=True, text=True, env=environment
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        returncode = completed.returncode

    report = extract_report(output) if use_subprocess else None
    if report is None:
        # Fallback 1: the per-world JSON report written by the script.
        report = _read_per_world_report()
        if report is not None and use_subprocess:
            print("[benchmark_irsim] report recovered from %s"
                  % os.path.relpath(PER_WORLD_REPORT_PATH, HERE))

    if report is None:
        # Fallback 2: run the world in-process (same script, same world file).
        print("[benchmark_irsim] running %s in-process" % world_rel)
        output += _run_in_process(world_rel, navigation_path)
        report = extract_report(output) or _read_per_world_report()

    if report is None:
        report = {
            "reached_goal": False,
            "collision_or_done": True,
            "steps_taken": 0,
            "efficiency_status": "failed",
            "efficiency_passed": False,
            "error": "no IR-SIM report could be extracted",
            "returncode": returncode,
        }

    report["world_file"] = world_rel
    report.setdefault("navigation_logic", NAVIGATION_LOGIC)
    if returncode is not None:
        report.setdefault("runner_returncode", returncode)
    if navigation_path:
        report["navigation_logic"] = os.path.relpath(os.path.abspath(navigation_path), HERE)
    return report, output


def _run_in_process(world_file, navigation_path=None):
    """Run the IR-SIM world inside this process (headless, fallback path)."""
    import importlib.util
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.show = lambda *args, **kwargs: None

    sys.argv = [IRSIM_TEST_SCRIPT, world_file]
    if "test_irsim_with_agent" in sys.modules:
        del sys.modules["test_irsim_with_agent"]
    module = importlib.import_module("test_irsim_with_agent")

    if navigation_path:
        path = os.path.abspath(navigation_path)
        module_name = "navigation_logic_%s" % os.path.splitext(os.path.basename(path))[0]
        spec = importlib.util.spec_from_file_location(module_name, path)
        navigation_module = importlib.util.module_from_spec(spec)
        navigation_module.__file__ = path
        navigation_module.__package__ = ""
        sys.modules[module_name] = navigation_module
        spec.loader.exec_module(navigation_module)
        module.decide_next_move = navigation_module.decide_next_move

    module.main()
    return "(in-process run)"


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------
def run_benchmark(world_files=None, navigation_path=None, use_subprocess=True,
                  verbose=True):
    """Run every world and build the benchmark report."""
    worlds = resolve_world_files(world_files)
    total = len(worlds)

    results = []
    reached_goal_count = 0
    efficient_count = 0
    inefficient_success_count = 0
    failed_count = 0
    total_steps = 0

    for world_file in worlds:
        print("=" * 60)
        print("[benchmark_irsim] running world: %s" % world_file)
        print("=" * 60)
        report, output = run_single_world(
            world_file, navigation_path=navigation_path, use_subprocess=use_subprocess
        )
        if output and verbose:
            print(output)
        elif output:
            # keep the trace file compact but preserve the per-world report line
            for line in output.splitlines():
                if line.strip().startswith("IR-SIM report:"):
                    print(line)

        reached_goal = bool(report.get("reached_goal"))
        steps = int(report.get("steps_taken") or 0)
        efficiency_status = report.get("efficiency_status")
        if efficiency_status is None:
            if not reached_goal:
                efficiency_status = "failed"
            elif steps <= EFFICIENT_STEP_LIMIT:
                efficiency_status = "efficient"
            else:
                efficiency_status = "acceptable_but_inefficient"

        if reached_goal:
            reached_goal_count += 1
            if efficiency_status == "efficient":
                efficient_count += 1
            else:
                inefficient_success_count += 1
        else:
            failed_count += 1

        report["efficiency_status"] = efficiency_status
        total_steps += steps
        results.append(report)

        print("[benchmark_irsim] %s -> reached_goal=%s, steps=%d, efficiency=%s"
              % (world_file, reached_goal, steps, efficiency_status))

    benchmark_report = {
        "total_worlds": total,
        "goals_reached": reached_goal_count,
        "success_rate": (reached_goal_count / total) if total else 0.0,
        "efficient_worlds": efficient_count,
        "inefficient_success_worlds": inefficient_success_count,
        "failed_worlds": failed_count,
        "efficiency_rate": (efficient_count / total) if total else 0.0,
        "average_steps_taken": (total_steps / total) if total else 0.0,
        "total_steps_taken": total_steps,
        "efficient_step_limit": EFFICIENT_STEP_LIMIT,
        "max_steps_allowed": MAX_STEPS_ALLOWED,
        "navigation_logic": os.path.relpath(
            os.path.abspath(navigation_path or os.path.join(HERE, NAVIGATION_LOGIC)), HERE
        ),
        "world_files": list(worlds),
        "results": results,
    }
    return benchmark_report


def save_benchmark_report(report, path=None):
    """Persist the benchmark report as JSON and return the file path."""
    if path is None:
        path = BENCHMARK_REPORT_PATH
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False, default=str)
        handle.write("\n")
    return path


def print_report(report):
    """Print the benchmark report in a readable format."""
    print("=" * 72)
    print("IR-SIM BENCHMARK REPORT")
    print("=" * 72)
    print("Navigation logic      : %s" % report.get("navigation_logic", "n/a"))
    print("Total worlds          : %d" % report.get("total_worlds", 0))
    print("Goals reached         : %d" % report.get("goals_reached", 0))
    print("Success rate          : %.2f%%" % (100.0 * report.get("success_rate", 0.0)))
    print("Efficient worlds      : %d" % report.get("efficient_worlds", 0))
    print("Inefficient successes : %d" % report.get("inefficient_success_worlds", 0))
    print("Failed worlds         : %d" % report.get("failed_worlds", 0))
    print("Efficiency rate       : %.2f%%" % (100.0 * report.get("efficiency_rate", 0.0)))
    print("Average steps taken   : %.1f (limit %s, max %s)"
          % (report.get("average_steps_taken", 0.0),
             report.get("efficient_step_limit", EFFICIENT_STEP_LIMIT),
             report.get("max_steps_allowed", MAX_STEPS_ALLOWED)))
    print("-" * 72)
    print("%-32s %-8s %-7s %-28s" % ("world", "goal", "steps", "efficiency"))
    for result in report.get("results", []):
        print("%-32s %-8s %-7s %-28s"
              % (os.path.basename(result.get("world_file", "?")),
                 result.get("reached_goal"),
                 result.get("steps_taken", 0),
                 result.get("efficiency_status", "?")))
    print("=" * 72)


def main(argv=None):
    argv = [arg for arg in (sys.argv[1:] if argv is None else argv) if arg != "--in-process"]

    navigation_path = argv[0] if argv else None
    world_files = argv[1:] or None
    use_subprocess = True

    report = run_benchmark(
        world_files=world_files,
        navigation_path=navigation_path,
        use_subprocess=use_subprocess,
    )
    path = save_benchmark_report(report)
    print_report(report)
    print("Saved benchmark report to %s" % path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
