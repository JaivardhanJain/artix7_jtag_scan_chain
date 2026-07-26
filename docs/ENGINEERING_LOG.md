# Engineering Log

A chronological record of the state of this project as inherited, the defects found in it, and the plan for addressing each one. Entries are append-only — corrections are made in later entries rather than by editing earlier ones.

---

## Entry 001 — 2026-07-26 — Audit of the inherited state

### 1.1 What was received

A single directory, doubly nested as `Scan Chain/Scan Chain/`, containing four things:

```
Scan Chain/Scan Chain/
├── Artix7test/                 3.4 MB   Vivado project, part xc7a35tftg256
├── Artix7test_2020/            3.3 MB   Vivado project, part xc7a15tftg256
├── scan_chain_demo.pptx        1.4 MB   presentation material
└── scan_chain_files/           264 KB   host script, tracefile, results
```

Total 8.3 MB, of which roughly 6.6 MB was regenerable Vivado build output (`.runs/`, `.gen/`, `.cache/`, `.Xil/`, `.hw/`, `.ip_user_files/`, `.sim/`, `vivado.log`, `vivado.jou`, `.dcp`, `.bit`).

There was **no version control**, no README, no build script, no testbench, and no documentation of any kind.

### 1.2 Source files, as inherited

Five hand-written files existed. Verbatim inventory:

| File | Location | Contents |
|---|---|---|
| `Toplevel.vhd` | `Artix7test.srcs/sources_1/new/` | The harness. Entity `TopLevel` with **no ports**. Instantiates `BSCANE2` (`JTAG_CHAIN => 1`, i.e. USER1) and a `DUT` component. Contains the scan register, the `io` phase bit, and the two width constants (`number_of_inputs := 7`, `number_of_outputs := 1`). |
| `DUT.vhd` | same | Wrapper flattening a `StringDetector` into `input_vector(6 downto 0)` / `output_vector(0 downto 0)`. Mapping documented in a header comment: bits 6–2 = `inp`, bit 1 = `reset`, bit 0 = `clock`. |
| `FSM.vhd` | same | Entity `ALU` — a 4-bit ALU with `MAX`/`ANDER`/`ROTATOR`/`EQUATOR` functions, 8 bits in, 6 out. Unrelated to `DUT.vhd`. Filename does not match its contents. |
| `constraints.xdc` | `Artix7test.srcs/constrs_1/new/` | Two lines only: an `IOSTANDARD LVCMOS33` assignment on `state_out[*]`, and `set_property SEVERITY Warning [get_drc_checks UCIO-1]`. |
| `scan_bscane2.py` | `scan_chain_files/` | ~250 lines. FTDI MPSSE host driver: opens channel 0, sets clock divider `0x3B`, resets the TAP, reads the 32-bit IDCODE, loads `USER1 = 0x02` into the 6-bit IR, then loops over the tracefile issuing DR scans and comparing results. Batches commands to 61440 bytes per USB transfer. |

Plus data files: `TRACEFILE.txt` (46 vectors, 7 bits in / 1 bit out) and three result files — `output.txt` (46 lines, all `Success`), `out.txt` and `output1.txt` (4096 lines each, 12 bits in / 8 bits out, all `Success`).

### 1.3 What demonstrably worked

This matters and should not be understated: **the protocol was proven.** `out.txt` and `output1.txt` are two independent 4096-vector exhaustive sweeps in which every single vector passed. That establishes that

- `BSCANE2` with `JTAG_CHAIN => 1` and a 6-bit `USER1 = 0x02` correctly places the user data register in the scan path on Artix-7,
- the two-phase `io` multiplexing scheme (inputs on one DR scan, outputs on the next) works,
- the last-bit-with-TMS technique for leaving Shift-DR is correct,
- the 61440-byte USB batching works and is fast enough to make thousands of vectors practical,
- the response byte-reversal decode is correct.

