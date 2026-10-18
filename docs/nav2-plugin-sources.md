# Nav2 controller and planner implementation sources

Three references add implementation roles beyond the nine existing Simple
Commander clients. All use the existing official
[`ros-navigation/navigation2` pin](https://github.com/ros-navigation/navigation2/tree/58e4019eb149ed4387938d9cd13f38659b86f754).
They are C++ shared-library plugins loaded by configured Nav2 lifecycle hosts,
not standalone programs or complete navigation tasks. Each remains
`access.mode: source_reference`, `hub_prepare: false`, unknown compatibility and
`runtime_verification: not_run`.

| Reference | Selected implementation | Registered class and host interface |
| --- | --- | --- |
| `nav2-mppi-controller` | `nav2_mppi_controller/src/controller.cpp` | `nav2_mppi_controller::MPPIController`, `nav2_core::Controller` |
| `nav2-regulated-pure-pursuit-controller` | `nav2_regulated_pure_pursuit_controller/src/regulated_pure_pursuit_controller.cpp` | `nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController`, `nav2_core::Controller` |
| `nav2-smac-hybrid-planner` | `nav2_smac_planner/src/smac_planner_hybrid.cpp` | `nav2_smac_planner::SmacPlannerHybrid`, `nav2_core::GlobalPlanner` |

The MPPI source configures optimizer, path, parameter and visualization objects.
Its velocity callback locks parameter/costmap state, transforms the supplied
goal/path and delegates control to `optimizer_.evalControl`. This selected file
does not contain the optimizer or critic algorithms. It returns a
`TwistStamped` to its host; visualization can publish trajectories when enabled.

The regulated pure pursuit source chooses lookahead points, calculates
curvature, handles heading rotation/reversing and constrains velocity using
curvature, obstacle cost and goal approach. It returns a velocity command and
publishes plan/lookahead/rotation diagnostics. Configured collision detection
calls a separate checker and may throw `NoValidControl`; this is source behavior,
not a measured collision-avoidance or safe-stopping guarantee. Cancellation,
reset, plan and speed-limit methods alter controller state.

The Smac Hybrid-A* source configures `AStarAlgorithm<NodeHybrid>`, footprint
collision checking, optional downsampling and smoothing. Its planning callback
locks the costmap, maps poses into search coordinates, requests a path with a
cancellation callback and returns world-frame poses. It raises planner errors
for several invalid/search-failure cases, and has a same-cell start/goal special
case. It can publish unsmoothed paths and optional expansion/footprint markers,
and registers dynamic-parameter and global-costmap resolution callbacks. The
default `DUBIN` model, unknown-space traversal setting and five-second planning
limit are source settings, not performance measurements or suitable parameters
for every robot. A returned path does not itself drive a robot.

Read each pinned package's `package.xml`, plugin registration XML and
`CMakeLists.txt` before building or configuring a host. The complete headers,
helper implementations, transforms, costmaps, footprint, parameters and ROS
dependencies are required; fetching one file is insufficient. RPP requests
C++17; Smac defaults to C++17 when unset and links OMPL/Eigen; MPPI links
xtensor/xsimd and uses compiler-conditional optimization flags. The cached
`jazzy` ref and declared package version `1.3.14` do not establish tested ROS,
OS, architecture, Python, robot or controller compatibility. No plugin was
compiled, loaded, installed or executed in this review.

All three selected files explicitly carry Apache-2.0 headers. RPP and Smac
package declarations agree. **MPPI's selected file is Apache-2.0 while its
package declares MIT.** The pinned root multi-license index says existing files
retain their file license; verification is scoped to the selected Apache-marked
file and preserves this discrepancy. It does not clear the whole package,
optimizer, third-party code, dependencies, assets or binaries. Retain copyright,
license and applicable notices for any separately authorized reuse.

The [review evidence](../evidence/sources/nav2-plugins-2026-10-18.json) records
57,716 selected source bytes, exact SHA-256 and Git blob identities, twelve
bounded anonymous source/setup GETs, and the separately rechecked cached root
license index. Package setup texts were read as inert data. No public intake
receipt, runtime claim, adoption measurement or hardware validation is implied.
