# Results

Measured outcomes, separated by how strong the evidence is. Anything not measured is marked as such — this document is only useful if it never overstates what has been shown.

**Evidence tiers used throughout:**

| Tier | Meaning |
|---|---|
| **Hardware** | Ran on the physical Artix-7 board. The only tier that proves the system works. |
| **Simulation** | Ran in a VHDL simulator. Proves the RTL is functionally correct; says nothing about real timing or `BSCANE2`. |
| **Model** | Ran against an offline model or test suite — `sim/model_scan_core.py` for the HDL, `host/test_scanchain.py` for the driver. Proves the logic is right *assuming the real thing matches the model*. Cannot catch VHDL errors or anything at the hardware boundary. |
| **Argued** | Reasoned from the code. No execution. |

---

## 1. Baseline — the inherited implementation

**Tier: hardware.** Captured before any changes, by the original author.

| Test | Vectors | Result | File |
|---|---|---|---|
| String detector | 46 | 46 pass, 0 fail | `results/string_detector_output.txt` |
| Exhaustive passthrough (12 in / 8 out) | 4096 | 4096 pass, 0 fail | `results/passthrough_4096_out.txt` |
| Exhaustive passthrough, second attempt | 4096 | **510 pass, 3586 fail — a captured failure** | `results/passthrough_4096_output1.txt` |

This is the number that matters most in the whole project, and it belongs to the original implementation: **the protocol works, at scale, on real hardware.** One clean 4096-vector sweep, 256 distinct output values. Everything since is robustness and usability work on top of a design that was already functionally correct.

### 1.1 The second file is a failed run, and this document said otherwise for two weeks

`passthrough_4096_output1.txt` was recorded here as a duplicate clean sweep. It is not. **TDO returned `00000000` on all 4096 vectors**; the 510 `Success` lines are exactly the 510 vectors whose correct output is `00000000`, and every `Failure` is one of the rest. The harness was returning a constant and observing nothing.

