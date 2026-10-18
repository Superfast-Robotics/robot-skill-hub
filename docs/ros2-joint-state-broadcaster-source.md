# Joint-state broadcaster implementation

The `ros2-joint-state-broadcaster` reference indexes the complete
[`joint_state_broadcaster.cpp`](https://github.com/ros-controls/ros2_controllers/blob/8ce934536c6404750fb8aafc0b62b7d365049143/joint_state_broadcaster/src/joint_state_broadcaster.cpp)
implementation at official ros2_controllers commit
`8ce934536c6404750fb8aafc0b62b7d365049143`. It complements the existing
[trajectory and differential-drive controller references](ros2-controller-sources.md)
and demo launch/configuration coverage. The class header, package XML, CMake,
plugin XML and complete pinned root Apache-2.0 license were also read.

The registered plugin name is `joint_state_broadcaster/JointStateBroadcaster`,
class `joint_state_broadcaster::JointStateBroadcaster`, base
`controller_interface::ControllerInterface`, and library `joint_state_broadcaster`.
The selected source exports that same class/base pair with
`PLUGINLIB_EXPORT_CLASS`; CMake exports `joint_state_plugin.xml`.
It requires a complete configured ros2_control controller-manager/lifecycle host,
the parameter YAML/generated header and the dependencies listed in the record.
Package version `4.43.0`, CMake `3.16` and C++17 are declarations, not tested
runtime combinations. No build, install or Hub execution adapter is provided.

The implementation requests **no command interfaces**. If either `joints` or
`interfaces` is empty it requests all available state interfaces; otherwise it
requests their configured cross-product. Non-DOUBLE interfaces are ignored.
Custom mappings can feed position, velocity and effort fields in
`sensor_msgs::msg::JointState`. It also supports optional URDF-based filtering
and ordering, and extra configured joint names initialized to zero.

Its update reads each DOUBLE interface once with `get_optional(0)`. A failed
read leaves the prior buffered value; a value never read can remain NaN.
The source stamps and attempts to publish `joint_states` and optional
`control_msgs::msg::DynamicJointState` on `dynamic_joint_states`. Topic names
use a `~/` prefix only when configured with `use_local_topics`. These messages
can expose the host's hardware state. Freshness, completeness, publication
success, timing and physical compatibility were not measured. Parameter YAML,
generated defaults and dependency implementations remain outside this review.

The source copyright names the ros2_control development team (2021), its reviewed
header names Open Source Robotics Foundation (2017), and package authors are
Jordan Palacios and Karsten Knese. Their notices and the Apache-2.0 license
remain applicable; this review does not clear all companion code or deployment.

The [review evidence](../evidence/sources/ros2-joint-state-broadcaster-2026-10-18.json)
preserves exact bytes, SHA-256 and Git blob identities for five new pinned raw
reads and the reused license. Existing canonical metadata and the complete
768-entry tree were reused offline. The reference remains `source_reviewed`,
runtime `not_run`, `hub_prepare: false`, with unknown compatibility and
`requirements.python: null`. No plugin, ROS process, simulator or robot was run.
