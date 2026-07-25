# Scripts

| Script | Purpose | Status |
|---|---|---|
| `build.tcl` | Headless Vivado project creation + synth + impl + bitstream | Written, **not yet validated on hardware** |
| `program.tcl` | Headless Hardware Manager programming, releases the cable on exit | Written, **not yet validated on hardware** |
| `new_lab.py` | Generate a `DUT.vhd` wrapper and width constants from a DUT entity | Not written — Roadmap Phase 4 |

## Usage

```
vivado -mode batch -source scripts/build.tcl -tclargs examples/string_detector
vivado -mode batch -source scripts/program.tcl
python host/scan_bscane2.py examples/string_detector/TRACEFILE.txt output.txt
```

Optional second argument to `build.tcl` overrides the part:

```
vivado -mode batch -source scripts/build.tcl -tclargs examples/string_detector xc7a15tftg256-1
```

## Why headless

The inherited flow required opening the Vivado GUI and clicking through project creation, synthesis, implementation and programming for every change. That is the main reason the project wasn't reproducible — the build state lived in a `.xpr` whose source list had drifted out of sync with the actual files (see [KNOWN_ISSUES.md](../docs/KNOWN_ISSUES.md) #6).

Generating the project from a script means the source list is defined in version control, not in a binary project file.

## Note on the cable

`program.tcl` explicitly calls `close_hw_target` before exiting. Vivado holds the FTDI channel open while a hardware target is open, and only one process can own it — leave it open and the host scan script fails with `DEVICE_NOT_OPENED`.
