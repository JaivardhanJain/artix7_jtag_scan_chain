# Artix-7 JTAG Scan Chain Tester

Automated, vector-based functional testing of VHDL designs on a Xilinx Artix-7 FPGA, driven entirely over JTAG from a host PC. No test pins, no switches, no LEDs — the design under test (DUT) is fed input vectors and read back through the FPGA's built-in JTAG TAP.

This is an Artix-7 port of an existing MAX 10 flow. The MAX 10 version used Altera's Virtual JTAG IP; this one uses Xilinx's `BSCANE2` primitive. See [docs/MIGRATION_MAX10_TO_ARTIX7.md](docs/MIGRATION_MAX10_TO_ARTIX7.md).

> **Status: working prototype, mid-rework.** The protocol is proven — 4096/4096 vectors pass on the bundled passthrough test ([results/](results/)). Two defects that could silently corrupt results have been fixed in HDL but **not yet verified on hardware**; see [Changes to the original implementation](#changes-to-the-original-implementation). Read [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) before trusting a result, and [docs/ROADMAP.md](docs/ROADMAP.md) for what's planned.

---

## Why this exists

Testing a student lab design on an FPGA normally means assigning switches and LEDs to every input and output, then toggling them by hand. That doesn't scale past a few bits, and it can't run a 4000-vector regression.

This harness wraps the DUT in a JTAG-accessible shift register. A Python script on the host shifts an input vector in, lets the DUT settle, shifts the output back out, and compares it against an expected value — thousands of vectors in seconds, fully automated, with no board I/O consumed.

---

## How it works (short version)

```
Host PC                          Artix-7 FPGA
┌──────────────┐                ┌──────────────────────────────┐
│ scan_bscane2 │                │  ┌────────┐                  │
│    .py       │   FTDI MPSSE   │  │BSCANE2 │  TCK/TDI/TDO     │
│              │◄──────────────►│  │ (USER1)│  SHIFT/CAPTURE/  │
│  TRACEFILE   │   raw JTAG     │  └───┬────┘  UPDATE          │
│      │       │   IR/DR scans  │      │                       │
│      ▼       │                │  ┌───▼──────────┐            │
│  compare vs  │                │  │ scan register│            │
│   expected   │                │  │  + io phase  │            │
└──────────────┘                │  └───┬──────────┘            │
                                │      │                       │
                                │  ┌───▼────┐                  │
                                │  │  DUT   │                  │
                                │  └────────┘                  │
                                └──────────────────────────────┘
```

Each vector is two DR scans:

1. **Input phase** — shift the input vector into `data`, UPDATE-DR latches it into `dut_input`. The `io` phase bit flips.
2. **Output phase** — CAPTURE-DR loads the DUT's output into `datau`, then it's shifted out on TDO. `io` flips back.

Full signal-level detail in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Repository layout

| Path | Contents |
|---|---|
| `hdl/` | The reusable harness — `TopLevel.vhd` (BSCANE2 wiring), `scan_core.vhd` (all scan logic, vendor-neutral), `constraints.xdc`. |
| `host/` | `scan_bscane2.py`, the host-side JTAG driver. |
| `examples/` | Per-lab DUT wrappers and their tracefiles. One folder per design. |
| `results/` | Captured output from real hardware runs. |
| `scripts/` | Headless Vivado build and program scripts. |
| `docs/` | Architecture, tracefile format, migration notes, troubleshooting, roadmap. |
| `assets/` | Presentation material. |
| `vivado/` | *Untracked.* Local Vivado project dirs — regenerable, gitignored. |

---

## Requirements

**Hardware**

- Xilinx Artix-7 board with an FTDI-based JTAG interface. Developed against **xc7a35tftg256** (an `xc7a15tftg256` variant also exists in history — confirm your part from the IDCODE the script prints).
- USB cable.

**Host software**

- Python 3.8+
- `pip install -r host/requirements.txt` (`ftd2xx`, `bitstring`)
- FTDI **D2XX** driver installed. On Windows this usually conflicts with the VCP driver — if the device isn't found, see [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).
- Vivado (any version that supports your part) for synthesis and programming.

---

## Quickstart

### 1. Pick or write a DUT

Copy an example and edit it, or write your own wrapper. A DUT wrapper flattens your design's ports into one input vector and one output vector:

```vhdl
entity DUT is
    port(input_vector  : in  std_logic_vector(6 downto 0);
         output_vector : out std_logic_vector(0 downto 0));
end entity DUT;
```

Then set the widths at the top of `hdl/TopLevel.vhd` to match:

```vhdl
constant number_of_inputs  : integer := 7;
constant number_of_outputs : integer := 1;
```

> These two edits are currently manual and are the main friction point for adding a new lab. Automating them is roadmap item **Phase 4 / `new_lab.py`**.

### 2. Build the bitstream

```
vivado -mode batch -source scripts/build.tcl -tclargs examples/string_detector
```

Or open Vivado, create a project with `hdl/TopLevel.vhd` + your DUT files, set `TopLevel` as top, and generate a bitstream.

### 3. Program the board

```
vivado -mode batch -source scripts/program.tcl
```

### 4. Run the test

```
python host/scan_bscane2.py examples/string_detector/TRACEFILE.txt output.txt
```

The script prints the IDCODE it read, then writes one line per vector:

```
0000010 0 Success
0000011 0 Success
```

Columns are: input vector, value read back, verdict.

---

## Tracefile format

One vector per line, three space-separated columns:

```
<input_bits> <expected_output_bits> <mask>
```

```
0000010 0 0
0001000 0 1
```

Bit order is **MSB-first as written**, i.e. the leftmost character is `input_vector(N-1)`. Full spec, including the mask column semantics and the known bug where the mask is currently ignored, is in [docs/TRACEFILE_FORMAT.md](docs/TRACEFILE_FORMAT.md).

---

## Known issues at a glance

| # | Issue | Impact | Status |
|---|---|---|---|
| 1 | `io` phase bit has no reset path (`BSCANE2.RESET` left open) | A crashed script permanently desyncs host and FPGA. Every later result is wrong. | **Fixed, pending hardware verification** |
| 2 | TDO launched and sampled on the same clock edge | Works at the current divider by timing luck, not design. | **Fixed, pending hardware verification** |
| 3 | Mask column parsed but never applied | Don't-care outputs are compared as hard values. | Open |
| 4 | Read parser reuses widths leaked from the write loop | Ragged tracefiles mis-parse instead of erroring. | Open |
| 5 | `StringDetector.vhd` is not in this repo | `examples/string_detector` will not elaborate as-is. | Open |

Nine issues in total. Full write-ups and fixes: [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md). How each was found, and which phase of the plan addresses it: [docs/ENGINEERING_LOG.md](docs/ENGINEERING_LOG.md).

---

## Changes to the original implementation

This section records every deviation from the code as inherited: what changed, what problem in the original it solves, and how the change will be proven correct. Nothing here has been validated on hardware yet — all three items are code-complete and awaiting the bench session.

### 1. Scan logic split into `scan_core.vhd`

**What.** `TopLevel.vhd` previously held both the `BSCANE2` instantiation and the entire scan register. It is now split: `TopLevel.vhd` contains only the Xilinx-specific wiring (BSCANE2 → scan_core → DUT), and the new `hdl/scan_core.vhd` holds all shift, capture and phase logic behind plain `std_logic` ports.

**Why — the problem in the original.** Every piece of scan logic sat in the same file as a vendor primitive. `BSCANE2` only exists inside Vivado's `unisim` library, so simulating the scan logic meant either pulling in `unisim` and a primitive model, or not simulating at all. In practice it meant the latter: there was no testbench, and every change to bit ordering or width had to be checked by synthesising, implementing, generating a bitstream, programming the board and running vectors — a ten-minute loop to answer a question a simulator answers in seconds. That is [issue #9](docs/KNOWN_ISSUES.md), and it is the single biggest drag on anyone trying to extend this project.

`scan_core` has no vendor dependency, so a testbench can drive `capture`/`shift`/`update` directly. This change is the prerequisite for the testbench, and it is also what makes the two fixes below small, local and reviewable.

**Verification.** This refactor is behaviour-preserving by construction — the process body is the original logic, unmodified apart from the two fixes below. It is proven by the 46-vector parity run in the bench checklist: same tracefile, same output as the committed `results/string_detector_output.txt`. Any behavioural drift shows up as a diff.

### 2. `io` phase bit now has a reset path — fixes [issue #1](docs/KNOWN_ISSUES.md)

**What.** `BSCANE2`'s `RESET` and `SEL` outputs, previously wired to `open`, are now connected to `scan_core`. `io` is cleared asynchronously in Test-Logic-Reset and synchronously whenever the USER1 data register is deselected.

**Why — the problem in the original.** `io` selects input phase vs output phase and inverts on every Update-DR. It was initialised only by its VHDL declaration, which takes effect once at FPGA configuration and never again. If the host script died between the two DR scans of a vector — Ctrl-C, a crash, a dropped USB transfer — the FPGA had advanced `io` an odd number of times relative to the host's model and stayed inverted **forever**. From then on input vectors were shifted into what the FPGA believed was an output phase. There was no error and no warning: just wholesale failures, or worse, coincidental passes. The only recovery was reprogramming the FPGA, and nothing in the code or docs told you that.

This is the most serious defect found, precisely because the passing 4096-vector results could never have caught it — an uninterrupted run is exactly the case where it doesn't bite.

The host already issues a TAP reset before its IDCODE read at startup, so with this fix every invocation self-synchronises for free. No host-side change needed.

**Verification.** The specific test is: start a run, `Ctrl-C` it mid-vector, then rerun **without reprogramming the FPGA** and confirm a full pass. That test fails on the original code and must pass now. It's step (a) of the bench checklist.

### 3. TDO registered on the falling edge of TCK — fixes [issue #2](docs/KNOWN_ISSUES.md)

**What.** `tdo <= datau(0)` was a combinational assignment from a rising-edge register. It is now a register clocked on the falling edge of TCK.

**Why — the problem in the original.** The host reads TDO with MPSSE opcodes `0x2C`/`0x2E`, which sample on the **rising** edge of TCK. `datau` updates on the rising edge too. So the FPGA changed TDO on the same edge the host latched it — a launch/sample race. IEEE 1149.1 specifies TDO changes on the falling edge for exactly this reason.

It worked, but only because the clock divider (`0x3B`, ~500 kHz) left enough slack for the output to settle before the FTDI's sample point. That is timing margin, not design, and it is a plausible explanation for why the divider was set so conservatively in the first place.

**Why the host needs no change.** Moving the launch edge does not shift the data. After Capture-DR on rising edge *N*, the falling edge of *N* launches bit 0; the host samples it on rising edge *N+1*, half a clock later, by which point it has been stable. Same bits, same order, no added latency — only the launch edge moves. The timing walkthrough is in the header of `scan_core.vhd`.

**Verification.** Two parts. First, the 46-vector parity run must still match byte-for-byte — if the fix had introduced an off-by-one, every vector would shift. Second, sweep the clock divider down from `0x3B` and record the fastest reliable setting before and after. A correct fix should raise the safe ceiling, and that delta is the project's one concrete, measurable improvement claim.

### Still unchanged

`host/scan_bscane2.py` is untouched, as are all example DUTs and tracefiles. Issues #3, #4, #5, #7 and #8 remain open. Deliberately: keeping the host constant across the HDL change means the parity run isolates the HDL fixes, and a diff against the committed results is a clean signal.

---

## Roadmap

Six phases, ~11–12 hours: make it build reproducibly, fix the two real bugs, harden the host script, automate the build/program/wrapper-generation, add a hardware-free simulation testbench, and document the results. See [docs/ROADMAP.md](docs/ROADMAP.md) for the phase checklists, and [docs/ENGINEERING_LOG.md](docs/ENGINEERING_LOG.md) for the state this project was inherited in, the reasoning behind the phase ordering, and a defect-to-phase traceability matrix.

---

## Credits

**Original implementation — Anubhav Bhura, Wadhwani Electronics Laboratory, IIT Bombay.**

The scan chain architecture, the `BSCANE2`-based `TopLevel.vhd` harness, the FTDI MPSSE host driver (`scan_bscane2.py`), the tracefile format, and the Artix-7 port of the original MAX 10 Virtual-JTAG flow are all his work. That includes every design decision this repository is built on: the two-phase `io` multiplexing scheme, the split-the-MSB-off trick for the final bit in Shift-DR, and the USB command batching that makes 4096-vector runs practical.

**This repository — JJ (Jaivardhan Jain).** Restructuring, documentation, defect analysis, and the improvements tracked in [docs/ROADMAP.md](docs/ROADMAP.md). The [known issues](docs/KNOWN_ISSUES.md) are findings from reading the original code, not regressions introduced here; every change made since is recorded in [Changes to the original implementation](#changes-to-the-original-implementation) above and in the [engineering log](docs/ENGINEERING_LOG.md).

Developed for undergraduate digital-design labs at IIT Bombay.

## License

No license is currently granted. The original code belongs to its author and the Wadhwani Electronics Laboratory, IIT Bombay; a license would be theirs to choose. Until one is added, this repository is viewable but not licensed for reuse or redistribution.
