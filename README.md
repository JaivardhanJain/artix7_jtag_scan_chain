# Artix-7 JTAG Scan Chain Tester

Automated, vector-based functional testing of VHDL designs on a Xilinx Artix-7 FPGA, driven entirely over JTAG from a host PC. No test pins, no switches, no LEDs — the design under test (DUT) is fed input vectors and read back through the FPGA's built-in JTAG TAP.

This is an Artix-7 port of an existing MAX 10 flow. The MAX 10 version used Altera's Virtual JTAG IP; this one uses Xilinx's `BSCANE2` primitive. See [docs/MIGRATION_MAX10_TO_ARTIX7.md](docs/MIGRATION_MAX10_TO_ARTIX7.md).

> **Status: working, hardware-verified.** One command builds, one programs, one runs. The reworked harness reproduces the original's results on the board: **44/44 unmasked vectors, with exactly the two predicted differences** from the pre-change capture ([docs/RESULTS.md](docs/RESULTS.md) §5A). Five defects fixed and confirmed; **one supposed defect (#2) is documented as unproven in both directions** rather than resolved by assertion. The desync defect (#1) is demonstrated on silicon by a controlled A/B against a pre-fix bitstream. Outstanding: the clock-rate sweep. See [Changes to the original implementation](#changes-to-the-original-implementation) and [docs/RESULTS.md](docs/RESULTS.md), which separates what is proven from what is argued.

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
| `hdl/` | The reusable harness — `TopLevel.vhd` (BSCANE2 wiring), `scan_core.vhd` (all scan logic, vendor-neutral), `constraints.xdc` (empty by design). |
| `host/` | `scanchain.py` (current driver), `scan_bscane2.py` (original, kept as reference), and offline tests. |
| `examples/` | Per-lab DUT wrappers and their tracefiles. Start with `seq1011`, which is complete and self-contained. |
| `results/` | Captured output from real hardware runs. |
| `scripts/` | Headless Vivado build and program scripts, plus `new_lab.py`, the DUT wrapper generator. |
| `sim/` | Self-checking testbench, an offline Python model, and run scripts. |
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
- Vivado for synthesis, simulation and programming. Developed and simulated against **2020.2**; nothing depends on a newer version.

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

**Or generate it.** `new_lab.py` reads your entity's port list, writes the wrapper with the correct bit slicing, and patches the width constants into `hdl/TopLevel.vhd`:

```
python3 scripts/new_lab.py path/to/YourDesign.vhd --patch-toplevel
```

Hand-writing the wrapper and editing the two constants was the main friction in adding a new design — mechanical, easy to get subtly wrong, and a wrong slice makes every vector fail with no indication of why.

### 2. Build the bitstream

```
scripts\build.bat examples\seq1011
```

The wrapper locates Vivado itself, so no Vivado command prompt is needed. Or call the Tcl directly if you already have the tools on `PATH`:

```
vivado -mode batch -source scripts/build.tcl -tclargs examples/seq1011
```

### 3. Program the board

```
scripts\program.bat
```

### 4. Run the test

```
python host/scanchain.py -t examples/seq1011/TRACEFILE.txt -o output.txt
```

The script prints the IDCODE it read, writes one line per vector, and finishes with a summary:

```
0000010 0 Skipped
0001000 0 Success
...
46 vectors: 44 passed, 0 failed, 2 skipped (masked)
0.31 s elapsed, 148 vectors/s
```

Columns are: input vector, value read back, verdict. Exit status is 0 only if every unmasked vector passed.

To check a tracefile without a board attached:

```
python host/scanchain.py --dry-run -t examples/seq1011/TRACEFILE.txt
```

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

Bit order is **MSB-first as written**, i.e. the leftmost character is `input_vector(N-1)`. The mask column is optional and may be a single `0`/`1` or one character per output bit; `x`/`-` don't-cares are allowed in the expected column. Full spec in [docs/TRACEFILE_FORMAT.md](docs/TRACEFILE_FORMAT.md).

---

## Known issues at a glance

| # | Issue | Impact | Status |
|---|---|---|---|
| 1 | `io` phase bit has no reset path (`BSCANE2.RESET` left open) | A crashed run desyncs host and FPGA permanently — and **93% of vectors still report Success** while the harness returns a constant. | **Fixed, demonstrated on hardware by A/B** |
| 2 | TDO launch edge | Unclear — see below | **Unproven both ways.** Reverted to the original. The evidence once used to close it turned out to be an unrelated host bug. [Details](docs/KNOWN_ISSUES.md) |
| 3 | Mask column parsed but never applied | Don't-care outputs are compared as hard values. | **Fixed, hardware-confirmed** |
| 4 | Read parser reuses widths leaked from the write loop | Ragged tracefiles mis-parse instead of erroring. | **Fixed, hardware-exercised** |
| 5 | `StringDetector.vhd` is not in this repo | `examples/string_detector` will not elaborate as-is. | **Resolved** — recovered and verified; kept local, `seq1011` added as a publishable substitute |
| 7 | Vestigial `state_out` constraint and a suppressed `UCIO-1` DRC | Hides genuine unconstrained-port errors in future DUTs. | **Resolved, confirmed by a clean build** |