The hard part — porting Altera Virtual JTAG semantics onto a Xilinx primitive — was already done and validated. Everything below is about robustness, reproducibility and usability, not about whether the approach works.

### 1.4 Corrections to earlier assessments

Two things previously believed to be problems are not:

- **The `if udr / elsif cdr / elsif sdr` chain in `Toplevel.vhd` is correct.** It was flagged as "CAPTURE and SHIFT nested when they should be parallel." Update-DR, Capture-DR and Shift-DR are mutually exclusive TAP states, so at most one branch can ever be eligible in a given cycle and priority ordering is irrelevant. No change needed.
- **No `v_jtag.vhdl` shim is needed.** The plan to write a wrapper reproducing Altera's 30-port `v_jtag` interface was unnecessary work — `BSCANE2` is instantiated directly and the surrounding scan logic is untouched. The port correspondence is one-to-one (documented in [MIGRATION_MAX10_TO_ARTIX7.md](MIGRATION_MAX10_TO_ARTIX7.md)).

---

## Entry 002 — 2026-07-26 — Defects found

Nine findings from reading the code. Full write-ups in [KNOWN_ISSUES.md](KNOWN_ISSUES.md); this entry records how each was found and why it matters. **`D`*n* here corresponds one-to-one with issue #*n* there.**

### D1 — `io` phase bit has no reset path *(high)*

`io` is initialised only by its signal declaration, which takes effect at FPGA configuration and never again. `BSCANE2`'s `RESET` and `SEL` outputs are both left `open`.

Found by asking what happens if the host script dies between the two DR scans of a vector. Answer: the FPGA has advanced `io` an odd number of times relative to the host's model, and stays inverted forever. Every subsequent vector is then shifted into the wrong phase. There is no error — just failures, or coincidental passes. Only reprogramming the FPGA recovers.

This is the most serious finding because it is silent and because the passing 4096-vector results cannot rule it out: an uninterrupted run is exactly the case where it doesn't bite.

### D2 — TDO launched and sampled on the same clock edge *(high)*

`tdo <= datau(0)` is combinational, `datau` is registered on the **rising** edge of TCK, and the host reads with MPSSE `0x2C`/`0x2E` — also rising edge. IEEE 1149.1 requires TDO to change on the falling edge precisely so the host can sample safely on the rising edge.

Found by cross-checking the MPSSE opcode edge semantics against the HDL clocking. It works today because the ~500 kHz divider leaves enough slack for the output to settle before the FTDI's sample point. That is timing margin, not design — and it is a plausible explanation for why the divider is set so conservatively in the first place.

### D3 — Mask column parsed and discarded *(medium)*

```python
maskbits = lineContent[2]    # assigned, never read again
```

The tracefile's third column marks which vectors to compare. It is extracted and dropped; comparison is always an exact full match. The bundled `TRACEFILE.txt` sets `mask = 0` on its first two lines, meaning those two vectors are *meant* to be skipped and currently are not. Also `lineContent[2]` raises a bare `IndexError` with no line number on any two-column line.

### D4 — Read parser depends on variables leaking from the write loop *(medium)*

The response decoder reads `outputLen`, `no_of_bytes` and `no_of_bits` without computing them — they hold whatever the final iteration of the *write* loop left behind. Correct only while every vector shares one width. A ragged tracefile silently decodes at the wrong width and produces plausible-looking wrong values. No width validation exists on load.

### D5 — `StringDetector.vhd` is missing *(blocking)*

`DUT.vhd` instantiates a `StringDetector` component that exists nowhere in the delivered files. `FSM.vhd` contains an unrelated `ALU`. **The project as received cannot elaborate.** Found by grepping for the component name across the whole tree.

### D6 — Vivado project state had drifted *(blocking for reproducibility)*

