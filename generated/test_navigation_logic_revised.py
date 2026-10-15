import pytest
import itertools
from generated.navigation_logic import decide_next_move

def expected_action(
    blocked_front, blocked_left, blocked_right,
    goal_front, goal_left, goal_right
):
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

def test_all_states():
    for state_tuple in itertools.product([True, False], repeat=6):
        state = {
            'blocked_front': state_tuple[0],
            'blocked_left': state_tuple[1],
            'blocked_right': state_tuple[2],
            'goal_front': state_tuple[3],
            'goal_left': state_tuple[4],
            'goal_right': state_tuple[5],
        }
        expected = expected_action(*state_tuple)
        actual = decide_next_move(state)
        assert actual == expected, f"Failed for state {state}"