Nine issues in total. Full write-ups and fixes: [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md). How each was found, and which phase of the plan addresses it: [docs/ENGINEERING_LOG.md](docs/ENGINEERING_LOG.md). What has actually been measured, and how strong the evidence is: [docs/RESULTS.md](docs/RESULTS.md).

---

## Changes to the original implementation

This section records every deviation from the code as inherited: what changed, what problem in the original it solves, and how the change was proven correct.

**All of it now runs on hardware.** One command builds, one programs, one tests. The scan-core split reproduces the original's captured output exactly; the desync fix is demonstrated by a controlled A/B on two bitstreams; a machine-generated wrapper passed 256/256 exhaustively; and throughput is 17x the inherited setting. Evidence tier by tier, including what is still unproven: [docs/RESULTS.md](docs/RESULTS.md).

### 1. Scan logic split into `scan_core.vhd`

**What.** `TopLevel.vhd` previously held both the `BSCANE2` instantiation and the entire scan register. It is now split: `TopLevel.vhd` contains only the Xilinx-specific wiring (BSCANE2 → scan_core → DUT), and the new `hdl/scan_core.vhd` holds all shift, capture and phase logic behind plain `std_logic` ports.

**Why — the problem in the original.** Every piece of scan logic sat in the same file as a vendor primitive. `BSCANE2` only exists inside Vivado's `unisim` library, so simulating the scan logic meant either pulling in `unisim` and a primitive model, or not simulating at all. In practice it meant the latter: there was no testbench, and every change to bit ordering or width had to be checked by synthesising, implementing, generating a bitstream, programming the board and running vectors — a ten-minute loop to answer a question a simulator answers in seconds. That is [issue #9](docs/KNOWN_ISSUES.md), and it is the single biggest drag on anyone trying to extend this project.

`scan_core` has no vendor dependency, so a testbench can drive `capture`/`shift`/`update` directly. This change is the prerequisite for the testbench, and it is also what makes the two fixes below small, local and reviewable.

**Verification.** This refactor is behaviour-preserving by construction — the process body is the original logic, unmodified apart from the two fixes below. Confirmed in simulation: 256 vectors exhaustively, 0 errors. The remaining check is the 46-vector hardware parity run against the committed `results/string_detector_output.txt`.

### 2. `io` phase bit now has a reset path — fixes [issue #1](docs/KNOWN_ISSUES.md)

**What.** `BSCANE2`'s `RESET` and `SEL` outputs, previously wired to `open`, are now connected to `scan_core`. `io` is cleared asynchronously in Test-Logic-Reset and synchronously whenever the USER1 data register is deselected.

**Why — the problem in the original.** `io` selects input phase vs output phase and inverts on every Update-DR. It was initialised only by its VHDL declaration, which takes effect once at FPGA configuration and never again. If the host script died between the two DR scans of a vector — Ctrl-C, a crash, a dropped USB transfer — the FPGA had advanced `io` an odd number of times relative to the host's model and stayed inverted **forever**. From then on input vectors were shifted into what the FPGA believed was an output phase. There was no error and no warning: just wholesale failures, or worse, coincidental passes. The only recovery was reprogramming the FPGA, and nothing in the code or docs told you that.

This is the most serious defect found, precisely because the passing 4096-vector results could never have caught it — an uninterrupted run is exactly the case where it doesn't bite.

The host already issues a TAP reset before its IDCODE read at startup, so with this fix every invocation self-synchronises for free. No host-side change needed.

**Verification.** Confirmed in simulation — `tb_scan_core` tests 2 and 3 abandon a vector mid-flight and recover via TAP reset and via deselect respectively, both passing. The remaining bench test is the real-world version: start a run, `Ctrl-C` it mid-vector, then rerun **without reprogramming the FPGA** and confirm a full pass. That fails on the original code.

### 3. TDO launch edge — proposed, then **reverted**. [Issue #2](docs/KNOWN_ISSUES.md) is open.

**The code here is the original's.** `tdo <= datau(0)`, combinational. This entry stays in the list because the change was made, shipped in an earlier commit, and then withdrawn — and the withdrawal is the part worth reading.

