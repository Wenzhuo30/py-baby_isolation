"""
navigation_logic.py
===================
Navigation logic for the mobile robot.

Implemented by the Developer Agent from the navigation plan:
 The robot prefers moving toward its goal whenever the direction is safe. It never moves into a blocked direction. When several safe directions are available, it first picks the one that points toward the goal; if none of the safe directions points toward the goal, it picks any safe direction. If ...
 Revision notes applied by the Developer Agent:
 Keep the current decide_next_move implementation and continue with the IR-SIM benchmark.

Contract:
    decide_next_move(state) -> "FORWARD" | "LEFT" | "RIGHT" | "STOP"

"state" is a dictionary with the six boolean keys blocked_front, blocked_left,
blocked_right, goal_front, goal_left, goal_right (the descriptive aliases
front_blocked / left_blocked / right_blocked and goal_ahead / goal_on_left /
goal_on_right are accepted as well).
"""

VALID_ACTIONS = ("FORWARD", "LEFT", "RIGHT", "STOP")

BLOCKED_KEYS = {
    "FORWARD": ("blocked_front", "front_blocked"),
    "LEFT": ("blocked_left", "left_blocked"),
    "RIGHT": ("blocked_right", "right_blocked"),
}

GOAL_KEYS = {
    "FORWARD": ("goal_front", "goal_ahead"),
    "LEFT": ("goal_left", "goal_on_left"),
    "RIGHT": ("goal_right", "goal_on_right"),
}


def _read_flag(state, keys):
    """Read the first present key of a flag, tolerating naming aliases."""
    for key in keys:
        if key in state:
            return bool(state[key])
    return False


def is_blocked(state, action):
    """True when the direction required by 'action' is blocked."""
    keys = BLOCKED_KEYS.get(action)
    if keys is None:
        return False
    return _read_flag(state, keys)


def points_to_goal(state, action):
    """True when 'action' moves the robot toward its goal."""
    keys = GOAL_KEYS.get(action)
    if keys is None:
        return False
    return _read_flag(state, keys)


def choose_action(blocked_front, blocked_left, blocked_right,
                  goal_front, goal_left, goal_right):
    """Pure decision function following the navigation plan."""
    # 1. prefer moving toward the goal whenever that direction is safe
    if goal_front and not blocked_front:
        return "FORWARD"
    if goal_left and not blocked_left:
        return "LEFT"
    if goal_right and not blocked_right:
        return "RIGHT"
    # 2. otherwise take any safe direction (reference priority front, left, right)
    if not blocked_front:
        return "FORWARD"
    if not blocked_left:
        return "LEFT"
    if not blocked_right:
        return "RIGHT"
    # 3. every direction is blocked: stop
    return "STOP"


def decide_next_move(state):
    """
    Standard external interface required by the project.

    Takes the perception state dictionary and returns one action string.
    This is the ONLY function that other programs should call.
    """
    if not isinstance(state, dict):
        raise TypeError("state must be a dict, got %s" % type(state).__name__)

    blocked_front = _read_flag(state, BLOCKED_KEYS["FORWARD"])
    blocked_left = _read_flag(state, BLOCKED_KEYS["LEFT"])
    blocked_right = _read_flag(state, BLOCKED_KEYS["RIGHT"])
    goal_front = _read_flag(state, GOAL_KEYS["FORWARD"])
    goal_left = _read_flag(state, GOAL_KEYS["LEFT"])
    goal_right = _read_flag(state, GOAL_KEYS["RIGHT"])

    action = choose_action(blocked_front, blocked_left, blocked_right,
                           goal_front, goal_left, goal_right)

    # final safety guard: never move into a blocked direction, never return
    # anything outside the allowed action set
    if action not in VALID_ACTIONS:
        return "STOP"
    if action != "STOP" and is_blocked(state, action):
        for candidate in ("FORWARD", "LEFT", "RIGHT"):
            if not is_blocked(state, candidate):
                return candidate
        return "STOP"
    return action
