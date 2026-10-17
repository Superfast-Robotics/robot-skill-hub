"""Hub adapter for the pinned official PullCube-v1 / panda motion planner.

Upstream solver: ManiSkill contributors, Apache-2.0. This wrapper contains no
upstream solver implementation. Simulation execution is a separate explicit step.
"""
import argparse
import importlib.metadata
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    actual = importlib.metadata.version("mani_skill")
    if actual != "3.0.0b22":
        raise RuntimeError(f"Expected mani_skill 3.0.0b22, found {actual}")
    import gymnasium as gym
    import mani_skill.envs
    from mani_skill.examples.motionplanning.panda.solutions.pull_cube import solve

    # Sparse reward avoids robot-specific dense reward helpers in upstream variants.
    env = gym.make("PullCube-v1", robot_uids="panda", obs_mode="state",
                   control_mode="pd_joint_pos", sim_backend="cpu",
                   render_backend="none", render_mode=None, reward_mode="sparse")
    try:
        result = solve(env, seed=args.seed, debug=False, vis=False)
        if isinstance(result, int) and result == -1:
            report = {"status": "failed", "reason_code": "motion_plan_failed"}
        else:
            info = result[-1]
            success = bool(info["success"].item())
            report = {"status": "task_complete" if success else "failed",
                      "success": success, "elapsed_steps": int(info["elapsed_steps"].item())}
        report.update(task="PullCube-v1", seed=args.seed, runtime="3.0.0b22",
                      robot="panda", controller="pd_joint_pos", observation="state",
                      sim_backend="cpu", render_backend="none")
        print(json.dumps(report))
        return 0 if report.get("success") else 1
    finally:
        env.close()


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception as error:
        print(json.dumps({"status": "failed", "reason_code": "runtime_error",
                          "error_type": type(error).__name__, "message": str(error)}))
        exit_code = 1
    raise SystemExit(exit_code)