**The original argument.** The host reads TDO with MPSSE opcodes `0x2C`/`0x2E`, which sample on the **rising** edge of TCK. `datau` updates on the rising edge too, so the FPGA changes TDO on the same edge the host latches it. IEEE 1149.1 specifies TDO changes on the falling edge for exactly this reason. The fix was a register on the falling edge.

**Why it was withdrawn — and why that reasoning was also wrong.** The first hardware run showed TDO stuck at 1, which looked like the new register breaking the link. It was not: the real cause was a bug in `host/scanchain.py` (`encode_ir` sent TMS=0 instead of TMS=1 leaving Shift-IR, so USER1 was never selected). The falling-edge register was therefore **never tested against a working host** — the evidence used to retire the issue was contaminated by an unrelated defect.

**Where it stands.** No evidence the register is harmful; no evidence the original is defective. The combinational version is kept because it is the configuration with a clean 4096-vector sweep behind it — an argument from evidence, not a demonstration. Simulation cannot settle it, since both `tb_scan_core` and `model_scan_core.py` stand in for `BSCANE2` and sample at the same point either way.

**What the sweep added, and what it did not.** The combinational version is now measured correct at a 167 ns TCK period ([RESULTS.md §5C](docs/RESULTS.md)) — the first timing evidence this design has ever had, since Vivado never analysed it. But no divider failed, so it found the FTDI's ceiling rather than the design's, and the ceiling turned out to be 6 MHz rather than the assumed 30 MHz. That is roughly where the 1149.1 argument would expect the combinational version to be fine anyway, so it does not discriminate. **The deciding experiment is to send MPSSE `0x8A` instead of `0x8B`, unlocking 30 MHz, and re-sweep.**

### 4. Simulation testbench — addresses [issue #9](docs/KNOWN_ISSUES.md)

**What.** `sim/tb_scan_core.vhd`, a self-checking testbench that plays the role `BSCANE2` plays on hardware, plus `sim/run_sim.bat` (xsim) / `sim/run_sim.sh` (GHDL) and `sim/model_scan_core.py`, a Python cycle model of the same logic.

**Why — the problem in the original.** There was no testbench of any kind. Every change to the scan logic, the width constants or a tracefile required a full synthesis → implementation → bitstream → program cycle before you learned whether the bit ordering was right. That ten-minute loop is the biggest practical drag on the project and the main reason it's hard for anyone else to pick up.

**What it checks.** An exhaustive scan of all 256 vectors; desync recovery via TAP reset and via deselect; and a bit-order sensitivity sweep. Critically, it samples `tdo` while `tck` is low, immediately before the rising edge — exactly what the host's MPSSE `0x2C`/`0x2E` reads see — so the falling-edge launch fix is exercised the same way hardware will exercise it.

**Verification — done, twice.** Under Vivado xsim 2020.2: **259 checks, 0 errors**, about 8 seconds. And `model_scan_core.py`, a Python model needing no toolchain, runs the same sequence and agrees — including on the 192/256 bit-order figure, which is a property of the golden function neither could have copied from the other. The model additionally reproduces the *original* code (`with_fixes=False`) and confirms the interrupt scenario desyncs it, so fix #2 above is demonstrated against the defect rather than merely argued.

The model also earned its keep immediately: the first version of the bit-order test used a single vector for which reversal was undetectable under the golden model, so it would have passed a testbench that was blind to bit order. That test is now a sweep.

**What it does not prove.** `BSCANE2`'s real pulse timing — the testbench substitutes for the primitive. Real clock margins — this is functional simulation with an idealised clock. Synthesis — compiling and synthesising are different. And nothing host-side.

### 5. Host driver rewritten as `host/scanchain.py` — fixes [#3](docs/KNOWN_ISSUES.md), [#4](docs/KNOWN_ISSUES.md), [#8](docs/KNOWN_ISSUES.md)

**What.** `host/scan_bscane2.py` is superseded by `host/scanchain.py`, with 22 offline tests in `host/test_scanchain.py`. The original is kept, unchanged, as the reference until the new one has a passing hardware run.

**What deliberately did *not* change: the wire protocol.** The MPSSE encoding and decoding carry 4096/4096 vectors of hardware evidence — more than anything else in this project — so rewriting them would have thrown away the strongest result available. They are ported verbatim. `test_scanchain.py` re-implements the original algorithm from `scan_bscane2.py` and asserts the new code emits byte-identical commands and decodes identically for **every width from 1 to 64 bits**. That is the guard against the rewrite quietly breaking what already worked.

**Why — the problems in the original.**

