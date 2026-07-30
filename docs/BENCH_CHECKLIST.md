# Bench Checklist

Everything that cannot be verified without the board, in the order it should be done. Each step says what to run, what to expect, and what it proves.

Work through it in order — later steps assume earlier ones passed. Record the actual output as you go; the numbers go into [RESULTS.md](RESULTS.md).

**Before you start:** all commands are run from the repository root unless stated. Vivado 2020.2 on `PATH` (or use `sim/run_sim.bat`, which finds it itself).

### If you are in PowerShell

Three differences that will otherwise waste your time:

| Trap | Fix |
|---|---|
| `run_sim.bat` → *"not recognized as the name of a cmdlet"* | PowerShell does not run scripts from the current directory. Use `.\run_sim.bat`. |
| `fc` compares nothing useful | In PowerShell `fc` is an alias for `Format-Custom`, not the file-compare tool. Use **`fc.exe`**. |
| `cd /d "path"` fails | `/d` is a `cmd` switch. Plain `cd "path"` works in PowerShell. |

`vivado` also may not be on `PATH`, and `settings64.bat` cannot be sourced from PowerShell. Either run the `vivado` lines from a plain `cmd` window, or call the binary directly:

```powershell
& "C:\Xilinx\Vivado\2020.2\bin\vivado.bat" -mode batch -source scripts/build.tcl -tclargs examples/seq1011
```

Note the `vivado` lines use forward slashes (Tcl wants them) while Python paths use backslashes. Both are correct as written.

---

## Step 0 — Re-run the simulation (2 min, no board)

`hdl/constraints.xdc` and the examples changed since the last simulation run. Confirm nothing regressed before spending time on hardware.

```
cd sim
run_sim.bat
cd ..
python3 host/test_scanchain.py
python3 scripts/test_new_lab.py
python3 sim/model_scan_core.py
```

**Expect:** `259 checks, 0 errors` / `192 of 256` from xsim, then `22 tests, 0 failures`, `19 tests, 0 failures`, `264 checks, 0 errors`.

**If it fails:** stop. Nothing below is meaningful.

---

## Step 1 — Parity run: does the harness still behave identically? (20 min)

**The single most important test in this list.** It compares a fresh run against the committed result captured before any of the changes. It is the regression check for the `scan_core` split and the falling-edge TDO move.

Uses `string_detector` because that is what `results/string_detector_output.txt` was captured from. Its detector sources are gitignored but present in your working copy.

```
python3 scripts/new_lab.py examples/string_detector/StringDetector.vhdl --patch-toplevel
vivado -mode batch -source scripts/build.tcl -tclargs examples/string_detector
vivado -mode batch -source scripts/program.tcl
python host/scanchain.py -t examples/string_detector/TRACEFILE.txt -o /tmp/parity.txt
```

**Expect from the generator:** `7 input bits, 1 output bits`, clock at bit 0, reset at bit 1, `inp` at `[6:2]`.

**Expect from the build:** a bitstream, and **no `UCIO-1` DRC message at all** — that confirms the emptied XDC is correct rather than merely quiet.

**Expect from the run:**

```
IDCODE: 0x........
46 vectors: 44 passed, 0 failed, 2 skipped (masked)
```

Then the diff that matters:

```
diff /tmp/parity.txt results/string_detector_output.txt
```

**Expect exactly two changed lines** — the two `mask = 0` vectors, now `Skipped` instead of `Success`:

```
< 0000010 0 Skipped        > 0000010 0 Success
< 0000011 0 Skipped        > 0000011 0 Success
```

**What each outcome means:**

| Result | Meaning |
|---|---|
| Exactly those 2 lines differ | Everything worked. No behavioural drift, and the mask fix is confirmed working. |
| **Zero** lines differ | Suspicious — the mask fix did not take effect. Check you ran `scanchain.py`, not `scan_bscane2.py`. |
| Other lines differ | **Regression.** Stop and report it. Since the host's wire protocol is pinned by tests, the cause is almost certainly in `hdl/`. |
| Every line fails | Check the IDCODE printed. If it looks valid, most likely the width constants — see [TROUBLESHOOTING.md](TROUBLESHOOTING.md). |

**Record:** the IDCODE, the summary line, and the diff.

The IDCODE also settles issue #6 — which part the board actually is. `0x0362D093` = xc7a35t, `0x0362C093` = xc7a15t.

---

## Step 2 — The desync test (5 min)

**This is the test that fails on the original code**, and the entire justification for the `BSCANE2.RESET` fix. It has been confirmed in simulation; this is the real thing.

```
python host/scanchain.py -t examples/string_detector/TRACEFILE.txt -o /tmp/a.txt
```

…and press **Ctrl-C while it is running**. With only 46 vectors that is hard to catch, so use a bigger target and interrupt mid-run:

```
python host/scanchain.py -t examples/alu/TRACEFILE.txt -o /tmp/a.txt
```

Then — **without reprogramming the FPGA** — run the parity test again:

```
python host/scanchain.py -t examples/string_detector/TRACEFILE.txt -o /tmp/after_interrupt.txt
diff /tmp/after_interrupt.txt /tmp/parity.txt
```

**Expect:** identical to the step 1 output. No difference at all.

**What it means:** a pass means the phase bit resynchronised off the TAP reset the host issues at startup. On the original code this run would have failed wholesale, recoverable only by reprogramming.