`Artix7test.xpr`'s source list contained `DUT.vhd`, `FSM.vhd` and `constraints.xdc` — **`Toplevel.vhd` was not listed at all.** The file that is the actual top level was not in the project. Meanwhile `Artix7test_2020.xpr` listed `Toplevel.vhd` and `DUT.vhd` but targeted a different part (`xc7a15tftg256` vs `xc7a35tftg256`), and which one matches the physical board is undocumented.

This is the root cause of the reproducibility problem: build configuration lived in a binary project file that nothing kept in sync with the source tree.

### D7 — Vestigial constraints *(low)*

`constraints.xdc` constrains a `state_out` port that is commented out in `Toplevel.vhd`, so `get_ports state_out[*]` matches nothing. The `UCIO-1` DRC downgrade existed to suppress the unconstrained-I/O error that port used to cause. A top level with no ports needs neither line — and leaving the DRC suppressed will hide genuine unconstrained-port errors in any DUT added later.

### D8 — Host script hygiene *(low individually)*

Stale MAX 10 comment on the Artix-7 clock divider; `ftd.open(0)` with no error handling, so an absent board yields a raw traceback; IDCODE read and printed but never validated; hardcoded channel; `61440` as an unexplained magic number appearing twice; no pass/fail summary across 4096 lines; always exits 0 so it can't gate a script; unused `time`/`math`/`bitstring` imports; CRLF tracefile with inconsistent trailing spaces that `split(' ')` tolerates only incidentally.

### D9 — No way to test without hardware

No testbench of any kind. Every change to the scan logic, the width constants or a tracefile requires a full synthesis → implementation → bitstream → program cycle before you learn whether the bit ordering was right. This is the largest practical drag on the project and the biggest barrier to anyone else picking it up.

---

## Entry 003 — 2026-07-26 — Repository restructure (completed)

First change made. Deliberately **non-functional**: no HDL or Python logic was modified, so the committed results remain valid as a baseline for everything that follows.

**Actions taken**

- Flattened the doubled `Scan Chain/Scan Chain/` nesting.
- Separated the reusable harness from per-lab material: `hdl/` (harness), `host/` (driver), `examples/<design>/` (DUT wrapper + tracefile), `results/`, `scripts/`, `docs/`.
- Renamed `FSM.vhd` → `examples/alu/ALU.vhd` so filename matches contents (D8 partial).
- Moved both Vivado project directories to an untracked `vivado/` — nothing deleted, still on disk, but excluded from version control since the state is regenerable and had drifted (D6).
- `git init`, `.gitignore` covering all Vivado output, `.gitattributes` normalising line endings to LF (addresses the CRLF half of D8).
- Wrote `scripts/build.tcl` and `scripts/program.tcl` for headless build and programming — untested, but they put the source list under version control instead of in a `.xpr` (D6).
- Documented the architecture, tracefile format, MAX 10 → Artix-7 migration, troubleshooting, known issues and roadmap.

**Outcome:** repo went from 8.3 MB of mixed source and build output with no documentation to 1.8 MB tracked, 27 files, fully documented. Three commits.

**Not addressed by this entry:** every defect D1–D5, D7, D9 and most of D8 remains open. Restructuring made them *visible and tracked*; it did not fix them.

---

## Entry 004 — 2026-07-26 — Plan, and how it maps to each defect

Six phases, ~11–12 hours, ordered so the project is buildable before anything is measured. Full detail in [ROADMAP.md](ROADMAP.md). This entry records the reasoning behind the ordering and the defect-to-phase mapping.

### Why this order

Nothing below Phase 1 is verifiable until the project elaborates (D5, D6). There is no point fixing a timing race you cannot build and test. Phase 2 then fixes the two defects that can corrupt results, because every measurement taken afterwards depends on the results being trustworthy. Only then is it worth investing in host-script quality (Phase 3), automation (Phase 4) and simulation (Phase 5) — each of which is easier to write correctly once the underlying behaviour is known-good.

### Traceability matrix

