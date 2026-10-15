def decide_next_move(state):
    blocked_front = bool(state['blocked_front'])
    blocked_left = bool(state['blocked_left'])
    blocked_right = bool(state['blocked_right'])
    goal_front = bool(state['goal_front'])
    goal_left = bool(state['goal_left'])
    goal_right = bool(state['goal_right'])
    
    if goal_front and not blocked_front:
        return "FORWARD"
    elif goal_left and not blocked_left:
        return "LEFT"
    elif goal_right and not blocked_right:
        return "RIGHT"
    else:
        if not blocked_front:
            return "FORWARD"
        elif not blocked_left:
            return "LEFT"
        elif not blocked_right:
            return "RIGHT"
        else:
            return "STOP"