- *Mask ignored (#3).* `maskbits = lineContent[2]` was assigned and never read again, so every vector was compared as an exact match. The bundled tracefile's first two vectors carry `mask = 0` — they were meant to be skipped and were being compared anyway.
- *Width leakage (#4).* The decode loop used `outputLen`, `no_of_bytes` and `no_of_bits` left behind by the final iteration of the *write* loop. Correct only while every vector shares one width; a ragged file decoded at the wrong width and produced plausible, wrong values with no error.
- *Ergonomics (#8).* Positional arguments, a raw `ftd2xx` traceback when no board was attached, an IDCODE that was printed but never checked, `61440` appearing twice unexplained, no summary across 4096 lines of output, and exit code 0 regardless — so it could not gate a script.

**Structure.** Everything above `class JtagDevice` is pure: no hardware, no I/O. Not incidental — parsing, encoding and decoding are exactly where the defects were, and they are now the parts testable without a board.

**Verification.** 22 tests, all passing offline. Byte-for-byte equivalence with the original across widths 1–64; read-count consistency (the decoder must consume exactly the bytes the encoder requested, or every later vector in the batch desynchronises silently); tracefile parsing including CRLF, comments and ragged-width rejection with line numbers; and mask handling including per-bit masks and don't-cares. **Untested:** anything touching the FTDI device or the USB batching path.

**One deliberate output difference.** Fully masked vectors now report `Skipped` instead of `Success`, so a diff against `results/string_detector_output.txt` will show **exactly two changed lines** — the two `mask = 0` vectors. Those two lines are the visible proof the mask fix works; any other difference in that diff is a regression.

### Still unchanged

The wire protocol. `host/scan_bscane2.py` is kept byte-for-byte as inherited, and the rewrite is pinned to its output across every width from 1 to 64 bits — the encoding and decoding are the part of this project with 4096/4096 behind them, and a rewrite that quietly changed one byte would have destroyed the strongest evidence available. That decision also paid for itself: running the untouched original against the same bitstream is what located the `encode_ir` bug in a single command.

**Of the nine findings, eight are resolved and one — [#2](docs/KNOWN_ISSUES.md), the TDO launch edge — is open and unproven in both directions.**

---

## Roadmap

**Status, 2026-08-11.** Three examples pass on hardware — `seq1011` 600/600 unmasked, `bcd_adder` 100/100 exhaustive, `string_detector` 44/44 — and the whole flow has been run head to head against the original one on the same design and board ([RESULTS.md §5E](docs/RESULTS.md)). Both produce correct results; the difference is what it costs to get there and whether the output tells you when it did not.

The bench work in [docs/BENCH_CHECKLIST.md](docs/BENCH_CHECKLIST.md) is done — build, program, parity, the D1 A/B, the ALU exhaustive run and the divider sweep all passed on the board. Results and evidence tiers: [docs/RESULTS.md](docs/RESULTS.md).

**Next step:** re-run the divider sweep with the FTDI's /5 prescaler disabled (MPSSE `0x8A`). It raises the ceiling from 6 MHz to 30 MHz and is the only experiment that can settle [issue #2](docs/KNOWN_ISSUES.md) in either direction.

Six phases, ~11–12 hours: make it build reproducibly, fix the two real bugs, harden the host script, automate the build/program/wrapper-generation, add a hardware-free simulation testbench, and document the results. See [docs/ROADMAP.md](docs/ROADMAP.md) for the phase checklists, and [docs/ENGINEERING_LOG.md](docs/ENGINEERING_LOG.md) for the state this project was inherited in, the reasoning behind the phase ordering, and a defect-to-phase traceability matrix.

---

## Credits

**Original implementation — Anubhav Bhura, Wadhwani Electronics Laboratory, IIT Bombay.**

The scan chain architecture, the `BSCANE2`-based `TopLevel.vhd` harness, the FTDI MPSSE host driver (`scan_bscane2.py`), the tracefile format, and the Artix-7 port of the original MAX 10 Virtual-JTAG flow are all his work. That includes every design decision this repository is built on: the two-phase `io` multiplexing scheme, the split-the-MSB-off trick for the final bit in Shift-DR, and the USB command batching that makes 4096-vector runs practical.

**This repository — JJ (Jaivardhan Jain).** Restructuring, documentation, defect analysis, and the improvements tracked in [docs/ROADMAP.md](docs/ROADMAP.md). The [known issues](docs/KNOWN_ISSUES.md) are findings from reading the original code, not regressions introduced here; every change made since is recorded in [Changes to the original implementation](#changes-to-the-original-implementation) above and in the [engineering log](docs/ENGINEERING_LOG.md).

Developed for undergraduate digital-design labs at IIT Bombay.

## License

No license is currently granted. The original code belongs to its author and the Wadhwani Electronics Laboratory, IIT Bombay; a license would be theirs to choose. Until one is added, this repository is viewable but not licensed for reuse or redistribution.