| Defect | Phase | How it is addressed | How the fix is verified |
|---|---|---|---|
| **D5** missing `StringDetector.vhd` | 1 | Recover from the original lab or rewrite from the port spec in `DUT.vhd`'s header comment. | Project elaborates; 46-vector run matches `results/string_detector_output.txt`. |
| **D6** project state drift, ambiguous part | 1, 4 | Stop committing `.xpr` entirely; generate the project from `scripts/build.tcl`, where the source list is version-controlled and `TopLevel` is explicitly set as top. Confirm the physical part from the IDCODE the script already prints. | A clean clone builds with one command and reproduces a committed result. |
| **D7** vestigial constraints | 1 | Replace `constraints.xdc` with an empty file — a portless top level needs no I/O constraints and no DRC suppression. | Build completes with no `UCIO-1` warning and no suppression in place. |
| **D1** `io` has no reset path | 2 | Wire `BSCANE2.RESET` (and `SEL`) into a synchronous clear of `io`. The host already issues a TAP reset before its IDCODE read, so with the HDL fix every invocation self-synchronises. | Deliberately `Ctrl-C` mid-run, then rerun **without reprogramming** and confirm a full pass. This is the specific test that fails today. |
| **D2** TDO edge race | 2 | Register TDO on the falling edge of TCK (spec-compliant), *or* switch the host to `0x2D`/`0x2F` negative-edge reads. One or the other, not both. | Sweep the clock divider from `0x3B` downward; record the fastest reliable setting and vectors/second. A fix should raise the safe ceiling — and that delta is the project's one measurable "it is better" claim. |
| **D3** mask ignored | 3 | Apply the mask per bit before comparing; support `x`/`-` don't-cares in the expected column; validate column count with line numbers in the error. | The two `mask = 0` vectors in the bundled tracefile are reported as skipped, not compared. |
| **D4** width leakage | 3 | Parse widths once at load time, assert every line matches, pass them explicitly into the decoder. | A deliberately ragged tracefile produces a clear error naming the offending line instead of wrong results. |
| **D8** hygiene | 3 | `argparse` for tracefile/out/channel/divider/expected-IDCODE; readable FTDI open failure; IDCODE validated against the part; named constant for the batch threshold; pass/fail/elapsed/throughput summary; non-zero exit on failure; dead imports and the stale MAX 10 comment removed. | Running with no board attached prints a useful message; a failing run exits non-zero; a passing run prints one summary line. |
| **D9** no hardware-free testing | 5 | `sim/tb_scanchain.vhd` — a behavioural testbench driving the CAPTURE/SHIFT/UPDATE handshake directly against the real `TopLevel` and DUT, so vectors and bit ordering are validated in simulation. | Introduce a deliberately reversed bit order and confirm simulation catches it without touching hardware. |
| *(usability, not a defect)* | 4 | `scripts/new_lab.py` parses a DUT entity and generates the `DUT.vhd` wrapper, the two width constants, and a tracefile layout comment. Today both edits are manual and are the real barrier to adoption. | A new DUT goes from entity file to a running test with one command plus a tracefile. |

### Definition of done

Someone who has never seen this repository can clone it, run one build command, one program command, and one test command, and get a passing result with a summary line — having read only the README. An interrupted run recovers by itself. A wrong bit order is caught in simulation rather than on the bench. Every defect above is either fixed or, if deliberately deferred, recorded here with the reason.

### Known risks to this plan

- `StringDetector.vhd` may be unrecoverable, in which case Phase 1 grows by about an hour to rewrite it from the spec — or a simpler sequential example is substituted.
- The divider sweep may show the current `0x3B` is already near the reliable ceiling, which would make the throughput result unimpressive. A documented safe-operating-margin figure is still a legitimate finding; the claim just becomes robustness rather than speed.
- The phase-reset fix could interact with Vivado's own use of the TAP. Using `SEL` deassertion should cover the case where Hardware Manager takes the chain, but this needs testing with Vivado both open and closed.
