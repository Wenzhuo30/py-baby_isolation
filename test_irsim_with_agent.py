import math
import irsim
import json
import os
import numpy as np
import matplotlib.pyplot as plt
import time
import sys
from generated.navigation_logic import decide_next_move

os.makedirs("artifacts", exist_ok=True)

MAX_STEPS = 300
EFFICIENT_STEP_LIMIT = 200


def classify_efficiency(reached_goal_status, steps_taken):
    """
    Classify a run based on goal completion and step count.

    The benchmark keeps 300 as the hard runtime limit, but treats
    anything above 200 steps as successful-but-inefficient.
    """
    if not reached_goal_status:
        return "failed"
    if steps_taken <= EFFICIENT_STEP_LIMIT:
        return "efficient"
    return "acceptable_but_inefficient"


def normalize_angle(angle):
    while angle > math.pi:
        angle -= 2 * math.pi
    while angle < -math.pi:
        angle += 2 * math.pi
    return angle


def angle_diff(a, b):
    return normalize_angle(a - b)


def is_blocked_in_direction(robot_x, robot_y, check_angle, obstacles, max_distance=1.8, angle_tolerance=0.9):
    """
    Simple directional obstacle check using obstacle centers.
    More permissive than before, so we can see whether detection starts working.
    """
    for obs in obstacles:
        obs_x = obs.state[0, 0]
        obs_y = obs.state[1, 0]

        dx = obs_x - robot_x
        dy = obs_y - robot_y
        distance = math.hypot(dx, dy)

        if distance > max_distance:
            continue

        obs_angle = math.atan2(dy, dx)
        diff = abs(angle_diff(obs_angle, check_angle))

        if diff <= angle_tolerance:
            return True

    return False

def build_state(robot, env, goal):
    x = robot.state[0, 0]
    y = robot.state[1, 0]
    theta = robot.state[2, 0]

    front_angle = theta
    left_angle = theta + math.pi / 2
    right_angle = theta - math.pi / 2

    obstacles = env.obstacle_list

    front_blocked = bool(is_blocked_in_direction(x, y, front_angle, obstacles))
    left_blocked = bool(is_blocked_in_direction(x, y, left_angle, obstacles))
    right_blocked = bool(is_blocked_in_direction(x, y, right_angle, obstacles))

    # The canonical state contract used everywhere in this project is the six
    # boolean keys below. The descriptive aliases are kept so that either
    # naming convention works for the generated navigation logic.
    state = {
        "blocked_front": front_blocked,
        "blocked_left": left_blocked,
        "blocked_right": right_blocked,
        "front_blocked": front_blocked,
        "left_blocked": left_blocked,
        "right_blocked": right_blocked,
    }

    state.update(goal_direction_flags(x, y, theta, goal[0], goal[1]))

    print(f"DEBUG build_state -> x={x:.2f}, y={y:.2f}, theta={theta:.2f}, state={state}")
    return state


def goal_direction_flags(robot_x, robot_y, theta, goal_x, goal_y):
    dx = goal_x - robot_x
    dy = goal_y - robot_y
    goal_angle = math.atan2(dy, dx)
    diff = angle_diff(goal_angle, theta)

    goal_ahead = bool(abs(diff) <= 0.4)
    goal_on_left = bool(diff > 0.4)
    goal_on_right = bool(diff < -0.4)

    return {
        "goal_front": goal_ahead,
        "goal_left": goal_on_left,
        "goal_right": goal_on_right,
        "goal_ahead": goal_ahead,
        "goal_on_left": goal_on_left,
        "goal_on_right": goal_on_right,
    }


def action_to_velocity(action):
    """
    Return a NumPy array for one differential-drive robot:
    [linear_velocity, angular_velocity]
    """
    if action == "FORWARD":
        return np.array([0.6, 0.0], dtype=float)
    if action == "LEFT":
        return np.array([0.3, 0.8], dtype=float)
    if action == "RIGHT":
        return np.array([0.3, -0.8], dtype=float)
    if action == "STOP":
        return np.array([0.0, 0.0], dtype=float)
    raise ValueError(f"Invalid action: {action}")


def reached_goal(robot, goal, tolerance=0.4):
    x = robot.state[0, 0]
    y = robot.state[1, 0]
    gx = goal[0]
    gy = goal[1]
    return math.hypot(x - gx, y - gy) <= tolerance


def main():
    
    world_file = sys.argv[1] if len(sys.argv) > 1 else "irsim_worlds/world_easy.yaml"
    env = irsim.make(world_file)

    robot = env.robot_list[0]
    goal = [
        float(robot.goal[0, 0]),
        float(robot.goal[1, 0])
    ]

    print("LOADED GOAL FROM WORLD:", goal)
    """ goal = [8, 8] """

    history = []

    turn_lock_action = None
    turn_lock_steps_remaining = 0
    
    for step in range(300):
        
        """ turn_lock_action = None
        turn_lock_steps_remaining = 0 """

        state = build_state(robot, env, goal)
        
        """ state = build_state(robot, env) """

        if turn_lock_steps_remaining > 0:
            action = turn_lock_action
            turn_lock_steps_remaining -= 1
            print(f"TURN LOCK ACTIVE -> action={action}, remaining={turn_lock_steps_remaining}")
        else:
            action = decide_next_move(state)

            if action in {"LEFT", "RIGHT"}:
                turn_lock_action = action
                turn_lock_steps_remaining = 2

        velocity = action_to_velocity(action)
        

        history.append({
            "step": step + 1,
            "robot_state": [float(robot.state[0, 0]), float(robot.state[1, 0]), float(robot.state[2, 0])],
            "perception_state": state,
            "action": action,
            "velocity": velocity
        })

        print(f"Step {step+1}: state={state} action={action} velocity={velocity}")

        if action == "STOP":
            print("Agent returned STOP.")
            break

        # Apply control to robot
        """ robot.vel = velocity """

        # Advance simulator one step
        """ env.step() """

        # Apply control through IR-SIM's step API
        env.step(velocity, action_id=0)
        env.render()

        if reached_goal(robot, goal):
            print("Goal reached.")
            break

        if env.done():
            print("Environment finished (collision or other terminal condition).")
            break

    env.end()

    print("Simulation finished. Keeping window open...")

    plt.show()

    time.sleep(5)

    """ print("\nRun completed.")
    print(f"Final pose: {[float(robot.state[0,0]), float(robot.state[1,0]), float(robot.state[2,0])]}")

    print("\nHistory:")
    for item in history:
        print(item) """
    
    
    reached_goal_status = reached_goal(robot, goal)
    steps_taken = len(history)
    efficiency_status = classify_efficiency(reached_goal_status, steps_taken)

    report = {

        "reached_goal": reached_goal_status,

        "collision_or_done": env.done(),

        "steps_taken": steps_taken,

        "max_steps_allowed": MAX_STEPS,

        "efficient_step_limit": EFFICIENT_STEP_LIMIT,

        "efficiency_status": efficiency_status,

        "efficiency_passed": efficiency_status == "efficient",

        "final_pose": [

            float(robot.state[0, 0]),

            float(robot.state[1, 0]),

            float(robot.state[2, 0])

        ],

        "history_length": len(history)

    }
    

    print("\nIR-SIM report:")

    print(report)

    with open("artifacts/irsim_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

if __name__ == "__main__":
    main()