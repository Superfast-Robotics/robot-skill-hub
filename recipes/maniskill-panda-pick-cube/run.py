"""CPU/state adapter around the pinned upstream ManiSkill PickCube solver.

The solver is authored by ManiSkill contributors (Apache-2.0); this hub wrapper
does not contain upstream solver code. It never renders or controls hardware.
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
    import mani_skill.envs  # registers simulation tasks
    from mani_skill.examples.motionplanning.panda.solutions.pick_cube import solve

    # Hub motion-planning horizon; separate from the upstream benchmark default.
    max_episode_steps = 1000
    env = gym.make("PickCube-v1", robot_uids="panda", obs_mode="state",
                   control_mode="pd_joint_pos", sim_backend="cpu",
                   render_backend="none", render_mode=None, max_episode_steps=max_episode_steps)
    try:
        result = solve(env, seed=args.seed, debug=False, vis=False)
        if isinstance(result, int) and result == -1:
            report = {"status": "failed", "reason_code": "motion_plan_failed"}
        else:
            info = result[-1]
            success = bool(info["success"].item())
            terminated = bool(result[2].item())
            truncated = bool(result[3].item())
            elapsed_steps = int(info["elapsed_steps"].item())
            complete = success and not truncated and 0 < elapsed_steps < max_episode_steps
            report = {"status": "task_complete" if complete else "failed",
                      "success": success, "elapsed_steps": elapsed_steps,
                      "terminated": terminated, "truncated": truncated}
            if truncated:
                report["reason_code"] = "episode_truncated"
            elif elapsed_steps >= max_episode_steps:
                report["reason_code"] = "horizon_exceeded"
            elif elapsed_steps <= 0:
                report["reason_code"] = "invalid_elapsed_steps"
            elif not success:
                report["reason_code"] = "task_objective_not_reached"
        report.update(task="PickCube-v1", seed=args.seed, runtime="3.0.0b22",
                      robot="panda", controller="pd_joint_pos", observation="state",
                      sim_backend="cpu", render_backend="none", max_episode_steps=max_episode_steps)
        print(json.dumps(report))
        return 0 if report.get("status") == "task_complete" else 1
    finally:
        env.close()


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception as error:
        # Keep the invocation contract even if an optional dependency is absent
        # or the simulator cannot initialize. Do not report this as task success.
        print(json.dumps({"status": "failed", "reason_code": "runtime_error",
                          "error_type": type(error).__name__, "message": str(error)}))
        exit_code = 1
    raise SystemExit(exit_code)
