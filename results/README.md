# Results

Captured output from real hardware runs. These are the reference results — after a rebuild, `diff` against them to confirm nothing regressed.

| File | Vectors | Outcome | Notes |
|---|---|---|---|
| `string_detector_output.txt` | 46 | 46 pass | The bundled string-detector tracefile. Widths 7 in / 1 out. |
| `passthrough_4096_out.txt` | 4096 | **4096 pass** | Exhaustive sweep, 12-bit input / 8-bit output, 256 distinct output values. **This is the evidence the protocol and USB batching work at scale.** |
| `passthrough_4096_output1.txt` | 4096 | **510 pass, 3586 fail** | **A failed run.** Not a duplicate. See below. |

## `passthrough_4096_output1.txt` is a captured failure

This file was described as a second clean sweep — in this README, in `docs/RESULTS.md`, and in engineering log entry 001 — from July 2026 until 2026-08-11. It is not. It records a run in which **TDO returned `00000000` for all 4096 vectors.**

The arithmetic is conclusive:

- The `got` column has **exactly one distinct value** across 4096 lines: `00000000`.
- **510** vectors report `Success`. Per the good run, exactly **510** vectors have a correct output of `00000000`.
- Every `Success` is one of those 510, and every `Failure` is not.

So the harness returned a constant, and the only vectors that "passed" are the ones whose right answer happened to be that constant. Nothing was being observed.

### Which fault

Constant TDO has two documented causes ([KNOWN_ISSUES.md](../docs/KNOWN_ISSUES.md)):

| Stuck at | Cause |
|---|---|
| `1` | The host never selected USER1 — the user register was never in the scan path, so TDO floated. |
| `0` | USER1 *is* selected, but the output register is never loaded — the phase-bit desync of issue #1. |

This is stuck at **0**, which matches issue #1. That is a signature match, not a proof: a capture file cannot distinguish a phase desync from, say, a DUT whose output was tied low. What can be said is that the failure mode issue #1 predicts was, at some point, occurring on this bench.

### Why it went unnoticed

The original driver printed no summary — the file is 4096 lines with no counts anywhere, so the outcome is invisible unless you explicitly count. The previous version of this README even gave the command (`grep -c Failure`). Nobody ran it, including the author of that line.

`host/scanchain.py` now prints a summary on every run, and detects the constant-TDO case specifically, reporting it as **one fault rather than N failures** and naming the likely cause.

## Reading the format

```
<input_bits> <bits_read_back> <Success|Failure|Skipped>
```

Failing lines carry more, because "it failed" is not enough to act on:

```
10011001 11001 Failure  expected=11000  diff=....^  line=17
```

`diff` marks only the bits that actually failed; masked (don't-care) positions show `-`.

## Caveat

All of these were captured *before* the phase-desync fix. They demonstrate that the flow works, not that it is robust — and `passthrough_4096_output1.txt` demonstrates precisely what happens when it isn't. Post-fix results are in [docs/RESULTS.md](../docs/RESULTS.md).
