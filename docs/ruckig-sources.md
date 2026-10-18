# Ruckig Community source review

This finite selection adds **seven numerical trajectory-generation entrypoints** from [Ruckig Community v0.19.4](https://github.com/pantor/ruckig/tree/a8db97a4e9c55e5160a3855f739fa3b270df8e4c), pinned to `a8db97a4e9c55e5160a3855f739fa3b270df8e4c`. The [source receipt](../evidence/sources/ruckig-community-2026-10-18.json) binds all 11,810 selected source bytes, the MIT license, setup declarations and the C++ formatting helper by SHA-256. The [manifest](../catalog/source-projects.json) supplies reviewed search aliases and exact acquisition pins.

| Source | Discovery scope |
| --- | --- |
| `examples/01_position.py` | Online jerk-limited position trajectory generation |
| `examples/02_position_offline.py` | Offline trajectory calculation, interpolation and position extrema |
| `examples/05_velocity.py` | Velocity-control trajectory generation |
| `examples/06_stop.py` | Stop trajectory with zero target velocity and independent DoF stopping |
| `examples/07_minimum_duration.py` | Minimum trajectory-duration constraint |
| `examples/09_dynamic_dofs.cpp` | Number of degrees of freedom selected at runtime |
| `examples/12_custom_vector_type.cpp` | Integration of a custom C++ vector type |

The pinned package declares Python **>=3.9**; its C++ library requires **C++20** and **CMake >=3.15**. Python source builds declare `scikit-build-core` and `nanobind`. Use the matching upstream checkout and bindings or native example target. The Python plotting code is commented out; C++ examples also include the matching `examples/plotter.hpp` formatting helper. Fetching one source file does not supply a complete build environment.

For local-only source builds, set `BUILD_CLOUD_CLIENT=OFF` and `BUILD_TESTS=OFF`: the upstream cloud-client default is on. This selection excludes intermediate-waypoint/cloud examples and Pro-only tracking/speed examples. The selected code computes and prints trajectories without a robot model, IK solver, collision checker, robot controller or hardware connection. MIT notices apply to these Community source files; separately obtained products and dependencies retain their own terms.

All seven entries remain `source_reviewed`, `runtime_verification: not_run`, `access.mode: source_reference` and `hub_prepare: false`. Frozen bytes, main entrypoints and setup declarations were inspected without installing, importing, compiling or running upstream code. No robot, simulator, cloud calculation or GPU was used; no measured task completion, real-time performance or hardware compatibility is claimed. Existing source records and project objects are preserved.
