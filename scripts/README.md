# Scripts

| Script | Purpose | Status |
|---|---|---|
| `build.bat` | Wrapper: finds Vivado, then runs `build.tcl`. **Use this.** | **Hardware-validated** — built 3 designs, 0 errors |
| `program.bat` | Wrapper: finds Vivado, then runs `program.tcl`. **Use this.** | **Hardware-validated** on xc7a35t |
| `build.tcl` | Headless Vivado project creation + synth + impl + bitstream | **Hardware-validated** — clean, no `UCIO-1` |
| `program.tcl` | Headless Hardware Manager programming, releases the cable on exit | **Hardware-validated**, cable released on every exit path |
| `find_vivado.bat` | Locates `settings64.bat` and puts the tools on `PATH`. Shared by the wrappers and `sim/run_sim.bat`. | — |
| `new_lab.py` | Generate a `DUT.vhd` wrapper and width constants from a DUT entity | **Hardware-validated** — its ALU wrapper passed 256/256 exhaustively |
| `sweep_divider.py` | Find the fastest JTAG clock divider that still passes, with repeats | **Hardware-validated** — produced [RESULTS.md §5C](../docs/RESULTS.md) |
| `test_new_lab.py` | Tests for the generator. No toolchain needed. | 19 offline tests |

## Usage

```
python scripts\new_lab.py examples\seq1011\Seq1011.vhd --patch-toplevel
scripts\build.bat examples\seq1011
scripts\program.bat
python host\scanchain.py -t examples\seq1011\TRACEFILE.txt -o output.txt
```

Optional second argument overrides the part:

```
scripts\build.bat examples\seq1011 xc7a15tftg256-1
```

### Finding a faster clock

```
python scripts\sweep_divider.py -t examples\alu\TRACEFILE.txt
```

Runs the driver at each divider `-n` times (default 3) and reports the fastest
that passed every repeat. Use a few hundred vectors at minimum — below that the
runtime is host-dominated and the numbers are noise.

The default `0x3B` is **100 kHz**; `TCK = 6 MHz / (divider + 1)` as the driver
is currently configured. `0x02` (2 MHz) is ~15x faster and has passed 3/3 on
hardware. Note that the driver enables the FTDI's /5 prescaler, so 6 MHz is the
current ceiling — not the 30 MHz this project assumed until 2026-07-31.
[RESULTS.md §5C](../docs/RESULTS.md) has the measurement and the correction.

### Why the `.bat` wrappers exist

`vivado` is not on `PATH` in a normal shell — it needs `settings64.bat` sourced first, which cannot be done from PowerShell at all. Rather than making every caller know where Vivado lives, `find_vivado.bat` searches the usual install roots, honours `VIVADO_SETTINGS` as an override, and fails with both fixes spelled out if it finds nothing. `build.bat`, `program.bat` and `sim/run_sim.bat` all call it, so the logic exists once.

They also translate backslashes to forward slashes for Tcl, so you can pass Windows-style paths, and they print what to do next on success and the likely causes on failure.

If you prefer calling Vivado directly, the underlying commands are unchanged:

```
vivado -mode batch -source scripts/build.tcl -tclargs examples/seq1011
```

---

## `new_lab.py` — DUT wrapper generator

```
python3 scripts/new_lab.py <your_design.vhd> [--patch-toplevel]
```

Reads the entity's port list, works out a bit layout, writes `DUT.vhd` beside the source, and prints the two width constants — optionally patching them into `hdl/TopLevel.vhd` directly.

**Why it exists.** Adapting the harness to a new design meant hand-writing a wrapper with correct bit slicing and hand-editing two constants. Both are mechanical, both are easy to get subtly wrong, and a wrong slice produces a run where every vector fails with no indication of why. That was the real barrier to anyone else using this — more than any of the defects in [KNOWN_ISSUES.md](../docs/KNOWN_ISSUES.md).

**Bit layout convention:**

```
input_vector(0)  = clock, if present
input_vector(1)  = reset, if present
input_vector(N)  = remaining inputs, first-declared in the HIGHEST bits
output_vector    = outputs, first-declared in the highest bits
```

Clock at bit 0 is deliberate. A clocked DUT needs vector pairs differing only in the clock, and putting it last makes those pairs readable at a glance:

```
0001000 0 1     <- clock = 0
0001001 0 1     <- clock = 1
```

Clock and reset are matched by name (`clock`, `clk`, `reset`, `rst`, …). Override with `--clock` / `--reset`, or pass `--no-special` to lay every port out in declaration order.

**Other flags:** `--entity` when a file declares several, `--dry-run` to print without writing, `--out` for a different path.

**Verification.** `test_reproduces_committed_wrappers` runs the generator against the same entities the committed wrappers were hand-written for, and requires the port maps to match. Those wrappers are known-good — one has 4096 passing hardware vectors behind it — so agreeing with them is the strongest available evidence the layout is right, and it will catch any future change to the convention. A second test asserts the assigned bit ranges tile the vector exactly, since a gap or an overlap would be silent corruption.

```
python3 scripts/test_new_lab.py
```

**Limits.** It flattens `std_logic` and `std_logic_vector` only. `inout` ports are rejected with an explanation — the scan chain carries inputs and outputs separately and cannot represent a bidirectional port. Integers, enums and records must be converted in your design first. It does not write a tracefile; see `examples/*/gen_tracefile.py` for worked examples.

## Why headless

The inherited flow required opening the Vivado GUI and clicking through project creation, synthesis, implementation and programming for every change. That is the main reason the project wasn't reproducible — the build state lived in a `.xpr` whose source list had drifted out of sync with the actual files (see [KNOWN_ISSUES.md](../docs/KNOWN_ISSUES.md) #6).

Generating the project from a script means the source list is defined in version control, not in a binary project file.

## Note on the cable

`program.tcl` explicitly calls `close_hw_target` before exiting. Vivado holds the FTDI channel open while a hardware target is open, and only one process can own it — leave it open and the host scan script fails with `DEVICE_NOT_OPENED`.
