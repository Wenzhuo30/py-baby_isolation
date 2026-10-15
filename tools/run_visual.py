"""
run_visual.py
=============
Headless batch version of ``run_visual.sh`` (Integration and Simulation
instructions, page 8 - IR-SIM):

    ./run_visual.sh irsim_worlds/world_easy.yaml
    ./run_visual.sh irsim_worlds/world_medium.yaml
    ./run_visual.sh irsim_worlds/world_difficult.yaml
    ./run_visual.sh irsim_worlds/world_custom.yaml

The instructions require the four worlds to be simulated one after another and
inspected visually.  ``run_visual.sh`` does exactly that with the interactive
matplotlib window that ``test_irsim_with_agent.py`` opens.  That window cannot
be looked at from a head-less process (a CI run, an automated agent, a remote
session), so this script runs the *same* entry point
(``test_irsim_with_agent.main()``) on the *same* four world files, with the
non-interactive matplotlib backend, and saves one PNG per world together with a
short summary:

    visuals/world_easy.png
    visuals/world_medium.png
    visuals/world_difficult.png
    visuals/world_custom.png
    visuals/visual_run_report.json

Nothing in ``run_visual.sh`` or ``test_irsim_with_agent.py`` is modified or
replaced: this is only a wrapper that makes the same four runs reproducible and
reviewable without a screen.

Usage:
    python run_visual.py                  # the four worlds of the instructions
    python run_visual.py <world.yaml> ... # explicit world files

The PNG snapshots are regenerable build output, so ``visuals/`` is git-ignored;
``--keep`` is not offered on purpose - re-running this script after a code change
is cheaper than trusting a stored picture.
"""

import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

VISUALS_DIR = os.path.join(HERE, "visuals")
REPORT_PATH = os.path.join(VISUALS_DIR, "visual_run_report.json")

# The four worlds the instructions list, in the order they must be simulated.
DEFAULT_WORLDS = (
    os.path.join("irsim_worlds", "world_easy.yaml"),
    os.path.join("irsim_worlds", "world_medium.yaml"),
    os.path.join("irsim_worlds", "world_difficult.yaml"),
    os.path.join("irsim_worlds", "world_custom.yaml"),
)


def _configure_headless_matplotlib():
    """Use the non-interactive backend and stop plt.show() from blocking."""
    if "MPLCONFIGDIR" not in os.environ:
        os.environ["MPLCONFIGDIR"] = os.path.join(HERE, ".mplconfig")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.show = lambda *args, **kwargs: None
    return plt


