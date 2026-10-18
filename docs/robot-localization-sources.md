# robot_localization EKF implementation source

`robot-localization-ekf` references the official
[`src/ekf.cpp`](https://github.com/cra-ros-pkg/robot_localization/blob/3efa714fb9c1ff40966327b7bed7053b2570be4d/src/ekf.cpp)
at the immutable `3efa714fb9c1ff40966327b7bed7053b2570be4d` revision. The
[official ROS package index](https://index.ros.org/p/robot_localization/)
identified this canonical repository and its `jazzy-devel` checkout. This is a
C++ library implementation of `robot_localization::Ekf`, not a standalone node
or a complete sensor-fusion deployment. It remains a source reference with no
Hub preparation adapter, unknown compatibility and runtime `not_run`.

`correct(const Measurement &)` selects finite measured dimensions, forms
measurement/covariance submatrices, calculates a Kalman gain, normalizes angular
innovation and uses a Mahalanobis threshold before updating filter state and
the Joseph-form covariance. It takes absolute negative covariance diagonals and
floors very small diagonal variances at `1e-9`. `predict` accepts `rclcpp::Time`
and `Duration`, builds a nonlinear transfer function and analytical Jacobian,
applies inherited control/noise handling, projects state and covariance and
wraps state angles. These are source operations, not measured numerical quality,
timing or sensor accuracy. The Euler-angle calculation includes
`1/cos(pitch)`; singularity and conditioning behavior were not tested.

The file mutates filter internals and can emit configured debug output. It
defines no `main`, ROS sensor subscription, publisher or physical robot command.
The pinned CMake configuration builds it into `rl_lib` alongside other sources
and links that library into a separate `ekf_node` target. The node main, ROS
filter wrapper and sensor I/O were outside this bounded source review. Obtain
and inspect the complete package, generated interfaces, headers, `FilterBase`,
measurement types, state initialization and noise/control configuration before
integration. The metadata lists the ROS, Eigen, Boost, GeographicLib and YAML
dependencies found in the actual package and CMake declarations. CMake selects
C++17 for non-WIN32 builds. Its package version `3.8.3` and indexed branch do not
establish tested ROS, OS, architecture, Python, sensor or robot compatibility.

The selected file has a complete **BSD-3-Clause** notice naming Charles River
Analytics (2014–2016) and Locus Robotics (2017). The root license contains BSD
notices, including an organization placeholder in one clause, while
`package.xml` declares **Apache License 2.0**. Verification is scoped to the
complete notice in this selected BSD-marked file. Retain its attribution,
conditions, disclaimer and non-endorsement requirement. This review does not
relicense or clear the full package, other components, dependencies or binaries.

The [review evidence](../evidence/sources/robot-localization-ekf-2026-10-18.json)
records 17,733 source bytes, SHA-256
`431331568e9cc042aca3fd06f7f70252ec9a70d32e09a47d9dccc1be678b5660`,
the complete 121-entry tree, exact Git blob identities, canonical-source
evidence and seven anonymous official responses for this family. No upstream
code was compiled, imported, loaded, installed or executed. No sensor data,
simulator or hardware result is attached.
