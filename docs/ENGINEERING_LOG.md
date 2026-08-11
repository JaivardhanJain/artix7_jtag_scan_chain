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

Plus data files: `TRACEFILE.txt` (46 vectors, 7 bits in / 1 bit out) and three result files — `output.txt` (46 lines, all `Success`), `out.txt` and `output1.txt` (4096 lines each, 12 bits in / 8 bits out, all `Success`). [**correction, entry 018: `output1.txt` is NOT all Success — it is 510 pass / 3586 fail, a captured stuck-at-0 failure. This line was written from the files' size and shape without counting.**]

### 1.3 What demonstrably worked

This matters and should not be understated: **the protocol was proven.** `out.txt` and `output1.txt` are two independent 4096-vector exhaustive sweeps in which every single vector passed. [**correction, entry 018: only `out.txt` passed. `output1.txt` is a failed run. The conclusions below stand on the one clean sweep; the claim of independent repetition does not.**] That establishes that

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

Found by cross-checking the MPSSE opcode edge semantics against the HDL clocking. It works today because the ~500 kHz divider [**correction, entry 016: the divider is 100 kHz, not 500 kHz — every frequency in this log before entry 016 is 5x too high**] leaves enough slack for the output to settle before the FTDI's sample point. That is timing margin, not design — and it is a plausible explanation for why the divider is set so conservatively in the first place.

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

`Artix7test.xpr`'s source list contained `DUT.vhd`, `FSM.vhd` and `constraints.xdc` — **`Toplevel.vhd` was not listed at all.** The file that is the actual top level was not in the project. Meanwhile `Artix7test_2020.xpr` listed `Toplevel.vhd` and `DUT.vhd` but targeted a different part (`xc7a15tftg256` vs `xc7a35tftg256`), and which one matches the physical board is undocumented. [**correction, entry 019: the parts are stated backwards here. `Artix7test` is the xc7a15t project; `Artix7test_2020` is the xc7a35t one and therefore the correct one for this board.**]

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

---

## Entry 005 — 2026-07-29 — Phase 1/2 HDL work: core split and both high-severity fixes

Three changes, one commit, all in `hdl/`. `host/scan_bscane2.py` deliberately untouched — see 5.4.

### 5.1 `scan_core` extracted from `TopLevel` *(enabler, no behavioural change)*

`TopLevel.vhd` previously contained both the `BSCANE2` instantiation and the whole shift register. Now:

- `hdl/TopLevel.vhd` — Xilinx-specific wiring only: BSCANE2 → scan_core → DUT, plus the two width constants.
- `hdl/scan_core.vhd` — all shift, capture and phase logic, behind plain `std_logic` ports (`tck`, `tdi`, `tdo`, `capture`, `shift`, `update`, `jtag_reset`, `sel`, `dut_input`, `dut_output`, `io_phase`).

**Motivation.** `BSCANE2` exists only in Vivado's `unisim` library, so with the logic and the primitive in one file there was no practical way to simulate the scan chain — which is why D9 existed and why every bit-ordering question cost a full synthesise-implement-program-test cycle. `scan_core` has no vendor dependency, so a testbench drives the TAP handshake ports directly.

Two secondary benefits: the DUT is instantiated in `TopLevel`, not in `scan_core`, so the core is DUT-agnostic and a testbench can substitute any DUT or drive `dut_output` directly; and both fixes below became small local edits inside one reviewable file rather than surgery on the top level.

The `io_phase` output was added for observability — a testbench can assert on it directly, and it is the signal the commented-out `state_out` debug port existed to expose. `TopLevel` leaves it `open`, so it costs nothing.

### 5.2 D1 fixed — `io` now has a reset path

`BSCANE2.RESET` and `SEL`, previously `open`, are wired into `scan_core`:

```vhdl
shift_reg : process(tck, jtag_reset)
begin
  if jtag_reset = '1' then       -- Test-Logic-Reset, asynchronous
    io <= '0';
  elsif rising_edge(tck) then
    if sel = '0' then            -- USER1 not selected
      io <= '0';
    elsif update = '1' then
      ...
```

The reset is asynchronous on `jtag_reset` deliberately: recovery must not depend on `tck` still being clocked. The `sel = '0'` clear covers the case where the TAP moves to another instruction — including Vivado's Hardware Manager taking the chain — and parks the phase at input so the next run starts from a known state.

No host change was required: `scan_bscane2.py` already issues a TAP reset before its IDCODE read, so with this fix every invocation self-synchronises.

### 5.3 D2 fixed — TDO launched on the falling edge

```vhdl
tdo_reg : process(tck)
begin
  if falling_edge(tck) then
    tdo <= datau(0);
  end if;
end process;
```

The concern with any change to a shift path is an off-by-one. There isn't one here, because moving the launch edge does not move the data:

| Edge | Event |
|---|---|
| rising *N* | Capture-DR: `datau <= dut_output`, so `datau(0) = d0` |
| falling *N* | `tdo <= d0` |
| rising *N+1* | host samples `tdo = d0` — stable, launched half a cycle earlier. `datau` shifts, `datau(0) = d1` |
| falling *N+1* | `tdo <= d1` |
| rising *N+2* | host samples `d1` |

Identical bit sequence, no added latency; only the launch instant moves earlier by half a period. The host stays on its rising-edge `0x2C`/`0x2E` reads. The alternative fix — switching the host to `0x2D`/`0x2F` — was rejected because fixing it in HDL makes the design spec-compliant for any future host, rather than making one particular host compensate.

### 5.4 Why the host was left alone

Keeping `scan_bscane2.py` byte-identical across this change means the 46-vector parity run isolates the HDL edits. If the output diffs against `results/string_detector_output.txt`, the cause is unambiguously in `hdl/`. Host-side work (D3, D4, D8) is a separate change with its own verification.

### 5.5 Verification status — nothing here is proven yet

Every claim above is a design argument, not a measurement. GHDL is not installable in the environment these edits were made in, so not even a compile check has been run; the code has been reviewed for syntax and elaboration, no more. Outstanding:

| Check | Expectation | Catches |
|---|---|---|
| `xvhdl` / `xelab` compile | clean | syntax, port map, null-slice errors |
| Build via `scripts/build.tcl` | bitstream produced, no `UCIO-1` | the added `scan_core.vhd` source entry |
| 46-vector parity vs committed result | byte-for-byte identical | any behavioural drift from the split; an off-by-one from the TDO edge move |
| Interrupt mid-run, rerun **without reprogramming** | full pass | D1. **This is the test that fails on the original code** — it is the fix's whole justification |
| Divider sweep down from `0x3B`, before/after | safe ceiling should rise | D2, and yields the one measurable improvement figure |

Until the parity run and the interrupt test both pass, D1 and D2 are recorded as *fixed in HDL, pending hardware verification* — not closed.

### 5.6 Also updated (see also entry 006)

`scripts/build.tcl` now adds `hdl/scan_core.vhd` alongside `TopLevel.vhd`. Easy to miss, and it would have produced a confusing "entity scan_core is not bound" at elaboration.

---

## Entry 006 — 2026-07-29 — Simulation: testbench, offline model, and a bug the model found

Addresses D9. Also produces the first actual *verification* of anything in this project — entry 005's changes were design arguments; some of them are now checked.

### 6.1 `sim/tb_scan_core.vhd`

A self-checking testbench that plays the role `BSCANE2` plays on hardware: it drives `tck`, `capture`, `shift`, `update`, `jtag_reset` and `sel`, and reads `tdo`. Possible only because entry 005 moved the logic into a vendor-neutral entity — no `unisim`, no primitive model.

The important detail is the sampling discipline: **`tdo` is sampled while `tck` is low, immediately before the rising edge.** That is exactly what an MPSSE `0x2C`/`0x2E` read sees. A testbench that sampled at a convenient moment instead would pass regardless of which edge the design launches on, and would have been useless for checking D2.

Four tests:

| # | What | Why it's there |
|---|---|---|
| 1 | Exhaustive scan, all 256 vectors | Shift ordering, phase alternation, capture timing, falling-edge launch |
| 2 | Abandon a vector, `jtag_reset`, run a normal vector | The simulation equivalent of the Ctrl-C bench test — **fails on the original code** |
| 3 | Same, recovering via `sel = '0'` | The path taken when Hardware Manager takes the chain between runs |
| 4 | Bit-order sweep | Keeps 1–3 honest |

### 6.2 `sim/model_scan_core.py` — not in the original plan

A Python re-implementation of `scan_core`'s cycle semantics, driven by the same sequence. Motivation was practical: no VHDL toolchain was available in the environment these edits were made in, and "write it and hope" was not an acceptable state to leave the repository in. A model that runs anywhere in under a second is a poor substitute for a simulator but a good substitute for nothing.

It carries a `with_fixes=False` mode reproducing the **original** design, where `RESET` and `SEL` were `open`. Test 2b runs the interrupt scenario against it and confirms it desyncs:

```
TEST 2b original code: after interruption got [0,0,0,0], expected [1,1,1,1]
                       -> desynced as expected
```

That matters more than it looks. D1 was found by reading code and reasoning about a failure mode nobody had observed. This is the first evidence the failure mode is real rather than a plausible story about pointer arithmetic in someone else's design.

Full result:

```
TEST 1 exhaustive scan      : 256 vectors, 0 errors
TEST 2 desync via TAP reset : 0 errors
TEST 2b original code       : desynced as expected
TEST 3 desync via deselect  : 0 errors
TEST 4 bit-order sensitivity: 192/256 reversed vectors detected as wrong
=== 264 checks, 0 errors ===
```

### 6.3 The model immediately found a bug — in the testbench

The first version of test 4 shifted **one** vector in backwards (`0xD2`) and asserted the result differed. The model reported it did *not* differ.

The cause is a property of the golden model, `low_slice xor high_slice`. Reversing all 8 bits maps the low slice onto the reverse of the high slice and vice versa, so the result is the bit-reversal of the correct result. Whenever that result happens to be a palindrome — `1111`, `0000`, `0110`, … — reversal is undetectable. 64 of 256 vectors have that property, and `0xD2` is one of them.

So the test would have passed a testbench that was completely blind to bit order, which is precisely the failure it exists to prevent. Switching the golden model to an adder was considered and rejected — it only reduces the blind set from 64 to 44, and leaves the test dependent on a lucky vector and on the widths never changing.

Test 4 is now a sweep over all vectors requiring at least one detection. It reports 192/256, and the count itself is diagnostic: a sudden drop would mean the golden model has drifted toward reversal symmetry.

The general lesson, worth stating because it applies to the rest of this project: a negative test that can pass for the wrong reason is worse than no negative test, because it manufactures confidence.

### 6.4 What is now verified, and what is not

**Verified.** The scan protocol logic — bit ordering, phase alternation, capture and update timing, and the recovery behaviour of both D1 fixes — against an independent model, exhaustively over the input space.

**Not verified.**

| | Why not |
|---|---|
| The VHDL compiles | No toolchain available here. `sim/run_sim.bat` is the first thing to run at a machine with Vivado. |
| `BSCANE2`'s real pulse timing | The testbench substitutes for it. If the primitive's CAPTURE/SHIFT/UPDATE behaviour differs from what's modelled, only hardware shows it. |
| The falling-edge launch at speed | The model proves the launch edge is *logically* right. It says nothing about the maximum safe TCK frequency; that still needs the divider sweep. |
| Synthesis | Simulating and synthesising are different. A green testbench does not guarantee `build.tcl` succeeds. |
| Anything host-side | MPSSE construction, batching and decoding are untouched by all of this. |

D1 and D2 stay recorded as *fixed in HDL, pending hardware verification*. The model raises confidence; it does not close them.

---

## Entry 007 — 2026-07-29 — Host driver rewritten, with equivalence tests

Addresses D3, D4 and D8. `host/scan_bscane2.py` is superseded by `host/scanchain.py`; the original is kept unchanged as the reference until the new one has a passing hardware run.

### 7.1 The constraint that shaped the rewrite

The MPSSE encoding and decoding are the only part of this project with **hardware-tier** evidence behind them — 4096/4096 vectors, twice. A rewrite that changed a single byte of that would have thrown away the strongest result available, and the resulting failures would have been indistinguishable from an FPGA problem.

So the encoding and decoding are ported verbatim, including the parts that look odd: the `format(b, '08b')[2]` extraction of the final TMS-read bit, the reverse-order byte reassembly, and `split_bytes_bits` returning `(1, 8)` rather than `(2, 0)` for a 16-bit vector so the last bit is always available to clock out with TMS.

`host/test_scanchain.py` re-implements the original algorithm verbatim from `scan_bscane2.py` and asserts byte-for-byte equivalence across **every width from 1 to 64 bits**, 20 random vectors each. That converts "the rewrite was careful" into something checkable, and it will keep being checkable as the driver evolves.

### 7.2 D3 — mask applied

`maskbits` was assigned and never read again. Now applied per bit, with `x`/`-` don't-cares in the expected column folded into the mask so there is exactly one comparison mechanism downstream. Both whole-vector (`1`/`0`) and per-bit masks are accepted.

Fully masked vectors now report `Skipped` rather than `Success`. This is a deliberate output change and it has a useful consequence — see 7.5.

### 7.3 D4 — widths fixed at parse time

Widths are established by the first vector and checked on every subsequent line, with the offending line number and both widths in the error message. They are then passed explicitly into the decoder instead of being read out of whatever the write loop happened to leave behind.

A test worth calling out is `test_decode_consumes_exactly_the_read_bytes`: for every width, the bytes the decoder consumes must equal the bytes the encoder told the device to send. A mismatch there would desynchronise every remaining vector in the batch — silently, since the data would still decode to something plausible. It is the same class of failure as D1, one layer up.

### 7.4 D8 — ergonomics

argparse; an FTDI-open error listing the four likely causes in order (Vivado holding the cable is first, because it is the most common); IDCODE validated against `--expect-idcode` and rejected if all-zeros or all-ones; `MAX_WRITE_CHUNK` named and explained; a pass/fail/skipped/throughput summary with a failures-only table; non-zero exit status. Dead `time`/`math`/`bitstring` imports and the "for MAX 10" comment removed.

Two additions beyond the plan: `--dry-run`, which validates a tracefile with no board attached, and `--divider`, which turns the clock-rate sweep from an edit-and-rerun loop into a flag.

### 7.5 A prediction the next hardware run will test

Because masked vectors now report `Skipped`, diffing a fresh 46-vector run against `results/string_detector_output.txt` should show **exactly two changed lines** — the `mask = 0` vectors at lines 1 and 2.

That prediction is worth stating in advance. Two changed lines confirms D3 is fixed and nothing else moved. Any *other* difference is a regression — and since the host's wire protocol is pinned by the equivalence tests, it would point at the HDL changes rather than the driver.

### 7.6 Structure, and why it is not incidental

Everything above `class JtagDevice` is pure: no hardware, no I/O. That is what makes 22 offline tests possible, and the boundary was drawn there deliberately — parsing, encoding and decoding are precisely where D3 and D4 lived.

The corollary is the honest limitation: the tests stop at the device boundary. Nothing exercises `JtagDevice`, the USB batching path, or how the batch threshold interacts with the read count on a real cable. Those remain hardware-only.

### 7.7 Verification status

| | Status |
|---|---|
| Wire protocol unchanged | Verified offline, widths 1–64 |
| D3, D4, D8 fixed | Verified offline, 22 tests |
| Runs against a board | **Not attempted** |
| FTDI transport and USB batching | **Untested** |

D3 and D4 are recorded as *fixed, offline-tested* — a weaker claim than *fixed*, and the right one until the driver has moved a vector across a real cable.

---

## Entry 008 — 2026-07-29 — VHDL simulation run: the model and the RTL agree

`sim/run_sim.bat`, Vivado Simulator **2020.2**. **259 checks, 0 errors**, 164 960 ns simulated in roughly 8 seconds of wall clock.

```
Note: TEST 1: exhaustive scan of all 256 input vectors
Note: TEST 2: desync recovery via jtag_reset
Note: TEST 3: desync recovery via sel = '0'
Note: TEST 4: bit-order sensitivity (reversed vectors must be detected)
Note: TEST 4: 192 of 256 reversed vectors detected as wrong
Note: === tb_scan_core done: 259 checks, 0 errors ===
Note: ALL TESTS PASSED
```

### 8.1 What this closes

Entry 006 was explicit that nothing had confirmed the VHDL even compiled. Every claim about the `scan_core` split, the `io` reset path and the falling-edge TDO register rested on a Python model written by the same person, in the same sitting, from the same set of assumptions — a model that can only ever confirm the author's own understanding of the design, not the design itself.

An independent toolchain now agrees. `xvhdl` and `xelab` analysed and elaborated cleanly with no warnings, and the testbench passes. Issues #1, #2 and #9 move from *model* tier to *simulation* tier in [RESULTS.md](RESULTS.md). #9 is closed outright.

### 8.2 The cross-check that carries the most weight

Both implementations independently report **192 of 256** reversed vectors detected.

That number is not a pass/fail flag either could have copied. It is a property of how the golden function `low_slice xor high_slice` interacts with bit reversal — the 64 vectors whose result is a palindrome are undetectable, leaving 192. Two implementations arriving at the same figure is evidence they are exercising the same logic, not merely both printing "passed".

### 8.3 259 checks versus the model's 264

A counting convention, not a coverage gap. The Python model routes its phase assertions — `io` cleared by reset, `io` set after a lone input phase, `io` cleared by deselect, and the pre-fix desync reproduction — through the same counter as vector comparisons. The VHDL testbench raises those as `assert` statements, which do not increment `checks`. Same four tests, same 256-vector space.

Recording this because an unexplained discrepancy between two supposedly equivalent suites is exactly the kind of thing that quietly erodes trust in both.

### 8.4 What simulation still cannot do

Test 2b — reproducing the defect against the *pre-fix* design — exists only in the Python model, and structurally must. The VHDL testbench instantiates the current `scan_core`, which has the fix; demonstrating the failure would mean maintaining a deliberately broken copy of the RTL alongside the good one. The model does that job for free, which is a reason to keep it rather than retire it now that xsim works.

Also still out of reach: `BSCANE2`'s real pulse timing, actual clock margins, synthesis, and the entire host-side transport.

### 8.5 Environment note

The Vivado install is **2020.2**, not the 2023.2 guessed earlier. Nothing in the project depends on a newer version — the HDL is plain VHDL-93 and the testbench uses no 2008 constructs. `scripts/build.tcl` defaults to `xc7a35tftg256-1`, which 2020.2 supports.

`xelab` also emitted `invalid command name "%"` from its Webtalk telemetry step. That is Xilinx failing to quote a path containing spaces (`Wadhwani Lab Research`); it occurs after elaboration completes and does not affect the result. Documented in [TROUBLESHOOTING.md](TROUBLESHOOTING.md) so it is not mistaken for a real failure later.

---

## Entry 009 — 2026-07-29 — D5 resolved: sources recovered, and a substitute example

### 9.1 Recovery

The missing `StringDetector` sources were located in the original MAX 10 lab material (a `lab7` tree, separate from this project). That tree is the complete pre-port flow — its `TopLevel.vhdl` still instantiates Altera's `v_jtag`, in the Vivado folders as well as the Quartus ones, which confirms the Artix-7 port never touched it.

Two variants existed, Wednesday and Friday, with different tracefiles. This repository's `TRACEFILE.txt` is a byte-for-byte match with the **Friday** variant, so that is the one installed. Guessing would have produced 46 confusing failures.

The design is three independent Mealy FSMs — `run`, `cry`, `broom` — with their outputs ORed. Subsequence rather than substring detection: on a mismatch each FSM holds its state. `broom` needs an extra state for the doubled `o`.

### 9.2 Verified before use, not assumed

Recovering a file is not the same as recovering the *right* file. Replaying all 46 vectors through a model of the three FSMs reproduces the expected column exactly — 0 mismatches across the 44 unmasked vectors. The hidden stimulus decodes to `" bringunocardsfrommybag"`, which contains all three target subsequences. That is conclusive: a wrong or differently-parameterised design would not reproduce 44 expected values by chance.

### 9.3 The publication problem, and `examples/seq1011`

The recovered files are filled-in coursework solutions — `RunDetector.vhdl` still carries its `-- Fill in:` template comments with the answers written underneath. This repository is intended to be public, and the lab may still be assigned.

They are therefore installed locally so the example builds, and **explicitly listed in `.gitignore`** rather than quietly omitted, so the exclusion is visible and deliberate. Everything else about the example stays committed: the wrapper, the tracefile, the captured hardware result, the documentation.

That alone would leave a public clone with no working example, so `examples/seq1011` was added: an overlapping `1011` sequence detector written for this repository. It exercises the same capabilities — clocked Mealy FSM, synchronous reset, generated tracefile — and is not coursework.

### 9.4 The new example's tracefile was wrong, and the cross-check caught it

Worth recording in full, because the failure mode is subtle and would have been diagnosed as a hardware problem.

`gen_tracefile.py` initially computed one expected output per stimulus bit and wrote it to **both** vectors of the clock pair. An independent check — transcribing `Seq1011.vhd`'s case statement directly from the VHDL and replaying the tracefile through it — disagreed on **65 of 600** vectors.

The generator was wrong. The scan chain captures one output per vector, so a clocked DUT needs two vectors per cycle, and for a Mealy output the correct expectation differs between them:

| Vector | State | Expected output |
|---|---|---|
| clock low | pre-edge | `mealy(state, din)` — the real detection for this bit |
| clock high | post-edge | `mealy(next_state(state, din), din)` — same input, advanced state |

Writing the same value twice is the natural first guess. The bundled string-detector tracefile shows the correct shape and could have been read as a specification: its detections appear as `1` on the clock-low line and `0` on the clock-high line following.

Two things this reinforces. First, the value of a cross-check derived from a *different* source than the artefact being checked — the transcription came from the VHDL text, not from the generator's model, so a shared misconception could not hide. Second, on hardware this would have presented as 65 scattered failures on an otherwise working harness, which is close to the worst diagnostic signal available: not a clean failure pointing at the tracefile, but a pattern that looks like marginal timing.

After the fix: 600 unmasked vectors, 0 mismatches.

### 9.5 Also changed

`scripts/build.tcl` now globs `*.vhdl` as well as `*.vhd`. The recovered lab files use the longer extension and were kept under their original names for provenance; without this they would simply not have been added to the project, and the failure would have surfaced as an unbound-entity error at elaboration.

### 9.6 Verification status

| | Status |
|---|---|
| Recovered sources match the tracefile | **Verified** — 44/44 unmasked vectors |
| `seq1011` tracefile matches its RTL | **Verified** — 600/600, against a transcription of the VHDL |
| Either design compiles | **Not verified** — neither has been through a VHDL toolchain |
| Either runs on hardware | **Not attempted** |

---

## Entry 010 — 2026-07-29 — D7 resolved, and the wrapper generator

### 10.1 D7 — constraints file emptied

`hdl/constraints.xdc` now contains only comments. A portless top level needs no I/O constraints, so the correct content is nothing.

The `state_out` line was harmless — it matched no ports. The `UCIO-1` downgrade was not: leaving it in place means a genuinely unconstrained port in any future DUT passes silently instead of failing the build. The comments explain both, so the lines do not get reinstated by someone hitting the DRC error and reaching for the quickest fix.

### 10.2 `scripts/new_lab.py`

Reads a VHDL entity, works out a bit layout, writes the `DUT.vhd` wrapper, and optionally patches the width constants into `TopLevel.vhd`.

This was identified in entry 004 as the item that actually determines whether anyone else can use this project. Every other defect makes the harness *wrong*; this one makes it *unusable by a stranger*. Hand-writing a wrapper means getting bit slicing right by hand, and a wrong slice produces a run where every vector fails with no indication of the cause — indistinguishable, from the output, from a dead board.

The layout convention was not invented; it was **derived from the wrappers that already existed** so generated and hand-written output agree:

```
input_vector(0) = clock,  input_vector(1) = reset,
remaining inputs above, first-declared in the highest bits
```

Clock at bit 0 has a practical justification beyond consistency: a clocked DUT needs vector pairs differing only in the clock, and putting it in the last character makes those pairs legible in a diff.

### 10.3 How it is verified

The strongest available check, and the reason the convention was derived rather than chosen: **run the generator against the same entities the committed wrappers were hand-written for, and require the port maps to match.**

Both match exactly — `Seq1011` and `StringDetector`. The latter's wrapper has 46 passing hardware vectors behind it, and the same harness has 4096, so agreeing with it is meaningful evidence rather than self-consistency. It also pins the convention: any future change that alters the layout breaks this test.

A second test asserts the assigned bit ranges tile the flattened vector exactly — no gaps, no overlaps, every bit covered once. A gap would shift every field above it; an overlap would silently alias two ports together. Neither produces an error message on hardware, only wrong results.

19 tests total, all passing offline. The error paths are tested for their *messages*, not just for raising: an `inout` port, an unsupported type and an ambiguous entity each have to say what to do about it.

### 10.4 The ALU, resolved

`examples/alu/ALU.vhd` arrived as `FSM.vhd` — a filename that did not match its contents, sitting next to an unrelated `DUT.vhd`. Entry 004 left its fate open.

Kept, as the **combinational** counterpart to `seq1011`, with the wrapper generated by `new_lab.py` and an exhaustive 256-vector tracefile. Exhaustive is the point: the input space is 8 bits, so there is no sampling and no seed, and this is the case the harness is unambiguously good at. 256 vectors by hand does not happen.

Cross-checked the same way as the other examples — a transcription of `ALU.vhd`'s four functions taken from the VHDL, replayed against the generated tracefile: 256 vectors, 0 mismatches.

Two design quirks surfaced while writing the golden model, now documented in the example's README because they look like bugs in a test report:

- `MAX` returns `0000` when the operands are equal, not the operand value.
- `Y(5 downto 4)` is never written by any branch, so the top two output bits are always `00`. The output is 6 bits wide but carries 4 bits of information.

`ROTATOR` also contains unreachable code: the branch is entered only when `B(3) = '1'` and then tests `B(3)` again to pick a direction, so the rotate-left arm can never execute. Left as-is — this is a record of the inherited design, not a rewrite of it.

### 10.5 Verification status

| | Status |
|---|---|
| Generator reproduces the known-good wrappers | **Verified** — both examples, port maps identical |
| Bit ranges tile without gaps or overlaps | **Verified** — all layouts tested |
| ALU tracefile matches its RTL | **Verified** — 256/256 against a transcription |
| Generated wrappers compile | **Not verified** — no VHDL toolchain run against them |
| Empty XDC still builds | **Not verified** — needs synthesis |

---

## Entry 011 — 2026-07-30 — First build: clean, and the netlist confirms the D1 fix

`scripts\build.bat examples\string_detector`, Vivado 2020.2, part **xc7a35tftg256-1**.

```
=== sources  : 7 files in the project, as expected
Synthesis finished with 0 errors, 0 critical warnings and 0 warnings.
INFO: [Project 1-461] DRC finished with 0 Errors
route_design completed successfully   (0 failed nets, 0 node overlaps)
write_bitstream completed successfully
```

This is the **first time this project has ever been synthesised** from the scripted flow. `build.tcl` had never run, the emptied XDC had never been through DRC, and `new_lab.py`'s generated wrapper had never met a synthesiser.

### 11.1 It took two attempts, and the failure was mine

The first run died at `add_files -fileset constrs_1 -norecurse $xdc`:

```
ERROR: [Vivado 12-172] File or Directory 'Lab' does not exist
```

Vivado's `add_files` **list-parses** its file argument. The repository sits under `Wadhwani Lab Research`, so a bare string was split into four nonexistent filenames, the first being `Lab`. The two earlier `add_files` calls survived because they were already wrapped in `[list ...]`; the constraints one was not.

Two things came out of the fix beyond the one-character-class change:

- The `[list ...]` requirement is now stated in a comment at the call site, not just applied — the next person adding an `add_files` line needs to know *why*.
- `build.tcl` now counts the project's sources against what it tried to add and, on mismatch, prints everything that did land. This is the same failure class as D6 — a project whose source list had silently drifted from the source tree — so it earns a permanent guard rather than a one-off patch. Its first successful run printed `sources : 7 files in the project, as expected`.

`program.tcl` gained the analogous check: it reads `PROGRAM.FILE` back after setting it, since programming a truncated path would surface as unexplained vector failures rather than an error.

### 11.2 D7 confirmed resolved, not just changed

**No `UCIO-1` message anywhere in the log, and `DRC finished with 0 Errors`** — with the check no longer downgraded to a warning. That distinction is the whole point of the issue: the original XDC suppressed the error rather than removing the port that caused it. A clean DRC with the suppression gone is the only evidence that actually settles it.

### 11.3 The netlist shows the D1 fix survived synthesis

Reported cell usage:

```
BSCANE2 1   LUT2 5   LUT3 2   LUT4 5   LUT5 11   LUT6 6   FDCE 1   FDRE 23
```

24 flip-flops, and the count reconciles exactly: `data` (7) + `din` (7) + `datau` (1) + `io` (1) + `tdo` (1) = 17 in `scan_core`, plus 2 + 2 + 3 = 7 bits of FSM state in the three detectors.

Worth pausing on the **single `FDCE`** among 23 `FDRE`s. `FDCE` is a flip-flop with an *asynchronous clear*; nothing else in this design has one. That is `io`, and its clear is the `jtag_reset` path added for D1.

So the fix now has three independent confirmations at different levels: the source says it, simulation exercises it, and synthesis mapped it to a primitive that physically has the asynchronous clear. Had `RESET` been left `open` as in the original, `io` would have been an ordinary `FDRE` indistinguishable from the rest.

### 11.4 A finding: the design has never been timed

Three messages, easy to skim past:

```
WARNING: [Timing 38-313] There are no user specified timing constraints.
WARNING: [Place 46-29] place_design is not in timing mode.
INFO:    [Route 35-64] The router will operate in resource-optimization mode.
```

Place and route ran with **no timing goal at all**. Which means the TDO launch-to-sample path — the entire subject of D2 — has never been analysed by any tool. The logic is right (simulation says so) and it works on hardware (the baseline results say so), but *no number exists* for how much margin there is.

This reframes the divider sweep slightly. It was planned as a throughput measurement; it is also the only source of information about that margin, because the toolchain has never computed it. A `create_clock` on the `BSCANE2` TCK output would let `report_timing` give the figure directly, which would be stronger evidence than an empirical pass/fail threshold.

Left as a commented, documented option in `constraints.xdc` rather than enabled: the object a `create_clock` must attach to for a BSCAN primitive varies between Vivado versions, and getting it wrong fails the build. Turning a working build into a broken one to chase a nice-to-have number is the wrong trade at this point. It is recorded so it can be tried deliberately.

### 11.5 Also fixed

`CFGBVS` and `CONFIG_VOLTAGE` are now set in `constraints.xdc`. `write_bitstream` was emitting `[DRC CFGBVS-1]` for their absence. The design uses no I/O so it is cosmetic, but the warning is legitimate and setting it correctly is better than learning to ignore build warnings — which is how the `UCIO-1` suppression came to exist in the first place.

Values are `VCCO` / 3.3 V, correct for the common Artix-7 boards. Flagged in the file as board-dependent, to be checked against a schematic rather than trusted from a comment.

### 11.6 Status

| | |
|---|---|
| Bitstream builds from one command | **Yes**, 0 errors, 0 warnings |
| D7 resolved | **Confirmed** by clean DRC |
| D1 reset path in the netlist | **Confirmed** by the `FDCE` |
| Generated wrapper synthesises | **Confirmed** |
| Anything programmed or run | **No** |
| Timing margin on the TDO path | **Unknown, and never computed by any tool** |

---

## Entry 012 — 2026-07-31 — First hardware run fails. D2 was a misdiagnosis.

```
IDCODE: 0x0362D093  (xc7a35t)
46 vectors: 3 passed, 41 failed, 2 skipped (masked)
```

Every vector read back `1`. The three "passes" are only the vectors whose expected value happened to be `1`. **TDO is stuck at 1.**

### 12.1 What that pattern rules out

A stuck output is diagnostically much better than scattered failures.

- **Not a bit-order or width error.** Those produce wrong-but-varying data. This is constant.
- **Not the host.** The wire protocol is pinned byte-for-byte against the original across widths 1–64, and the IDCODE read — over the same cable, same driver — returned the correct value for the correct part.
- **Not the desync fix.** `io` failing would produce inputs and outputs swapping, not a constant.
- **Not the build.** Synthesis was clean, DRC clean, the netlist accounted for every flip-flop.

That leaves the one thing changed in the TDO path: the falling-edge register added for D2.

### 12.2 The reasoning error

D2 said: TDO is launched on the rising edge and the host samples on the rising edge, so launch and sample coincide; IEEE 1149.1 requires TDO to change on the falling edge; therefore register it on the falling edge.

Every clause is true. The conclusion does not follow, because of an assumption never stated: **that `scan_core.tdo` is the TDO the standard is talking about.**

It is not. `BSCANE2` is inside the TAP, not at a pin. The primitive samples this port and drives the physical TDO pad itself, performing the falling-edge launch the standard requires. The obligation was already met one level up. Adding a second falling-edge register put half a cycle of delay *inside* the TAP's own path, so the data missed the primitive's sample point.

**The original combinational assignment was correct.** Its 4096/4096 hardware record was evidence of correctness — and the original D2 write-up explicitly dismissed that evidence as "timing margin, not design". That was the actual mistake: treating a passing hardware result as luck because it disagreed with a spec argument, rather than treating it as data that the spec argument had to explain.

### 12.3 Why every layer of verification passed it

This is the part worth keeping.

| Layer | Result | Why it could not catch this |
|---|---|---|
| `model_scan_core.py` | pass | Substitutes for BSCANE2; cannot distinguish a combinational `tdo` from a registered one |
| `tb_scan_core.vhd` | pass, 259 checks | Same — it *is* the stand-in for the primitive whose timing was violated |
| Synthesis | clean, 0 warnings | A falling-edge flip-flop is perfectly legal |
| Netlist inspection | consistent | Correctly showed the register I asked for |

Every one of them tested the design against my model of `BSCANE2`. None could test it against `BSCANE2`. The gap was known and written down when the testbench was built — *"if the primitive's CAPTURE/SHIFT/UPDATE pulse timing differs from what's modelled here, only hardware will show it"* — and it named this failure in advance.

The lesson is not "test on hardware sooner". It is narrower and more useful: **a testbench that substitutes for a component cannot validate that component's contract.** Everything `scan_core` does internally was well covered. Everything at its boundary with the primitive was, structurally, untestable by those means — and both defects it was supposed to be protecting lived exactly there.

### 12.4 What this does not undermine

D1 is untouched and stands: the `io` reset path is independent of the TDO path, verified in simulation, and visible in the netlist as the design's only `FDCE`. The host fixes (D3, D4, D8) are unaffected. D5, D6 and D7 are closed. The IDCODE decode is confirmed correct against the real board.

The `scan_core` split also stands, and is worth noting: it made this revert a three-line change to one file rather than surgery on a top level tangled with a vendor primitive.

### 12.5 Status

Reverted to `tdo <= datau(0)`. **This is a hypothesis with strong support, not a confirmed diagnosis** — the stuck-at-1 pattern and the single-variable change point at it, but the decisive evidence is a rebuild and a rerun. If the parity run passes after this revert, the diagnosis is confirmed. If it does not, the cause is elsewhere and this entry needs rewriting.

D2 is recorded as **withdrawn**, with the original analysis kept in `KNOWN_ISSUES.md` as a record of the mistake. Deleting it would hide the most instructive thing in the project.

---

## Entry 013 — 2026-07-31 — The real bug: one wrong byte in the IR sequence

The bisection settled it. Against the *current* bitstream:

```
python host\scan_bscane2.py examples\string_detector\TRACEFILE.txt orig.txt
  -> 46/46 Success
python host\scanchain.py  -t examples\string_detector\TRACEFILE.txt -o parity.txt
  -> 3 passed, 41 failed
```

**The HDL is fine. The bug was mine, in `scanchain.py`.**

That also means entry 012 was wrong, and I will come back to that.

### 13.1 The bug

`encode_ir` builds the sequence that loads a 6-bit instruction. Its last command clocks the top instruction bit out while TMS rises to leave Shift-IR. I wrote:

```python
out += bytes([CMD_CLOCK_TMS_NOREAD, 0x00, (instruction >> 5) & 1])
```

reading the payload byte as a data value. It is not. In a `0x4B` command:

```
bits 6..0   TMS values, clocked out LSB first
bit 7       the TDI level, held constant for the command
```

The correct byte is `(top_bit << 7) | 0x01` — TDI carries the instruction bit, and the `0x01` is **TMS=1**, which is the part that actually leaves Shift-IR.

For USER1 (`0x02`) the top bit is 0, so my version emitted `0x00`: TMS=0. The TAP stayed in Shift-IR, the instruction was never latched into the IR, USER1 was never selected, and the `BSCANE2` data register was never placed in the scan path. TDO then read back as 1 on every vector — exactly the stuck-at-1 symptom.

The IDCODE read still worked throughout, which is what made it confusing: that sequence runs *before* `select_user1` and never depended on the broken byte.

One byte. `0x00` where `0x01` was needed.

### 13.2 Why the test suite did not catch it

The equivalence tests compare `encode_input_scan`, `encode_output_scan` and `decode_output` against the original across widths 1–64. They do not cover the **initialisation sequence** — divider, pin setup, TAP reset, IDCODE read, `select_user1`.

That gap was actually written down, in `host/README.md`, before the hardware run: *"What these tests do not cover: anything involving the FTDI device..."* — and the previous entry noted the same gap explicitly while looking for this bug. Naming a gap is not the same as closing it.

Worse: I wrote `test_encode_ir_shape` and asserted `out[8] == 0`, encoding my own misunderstanding into a test. It passed, and it was wrong. **A test written from the same wrong model as the code confirms the model, not the code.** The equivalence tests avoid this by construction — they compare against an independent artefact, the original source — which is precisely why they are the ones that held.

Now fixed: `test_encode_ir_matches_the_original_byte_for_byte` pins the whole sequence to the original's literal bytes, and a second test asserts the TMS bit is set for all 64 instructions.

### 13.3 Entry 012 was wrong, and this is the more important correction

Entry 012 concluded that the falling-edge TDO register broke the board, that D2 was a misdiagnosis, and that the original combinational assignment was thereby vindicated.

**That conclusion rested on contaminated evidence.** The stuck-at-1 is fully explained by the IR bug. The falling-edge register was never tested against a working host — it was in the bitstream during two runs where the host could not select the user data register at all, so it could not have been exercised either way.

So the honest position on D2 is now: **unproven in both directions.** No evidence the falling-edge register is harmful. No evidence the original assignment is defective. The combinational version is retained on a "don't change what has hardware evidence" basis, which is a reason to prefer it, not a demonstration that the alternative fails.

It is cheaply testable now — reinstate the register, rebuild, rerun — and that experiment is worth an entry of its own if anyone runs it.

I am recording this rather than quietly editing entry 012 because the pattern is the point: **I produced a confident, well-argued, internally consistent diagnosis from a symptom that had a completely different cause, twice in the same session, on the same issue.** Both times the reasoning was sound and the premise was wrong. The thing that broke the loop was not better reasoning; it was running the original driver against the same bitstream — a measurement that could only come out one of two ways, and eliminated half the search space regardless of which.

### 13.4 What the bisection cost and saved

One command. It was possible only because `scan_bscane2.py` was kept unmodified in the repository specifically as a reference — a decision made when the rewrite started, for exactly this situation. Without it, the next step would have been another round of theorising about `BSCANE2` timing.

### 13.5 Status

| | |
|---|---|
| HDL (D1 fix, scan_core split, empty XDC) | **Sound** — original driver passes 46/46 against the current bitstream |
| `scanchain.py` IR bug | **Fixed**, pinned to the original's bytes, 30 tests passing |
| D2 (TDO launch edge) | **Unproven both ways.** Reverted; testable in one cycle |
| Parity run with the fixed host | **Not yet run** |

---

## Entry 014 — 2026-07-31 — Parity run passes. The rework is hardware-verified.

```
IDCODE: 0x0362D093  (xc7a35t)
46 vectors: 44 passed, 0 failed, 2 skipped (masked)
0.01 s elapsed, 4521 vectors/s
```

Diff against the capture taken before any of this work:

```
***** parity.txt              ***** RESULTS\STRING_DETECTOR_OUTPUT.TXT
0000010 0 Skipped             0000010 0 Success
0000011 0 Skipped             0000011 0 Success
0001000 0 Success             0001000 0 Success
*****
```

**Exactly two differing lines, and they are the two that were predicted.**

### 14.1 The prediction is the result

The interesting artefact here is not the pass. It is that the exact shape of the diff was written down in `RESULTS.md` and `host/README.md` *before* the run:

> *"this predicts exactly two changed lines — the two `mask = 0` vectors at lines 1–2. Those two lines are the visible confirmation that #3 is fixed. Any other difference is a regression."*

Three outcomes were enumerated in advance, each with a meaning: two lines (correct), zero lines (mask fix silently ineffective), any third line (regression). The run produced the first. That is a falsifiable prediction confirmed, not a test that was declared to pass after the fact.

It also means the two lines carry real information. They are the only direct evidence that D3 changed behaviour on silicon, and they could not have been produced by anything else.

### 14.2 What moves to hardware tier

| Claim | Was | Now |
|---|---|---|
| The `scan_core` split preserves behaviour | simulation | **hardware** |
| `scanchain.py` works against a real board | untested | **hardware**, 44/44 unmasked |
| D3 (mask ignored) fixed | offline tests | **hardware** — the two `Skipped` lines |
| D4, D8 | offline tests | **hardware-exercised** end to end |
| `build.tcl` + `program.bat` produce a working bitstream | untested | **hardware** |
| Recovered `StringDetector` sources are the right ones | model | **hardware** — they reproduce the original's outputs on silicon |
| D6 — which part the board is | undocumented | **settled**: `xc7a35t`, agreed by Vivado's enumeration and the TAP's IDCODE |

### 14.3 The cost, honestly

Getting from "code complete" to this took three of my own bugs, all at the FTDI boundary — the one place the offline tests structurally could not reach:

1. `encode_ir` returned `bytearray`; `ftd2xx` rejects it with an opaque `ctypes` error.
2. IDCODE decode applied one of two required reversals — a plausible wrong number, worse than an obvious one.
3. `encode_ir` sent TMS=0 instead of TMS=1 leaving Shift-IR.

The third cost the most: two confident, internally consistent, entirely wrong diagnoses (entries 012 and 013), including reverting a change and writing a detailed explanation of why it had broken the board. It had not.

What actually found it was running the untouched original driver against the same bitstream — one command, and it eliminated half the search space regardless of which way it came out. That option existed only because `scan_bscane2.py` was deliberately preserved unmodified at the start of the rewrite. Of every decision in this project, that one paid back the most.

### 14.4 The pattern worth carrying forward

The tests that held were the ones comparing against an **independent artefact** — the original source — across the full input space. The test that failed me was one I hand-wrote from my own understanding: `test_encode_ir_shape`, asserting `out[8] == 0`, encoding the exact misconception that caused the bug. It passed, and it was wrong.

A test written from the same model as the code under test can only confirm the model. That is why `encode_ir` is now pinned to the original's literal bytes, the way the other encoders always were — and why the equivalence suite, not the hand-written assertions, is the part of this project I would trust in someone else's hands.

### 14.5 Remaining

| | |
|---|---|
| Interrupt mid-run, rerun without reprogramming (D1) | **Outstanding** — the test that fails on the original code |
| Divider sweep, before/after throughput | **Outstanding** |
| ALU 256-vector exhaustive, generated wrapper end to end | **Outstanding** |
| seq1011 602-vector run | **Outstanding** |
| D2 — settle it by rebuilding with the falling-edge register | **Optional**, one cycle |

---

## Entry 015 — 2026-07-31 — D1 demonstrated on silicon, and it is quieter than claimed

The A/B ran. Two bitstreams, differing **only** in whether `BSCANE2.RESET`/`SEL` reach `scan_core` — `scan_core.vhd` byte-identical between them, the pre-fix build tying `jtag_reset => '0'`, `sel => '1'` in `TopLevel.vhd` to reproduce the original's `open` wiring.

Same injected fault on both: `--abort-after-input 10`, which sends only the input phase of a vector and exits, leaving `io` inverted.

| Build | Before | After injection, no reprogramming |
|---|---|---|
| Fixed | 44/44 | **44/44, byte-identical to baseline** |
| Pre-fix | 44/44 | **41 pass, 3 fail** |

Both healthy until interrupted; only the pre-fix build stays broken. One variable, both directions. **D1 is a real defect and the reset path is what prevents it** — no longer an argument from reading code.

### 15.1 The number that matters is 93%, not 3

The three failures are lines 15, 35 and 39, which are **exactly the three vectors in this tracefile whose expected output is `1`.** The other 43 expect `0`.

The desynced design returns a constant `0` — with `io` inverted, Capture-DR never fires in the phase that loads `datau`, so the output register is never written. So the failure signature is:

```
41 of 44 unmasked vectors still report Success
= 93% of the suite passing on a harness that is returning a constant
```

The original write-up said D1 was dangerous because it fails quietly. It is quieter than that argument gave it credit for. A student reading the summary line would see "41 passed, 3 failed" and reasonably conclude their DUT has a minor bug — when in fact the scan chain is dead and the design under test is not being observed at all.

Worse, the three visible failures are the *detections* — the interesting behaviour the test exists to check. **A stuck-at-0 scan chain is indistinguishable from a DUT that never asserts its output.** That is the most plausible-looking possible failure, and it is the one this defect produces.

This is a better result than "everything fails". A total failure is self-announcing. This one is not, and now there is a measured figure for exactly how not.

### 15.2 Why the two earlier attempts proved nothing

Two earlier runs completed a full tracefile, reran, and passed — on both builds. That looked like recovery and was not.

**A complete vector performs both phases and leaves `io` back at `'0'` whether or not the reset path exists.** The desync needs a run that dies *between* the two phases of one vector. At 0.01–0.08 s per run, that window cannot be hit by hand, so the bench checklist's "press Ctrl-C mid-run" was asking for something physically impossible — my error in writing it.

Hence `--abort-after-input`. The fault had to be injected deterministically rather than caught opportunistically. Building the fault injection into the tool was the step that made the experiment possible at all.

### 15.3 Two constants, two different faults

Both major failures this session presented as a constant on TDO:

| Symptom | Cause | Mechanism |
|---|---|---|
| Stuck at **1** | Host: `encode_ir` sent TMS=0 | USER1 never selected — user DR never in the scan path, TDO floating |
| Stuck at **0** | D1: phase desync | USER1 selected; `datau` simply never loaded |

"TDO is constant" was ambiguous between a host fault and an HDL fault, and I guessed wrong about it twice. What resolved it was not inspection but bisection — running the untouched original driver against the same bitstream. Recording the two signatures together so the next person can tell them apart from the value alone.

### 15.4 Status

D1 moves to **hardware-demonstrated**, with a controlled A/B and a quantified silent-failure rate. Of everything in this project this is the strongest single result: it shows a defect the original author's 4096-vector sweep could not have exposed, because an uninterrupted run never enters the failing state.

The pre-fix `TopLevel.vhd` edit is uncommitted and must be reverted with `git checkout hdl/TopLevel.vhd`, then rebuilt and reprogrammed.

---

## Entry 016 — 2026-07-31 — The sweep found a bug in the sweep

Two things ran: the ALU exhaustive test, and the divider sweep it was gating.

### 16.1 First hardware run of a machine-generated wrapper

```
examples\alu\TRACEFILE.txt: 256 vectors, 8 in / 6 out
256 vectors: 256 passed, 0 failed, 0 skipped (masked)
```

**256/256, the whole input space.** Everything in that pipeline was generated: `new_lab.py` read `ALU.vhd` and wrote `DUT.vhd`, patched the width constants in `TopLevel.vhd`, and the tracefile came from a Python golden model of the same entity. Nobody hand-wrote a bit mapping.

That is the plug-and-play claim demonstrated rather than asserted. It also retires a specific worry: `new_lab.py`'s bit layout was derived by reproducing two existing hand-written wrappers, so it was only ever known to agree with the convention it was reverse-engineered from. It now agrees with silicon.

### 16.2 The sweep, and a prediction that failed usefully

Every divider passed 3/3, up to the fastest available. **4062 → 70276 vectors/s, 17.3x.**

I had written down the opposite beforehand: *"I expect little or no throughput gain … roughly 90% of the time is USB round-trip and Python overhead, not TCK."*

Worth dwelling on why that was wrong, because the reasoning was not sloppy — it was arithmetic on a wrong constant. The estimate of JTAG traffic per vector was about right (I guessed ~30 µs; counted properly from the encoders it is 24 TCK cycles). What was wrong was the clock those 24 cycles run at. I took `500 kHz` from the comment in the source. The real figure is **100 kHz**, so the traffic takes 240 µs, not 48 µs — it was never the small term, and there was never 90% of anything to be dominated by host overhead.

A prediction derived correctly from a wrong input fails in a way that points at the input. That is the only reason this was found.

### 16.3 `0x8B` enables the prescaler; the comment says it disables it

```python
self.dev.write(b"\x8B")        # disable /5 prescaler
```

MPSSE `0x8A` disables the divide-by-5 prescaler. `0x8B` **enables** it. So the master clock is 60/5 = 12 MHz, and

```
TCK = 12 MHz / (2 * (divider + 1)) = 6 MHz / (divider + 1)
```

not `30 MHz / (n+1)`. Every frequency this project has ever quoted — in the driver, in `KNOWN_ISSUES.md` #2, in the first version of `sweep_divider.py`, and in my own reasoning all week — is **5x too high**. `0x3B` is 100 kHz. The ceiling is 6 MHz.

The line is inherited verbatim from `scan_bscane2.py`, comment included. It was copied without being questioned, which is exactly what one does with a line that has 4096/4096 behind it.

### 16.4 The measurement identifies the base clock without appealing to a datasheet

This is the part I want on record, because "I misremembered an opcode" is not evidence either way and I have already been confidently wrong twice this project.

Model a vector as `t = 24/f_tck + a`, where 24 is *counted* from the encoders and `a` is a constant host cost. Solve for `a` at each of the seven dividers under the 6 MHz base: the residuals are 6.2, −2.2, 11.1, 5.2, 3.8, 7.2, 10.2 µs — **mean 5.9, flat across a 60x range of clock rates.** That is what a constant looks like.

Under the 30 MHz assumption the residual would have to be 198 µs at `0x3B` and 13 µs at `0x00`. A "constant" that varies 15x with the clock is not a constant; it is the clock, mislabelled.

So the sweep's own timing data falsifies the sweep's own frequency column. I would not have trusted this from recall alone.

### 16.5 It cuts the other way on issue #2

The pleasant reading of the sweep was "the TDO path survives 30 MHz, issue #2 is closed." That reading is gone. What is actually established is that it survives **6 MHz**, which is about where the original 1149.1 argument would have predicted it was fine anyway. The measurement does not discriminate between the two positions.

Nor did the sweep find a failure at all — it ran out of clock, not out of margin. Both the throughput number and the timing bound are censored at the top.

The follow-up is now sharp and cheap: **send `0x8A`, re-sweep to 30 MHz.** Five times faster than anything tested, and issue #2 names the combinational TDO assignment as the thing that should break first. If a divider fails, that is the timing ceiling, measured — and the first hard evidence in either direction on a question that has already produced one defect claim, one withdrawal, and one withdrawal of the withdrawal.

Not done in this commit. The prescaler stays on, and the default stays `0x3B`: every hardware result in `RESULTS.md` was taken under those conditions, and changing them is an experiment to run deliberately, not a tidy-up to slip in alongside a documentation edit.

### 16.6 What changed here

| | |
|---|---|
| `sweep_divider.py` | `FTDI_BASE_HZ` 30 MHz → 6 MHz, with the derivation in a comment |
| `scanchain.py` | Corrected comment on `0x8B`, corrected `--divider` help, `0x02` documented as the fast option |
| `RESULTS.md` | Section 5C |
| `KNOWN_ISSUES.md` #2 | Frequencies corrected; the 6 MHz bound recorded; `0x8A` named as the deciding experiment |

### 16.7 Remaining

| | |
|---|---|
| Re-sweep with `0x8A` to locate the real ceiling (D2) | **Outstanding** — the highest-value single experiment left |
| `seq1011` 602-vector run | **Outstanding** |
| Change the default divider to `0x02` after more repeats | **Deferred**, deliberately |
| Clean-clone walkthrough | **Outstanding** |

---

## Entry 017 — 2026-07-31 — Clean-clone review: what the repo actually ships

Final review. Method: clone the repository into an empty directory and behave like someone who has never seen it — run every command the docs promise, follow every link, and check whether the claims match the code.

Six problems. All six were invisible from inside the working tree, which is the argument for doing this at all.

### 17.1 The tool that produced the headline result was never committed

`scripts/sweep_divider.py` was untracked. `RESULTS.md` §5C, `KNOWN_ISSUES.md` #2 and the engineering log all cite it by name; a fresh clone did not have it. The single worst kind of documentation bug — a reproducibility claim pointing at a file that does not exist.

### 17.2 The default configuration pointed at the one example that cannot be built

`hdl/TopLevel.vhd` was committed with `number_of_inputs = 7, number_of_outputs = 1` — the string detector's widths. Those sources are deliberately gitignored, so out of the box the repository was configured for the example a fresh clone is guaranteed not to have. Now committed at seq1011's 3/1, matching the quickstart, the `scripts/README.md` usage block and `examples/README.md`'s "the example to start from".

Worth noting how this happened: `new_lab.py --patch-toplevel` rewrites those constants every time anyone targets a different DUT, so the committed value is whatever the last bench session happened to leave behind. It is a working file masquerading as a configuration file. Not fixed here, but it is the reason this will drift again.

### 17.3 `seq1011/DUT.vhd` was hand-written, not generated

The flagship example's wrapper predated `new_lab.py` and differed from the generator's output — in comment wording and column alignment only; normalising whitespace and stripping comments showed the two semantically identical, and the port map was already byte-identical in substance.

Cosmetic, but the example exists to demonstrate the generated workflow, and it was not actually a product of it. Regenerated. Both committed wrappers whose sources ship now match `new_lab.py` output **byte for byte**, so the check is a trivially repeatable one-liner rather than a judgement call.

### 17.4 The generator's regression test omitted the case with hardware behind it

`test_reproduces_committed_wrappers` covered seq1011 and string_detector. It did not cover the ALU — the only wrapper that has been validated on silicon, 256/256 exhaustively. Added.

The test was otherwise well built and I want to record why: it compares extracted **port pairs** rather than text, which is why it stayed green through 17.3 rather than failing on comment wording; and it counts what it checked and asserts `checked >= 1`, so it cannot pass vacuously in a clone that lacks the gitignored sources. That guard is precisely the failure this project already walked into once with `test_encode_ir_shape` (entry 013).

### 17.5 The README claimed a change that had been reverted

`### 3. TDO registered on the falling edge of TCK — fixes issue #2`, stated as fact, with a verification paragraph. The code says otherwise: the register was withdrawn and `KNOWN_ISSUES.md` #2 has said "unproven in both directions" for two days. The top-level README — the file most people read and the only one many read — was asserting a fix the repository does not contain.

Rewritten to describe the change, the withdrawal, and the contaminated evidence behind the withdrawal, and retitled so the status is legible from the heading.

### 17.6 Stale status claims throughout

`README.md`: *"nothing has been validated on hardware yet"* — untrue since entry 014. `scripts/README.md`: four scripts marked **"not yet validated on hardware"** that have each since built or programmed a real board, and no mention of `sweep_divider.py` at all. Both corrected, with the specific evidence rather than a bare "working".

### 17.7 What the clean clone now does, unassisted

```
host/test_scanchain.py     30 tests, 0 failures
scripts/test_new_lab.py    19 tests, 0 failures
sim/model_scan_core.py     264 checks, 0 errors
--dry-run                  all 3 tracefiles valid
new_lab.py                 regenerates both shipped wrappers byte-identically
gen_tracefile.py           regenerates both tracefiles byte-identically
markdown links             0 broken across 52 files
```

No board, no Vivado, no network. Everything a reviewer needs to convince themselves the tooling is real, before deciding whether to trust the hardware claims.

### 17.8 The general lesson

Every one of these six is a claim that was true when written and quietly stopped being true. None were caught by any test, because none are the kind of thing tests check — the repository was internally consistent and externally wrong.

The only mechanism that found them was leaving the working tree and reading the artefact as a stranger would. That took about fifteen minutes and found a missing file, a misconfigured default, and a README asserting a fix that had been reverted a day earlier. Worth doing before any repository is shown to anyone.

### 17.9 Remaining

| | |
|---|---|
| Re-sweep with `0x8A` to locate the real timing ceiling (D2) | **Outstanding** — the highest-value experiment left |
| `seq1011` 602-vector hardware run | **Outstanding** |
| Change the default divider to `0x02` after more repeats | **Deferred**, deliberately |
| `TopLevel.vhd` widths are a generated value under version control | **Known wart** — see 17.2 |

---

## Entry 018 — 2026-08-11 — Lab 4, and a failed run that has been sitting in `results/` the whole time

Two things. A clean blind test of the generator, and a documentation error in the most-cited claim in this repository.

### 18.1 The generator passed a genuinely blind test

Lab 4 is a BCD adder — two 4-bit decimal operands in, a digit and a carry out, structural down to gate level. Its wrapper was written by the lab's author, for a design `new_lab.py` had never seen, before `new_lab.py` existed.

Run the generator on `BCDAdder.vhdl` and it produces the same layout, independently:

```
A => input_vector(7 downto 4)
B => input_vector(3 downto 0)
Y => output_vector
```

**This is the first reference wrapper in the project that is actually independent.** The others are not: `seq1011` was written for this repository, `alu`'s wrapper was produced by the generator itself, and `string_detector`'s is the file I *derived* the layout convention from in the first place. Each checks the generator against something related to it. `test_reproduces_committed_wrappers` looked like four cases and was closer to one.

It also parsed `port(A, B : in std_logic_vector(3 downto 0);` — two ports sharing a declaration, a syntax neither committed example uses.

The tracefile was checked against an independent Python model of BCD addition before the board run: 100 vectors, 0 mismatches, exhaustive over all 100 valid operand pairs (though only 100 of 256 possible 8-bit inputs — operands above 9 are never applied, which the example README states). Hardware: **100/100**, as predicted.

### 18.2 A test that failed on notation

`port_pairs` compared port maps textually, so the generator's `output_vector(4 downto 0)` and the lab author's bare `output_vector` came back as a difference. Identical signals.

Fixed by normalising full-width slices before comparing — not by editing either file. A test that fails on notation rather than meaning is worse than no test, because it teaches you to skim its output.

### 18.3 `passthrough_4096_output1.txt` is a failed run

Found by accident. I was grepping for `Failure` while building better per-vector failure reporting, and one of the inherited result files returned 3586 hits.

```
distinct 'got' values across 4096 lines : 1  -> '00000000'
Success                                  : 510
vectors whose correct output is 00000000 : 510   (per the good run)
every Success is one of those            : yes
every Failure is not                     : yes
```

**TDO returned a constant for the entire run.** The 510 "passes" are the vectors whose right answer happened to equal that constant. Nothing was being observed.

Stuck-at-0 is the signature this project already documented for D1: USER1 selected, output register never loaded (entry 015, §15.3). A capture file cannot separate that from a DUT tied low, so this is a signature match rather than a proof — but the failure mode D1 argues for was evidently occurring on that bench, before any of this work started.

### 18.4 How the error propagated, which is the part worth keeping

Entry 001 §1.2 lists the inherited files and says all three result files are "all `Success`". I wrote that from their size and shape. I did not count.

Everything downstream inherited it:

| Document | Claim |
|---|---|
| Entry 001 §1.3 | "two independent 4096-vector exhaustive sweeps in which every single vector passed" |
| `RESULTS.md` §1 | "4096 pass, 0 fail" — table row |
| `RESULTS.md` §7 | "**Hardware** — 4096/4096, twice" |
| `results/README.md` | "Duplicate run of the same sweep" |
| `ROADMAP.md`, `TRACEFILE_FORMAT.md`, `README.md`, `host/README.md` | "4096/4096" as the wire protocol's evidence |
| The project presentation | A slide reading "4096 / 4096 — two independent exhaustive sweeps" |

One `grep -c Failure` at any point in three weeks would have caught it. The previous `results/README.md` **printed that exact command** as the way to check a run. I wrote that line and never ran it.

This is the same failure as `test_encode_ir_shape` (entry 013) in a different costume: an assertion made from an assumption, then treated as established because it had been written down. The tell in both cases is that the claim was never executed — and both times the check was cheap and obvious in hindsight.

### 18.5 What the correction actually costs

Less than the size of the error suggests. Every "the wire protocol is proven" argument in this repository — the reason `scan_bscane2.py` was preserved byte-for-byte, the reason the rewrite is pinned to its output across widths 1–64 — rests on **one clean exhaustive 4096-vector sweep with 256 distinct output values**. That file is real and unaffected.

What is gone is the word *twice*: the independent repetition. And D1 gains a piece of historical evidence it did not have.

### 18.6 The tooling change that follows from it

The original driver printed no summary — 4096 lines, no counts, outcome invisible unless you go looking. That is *why* this survived.

`host/scanchain.py` now:

- writes failing lines as `<input> <got> Failure  expected=<bits>  diff=<..^.>  line=<n>`, so a failure is actionable from the report alone without cross-referencing a tracefile by line number. Passing and skipped lines are byte-identical to the old format, so the `results/` parity check is undisturbed.
- marks in `diff` only the bits that actually failed — masked positions show `-`, because flagging a don't-care sends you hunting a fault that isn't there.
- **detects the constant-TDO case and reports it as one fault rather than N.** Replaying `passthrough_4096_output1.txt` through it now prints:

```
  !! TDO was constant '00000000' for all 4096 vectors.
     This is one fault, not 3586 -- the scan chain returned nothing.
     Stuck at 0: USER1 is selected but the output register is never
     loaded -- the phase-bit desync of KNOWN_ISSUES #1.
```

The per-vector table was actively harmful here: 3586 failures reads like a design with many bugs. It was one fault, and naming it is the difference between a diagnosis and a wall of output.

### 18.7 Remaining

| | |
|---|---|
| Re-sweep with `0x8A` to locate the real timing ceiling (D2) | **Outstanding** |
| `seq1011` 602-vector hardware run | **Outstanding** |
| Audit the remaining inherited claims the same way — count, don't assume | **Ongoing** |

---

## Entry 019 — 2026-08-11 — The bitstream and the tracefile now have to agree

### 19.1 The gap

Nothing tied a bitstream to a tracefile. `scanchain.py` takes its scan widths entirely from the tracefile, and the FPGA has no way to say "that is not how wide I am". Build one example, run another's vectors, and every shift is misaligned — producing not an error but a screen of plausible-looking failures.

That is the same shape as the two worst defects this project has dealt with: **wrong answers that look like a broken DUT.** It is also the easiest mistake to make right now, while running the same board through several labs to compare the old and new flows.

### 19.2 What was added

`build.tcl` parses the widths out of `TopLevel.vhd` after a successful bitstream and writes `vivado/build/build_info.json`. `program.tcl` copies that to `.programmed.json` at the repo root **once the device has actually been programmed** — the build manifest alone describes the most recent build, which is not necessarily what is on the chip. `scanchain.py` reads it and refuses a mismatched tracefile:

```
error: tracefile does not match the design on the board.
  on the board : 8 in / 5 out   (built from examples/bcd_adder, programmed ...)
  tracefile    : 3 in / 1 out
```

Three deliberate choices:

**Fatal, not a warning.** There is no case where continuing produces a meaningful result, and a warning above a wall of failures is a warning nobody reads.

**A missing manifest is not an error.** Programming through the Vivado GUI is a legitimate workflow — it is the one the original procedure documents, and the one being used for the comparison right now. Absence of a manifest prints "skipped" and continues. `--no-build-check` overrides the check itself.

**The message names the design that is loaded.** "Widths mismatch" tells you something is wrong; "the board has `examples/bcd_adder`, your tracefile is `seq1011`" tells you what to do.

### 19.3 What it does not do

It compares a tracefile against a *record* of what was programmed, not against the silicon. Program the board by other means, or edit `TopLevel.vhd` and rebuild without reprogramming, and the record is stale.

Reading the width from the hardware directly is not available here: the input and output registers are separate and which one sits in the scan path depends on the phase bit, so the usual JTAG DR-length probe does not apply. A record-based check closes the mistake that actually happens — a stale bitstream — and it should not be described as more than that.

### 19.4 Verified

Tclsh reproduction of both manifest steps, including a bitstream path containing spaces (the recurring hazard in this flow), with Python parsing the result. End to end: matching tracefile accepted, mismatched tracefile rejected with exit code 2, `--no-build-check` overrides, absent manifest skips cleanly. 7 new offline tests, 41 total.

---

## Entry 020 — 2026-08-11 — Both flows run on the same design, same board, same night

The comparison this project has been implicitly arguing for, finally done as an experiment rather than an assertion: lab 4's BCD adder, built and run through the inherited flow and through this repository's flow, on the same board, hours apart.

### 20.1 The setup is genuinely matched

Both flows build from **byte-identical sources**. `examples/bcd_adder/` holds copies of `lab4/fri/fri_vivado/`, verified by hash, and the tracefile is the same file in both — also verified. That mattered more than it sounds: `BCDAdder.vhdl` and `Gates.vhdl` **differ between the lab's `fri_quartus` and `fri_vivado` folders**, so taking the wrong copy would have compared two different designs without anything indicating it.

The one intended difference is the wrapper: hand-written by the lab's author versus generated by `new_lab.py`. Their port maps were shown identical in entry 018, so this is the variable under test, not a confound.

### 20.2 The old flow works, and that is the correct result

It produced a working bitstream and correct results. Nothing here argues otherwise, and a write-up claiming the inherited flow is broken would be false.

What it cost to get there is the finding:

- **Three `.xpr` files, one correct.** Opening `Lab4_fri.xpr` runs a full synthesis and then fails, because it contains a testbench that reads a file at elaboration.
- **The project does not build out of the box.** `UCIO-1` blocks bitstream generation: the original `TopLevel` exposes a 5-bit `state_out` debug port with no pin constraints, and the suppression in `constraints.xdc` does not apply to `write_bitstream` under the Runs infrastructure. Vivado's own error text says so. A manual `open_run` / `set_property SEVERITY` / `write_bitstream` is required.
- **`DEVICE_NOT_OPENED`, twice**, reported as a bare `ftd2xx` traceback.
- **The wrong tracefile is the nearest one.** The procedure says navigate to the scan-chain files; the `TRACEFILE.txt` in that folder is 8 in / 6 out from another lab, against a board that is 8 in / 5 out. Nothing in the old flow checks.

Every one of those was hit by someone three weeks into this codebase, following a written procedure.

### 20.3 The netlist evidence, on the original design

Synthesis of the inherited design reported `FDRE 22` and **no `FDCE`**. This repository's build of the same DUT reports `FDCE 1, FDRE 23`.

That one flip-flop with an asynchronous clear is the phase-bit reset path of D1. Its absence is the defect, visible in the synthesised netlist of the original, with the DUT held constant. Entry 015 demonstrated D1 by an A/B on two bitstreams I built; this is the same conclusion reached from the original project as delivered.

### 20.4 What is new in the tooling because of tonight

Three changes, all driven by something that actually happened:

- **The bitstream/tracefile guard** (entry 019), which the old flow's wrong-tracefile trap justifies precisely.
- **`program.tcl` announces success before bookkeeping.** A Tcl parse error in the manifest block reported PROGRAMMING FAILED on a board that had been correctly programmed, and the user reprogrammed it. Bookkeeping must never be able to fail the operation it records.
- **The stuck-at-1 diagnosis now names "no design loaded" first**, because a power cycle wipes a volatile configuration and the manifest cannot know.

### 20.5 Two bugs of my own, in four minutes

Worth recording because the pattern is the same one this log keeps returning to.

Tcl counts braces when parsing a braced block, ignoring quotes *and* comments. The JSON assembly needed a literal closing brace as data, which ended the block early — a **parse** error, so the surrounding `catch` could not catch it. I fixed it, then reintroduced the identical bug in the comment written to explain the fix, by quoting the character.

Both versions would have been caught instantly by sourcing the file. I had "verified" the logic by running its *fragments* under `tclsh`, which cannot detect a parse error, because the parse error is a property of the enclosing block. The check now sources the whole script with Vivado's commands stubbed out.

Same shape as `test_encode_ir_shape` (013) and the 4096 miscount (018): a verification that did not execute the thing it claimed to verify.

### 20.6 Status

Three examples pass on hardware: `seq1011` 600/600 unmasked, `bcd_adder` 100/100 exhaustive, `string_detector` 44/44. The generated wrapper, the headless build, the manifest, the headless program, the guard and the run all worked end to end, and the guard was demonstrated refusing a real mismatch.

Outstanding: the `0x8A` re-sweep for D2, and the wall-clock figures for both flows, which belong in RESULTS.md §5E once measured.
