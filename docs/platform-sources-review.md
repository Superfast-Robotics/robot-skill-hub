# MAVSDK and Spot SDK source review

This finite selection adds **30 Python source entrypoints**: 12 MAVSDK examples and 18 Boston Dynamics Spot SDK examples. They cover flight control, telemetry, missions, camera/gimbal control, robot inspection, manipulation, navigation, docking and E-Stop. Counts describe reviewed source files, not installed capabilities or measured robot success.

| Official upstream | Exact commit | Sources | Source bytes |
| --- | --- | ---: | ---: |
| [MAVSDK-Python](https://github.com/mavlink/MAVSDK-Python/tree/8fa280f1d7473524a32d061e60b7bb346ff65264) | `8fa280f1d7473524a32d061e60b7bb346ff65264` | 12 | 27,708 |
| [Boston Dynamics Spot SDK](https://github.com/boston-dynamics/spot-sdk/tree/04537ddafe0641d1751af3eb9e76cb785fc18594) | `04537ddafe0641d1751af3eb9e76cb785fc18594` | 18 | 225,236 |

The [source receipt](../evidence/integration/v0.3.3/source-review.json) binds every source URL, SHA-256, byte count, Git blob/mode, author, applicable license scope and setup declaration independently of later additions to the [workflow manifest](../catalog/workflow-projects.json). Review covered 75 bounded text files totaling 338,989 bytes: 252,944 source bytes and 86,045 supporting license/setup bytes. Both regular Git file modes were checked: the twelve MAVSDK examples use `100755`, while the eighteen Spot examples use `100644`. Helpers, tests and configuration files are not counted as additional skills.

## MAVSDK scope and setup

The twelve sources cover takeoff/landing, telemetry, flight-mode telemetry, standard and raw missions, offboard NED position and body velocity, global position commands, geofencing, cameras, gimbals and follow-me targets. Each has a main guard that invokes a source async function through `asyncio.run`, with a real operational SDK call present in the AST.

The [pinned BSD-3-Clause license](https://github.com/mavlink/MAVSDK-Python/blob/8fa280f1d7473524a32d061e60b7bb346ff65264/LICENSE.txt) attributes the MAVSDK Development Team. Pinned setup metadata identifies maintainers Jonas Vautherin and Julian Oes. Source terms do not establish terms for separately obtained server binaries, autopilot firmware, hardware or payloads.

The [pinned README](https://github.com/mavlink/MAVSDK-Python/blob/8fa280f1d7473524a32d061e60b7bb346ff65264/README.md) now specifies distribution **`mavsdk-grpc`** and import **`mavsdk_grpc`**. The native `mavsdk` v4 binding has a different API. Python `>=3.7`, `protobuf>=6.32.1` and `grpcio>=1.64.1` remain separate upstream declarations; no combined environment was resolved. The [server version file](https://github.com/mavlink/MAVSDK-Python/blob/8fa280f1d7473524a32d061e60b7bb346ff65264/MAVSDK_SERVER_VERSION) declares binary `v4.0.5`, not an autopilot firmware or verified Python distribution version. Upstream build can download that binary and `connect()` can launch it; neither occurred during review.

Examples embed connection addresses and motion/mission coordinates. No autopilot, airframe, firmware or payload compatibility is inferred. Raw mission upload does not start a mission. Geofencing leaves fence-hit behavior unconfigured. NED offboard position documents a non-GPS/HOLD-transition limitation. Camera and gimbal workflows need their respective configured payload/plugins.

## Spot SDK scope and source terms

The eighteen sources cover posture/image commands, state and world-object inspection, camera images, Cartesian and joint arm control, gaze, grasping, image-guided walking, frame-relative trajectories, docking, GraphNav navigation/recording, Autowalk recording, stored mission replay, reachability and terminal E-Stop. Every selected source has a main guard invoking a source function and an operational SDK call.

Spot uses the [Boston Dynamics SDK License](https://github.com/boston-dynamics/spot-sdk/blob/04537ddafe0641d1751af3eb9e76cb785fc18594/LICENSE), identifier `20191101-BDSDK-SL`. All selected source headers attribute Boston Dynamics, Inc. and reference these terms. Records retain **`LicenseRef-BostonDynamics-SDK-20191101-BDSDK-SL`**, **`verified: false`**, and **`review_status: nonstandard_upstream_terms`**. This local LicenseRef identifies the pinned terms; it does not assert an OSI/SPDX-standard license grant or legal clearance. Upstream product-use conditions, complete-license/notices requirements and possible separately issued keys remain declarations, with no robot entitlement inferred.

The checkout declares SDK `5.2.0`. The [quickstart](https://github.com/boston-dynamics/spot-sdk/blob/04537ddafe0641d1751af3eb9e76cb785fc18594/docs/python/quickstart.md) separately requires robot software aligned with installed package versions. Python `>=3.7` and each folder's dependency declarations remain distinct: world objects declares `bosdyn-client >=5.0.1.2`, GraphNav `>=4.0`, reachability `>=3.3`, and many other workflows `>=3.1`. Optional image, plotting and GUI dependencies and the local prebuilt-package lookup remain attached to their own workflows. These are not interchangeable tested environments.

Authorized robot addresses/credentials are operator prerequisites. Motion workflows additionally declare E-Stop, lease, time-sync, power and payload conditions. Docking checks feature entitlement; navigation/replay needs configured maps, localization or missions. Reachability also sends physical arm commands, so it is not an offline numerical-only solver. The E-Stop folder shares GUI dependency declarations although the selected `estop_nogui` entrypoint uses terminal/curses controls.

## Evidence boundary

Fourteen Spot records carry the literal discovery name `spot`, backed by a checksum-bound quote in the selected source or its own folder README. Robot-state inspection, both GraphNav CLIs and Autowalk recording remain without exact robot labels because those particular source/folder texts do not explicitly name Spot. MAVSDK receives no robot-model labels. Classification, names and capabilities are discovery data; no model revision, firmware, payload, feature entitlement or runtime combination is inferred.

All thirty records remain `source_reviewed`, `runtime_verification: not_run`, `access.mode: source_reference` and `hub_prepare: false`, with no Hub execution adapter or compatibility combinations. Review verified frozen bytes and parsed source as inert data. No upstream module/setup command was run, no package or binary installed, no model/map/mission assets retrieved, and no robot, simulator or model endpoint contacted. Coverage is exactly this finite selection, not an exhaustive SDK or Internet inventory.
