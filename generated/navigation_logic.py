def choose_action(blocked_front, blocked_left, blocked_right, goal_front, goal_left, goal_right):
    # prefer moving toward the goal whenever that direction is safe
    if goal_front and not blocked_front:
        return "FORWARD"
    if goal_left and not blocked_left:
        return "LEFT"
    if goal_right and not blocked_right:
        return "RIGHT"
    # no goal direction is safe, so pick any safe direction
    if not blocked_front:
        return "FORWARD"
    if not blocked_left:
        return "LEFT"
    if not blocked_right:
        return "RIGHT"
    # everything is blocked, stop
    return "STOP"


def decide_next_move(state):
    """
    Standard external interface required by the project.
    Takes a state dictionary and returns one action string.
    This is the ONLY function that other programs should call.
    """
    blocked_front = state["blocked_front"]
    blocked_left = state["blocked_left"]
    blocked_right = state["blocked_right"]
    goal_front = state["goal_front"]
    goal_left = state["goal_left"]
    goal_right = state["goal_right"]
    
    return choose_action(blocked_front, blocked_left, blocked_right, goal_front, goal_left, goal_right)
