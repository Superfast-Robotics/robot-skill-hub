# ViSP image-based visual servo source

`visp-ibvs-four-points` references the official
[`lagadic/visp`](https://github.com/lagadic/visp) C++ tutorial
[`tutorial-ibvs-4pts.cpp`](https://github.com/lagadic/visp/blob/372e03076373e012f2bec765b026bc1e4e7487bd/tutorial/visual-servo/ibvs/tutorial-ibvs-4pts.cpp)
at commit `372e03076373e012f2bec765b026bc1e4e7487bd`. Its 1,798 bytes have
SHA-256 `1d0d3f32617c912e4eafdeb6506b6fc003b5c22c62405a828cda19d418ff767b`.

The source defines four corners of a square and projects them into current and
desired camera frames. It configures `vpServo::EYEINHAND_CAMERA`, the current
interaction matrix and gain 0.5. Each of 150 iterations updates the point
features, computes a control law and applies its camera-frame velocity to
`vpSimulatorCamera`, whose declared sampling time is 0.040 seconds. This is a
numerical free-flying camera example. It does not acquire camera images, track
image blobs, solve robot arm joint IK or connect a hardware driver. There is no
final-error success assertion; a caught `vpException` is printed without an
explicit failure return. No convergence or robot execution was tested.

Use the complete upstream ViSP headers, libraries and build configuration.
The [tutorial CMake](https://github.com/lagadic/visp/blob/372e03076373e012f2bec765b026bc1e4e7487bd/tutorial/visual-servo/ibvs/CMakeLists.txt)
declares CMake 3.10 or later, requests eight ViSP components, builds additional
tutorials and copies their data. Retrieving this one file supplies no complete
dependency bundle. Root CMake declares ViSP 3.7.1; that declaration and the
project's platform badges are not measured compatibility. No build, install,
compiler, simulator or robot was run. The pinned IBVS documentation has an old
directory link and an obsolete `task.kill()` mention; the immutable source and
tree determine this record's path and behavior.

The project distributes this tutorial under **GPL-2.0-or-later**, as declared by
the complete pinned root license and corroborated by README and root CMake.
The selected file has no individual author, copyright or license header. Its
attribution is to ViSP project contributors; the pinned mainpage identifies the
Inria Rainbow/former Lagadic team as project developers and maintainers. The
complete tree contains no additional license or notice file in the selected
file's ancestor directories. Preserve applicable GPL source, attribution,
license and modification obligations. The separate Professional Edition is not
granted here, and dependencies and binaries were not cleared by this review.

The [review evidence](../evidence/sources/visp-ibvs-2026-10-18.json) records seven
immutable file hashes and Git blobs against the complete 4,800-entry tree. It
also records ten successful anonymous primary GETs and one official-site TLS
verification failure, which was not retried or bypassed. This maintainer-curated
reference remains `source_reviewed`, runtime `not_run`, `hub_prepare: false`,
with unknown environment combinations and `requirements.python: null`. It
adds grounded visual-servo source coverage without an API submission, execution
adapter, measured task success or external adoption claim.
