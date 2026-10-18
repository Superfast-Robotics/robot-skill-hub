# ros2_controllers implementation sources

Two source references add controller implementations beyond the existing
ros2_control demo launch, YAML and Xacro files. Both use official
[`ros-controls/ros2_controllers`](https://github.com/ros-controls/ros2_controllers)
commit `8ce934536c6404750fb8aafc0b62b7d365049143`. The
[ROS package index](https://index.ros.org/p/joint_trajectory_controller/)
identifies this canonical repository and its `jazzy` checkout; the pinned README
also lists that branch. Package version `4.43.0`, the branch and C++17 build
declarations are requirements/provenance, not tested environment combinations.

| Record | Selected implementation | Registered host interface |
| --- | --- | --- |
| `ros2-joint-trajectory-controller` | [`joint_trajectory_controller.cpp`](https://github.com/ros-controls/ros2_controllers/blob/8ce934536c6404750fb8aafc0b62b7d365049143/joint_trajectory_controller/src/joint_trajectory_controller.cpp) | `joint_trajectory_controller/JointTrajectoryController`, `controller_interface::ControllerInterface` |
| `ros2-diff-drive-controller` | [`diff_drive_controller.cpp`](https://github.com/ros-controls/ros2_controllers/blob/8ce934536c6404750fb8aafc0b62b7d365049143/diff_drive_controller/src/diff_drive_controller.cpp) | `diff_drive_controller/DiffDriveController`, `controller_interface::ChainableControllerInterface` |

The joint trajectory plugin accepts `~/joint_trajectory` messages and the
`<node_name>/follow_joint_trajectory` action. Its selected implementation checks
incoming joint names, point fields and timing, samples a companion trajectory,
checks configured tolerances, updates optional PID/feedforward commands and
writes claimed position, velocity, acceleration or effort interfaces. It also
publishes `~/controller_state`, supplies `query_state`, handles goal
preemption/cancellation and can use configured speed-scaling input. Hold and
deceleration paths are source behavior, not verified stopping guarantees.
The trajectory helper, class/type declarations, parameter YAML and validators
remain required and were not read in this finite review. No kinematics solver,
trajectory construction or complete robot deployment is supplied here.

The differential-drive plugin consumes its `TwistStamped` subscriber input on
`~/cmd_vel` or exported linear/angular velocity reference interfaces. Its update
applies configured speed limits, calculates left/right wheel rates from linear
`x`, angular `z` and wheel geometry, and writes wheel velocity command handles.
It delegates odometry to a companion implementation and publishes `~/odom`,
conditional `/tf` and conditional `~/cmd_vel_out`. The timeout can be disabled
with a zero setting; deactivation calls a function that writes zero wheel
commands. Odometry accuracy, braking, latency and real-time behavior were not
tested. Companion odometry/speed-limiter code, headers and generated parameter
YAML/validators remain outside this source review.

Both selected files are shared-library plugins requiring a complete configured
ros2_control controller manager/lifecycle host and matching interfaces. They
are not standalone programs. Loading them in an appropriately configured host
can write actual robot command interfaces and publish ROS messages. The records
list the actual package/CMake build/runtime dependencies and source-used ROS
interfaces; optional `BUILD_TESTING` adds the test dependencies recorded in the
review evidence. No package, compiler, controller manager or plugin was run.

Both source headers explicitly declare **Apache-2.0**, matching their package
declarations and the complete pinned root license. Retain applicable copyright,
license, modification and notice obligations. The joint trajectory source names
the ros2_control Development Team (2021); the differential-drive source names
PAL Robotics (2020) and Bence Magyar, Enrique Fernández and Manuel Meraz. This
review is limited to the selected files and does not clear companion sources,
dependencies, binaries, hardware drivers or deployment.

The [review evidence](../evidence/sources/ros2-controllers-2026-10-18.json)
records the complete 768-entry tree, exact Git blobs and hashes for ten immutable
files, dependency/plugin manifests and all 14 anonymous primary GETs. Both
records remain `source_reviewed`, runtime `not_run`, `hub_prepare: false`, with
all required compatibility dimensions/status unknown and
`requirements.python: null`. No Hub adapter, API receipt, popularity measurement, simulator/robot
execution, GPU use or physical compatibility result was created.