Stuck-at-0 is the documented signature of the phase desync in [KNOWN_ISSUES #1](KNOWN_ISSUES.md) — USER1 selected, output register never loaded. That is a signature match and not a proof; a capture file cannot separate a desync from a DUT tied low. But it means the failure mode #1 predicts was, at some point, actually happening on this bench.

**How the error was made.** Engineering log entry 001 recorded all three inherited result files as "all `Success`" on the basis of their size and shape. Nobody counted, including me, and every later document inherited the claim — the README, the roadmap, the tracefile guide, and a presentation slide reading "4096 / 4096, two independent exhaustive sweeps". One `grep -c Failure` would have caught it at any point. The previous `results/README.md` even printed that exact command as the way to check a run.

**What actually changes.** Less than it looks. The protocol still has one clean exhaustive 4096-vector run behind it, which is what every "the wire protocol is proven" argument in this repository rests on. What is gone is the word *twice* — the independent repetition. See entry 018.

**What the baseline does not establish.** Every one of these runs completed without interruption, at a clock divider of `0x3B` (100 kHz). Neither the desync failure mode nor the TDO edge race can appear under those conditions, so a clean sweep here is consistent with both defects being present. It was.

---

## 2. Scan protocol logic after the HDL changes

**Tier: model.** `python3 sim/model_scan_core.py` — 2026-07-29.

```
TEST 1 exhaustive scan      : 256 vectors, 0 errors
TEST 2 desync via TAP reset : 0 errors
TEST 2b original code       : after interruption got [0, 0, 0, 0],
                              expected [1, 1, 1, 1] -> desynced as expected
TEST 3 desync via deselect  : 0 errors
TEST 4 bit-order sensitivity: 192/256 reversed vectors detected as wrong

=== 264 checks, 0 errors ===
ALL PASSED
```

| Claim | Evidence |
|---|---|
| Shift ordering, phase alternation and capture timing are correct after the `scan_core` split | Test 1, exhaustive over the input space |
| The falling-edge TDO launch delivers the same bits in the same order | Test 1 — the model samples `tdo` before the rising edge, as MPSSE reads do. An off-by-one would fail every vector |
| A TAP reset restores the phase after an interrupted run | Test 2 |
| Deselecting the DR restores the phase | Test 3 |
| **The original design really does desync** | Test 2b, against a model of the pre-fix code |
| The test suite can actually detect wrong bit order | Test 4, 192/256 |

### 2.1 The desync defect is real, not just plausible

Issue #1 was found by reading code and reasoning about a failure nobody had observed — a mode of discovery that produces false alarms as often as findings. Test 2b runs the interrupt scenario against a model of the original design (`with_fixes=False`, `RESET`/`SEL` left `open`) and reproduces the failure: after an interrupted vector, the next result comes back `[0,0,0,0]` instead of `[1,1,1,1]`, and stays wrong.

This is a model of the defect, not the defect on silicon. It confirms the reasoning is sound. The bench test — interrupt a run, rerun **without reprogramming** — remains the real proof.

### 2.2 A negative test that passed for the wrong reason

Worth recording because it nearly went unnoticed.

Test 4 originally reversed a single vector (`0xD2`) and asserted the result differed. The model reported it did not. Under the golden model `low_slice xor high_slice`, reversing all bits produces the bit-reversal of the correct answer — so whenever that answer is a palindrome, the reversal is undetectable. 64 of 256 vectors have that property; `0xD2` is one.

The test would therefore have passed a testbench completely blind to bit order, which is the single failure it exists to prevent — and Test 1 would have looked equally green either way.

Switching the golden model to an adder was considered and rejected: it only shrinks the blind set from 64 to 44, and leaves the result dependent on a lucky vector and on the widths never changing. Test 4 is now a sweep requiring at least one detection, and the reported count is itself diagnostic — a sudden drop from 192 would mean the golden model has drifted toward reversal symmetry.

---

## 3. VHDL simulation

**Tier: simulation.** `sim/run_sim.bat` — Vivado Simulator **2020.2**, 2026-07-29.

```
=== analysing ===
INFO: [VRFC 10-3107] analyzing entity 'scan_core'
INFO: [VRFC 10-3107] analyzing entity 'tb_scan_core'
=== elaborating ===
Compiling architecture rtl of entity work.scan_core [\scan_core(number_of_inputs=8,nu...]
Compiling architecture sim of entity work.tb_scan_core
Built simulation snapshot tb_snapshot
=== simulating ===
Note: TEST 1: exhaustive scan of all 256 input vectors
Note: TEST 2: desync recovery via jtag_reset
Note: TEST 3: desync recovery via sel = '0'
Note: TEST 4: bit-order sensitivity (reversed vectors must be detected)
Note: TEST 4: 192 of 256 reversed vectors detected as wrong
Note: === tb_scan_core done: 259 checks, 0 errors ===
Note: ALL TESTS PASSED
```

Simulated time 164 960 ns; wall clock about 8 seconds.

**This closes the largest gap in the project's evidence.** Until this run, nothing had confirmed the HDL even compiled — the `scan_core` split, the `io` reset path and the falling-edge TDO register had only ever been checked against a Python model written by the same author, in the same sitting, from the same misconceptions. An independent toolchain now agrees.

| Claim | Was | Now |
|---|---|---|
| The VHDL compiles and elaborates | unverified | **verified** — `xvhdl` + `xelab` clean, no warnings |
| Scan protocol logic is correct after the split | model | **simulation** |
| Issue #1 — `io` recovers via TAP reset and via deselect | model | **simulation** |
| Issue #2 — falling-edge TDO introduces no off-by-one | argued + model | **simulation** |
| The suite detects wrong bit order | model | **simulation**, same 192/256 |

### 3.1 The two runs agree, including on the number that could have drifted

`model_scan_core.py` and the VHDL testbench independently report **192 of 256** reversed vectors detected. That figure is a property of the golden function's interaction with bit reversal, not something either implementation could have copied from the other — so it is a real cross-check that the two are exercising the same logic, not just both printing "passed".

### 3.2 Why the check counts differ (259 vs 264)

The Python model reports 264 checks, the VHDL testbench 259. This is a counting convention, not a discrepancy in coverage: the model routes its phase-bit assertions (`io` cleared by reset, `io` set after a lone input phase, `io` cleared by deselect, and the pre-fix desync reproduction) through the same counter as the vector comparisons, while the testbench raises those as VHDL `assert` statements, which do not increment `checks`. Both run the same four tests over the same 256-vector space.

### 3.3 The one thing simulation still cannot reach

Test 2b — the reproduction of the defect against the *pre-fix* design — exists only in the Python model. The VHDL testbench instantiates the current `scan_core`, which has the fix, so it cannot demonstrate the failure it prevents. Reproducing it in VHDL would mean maintaining a deliberately broken copy of the RTL; the model does that job at a fraction of the cost.

### 3.4 A cosmetic Vivado issue, worth knowing

`xelab` emitted this during elaboration:

```
source C:/Users/Owner/Wadhwani -notrace
invalid command name "%"
```

That is Vivado 2020.2's Webtalk telemetry step failing to quote a repository path containing spaces (`Wadhwani Lab Research`). It is a Xilinx bug in a usage-reporting step, entirely outside the simulation, and it did not affect the result — elaboration completed and the snapshot built. Cloning to a path without spaces makes it disappear.

---

## 4. Synthesis and implementation

**Tier: hardware-adjacent** (real toolchain, real device database; not yet on silicon). `scripts\build.bat examples\string_detector` — Vivado 2020.2, part **xc7a35tftg256-1**, 2026-07-30.

```
=== sources  : 7 files in the project, as expected
Synthesis finished with 0 errors, 0 critical warnings and 0 warnings.
INFO: [Project 1-461] DRC finished with 0 Errors
route_design completed successfully   (0 failed nets, 0 node overlaps)
write_bitstream completed successfully
=== SUCCESS: bitstream at .../impl_1/TopLevel.bit
```

**First build of this project, ever.** `scripts/build.tcl` had never run and the emptied XDC had never been through synthesis.

| Claim | Result |
|---|---|
| `build.tcl` works headlessly, end to end | **Yes** — project creation → synth → impl → bitstream, no GUI |
| The emptied XDC is correct, not merely quiet | **Yes** — **no `UCIO-1` message at all**, DRC 0 errors. Issue #7 confirmed resolved |
| `scan_core` and `TopLevel` synthesise | **Yes** — 0 errors, 0 critical warnings, **0 warnings** |
| `BSCANE2` binds and is instantiated | **Yes** — 1 `BSCANE2` cell in the netlist, bound to `unisim_comp.v` |
| The recovered detector sources synthesise | **Yes** — all three FSMs inferred and encoded |
| The generated `DUT.vhd` synthesises | **Yes** — bound and elaborated cleanly |

### 4.1 The netlist shows the D1 fix is physically present

Reported cell usage:

```
BSCANE2  1     LUT2 5   LUT3 2   LUT4 5   LUT5 11   LUT6 6
FDCE     1     FDRE 23
```

24 flip-flops, which accounts exactly: `data` (7) + `din` (7) + `datau` (1) + `io` (1) + `tdo` (1) = 17 in `scan_core`, plus 7 of FSM state in the detectors (2 + 2 + 3) = **24**.

The interesting one is the lone **`FDCE`** — a flip-flop with an *asynchronous clear* — among 23 plain `FDRE`s. Nothing else in the design has an async reset. That is the `io` phase bit, and its clear is the `jtag_reset` path added for [issue #1](KNOWN_ISSUES.md).

So the fix is not merely in the source and in simulation: it survived synthesis into a distinct primitive with the async clear intact. Had `RESET` been left `open`, `io` would have been an ordinary `FDRE` like everything else.

### 4.2 Two warnings, one of them worth acting on

**`[DRC CFGBVS-1]`** — missing `CFGBVS` / `CONFIG_VOLTAGE`. Cosmetic for a design with no I/O, but a legitimate device property. Now set correctly in `constraints.xdc` (`VCCO` / 3.3 V, matching the common Artix-7 boards) rather than ignored.

**`[Timing 38-313] There are no user specified timing constraints`** — and with it `place_design is not in timing mode` and `the router will operate in resource-optimization mode`.

This one matters more than it looks. **Place and route ran with no timing goal whatsoever**, which means the TDO launch-to-sample path — the entire subject of issue #2 — has never been analysed by the tools. It works, and simulation says the logic is right, but no number exists for how much margin there is.

The divider sweep will measure that empirically. A `create_clock` on the `BSCANE2` TCK would let `report_timing` compute it directly. That is left as a commented, documented option in `constraints.xdc` rather than enabled, because the object to attach the clock to varies between Vivado versions and a wrong reference fails the build — it should be verified before being relied on.

### 4.3 What this still does not prove

The bitstream exists and is internally consistent. Nothing has been programmed, and no vector has crossed a cable.

---

## 5. Host driver after the rewrite

**Tier: model** (offline tests; no hardware involved). `python3 host/test_scanchain.py` — 2026-07-29. **22 tests, 0 failures.**

| Claim | Evidence |
|---|---|
| The wire protocol is unchanged by the rewrite | `test_matches_original_input_encoding`, `..._output_encoding`, `..._decoding` — the original algorithm re-implemented verbatim from `scan_bscane2.py`, compared byte-for-byte across **every width from 1 to 64 bits**, 20 random vectors each |
| The decoder consumes exactly the bytes the encoder requests | `test_decode_consumes_exactly_the_read_bytes`, all widths |
| Mask column is applied (#3) | `test_mask_zero_disables_comparison`, `test_mask_one_enables_comparison`, `test_per_bit_mask`, `test_dont_care_in_expected_column` |
| Ragged tracefiles are rejected with a line number (#4) | `test_rejects_ragged_input_width`, `test_rejects_ragged_output_width` |
| The bundled tracefile still parses, and its 2 masked vectors are recognised | `test_bundled_tracefile_parses` |

### 5.1 Why the equivalence tests are the important ones

The MPSSE encoding and decoding are the only part of this project with hardware-tier evidence behind them. A rewrite that quietly changed a single byte would have destroyed the strongest result available and produced failures indistinguishable from an FPGA problem. Asserting byte-for-byte equivalence across the full width range converts "I was careful" into something checkable.

### 5.2 Expected diff on the first hardware run

`scanchain.py` reports fully masked vectors as `Skipped`; the original reported them as `Success`. Against `results/string_detector_output.txt` this predicts **exactly two changed lines** — the two `mask = 0` vectors at lines 1–2:

```
- 0000010 0 Success        + 0000010 0 Skipped
- 0000011 0 Success        + 0000011 0 Skipped
```

Those two lines are the visible confirmation that #3 is fixed. **Any other difference is a regression** and should be run down before anything else — it would most likely indicate the HDL changes, not the host rewrite, since the host's wire protocol is test-pinned.

---

## 5A. FIRST PASSING HARDWARE RUN — parity confirmed

**Tier: hardware.** 2026-07-31, xc7a35t, divider `0x3B` (100 kHz).

```
IDCODE: 0x0362D093  (xc7a35t)
46 vectors: 44 passed, 0 failed, 2 skipped (masked)
0.01 s elapsed, 4521 vectors/s
```

`fc.exe parity.txt results\string_detector_output.txt`:

```
***** parity.txt                    ***** RESULTS\STRING_DETECTOR_OUTPUT.TXT
0000010 0 Skipped                   0000010 0 Success
0000011 0 Skipped                   0000011 0 Success
0001000 0 Success                   0001000 0 Success
*****
```

**Exactly two differing lines, and they are the two predicted ones.**

### 5A.1 What this establishes

| Claim | Was | Now |
|---|---|---|
| The `scan_core` split preserves behaviour | simulation | **hardware** — same tracefile, same results as the pre-change capture |
| `scanchain.py` works against a real board | untested | **hardware** — 44/44 unmasked vectors |
| Issue #3 (mask ignored) is fixed | offline tests | **hardware** — the two `mask = 0` vectors report `Skipped`; the original reported them `Success` |
| Issues #4, #8 (widths, ergonomics) | offline tests | **hardware-exercised** end to end |
| `build.tcl` / `program.bat` produce a working bitstream | untested | **hardware** |
| The recovered `StringDetector` sources are correct | model | **hardware** — they produce the original's outputs on silicon |

The prediction is the part worth keeping. It was written into `RESULTS.md` and `host/README.md` **before** the run: *"this predicts exactly two changed lines — the two `mask = 0` vectors at lines 1–2."* A falsifiable claim, stated in advance, that came out exactly right. Zero differing lines would have meant the mask fix silently did nothing; any third difference would have meant a regression.

### 5A.2 Throughput baseline

4521 vectors/s at divider `0x3B`, for a 7-in / 1-out vector. Recorded as the *before* figure for the divider sweep. Note this is dominated by USB round-trip overhead at 46 vectors, not by TCK — the 4096-vector runs are the meaningful throughput measurement.

### 5A.3 What it took to get here

Three bugs, all mine, all at the hardware boundary that offline tests structurally could not reach:

1. `encode_ir` returned a `bytearray`; `ftd2xx` rejects it with an opaque `ctypes` error.
2. The IDCODE decode applied one of the two required reversals, giving a plausible wrong number.
3. `encode_ir` sent **TMS=0 instead of TMS=1** leaving Shift-IR, so USER1 was never selected and TDO read `1` on every vector.

The third produced two confident and wrong diagnoses before a bisection against the untouched original driver located it. See engineering log entries 012 and 013.

---

## 5B. THE D1 A/B EXPERIMENT — the desync defect demonstrated on silicon

**Tier: hardware.** 2026-07-31. Controlled comparison, one variable.

Two bitstreams differing **only** in whether `BSCANE2.RESET`/`SEL` reach `scan_core`. `scan_core.vhd` itself is byte-identical between them; the pre-fix build ties `jtag_reset => '0'`, `sel => '1'` in `TopLevel.vhd`, reproducing the original's `open` wiring.

Both were subjected to the same fault: `--abort-after-input 10` sends only the input phase of vector 10 and exits, leaving the FPGA's `io` phase bit inverted — the state a crash or dropped USB transfer produces.

| Build | Before injection | After injection, **no reprogramming** |
|---|---|---|
| **Fixed** (`RESET`/`SEL` wired) | 44/44 pass | **44/44 pass** — byte-identical to the baseline |
| **Pre-fix** (`RESET`/`SEL` open) | 44/44 pass | **41 pass, 3 FAIL** |

**D1 is a real defect, and the fix is what prevents it.** Both builds are healthy until interrupted; only the pre-fix build stays broken afterwards. That is the claim the whole issue rested on, now demonstrated rather than argued.

### 5B.1 The failure is worse than "3 vectors failed"

The three failures are lines 15, 35 and 39 — and those are **exactly the three vectors in the tracefile whose expected output is `1`.** Every other vector expects `0`.

The desynced design returns a constant `0`: with `io` inverted, Capture-DR never fires in the phase that loads `datau`, so the output register is never written and `tdo` reads its reset value forever.

Which means:

```
43 of 46 vectors expect 0
 3 of 46 vectors expect 1  (the detections)

A stuck-at-0 harness fails only those 3
=> 41 of 44 unmasked vectors still report "Success"
=> 93% of the suite passes while the harness is completely broken
```

**This is the silent-corruption property, measured.** The original write-up argued D1 was dangerous because it fails quietly. On this tracefile it is quieter than expected: a 93% pass rate on a design that is returning a constant. A student glancing at the summary line — "41 passed" — would reasonably conclude their DUT mostly works.

And the visible failures are the *detections*, i.e. precisely the interesting behaviour the test exists to check. A stuck-at-0 scan chain looks exactly like a DUT that never asserts its output.

### 5B.2 Why the earlier "recovery" attempts proved nothing

Two earlier attempts ran a complete tracefile and then reran — and passed on the pre-fix design too. That was not evidence of recovery. **A complete vector performs both phases and leaves `io` back at `'0'` regardless of whether the reset path exists.** The desync requires dying *between* the two phases of a single vector, and at 0.01–0.08 s per run that window is unreachable by hand.

Which is why `--abort-after-input` exists. The fault had to be injected deterministically; it could not be caught.

### 5B.3 Contrast with the earlier stuck-at-1

Both failure modes present as a constant on TDO, and they are not the same fault:

| Symptom | Cause | Mechanism |
|---|---|---|
| Stuck at **1** | Host bug — `encode_ir` sent TMS=0 | USER1 never selected; the user DR was never in the scan path, so TDO floated |
| Stuck at **0** | D1 — phase desync | USER1 *is* selected; `datau` is simply never loaded |

Worth recording together, because "TDO is constant" was ambiguous between a host fault and an HDL fault, and telling them apart is what the bisection against `scan_bscane2.py` accomplished.

---

## 5C. THE DIVIDER SWEEP — 17x throughput, and a five-fold error in every frequency this project ever quoted

**Tier: hardware.** 2026-07-31, `examples/alu` (256 vectors, exhaustive, 8 in / 6 out), 3 repeats per divider.

The gating run first — the ALU example, whose wrapper `new_lab.py` generated and whose tracefile came from a golden model:

```
examples\alu\TRACEFILE.txt: 256 vectors, 8 in / 6 out
IDCODE: 0x0362D093  (xc7a35t)
256 vectors: 256 passed, 0 failed, 0 skipped (masked)
```

**256/256, exhaustive over the entire input space.** This is the first hardware validation of a machine-generated wrapper: it confirms `new_lab.py`'s bit layout is right on silicon, not merely consistent with the two hand-written wrappers it was checked against, and it exercises `build.tcl` on a second design with different widths.

### 5C.1 The sweep

```
 divider        TCK              result             vectors/s
----------------------------------------------------------------
    0x3b    100 kHz            PASS 3/3             3892-4062
    0x1d    200 kHz            PASS 3/3             7394-8491
     0xe    400 kHz            PASS 3/3           11329-14069
     0x6    857 kHz            PASS 3/3           22588-30099
     0x2   2.00 MHz            PASS 3/3           30844-63299
     0x1   3.00 MHz            PASS 3/3           26848-65729
     0x0   6.00 MHz            PASS 3/3           58134-70276
```

(The TCK column is the corrected one — see 5C.3. The script printed 500 kHz … 30 MHz on the day.)

**Every divider passed every repeat, up to the fastest the FTDI can produce with its current configuration. 4062 → 70276 vectors/s, a 17.3x speed-up.**

No `INTERMITTENT` row appeared, which is the one outcome that would have located the timing margin. The sweep is **censored at the top**: it establishes that the design works at 6 MHz, not where it stops working.

### 5C.2 The prediction was wrong, and the way it was wrong is the finding

Written down before the sweep ran:

> *"I expect little or no throughput gain. At 0.07 s for 256 vectors, that's ~270 µs per vector, while the actual JTAG traffic at 500 kHz is only ~30 µs. So roughly 90% of the time is USB round-trip and Python overhead, not TCK."*

17.3x is not "little or no gain". But the ~30 µs estimate of JTAG traffic was close to right — counted properly from the encoders, an 8-in/6-out vector is **24 TCK cycles** (13 input phase, 11 output phase). The error was in the other term: at a *real* 100 kHz rather than the assumed 500 kHz, those 24 cycles take 240 µs, not 48 µs. They were never the small term. **The prediction failed because the clock was 5x slower than the number in the source comment.**

### 5C.3 The driver enables the /5 prescaler while claiming to disable it

`host/scanchain.py`, inherited verbatim from `scan_bscane2.py`:

```python
self.dev.write(b"\x8B")        # disable /5 prescaler   <-- WRONG COMMENT
```

MPSSE `0x8A` disables the divide-by-5 prescaler; **`0x8B` enables it.** With it enabled the master clock is 60/5 = 12 MHz and

```
TCK = 12 MHz / (2 * (divider + 1)) = 6 MHz / (divider + 1)
```

not the `30 MHz / (n+1)` asserted in the code, in `KNOWN_ISSUES.md`, and in the first version of `sweep_divider.py`. So `0x3B` is **100 kHz, not 500 kHz**, and the maximum available is **6 MHz, not 30 MHz**.

### 5C.4 The sweep measures its own base clock, independently of any datasheet

This does not rest on remembering which opcode is which. Model each vector as a fixed TCK cost plus a fixed host cost:

```
t_vector = 24 / f_tck  +  a
```

24 is counted from `encode_input_scan(8)` and `encode_output_scan(6)`, not fitted. Solving for `a` at each divider, using the best of the three repeats:

| divider | TCK @ 6 MHz base | µs/vector observed | TCK part | residual `a` |
|---|---|---|---|---|
| `0x3B` | 100 kHz | 246.2 | 240.0 | 6.2 |
| `0x1D` | 200 kHz | 117.8 | 120.0 | −2.2 |
| `0x0E` | 400 kHz | 71.1 | 60.0 | 11.1 |
| `0x06` | 857 kHz | 33.2 | 28.0 | 5.2 |
| `0x02` | 2.00 MHz | 15.8 | 12.0 | 3.8 |
| `0x01` | 3.00 MHz | 15.2 | 8.0 | 7.2 |
| `0x00` | 6.00 MHz | 14.2 | 4.0 | 10.2 |

**Mean residual 5.9 µs/vector, and it is flat across a 60x range of clock rates** — which is what a constant host cost should look like. Under the 30 MHz assumption the TCK part at `0x3B` would be 48 µs, leaving ~198 µs of "host cost" at the slow end against ~13 µs at the fast end: a residual that tracks the clock, which is not a constant and not an explanation.

The sweep therefore contains the evidence that the sweep's own frequency labels were wrong. That is worth more than the throughput number.

### 5C.5 Where the knee is, and what to set the default to

TCK cost equals host cost at 24/f = 5.9 µs, i.e. **f ≈ 4 MHz**. Above that, throughput saturates — visible in the table as `0x02` → `0x00` tripling the clock for 11% more vectors/s.

| Divider | True TCK | vs `0x3B` | Note |
|---|---|---|---|
| `0x3B` | 100 kHz | 1.0x | Inherited. Now known to be ~60x slower than necessary |
| `0x02` | 2.00 MHz | **15.6x** | Captures 90% of the available gain at a third of the clock rate |
| `0x00` | 6.00 MHz | 17.3x | Fastest available; no margin left below it to fall back on |

**`0x02` is the defensible default** — three divider steps below the fastest that passed, and it gives up 11% of a 17x improvement to buy that margin. The default is left at `0x3B` in this commit: three passes is not a basis for changing the setting every hardware result on record was taken at. `--divider 0x02` is documented, and the help text now points at it.

### 5C.6 What this says about issue #2, and the 5x still on the table

The TDO path is combinational and sampled on the rising edge — the entire subject of issue #2. It now has a **measured bound**: correct on 3×256 vectors at a 167 ns clock period, so the launch-to-sample path settles in well under half of that. That is real evidence where previously there was none, since Vivado never timed this design at all (§4.2).

It is also a much weaker bound than it looked like an hour ago. "Works at 30 MHz" would have effectively closed issue #2. **"Works at 6 MHz" does not** — it is roughly the frequency the original 1149.1 argument would predict is safe anyway.

And the experiment that would settle it is now obvious: **send `0x8A` instead of `0x8B`.** That unlocks 30 MHz, five times faster than anything tested here, and issue #2 predicts the combinational TDO path is exactly what fails first. A sweep that finds the edge would settle the question that two wrong diagnoses and one simulation could not. Untested — the prescaler is left enabled deliberately, because every result in this document was taken with it on.

---

## 6. Outstanding — hardware

Simulation and synthesis are complete. Everything remaining needs the board.

### 6.1 Hardware

| Check | Expected | Proves |
|---|---|---|
| ~~`scripts/build.tcl` produces a bitstream~~ | ~~clean, no `UCIO-1`~~ | **Done — section 4** |
| ~~46-vector parity run~~ | ~~2 lines differ~~ | **Done — section 5A. Exactly 2, as predicted** |
| `scripts/program.tcl` programs and releases the cable | device programmed | Same |
| ~~46-vector run vs `results/string_detector_output.txt`~~ | ~~identical except lines 1–2~~ | **Done — section 5A** |
| ~~Interrupt mid-run, rerun without reprogramming~~ | ~~full pass~~ | **Done — section 5B, with the pre-fix A/B** |
| ~~Divider sweep down from `0x3B`~~ | ~~safe ceiling rises~~ | **Done — section 5C. 17.3x, no failure found; ceiling not located** |
| ~~ALU 256-vector exhaustive, generated wrapper~~ | ~~256/256~~ | **Done — section 5C** |
| Re-sweep with `0x8A` (prescaler off), reaching 30 MHz | a divider that fails | Would locate the real timing ceiling and settle issue #2 |
| `seq1011` 602-vector run | 602/602 | The clocked-FSM path end to end on a design written for this repo |

### 6.2 Deliberately out of scope for simulation

- **`BSCANE2` itself.** The testbench substitutes for it. If the primitive's CAPTURE/SHIFT/UPDATE pulse timing differs from what is modelled, only hardware will show it.
- **Real timing.** Functional simulation with an idealised clock proves the launch edge is *logically* right. It says nothing about the maximum safe TCK frequency.
- **Synthesis.** A green testbench does not guarantee `build.tcl` succeeds.
- **The FTDI transport.** The host tests stop at the device boundary: nothing exercises `JtagDevice`, the USB batching path, or the interaction between the batch size and the read count on a real cable.

---

## 7. Summary of claims

| Claim | Strongest evidence to date |
|---|---|
| The scan chain approach works on Artix-7 | **Hardware** — 4096/4096, once (the second such file is a captured failure, §1.1) |
| The HDL compiles and elaborates | **Simulation** — Vivado 2020.2, clean |
| The design synthesises, implements and produces a bitstream | **Toolchain** — 0 errors, 0 warnings, no `UCIO-1` |
| Issue #7 (vestigial constraints) is resolved | **Toolchain** — no `UCIO-1` with the DRC no longer suppressed |
| The `io` async reset survives into the netlist | **Toolchain** — a single `FDCE` among 23 `FDRE`s |
| `new_lab.py`'s generated wrapper synthesises | **Toolchain** — bound and elaborated cleanly |
| The `scan_core` split preserves behaviour | **Hardware** — 46-vector parity run, exactly the 2 predicted differences |
| `scanchain.py` works on real hardware | **Hardware** — 44/44 unmasked |
| Issue #3 (mask) is fixed | **Hardware** — masked vectors report `Skipped` |
| Issue #1 (desync) was a real defect | **Hardware** — pre-fix build fails the injected fault, 3/44 |
| Issue #1 is fixed | **Hardware** — fixed build recovers byte-identically; controlled A/B, one variable |
| Issue #1 fails *silently* | **Hardware** — 93% of vectors still report Success while the harness returns a constant |
| `new_lab.py`'s generated wrapper is correct on silicon | **Hardware** — ALU, 256/256 exhaustive |
| Issue #2 (TDO edge) is fixed | **Simulation** — no off-by-one. Hardware bounds the margin only to 6 MHz, which does not discriminate |
| Throughput can be raised well above the inherited setting | **Hardware** — 17.3x, 3/3 at every divider tested |
| Every TCK frequency previously quoted in this project | **Wrong by 5x** — the /5 prescaler is enabled, not disabled; see 5C.3–5C.4 |
| The host rewrite preserves the wire protocol | **Model** — byte-for-byte equivalence, widths 1–64 |
| Issues #3, #4, #8 are fixed | **Model** — 22 offline tests. No hardware run |
| Throughput improved | **No evidence.** Divider sweep not yet run |
| Issues #5, #6, #7 | Open, unaddressed |

The honest one-line status: *the protocol was proven on hardware by its original author, and the reworked version now reproduces that result on the same board — one command to build, one to program, one to run. Five defects fixed and confirmed; one (#2) withdrawn as unproven in both directions; the desync fix and the throughput sweep remain the outstanding hardware work.*
