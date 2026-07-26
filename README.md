# Artix-7 JTAG Scan Chain Tester

Automated, vector-based functional testing of VHDL designs on a Xilinx Artix-7 FPGA, driven entirely over JTAG from a host PC. No test pins, no switches, no LEDs — the design under test (DUT) is fed input vectors and read back through the FPGA's built-in JTAG TAP.

This is an Artix-7 port of an existing MAX 10 flow. The MAX 10 version used Altera's Virtual JTAG IP; this one uses Xilinx's `BSCANE2` primitive. See [docs/MIGRATION_MAX10_TO_ARTIX7.md](docs/MIGRATION_MAX10_TO_ARTIX7.md).

> **Status: working prototype.** The protocol is proven — 4096/4096 vectors pass on the bundled passthrough test ([results/](results/)). But the repo has known defects and gaps that are being worked through; read [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) before trusting a result, and [docs/ROADMAP.md](docs/ROADMAP.md) for what's planned.

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
| `hdl/` | The reusable harness — `TopLevel.vhd` (BSCANE2 + scan register) and `constraints.xdc`. |
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

Two of these can produce **silently wrong passes or failures** — read the detail before relying on results.

| # | Issue | Impact |
|---|---|---|
| 1 | `io` phase bit has no reset path (`BSCANE2.RESET` is left open) | A crashed script permanently desyncs host and FPGA. Every later result is wrong. |
| 2 | TDO launched and sampled on the same clock edge | Works at the current divider by timing luck, not design. |
| 3 | Mask column parsed but never applied | Don't-care outputs are compared as hard values. |
| 4 | Read parser reuses widths leaked from the write loop | Ragged tracefiles mis-parse instead of erroring. |
| 5 | `StringDetector.vhd` is not in this repo | `examples/string_detector` will not elaborate as-is. |

Full write-ups and fixes: [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md).

---

## Roadmap

Six phases, ~11–12 hours: make it build reproducibly, fix the two real bugs, harden the host script, automate the build/program/wrapper-generation, add a hardware-free simulation testbench, and document the results. See [docs/ROADMAP.md](docs/ROADMAP.md).

---

## Credits

**Original implementation — Anubhav Bhura, Wadhwani Electronics Laboratory, IIT Bombay.**

The scan chain architecture, the `BSCANE2`-based `TopLevel.vhd` harness, the FTDI MPSSE host driver (`scan_bscane2.py`), the tracefile format, and the Artix-7 port of the original MAX 10 Virtual-JTAG flow are all his work. That includes every design decision this repository is built on: the two-phase `io` multiplexing scheme, the split-the-MSB-off trick for the final bit in Shift-DR, and the USB command batching that makes 4096-vector runs practical.

**This repository — JJ (Jaivardhan Jain).** Restructuring, documentation, defect analysis, and the improvements tracked in [docs/ROADMAP.md](docs/ROADMAP.md). No functional changes have been made to the original HDL or host code as of the initial commit; the [known issues](docs/KNOWN_ISSUES.md) are documented findings from reading the code, not regressions.

Developed for undergraduate digital-design labs at IIT Bombay.

## License

MIT — see [LICENSE](LICENSE).
