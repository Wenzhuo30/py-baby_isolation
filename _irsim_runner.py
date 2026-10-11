"""
_irsim_runner.py
================
Internal, non-interactive bridge used by ``benchmark_irsim.py``.

``test_irsim_with_agent.py`` is the entry point for a single IR-SIM world and
its instructions say it must not be changed. It opens a matplotlib window
(``plt.show()``) and sleeps briefly at the end, which is exactly what we want
for the visual inspection (``./run_visual.sh <world>``) but not for an
automated benchmark that loads all worlds one after another.

This bridge therefore imports that module, forces the non-interactive
matplotlib backend, optionally selects which navigation logic the simulation
must use (the original or the revised one) and runs the simulation once.
It is a *runner*, not a simulator: it does not touch the navigation logic or
the IR-SIM world.

Usage (normally called by benchmark_irsim.py):
    python _irsim_runner.py irsim_worlds/world_easy.yaml [generated/navigation_logic.py]
"""

import importlib.util
import os
import sys
import time

# ---------------------------------------------------------------------------
# Headless (non-interactive) matplotlib configuration.
# MPLCONFIGDIR must be set before matplotlib is imported so that no font cache
# is written outside the project directory.
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
if "MPLCONFIGDIR" not in os.environ:
    os.environ["MPLCONFIGDIR"] = os.path.join(HERE, ".mplconfig")


def load_navigation_module(path):
    """Import an arbitrary navigation logic file as a standalone module."""
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise FileNotFoundError("navigation logic not found: %s" % path)

    module_name = "navigation_logic_%s" % os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = path
    module.__package__ = ""
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    if not callable(getattr(module, "decide_next_move", None)):
        raise AttributeError("%s does not define a callable decide_next_move(state)" % path)
    return module


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    world_file = argv[0] if argv else os.path.join("irsim_worlds", "world_easy.yaml")
    navigation_path = argv[1] if len(argv) > 1 else None

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.show = lambda *args, **kwargs: None  # never block an automated run

    sys.argv = ["test_irsim_with_agent.py", world_file]
    import test_irsim_with_agent

    if navigation_path:
        # test_irsim_with_agent imported generated.navigation_logic at module
        # level; replace the function it calls with the requested logic.
        navigation_module = load_navigation_module(navigation_path)
        test_irsim_with_agent.decide_next_move = navigation_module.decide_next_move

    # The module sleeps at the end only to keep the visual window open. In the
    # automated batch run there is no window to look at, so the delay is
    # suppressed for the duration of the call (and restored afterwards).
    original_sleep = time.sleep
    time.sleep = lambda seconds=0: None
    try:
        test_irsim_with_agent.main()
    finally:
        time.sleep = original_sleep
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
