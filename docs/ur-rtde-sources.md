# UR RTDE source review

The catalog references three Python examples from [SDU Robotics ur_rtde](https://gitlab.com/sdurobotics/ur_rtde/-/tree/f5492109848a9fa6582df76dffa09c510ac36393), pinned to `f5492109848a9fa6582df76dffa09c510ac36393`. This curation adds the servo and I/O examples to the existing basic-motion reference. The [source evidence](../evidence/sources/ur-rtde-2026-10-18.json) records exact source, MIT license and setup hashes, with separate retrieval histories for the two additions and the earlier basic-motion review.

| Source | Bytes | Static source behavior |
| --- | ---: | --- |
| `examples/py/basic_move.py` | 1,108 | Joint motion to a fixed target, TCP-pose read, Cartesian offsets and return motion |
| `examples/py/servoj_example.py` | 1,201 | Initial joint motion followed by an indefinite sinusoidal joint-servo loop |
| `examples/py/io_example.py` | 1,124 | Read output states, set standard/tool digital outputs and set an analog-current output ratio |

All three are straight-line scripts without a main guard. Importing or running them can connect to a controller and affect physical hardware. These Hub records supply pinned source data with `access.mode: source_reference` and `hub_prepare: false`; they do not install bindings, configure controllers or execute the examples.

The servo example requests a `1/500`-second period using `initPeriod`, `servoJ` and `waitPeriod`. This is a source parameter, not a measured frequency or real-time guarantee. Its control connection and initial `moveJ` occur before the loop's `try/finally`; the loop cleanup calls `servoStop` and `stopScript`. Its loopback demonstration address does not establish a simulator-only environment.

The I/O example reads output-state indices 7 and 16, sets standard digital output 7 and tool digital output 0 high, waits 0.01 seconds, reads the states again, then sets analog output 1 to current ratio 0.25. It does not restore the previous outputs. Controller addresses, channel mapping, wiring, joint targets and motion parameters require operator review for the intended installation.

The selected source code uses the pinned repository's MIT license, attributed to Anders Prier Lindvig - SDU Robotics. Preserve its copyright and permission notice. Dependencies, robot firmware, URCaps and hardware retain their own terms. The reviewed README provides project-level installation and robot/platform declarations; these do not establish a tested environment for the selected files. NumPy is imported by the motion examples, while the I/O example uses the RTDE I/O and receive bindings without NumPy.

Every record remains `runtime_verification: not_run`. The two maintainer-reviewed additions keep all required compatibility dimensions `unknown`, omit unobserved optional Python/architecture dimensions, and use `requirements.python: null`. Their source-review and license observations do not establish robot compatibility, collision safety, successful I/O behavior or real-time performance. The existing basic-motion intake record and its verification fields are preserved byte-for-byte. No upstream example, installer, controller, simulator or GPU was executed during this review.
