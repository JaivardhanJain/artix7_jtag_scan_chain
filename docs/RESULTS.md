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
| Exhaustive passthrough, repeat | 4096 | 4096 pass, 0 fail | `results/passthrough_4096_output1.txt` |

This is the number that matters most in the whole project, and it belongs to the original implementation: **the protocol works, at scale, on real hardware.** Everything since is robustness and usability work on top of a design that was already functionally correct.

**What the baseline does not establish.** Every one of these runs completed without interruption, at a clock divider of `0x3B` (~500 kHz). Neither the desync failure mode nor the TDO edge race can appear under those conditions, so a clean sweep here is consistent with both defects being present. It was.

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

## 3. Host driver after the rewrite

**Tier: model** (offline tests; no hardware involved). `python3 host/test_scanchain.py` — 2026-07-29. **22 tests, 0 failures.**

| Claim | Evidence |
|---|---|
| The wire protocol is unchanged by the rewrite | `test_matches_original_input_encoding`, `..._output_encoding`, `..._decoding` — the original algorithm re-implemented verbatim from `scan_bscane2.py`, compared byte-for-byte across **every width from 1 to 64 bits**, 20 random vectors each |
| The decoder consumes exactly the bytes the encoder requests | `test_decode_consumes_exactly_the_read_bytes`, all widths |
| Mask column is applied (#3) | `test_mask_zero_disables_comparison`, `test_mask_one_enables_comparison`, `test_per_bit_mask`, `test_dont_care_in_expected_column` |
| Ragged tracefiles are rejected with a line number (#4) | `test_rejects_ragged_input_width`, `test_rejects_ragged_output_width` |
| The bundled tracefile still parses, and its 2 masked vectors are recognised | `test_bundled_tracefile_parses` |

### 3.1 Why the equivalence tests are the important ones

The MPSSE encoding and decoding are the only part of this project with hardware-tier evidence behind them. A rewrite that quietly changed a single byte would have destroyed the strongest result available and produced failures indistinguishable from an FPGA problem. Asserting byte-for-byte equivalence across the full width range converts "I was careful" into something checkable.

### 3.2 Expected diff on the first hardware run

`scanchain.py` reports fully masked vectors as `Skipped`; the original reported them as `Success`. Against `results/string_detector_output.txt` this predicts **exactly two changed lines** — the two `mask = 0` vectors at lines 1–2:

```
- 0000010 0 Success        + 0000010 0 Skipped
- 0000011 0 Success        + 0000011 0 Skipped
```

Those two lines are the visible confirmation that #3 is fixed. **Any other difference is a regression** and should be run down before anything else — it would most likely indicate the HDL changes, not the host rewrite, since the host's wire protocol is test-pinned.

---

## 4. Outstanding — nothing below has been run

### 4.1 Simulation

| Check | Command | Why it matters |
|---|---|---|
| VHDL compiles and elaborates | `sim/run_sim.bat` | **Nothing has confirmed this.** No VHDL toolchain was available where the code was written. First thing to run. |
| All four testbench tests pass in VHDL | same | Confirms the model and the RTL agree |

### 4.2 Hardware

| Check | Expected | Proves |
|---|---|---|
| `scripts/build.tcl` produces a bitstream | clean, no `UCIO-1` | The build script works at all — it is untested |
| `scripts/program.tcl` programs and releases the cable | device programmed | Same |
| 46-vector run vs `results/string_detector_output.txt` | identical **except lines 1–2**, which become `Skipped` (see 3.2) | No behavioural drift from the `scan_core` split or the TDO edge move, and confirmation the mask fix took effect |
| Interrupt mid-run, rerun **without reprogramming** | full pass | Issue #1. **Fails on the original code** — this is the fix's entire justification |
| Divider sweep down from `0x3B`, before vs after the TDO fix | safe ceiling rises | Issue #2, and yields the one measurable throughput figure in the project |

### 4.3 Deliberately out of scope for simulation

- **`BSCANE2` itself.** The testbench substitutes for it. If the primitive's CAPTURE/SHIFT/UPDATE pulse timing differs from what is modelled, only hardware will show it.
- **Real timing.** Functional simulation with an idealised clock proves the launch edge is *logically* right. It says nothing about the maximum safe TCK frequency.
- **Synthesis.** A green testbench does not guarantee `build.tcl` succeeds.
- **The FTDI transport.** The host tests stop at the device boundary: nothing exercises `JtagDevice`, the USB batching path, or the interaction between the batch size and the read count on a real cable.

---

## 5. Summary of claims

| Claim | Strongest evidence to date |
|---|---|
| The scan chain approach works on Artix-7 | **Hardware** — 4096/4096, twice |
| The `scan_core` split preserves behaviour | **Model** — exhaustive. Hardware parity run outstanding |
| Issue #1 (desync) was a real defect | **Model** — reproduced against the pre-fix design |
| Issue #1 is fixed | **Model.** Hardware interrupt test outstanding |
| Issue #2 (TDO edge) is fixed | **Argued** + model shows no off-by-one. Real timing margin unmeasured |
| The host rewrite preserves the wire protocol | **Model** — byte-for-byte equivalence, widths 1–64 |
| Issues #3, #4, #8 are fixed | **Model** — 22 offline tests. No hardware run |
| Throughput improved | **No evidence.** Divider sweep not yet run |
| Issues #5, #6, #7 | Open, unaddressed |

The honest one-line status: *the protocol was already proven on hardware by its original author; five defects have been found and fixed — two in HDL, three in the host — and all of them are verified only against offline models and tests. Nothing has been rebuilt, reprogrammed or rerun on the board.*
