# Examples

One folder per design under test. Each folder holds a `DUT.vhd` wrapper, the design's own source files, and a `TRACEFILE.txt`.

| Example | Widths (in/out) | Status |
|---|---|---|
| [`string_detector/`](string_detector/) | 7 / 1 | **Does not elaborate** — `StringDetector.vhd` is missing (Known Issues #5). Tracefile and a captured hardware result are present. |
| [`alu/`](alu/) | 8 / 6 | Source present, no wrapper and no tracefile yet. |

## Adding a new example

1. Create a folder. Put your design's VHDL in it.
2. Write a `DUT.vhd` wrapper that flattens all inputs into one `input_vector` and all outputs into one `output_vector`. **Document the bit mapping in a comment at the top** — it isn't recoverable from the tracefile.
3. Set `number_of_inputs` and `number_of_outputs` in `hdl/TopLevel.vhd` to match.
4. Write a `TRACEFILE.txt` — see [../docs/TRACEFILE_FORMAT.md](../docs/TRACEFILE_FORMAT.md).
5. Build, program, run.

Steps 2 and 3 are what `scripts/new_lab.py` will generate (Roadmap Phase 4).

## A note on coursework

These are teaching-lab designs. If you are currently enrolled in a course that assigns them, check your institution's academic-integrity policy before using or publishing solution files.
