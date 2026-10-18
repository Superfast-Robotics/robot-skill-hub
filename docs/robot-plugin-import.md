# Maintainer-side ROS 2 plugin registration checks

`tools/import_robot_plugins.py` checks a finite, reviewed manifest against local
immutable source bytes. It can verify already owned intake records or write
separate new-skill metadata drafts. It has no network or publication command and
does not discover repositories, compile code, evaluate CMake, load a package or
plugin, install dependencies, run a controller or contact a robot.

The result is **literal registration consistency**, not verified binary
registration, successful compilation, active controller loading or runtime
compatibility. A correct registration alone says nothing about task success or
physical behavior.

## Check the two existing examples

The finite [manifest](../catalog/plugin-projects.json) describes the existing
`ros2-joint-trajectory-controller` and `ros2-diff-drive-controller` intake records
at `ros-controls/ros2_controllers` commit
`8ce934536c6404750fb8aafc0b62b7d365049143`. Their implementation effects and source
review remain in [the controller guide](ros2-controller-sources.md) and its
linked evidence. No canonical record is moved, rewritten or re-owned by this
tool.

Supply a cache containing only the reviewed files listed by the manifest:

```text
CACHE/ros2-controllers/8ce934536c6404750fb8aafc0b62b7d365049143/LICENSE
CACHE/ros2-controllers/8ce934536c6404750fb8aafc0b62b7d365049143/README.md
CACHE/ros2-controllers/8ce934536c6404750fb8aafc0b62b7d365049143/joint_trajectory_controller/...
CACHE/ros2-controllers/8ce934536c6404750fb8aafc0b62b7d365049143/diff_drive_controller/...
```

```sh
python tools/import_robot_plugins.py --cache /path/to/reviewed-cache --check
```

The ten exact files are the selected C++ implementations, their package XML,
CMake and plugin XML, the complete shared license and reviewed README. Each
cache file must match its declared bytes, SHA-256 and Git blob SHA-1. A missing
or changed file fails; the tool never fills a missing cache from the network.
`--check` also binds each existing intake's exact JSON bytes and normalized
metadata, and rejects competing canonical IDs or source identities.

These records remain `code/cpp`, Python `null`, all required compatibility
dimensions/status `unknown`, `source_reviewed`, runtime `not_run`, and
`source_reference` with `hub_prepare: false`. Those states are checked rather
than inferred from the package branch, version, registered class or build flags.

## Prepare a new, separately reviewed draft

For a genuinely new source, prepare a separate manifest with the same finite
structure and cache layout. Supply the source, plugin XML, package XML, CMake,
full applicable license and every other supporting file explicitly. Provide
reviewed names, capabilities, attribution, requirements and behavioral notes;
the tool does not derive robot compatibility or source behavior from a filename
or class name.

```sh
python tools/import_robot_plugins.py --manifest /path/to/new-reviewed-plugin.json --cache /path/to/reviewed-cache --output-directory /path/to/fresh-drafts
```

The output directory must not exist. Its parent must exist, and it must be
outside the repository or underneath the repository's `.local` directory.
No other in-repository directory is allowed, including `schemas`, `api`,
`plugins`, `.git` or `brand`. Files are created exclusively. Existing files are
not replaced or removed. An interrupted write may leave a partial draft directory;
inspect that result and choose a new directory instead of overwriting it.

Every generated file is the raw skill metadata accepted by the existing
`rsh.py register` input validator. It includes `setup_url` and unknown
compatibility, and has no canonical `access`, `evidence`, `maintenance`, license
verification flag, submission receipt or publication assertion. The existing
registration command still applies its own bundle size, project policy,
contributor attribution, permission and authentication checks:

```sh
python skills/find-robot-skills/scripts/rsh.py register /path/to/fresh-drafts/new-plugin-id.json --project /path/to/authorized-project --contributor "Maintainer label" --draft
```

Draft generation rejects an ID or normalized immutable source identity already
present in managed references, intake records or preparation records. The
default demonstration manifest therefore works with `--check`; draft mode
rejects its two already published entries. Renaming an existing source ID does
not evade source duplication checks. GitHub repository case and a trailing
`.git/` are normalized for duplicate detection only; source provenance is not
rewritten.

## Deliberately limited structural checks

- A selected `.cpp`, `.cc` or `.cxx` file must have exactly one supported global
  literal `PLUGINLIB_EXPORT_CLASS(type, base)` or
  `CLASS_LOADER_REGISTER_CLASS(type, base)`. Its class and base must match the
  selected plugin XML class. Comments, ordinary/raw strings and character
  literals do not count as exports. Translation-line splices, conditional or
  preprocessor exports, non-global exports, duplicate exports and dynamic
  argument expressions are rejected. This is not C++ name resolution,
  preprocessing, type checking or a proof that a binary can load.
- Plugin XML must have a literal `library` root and a unique selected class
  name, type and base. DTD/entity declarations are rejected. XML includes and
  external resources are not resolved.
- The reviewed CMake file must contain exactly one literal, unconditional
  `project` matching the package name, one selected literal `SHARED` library
  declaration containing the source, and one matching unconditional plugin XML
  export. Unquoted or double-quoted literal arguments and the already declared
  `${PROJECT_NAME}` are supported. Other substitutions, selected `target_sources`,
  conditional selected declarations, project-name mutation and command
  overrides are rejected. Selected target output-name, prefix, suffix or postfix
  property changes also require separate review. Other CMake commands are not
  evaluated; this does not establish the complete evaluated dependency graph or
  final binary contents.
- Declared package build/runtime dependencies must appear in the reviewed
  requirement list. Test dependencies are separate. Source-used interfaces and
  complete-package/helper requirements still require explicit source review;
  parsing package XML does not discover them automatically.

The existing example importer still requires a native `main`; its library
rejection is unchanged. Controller YAML mapping, launch execution, arbitrary
library entrypoints, generated plugin XML, alternate macro wrappers, dynamic
CMake and automatic registry migration are outside this tool's scope. Other
generic artifact types remain available through ordinary reviewed intake.

## License boundary

The source header must contain the reviewed copyright/license notice quotes.
Each credited author has explicit `author_provenance`: either a `source_header`
quote containing that credit, or `package_author` with the pinned package XML
path and exact `<author>` text. Package maintainers, partial-name matches and
unlisted files do not supply author credit. A package author is not thereby
identified as the selected file's author or copyright holder; that provenance
remains distinct in the manifest and does not replace the source notice.
Recognized source-comment declarations, package declarations and the pinned
license text must agree. This version supports the explicitly reviewed standard
Apache-2.0, MIT, BSD-2-Clause and BSD-3-Clause identities. Recognized conflicting
declarations and unrecognized SPDX expressions are rejected. Other terms and
mixed licenses require a separate manual review rather than an automatic
override.

Hashes and text markers bind the operator-reviewed license file; they are not
independent legal clearance. The operator must review the complete applicable
text before supplying a manifest. A draft never sets `license.verified`.
Existing verified source-only records are checked against their retained exact
bytes. No license is inferred for companion implementations, dependencies,
drivers, meshes, assets, binaries or robot deployment from the selected source
or package license.

Run the focused data contracts without upstream execution:

```sh
python -m unittest discover -s tests/python -p test_robot_plugin_import.py -v
```
