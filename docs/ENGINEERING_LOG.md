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