def run_world(world_file, plt):
    """Run one world through test_irsim_with_agent.py and save a PNG.

    Returns the report dict that ``test_irsim_with_agent.main()`` writes to
    ``artifacts/irsim_report.json``, extended with the snapshot path.
    """
    import irsim
    import test_irsim_with_agent as sim

    if os.path.isabs(world_file):
        world_path = world_file
    else:
        world_path = os.path.join(HERE, world_file)
    if not os.path.exists(world_path):
        raise FileNotFoundError("IR-SIM world file not found: %s" % world_path)

    world_rel = os.path.relpath(world_path, HERE)
    name = os.path.splitext(os.path.basename(world_rel))[0]
    snapshot_path = os.path.join(VISUALS_DIR, "%s.png" % name)

    print("=" * 72)
    print("[run_visual] world: %s" % world_rel)
    print("=" * 72)

    os.makedirs(VISUALS_DIR, exist_ok=True)

    # ``test_irsim_with_agent.main()`` builds its OWN environment internally, so
    # the environment, the robot and the figure we must look at are only known
    # once it has been created.  irsim.make is therefore wrapped for the
    # duration of the call to capture that live environment, and its end() is
    # wrapped as well because end() closes the matplotlib figure - the picture
    # has to be written just before that happens.  The provided script itself
    # is not modified in any way.
    captured = {"env": None, "saved": False}

    def save_snapshot(*args, **kwargs):
        if captured["saved"]:
            return
        captured["saved"] = True
        figure_numbers = plt.get_fignums()
        if not figure_numbers:
            print("[run_visual] no matplotlib figure available for the snapshot")
            return
        for figure_number in figure_numbers:
            try:
                plt.figure(figure_number).savefig(
                    snapshot_path, dpi=110, bbox_inches="tight"
                )
                print("[run_visual] snapshot written as the run finished: %s"
                      % os.path.relpath(snapshot_path, HERE))
            except Exception as error:  # a failed snapshot must not break the run
                print("[run_visual] could not save the snapshot: %s: %s"
                      % (type(error).__name__, error))

    def capture_env(*args, **kwargs):
        env = original_make(*args, **kwargs)
        captured["env"] = env
        original_end = env.end

        def end_and_save(*end_args, **end_kwargs):
            save_snapshot()
            env.end = original_end
            return original_end(*end_args, **end_kwargs)

        env.end = end_and_save
        return env

    original_make = irsim.make
    original_sleep = time.sleep
    original_argv = list(sys.argv)
    irsim.make = capture_env
    sys.argv = ["test_irsim_with_agent.py", world_rel]
    time.sleep = lambda seconds=0: None  # only there to keep the GUI window open
    try:
        sim.main()  # the provided entry point, unchanged
    finally:
        irsim.make = original_make
        time.sleep = original_sleep
        sys.argv = original_argv

    # If the world returned early, or end() was never reached, capture whatever
    # the figure currently shows.
    if not captured["saved"]:
        save_snapshot()
    plt.close("all")

    env = captured["env"]
    robot = env.robot_list[0] if env is not None else None
    goal = ([float(robot.goal[0, 0]), float(robot.goal[1, 0])]
            if robot is not None else None)
    final_pose = ([float(robot.state[0, 0]), float(robot.state[1, 0]),
                   float(robot.state[2, 0])] if robot is not None else None)
    distance_to_goal = (math.hypot(final_pose[0] - goal[0], final_pose[1] - goal[1])
                        if final_pose and goal else None)
    saved = captured["saved"]

    report_path = os.path.join(HERE, "artifacts", "irsim_report.json")
    report = {}
    if os.path.exists(report_path):
        try:
            with open(report_path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
        except (OSError, json.JSONDecodeError):
            report = {}

    report.update({
        "world_file": world_rel,
        "goal": goal,
        "final_pose": final_pose,
        "distance_to_goal": (round(distance_to_goal, 3)
                             if distance_to_goal is not None else None),
        "snapshot": os.path.relpath(snapshot_path, HERE) if saved else None,
        "visual_check": "goal reached" if report.get("reached_goal")
                        else "goal NOT reached",
    })
    print("[run_visual] %s -> reached_goal=%s steps=%s snapshot=%s"
          % (world_rel, report.get("reached_goal"), report.get("steps_taken"),
             report.get("snapshot")))
    return report


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    world_files = argv or list(DEFAULT_WORLDS)

    plt = _configure_headless_matplotlib()
    os.makedirs(VISUALS_DIR, exist_ok=True)

    print("IR-SIM VISUAL RUN (head-less batch, same four worlds as run_visual.sh)")
    print("Navigation logic: generated/navigation_logic.py")
    print()

    results = []
    failures = 0
    for world_file in world_files:
        try:
            results.append(run_world(world_file, plt))
        except Exception as error:  # a broken world must not abort the batch
            failures += 1
            print("[run_visual] %s FAILED: %s: %s"
                  % (world_file, type(error).__name__, error))
            results.append({"world_file": world_file, "reached_goal": False,
                            "error": "%s: %s" % (type(error).__name__, error)})

    reached = sum(1 for r in results if r.get("reached_goal"))
    total = len(results)
    summary = {
        "navigation_logic": "generated/navigation_logic.py",
        "total_worlds": total,
        "goals_reached": reached,
        "success_rate": (reached / total) if total else 0.0,
        "failures": failures,
        "results": results,
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    print()
    print("=" * 72)
    print("VISUAL RUN SUMMARY")
    print("=" * 72)
    for result in results:
        print("%-30s goal=%-6s steps=%-5s %s"
              % (os.path.basename(str(result.get("world_file"))),
                 result.get("reached_goal"), result.get("steps_taken"),
                 result.get("snapshot") or result.get("error", "")))
    print("-" * 72)
    print("goals reached: %d/%d (success rate %.2f)"
          % (reached, total, summary["success_rate"]))
    print("snapshots     : %s" % os.path.relpath(VISUALS_DIR, HERE))
    print("report        : %s" % os.path.relpath(REPORT_PATH, HERE))
    print("=" * 72)
    return 0 if reached == total and total else 1


if __name__ == "__main__":
    raise SystemExit(main())
