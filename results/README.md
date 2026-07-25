# Results

Captured output from real hardware runs. These are the reference results — after a rebuild, `diff` against them to confirm nothing regressed.

| File | Vectors | Outcome | Notes |
|---|---|---|---|
| `string_detector_output.txt` | 46 | 46 pass | The bundled string-detector tracefile. Widths 7 in / 1 out. |
| `passthrough_4096_out.txt` | 4096 | 4096 pass | Exhaustive sweep, 12-bit input / 8-bit output. **This is the evidence the protocol and USB batching work at scale.** |
| `passthrough_4096_output1.txt` | 4096 | 4096 pass | Duplicate run of the same sweep. |

## Reading the format

```
<input_bits> <bits_read_back> <Success|Failure>
```

```
000000000000 00000000 Success
000000000001 00000001 Success
```

## Caveat

All of these were captured *before* the phase-desync and TDO-edge fixes (Known Issues #1 and #2). They demonstrate that the flow works, not that it is robust — a run that completes without interruption at the current slow clock rate is expected to pass. Post-fix results with throughput measurements belong in `docs/RESULTS.md` (Roadmap Phase 6).

There is no summary line in these files because the script doesn't emit one yet. To check a run:

```
grep -c Success output.txt
grep -c Failure output.txt
```
