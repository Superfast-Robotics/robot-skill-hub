# Nav2 behavior-tree workflow sources

Twelve declarative workflows come from
[`ros-navigation/navigation2`](https://github.com/ros-navigation/navigation2/tree/58e4019eb149ed4387938d9cd13f38659b86f754),
commit `58e4019eb149ed4387938d9cd13f38659b86f754`. They add task composition
beyond the existing Simple Commander clients and controller/planner sources.
They remain source references: `hub_prepare: false`, `source_reviewed`, runtime
`not_run`, and unknown environment and robot compatibility. Fetching one XML
does not install or start Nav2.

All paths below are relative to `nav2_bt_navigator/behavior_trees/`.

| XML | Declared source role |
| --- | --- |
| `follow_point.xml` | Update a dynamic goal, plan, truncate and follow its path |
| `nav_to_pose_with_consistent_replanning_and_if_path_becomes_invalid.xml` | Timed/path-validity/goal checks with contextual and general recovery |
| `navigate_through_poses_w_replanning_and_recovery.xml` | Remove passed goals, plan through poses, follow and recover |
| `navigate_to_pose_w_replanning_and_recovery.xml` | Plan to a pose, follow and recover |
| `navigate_to_pose_w_replanning_goal_patience_and_recovery.xml` | Cancel control and wait on approach-path conditions, with recovery |
| `navigate_w_recovery_and_replanning_only_if_path_becomes_invalid.xml` | Goal/path-validity checks, replanning and recovery |
| `navigate_w_replanning_distance.xml` | Distance-controlled replanning |
| `navigate_w_replanning_only_if_goal_is_updated.xml` | Goal-update-controlled replanning |
| `navigate_w_replanning_only_if_path_becomes_invalid.xml` | Goal/path-validity checks and replanning |
| `navigate_w_replanning_speed.xml` | Speed-controlled replanning |
| `navigate_w_replanning_time.xml` | Rate-controlled replanning |
| `odometry_calibration.xml` | Repeated drive-on-heading and spin motion experiment |

These are declarations in XML, not measured action behavior or successful
tasks. The package README describes a configured BT Navigator loading an XML
selected by Node parameter or per task. CMake installs this directory into
`share/${PROJECT_NAME}/behavior_trees`. The complete package, BehaviorTree.CPP,
node plugins, lifecycle hosts and applicable planner/controller/behavior
servers, transforms, costmaps, odometry, maps and goals are prerequisites.
The referenced nodes can command hardware when loaded by an authorized host.
No host, plugin or robot ran during source review.

Package `1.3.14`, CMake `>=3.5` and the `jazzy` ref are separate source
declarations. They do not establish tested ROS, OS, architecture, Python,
controller or robot combinations. Optional `BUILD_TESTING` declares its own
lint dependencies. The complete node implementations and their port types,
availability, scheduling, stopping and physical behavior were not reviewed.

Preserve the exact source values. The consistent-replanning comment says
15 seconds, while its XML uses `hz="2.0"` and a ten-second expiration timer.
The through-poses comment says 1 Hz while the attribute is `hz="0.333"`.
Backup error blackboard names differ between two trees. These discrepancies
were retained, not repaired or classified as runtime failures. The odometry
motion sequence is not a verified calibration result.

## License and attribution binding

The primary license URL and SHA identify the pinned repository's
[`LICENSE` index](https://github.com/ros-navigation/navigation2/blob/58e4019eb149ed4387938d9cd13f38659b86f754/LICENSE).
It directs readers to package declarations and explicitly supplies Apache-2.0
for otherwise unmarked files. The selected
[`package.xml`](https://github.com/ros-navigation/navigation2/blob/58e4019eb149ed4387938d9cd13f38659b86f754/nav2_bt_navigator/package.xml)
declares Apache-2.0. The twelve complete XML texts contain no alternate license,
copyright or individual author notice.

The separately pinned
[`nav2_docking/LICENSE`](https://github.com/ros-navigation/navigation2/blob/58e4019eb149ed4387938d9cd13f38659b86f754/nav2_docking/LICENSE)
supplies the complete standard Apache-2.0 terms. It does not grant navigator
rights or transfer docking attribution. Generated records preserve the root
index, selected package declaration and terms text as distinct evidence.
Retain applicable license/notices and mark modifications on separately
authorized redistribution. This does not clear dependencies, binaries,
assets, maps, firmware, trademarks or hardware use.

Michael Jeronimo is named as package maintainer, with no package `<author>`
node. He and the terms Appendix's copyright placeholders are not inferred as
XML authors. No individual XML authorship was manufactured.

## Reusing the bounded importer

The existing [`artifact-projects.json`](../catalog/artifact-projects.json) and
[`import_robot_artifacts.py`](../tools/import_robot_artifacts.py) now accept
the coupled `workflow` / `behaviortree-cpp-xml` form. Normal checks use only a
reviewed populated cache:

```sh
python tools/import_robot_artifacts.py --cache /path/to/reviewed-text-cache --check
```

An explicit `--fetch` retrieves only existing immutable manifest source,
license and support paths; it does not discover or refresh upstream sources.
Package, CMake, README and terms pins need exact SHA-256/byte counts. A new
package-fallback license descriptor additionally requires the exact selected
package name/license, a reviewed matching root fallback quote, source paths
within that package, and complete terms evidence. This opt-in form accepts
otherwise-unmarked files only. Any file notice requires separate review;
ordinary existing full-license descriptors retain their previous behavior.

The first parser subset accepts unnamespaced BTCPP format 4, one literal
selected `BehaviorTree`, and one body root. DTD/entities, includes, SubTree
variants, TreeNodesModel, namespaces anywhere, mixed text and unknown root
structure/version are rejected. Inventory is bounded to 512 nodes, depth 64
and 32 KiB. Parsed node tags/attributes and blackboard references are data:
node arity, port correctness, expressions and runtime semantics are not
validated. Unsupported forms require review instead of automatic expansion.

The [source evidence](../evidence/sources/nav2-bt-workflows-2026-10-18.json)
retains the exact selected pins and original bounded retrieval scope. No Hub
adapter, new runtime status, API change or Worker change accompanies this
selection.
