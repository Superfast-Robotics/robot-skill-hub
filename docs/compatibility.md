# Preview compatibility

The first two recipes wrap the official ManiSkill 3.0.0b22 Panda motion planners for PickCube-v1 and StackCube-v1. The catalog pins a full upstream commit and archive SHA-256. All requirements are recorded as combinations, not independent robot/runtime lists.

Intended combination: Linux x86_64, Python 3.10, `maniskill` 3.0.0b22, Panda, `pd_joint_pos`, simulator state observations, one CPU simulation environment. Consult each record for package versions and command arguments. A state-based planner has privileged simulator information and is not comparable to an RGB-only controller under equal observation conditions.

Runtime execution has not been verified on this Windows development host. Source review and structural tests do not establish installation, import, success rate, physical robot safety, performance improvement or compatibility with other ManiSkill releases. Video rendering and real hardware control are outside this preview.

Windows/macOS can read the public catalog. The local tool reports unsupported simulator OS rather than treating it as compatible. Unknown requirements remain unknown. Existing research locks remain unchanged until an explicit new preparation is requested.