> Note: the ALU tracefile has 8 input bits, so the widths no longer match while it runs. That does not matter here — the point is to interrupt a scan mid-flight and leave the FPGA's phase inverted. You are testing recovery, not correctness.

**Record:** whether the post-interrupt run matched.

---

## Step 3 — Divider sweep: the one measurable improvement (15 min)

The clock was left at `0x3B` (~500 kHz) by the original author, with no recorded justification. With the TDO race fixed, the safe ceiling should be higher. This produces the project's only quantitative before/after number.

```
python host/scanchain.py -t examples/alu/TRACEFILE.txt -o /tmp/d3B.txt -d 0x3B
python host/scanchain.py -t examples/alu/TRACEFILE.txt -o /tmp/d1D.txt -d 0x1D
python host/scanchain.py -t examples/alu/TRACEFILE.txt -o /tmp/d0E.txt -d 0x0E
python host/scanchain.py -t examples/alu/TRACEFILE.txt -o /tmp/d06.txt -d 0x06
python host/scanchain.py -t examples/alu/TRACEFILE.txt -o /tmp/d02.txt -d 0x02
python host/scanchain.py -t examples/alu/TRACEFILE.txt -o /tmp/d00.txt -d 0x00
```

You will need to run `new_lab.py --patch-toplevel` on the ALU and rebuild first — see step 4. Do step 4, then come back.

`TCK = 30 MHz / (divider + 1)`:

| Divider | TCK |
|---|---|
| `0x3B` | 500 kHz |
| `0x1D` | 1 MHz |
| `0x0E` | 2 MHz |
| `0x06` | 4.3 MHz |
| `0x02` | 10 MHz |
| `0x00` | 30 MHz |

**Record for each:** pass/fail count and the `vectors/s` figure from the summary. The fastest divider that still passes 256/256 is the result.

**Interpreting it honestly:**

- If it now runs materially faster than `0x3B`, that is the improvement claim — state the before and after.
- If `0x3B` was already near the ceiling, say so. "Here is the measured safe operating margin, previously undocumented" is a legitimate finding; it just makes this a robustness result rather than a speed one.
- Run the fastest passing setting **three times** before believing it. A marginal clock fails intermittently, which is exactly what issue #2 predicted.

---

## Step 4 — The generated wrapper, end to end (15 min)

Proves `new_lab.py`'s output actually synthesises and works — so far it has only been checked against hand-written wrappers on paper.

```
python3 scripts/new_lab.py examples/alu/ALU.vhd --patch-toplevel
vivado -mode batch -source scripts/build.tcl -tclargs examples/alu
vivado -mode batch -source scripts/program.tcl
python host/scanchain.py -t examples/alu/TRACEFILE.txt -o /tmp/alu.txt
```

**Expect:** `8 input bits, 6 output bits`, no clock or reset detected, then

```
256 vectors: 256 passed, 0 failed, 0 skipped (masked)
```

**What it means:** 256/256 is an exhaustive test of the whole input space, against a wrapper nobody hand-wrote and a tracefile generated from a golden model. That is the plug-and-play path working end to end.

**If some vectors fail:** check them against the ALU quirks in `examples/alu/README.md` — `MAX` returns `0000` for equal operands, and `Y(5 downto 4)` is always `00`. If the failures are all at `A = B`, my golden model is wrong, not the hardware.

---

## Step 5 — The clocked example (10 min)

```
python3 scripts/new_lab.py examples/seq1011/Seq1011.vhd --patch-toplevel
vivado -mode batch -source scripts/build.tcl -tclargs examples/seq1011
vivado -mode batch -source scripts/program.tcl
python host/scanchain.py -t examples/seq1011/TRACEFILE.txt -o /tmp/seq.txt
```

**Expect:** `3 input bits, 1 output bits`, then `602 vectors: 600 passed, 0 failed, 2 skipped`.

**What it means:** the repository's self-contained example works on real hardware, so a fresh public clone has something a stranger can actually run.

**If failures cluster on the clock-high lines**, the Mealy two-phase expectation is wrong again — see `examples/seq1011/README.md`. That would be my bug, not the board's.

---

## Step 6 — Report back

Paste me:

1. Step 1: IDCODE, summary line, and the `diff`
2. Step 2: whether the post-interrupt run matched
3. Step 3: the pass/fail and vectors/s for each divider
4. Steps 4 and 5: the summary lines
5. Anything unexpected, verbatim

I will fold it into `RESULTS.md`, close the resolved entries in `KNOWN_ISSUES.md`, and add the engineering log entry.

---

## Reference: interpreting a bad run

| Symptom | Likely cause |
|---|---|
| `DEVICE_NOT_OPENED` | Vivado Hardware Manager still holds the cable. `program.tcl` releases it; the GUI does not. |
| IDCODE all `f`s or all `0`s | TAP not responding — power, cable, or wrong FTDI channel (`--channel 1`). |
| Every vector fails, IDCODE fine | Width constants don't match the tracefile, or `TopLevel` isn't the top. |
| Values look bit-reversed | DUT wrapper bit mapping inverted. |
| Intermittent pass/fail | Clock too fast for the margin — back the divider off. |
| Fails only after an interrupted run | The #1 fix is not in the bitstream you programmed. Rebuild. |

Full detail in [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
