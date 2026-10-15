"""Shared helper package for the robot-navigation project.

The agent modules live at the repository root (the course structure diagram
requires that), while the helper scripts added on top of the assignment live
here in ``tools/``. They are importable as ``tools.<module>``:

    from tools.llm_client import get_client      # used by the agents
    python tools/check_llm.py                    # runnable on their own too

``run_visual.py``, ``check_llm.py`` and ``compare_navigation_logic.py`` insert the
repository root on ``sys.path`` before importing the agents, so they work whether
they are started from the root or from inside ``tools/``.
"""
