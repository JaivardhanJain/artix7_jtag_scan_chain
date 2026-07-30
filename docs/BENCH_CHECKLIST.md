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

**`vivado` will not be on `PATH`** in a normal shell, and `settings64.bat` cannot be sourced from PowerShell. So use the wrapper scripts instead of calling `vivado` directly — they locate the install themselves, exactly as `run_sim.bat` does:

```powershell
.\scripts\build.bat examples\seq1011
.\scripts\program.bat
```

Set `VIVADO_SETTINGS` if your install is somewhere unusual:

```powershell
$env:VIVADO_SETTINGS = "C:\path\to\Vivado\20XX.X\settings64.bat"
```

---

## Step 0 — Re-run the simulation (2 min, no board)

`hdl/constraints.xdc` and the examples changed since the last simulation run. Confirm nothing regressed before spending time on hardware.

```
cd sim
.\run_sim.bat
cd ..
python host\test_scanchain.py
python scripts\test_new_lab.py
python sim\model_scan_core.py
```

**Expect:** `259 checks, 0 errors` / `192 of 256` from xsim, then `22 tests, 0 failures`, `19 tests, 0 failures`, `264 checks, 0 errors`.

**If it fails:** stop. Nothing below is meaningful.

---

## Step 1 — Parity run: does the harness still behave identically? (20 min)

**The single most important test in this list.** It compares a fresh run against the committed result captured before any of the changes. It is the regression check for the `scan_core` split and the falling-edge TDO move.

Uses `string_detector` because that is what `results/string_detector_output.txt` was captured from. Its detector sources are gitignored but present in your working copy.

```
python scripts\new_lab.py examples\string_detector\StringDetector.vhdl --patch-toplevel
.\scripts\build.bat examples\string_detector
.\scripts\program.bat
python host\scanchain.py -t examples\string_detector\TRACEFILE.txt -o parity.txt
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
fc.exe parity.txt results\string_detector_output.txt
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
python host\scanchain.py -t examples\string_detector\TRACEFILE.txt -o scratch.txt
```

…and press **Ctrl-C while it is running**. With only 46 vectors that is hard to catch, so use a bigger target and interrupt mid-run:

```
python host\scanchain.py -t examples\alu\TRACEFILE.txt -o scratch.txt
```

Then — **without reprogramming the FPGA** — run the parity test again:

```
python host\scanchain.py -t examples\string_detector\TRACEFILE.txt -o after_interrupt.txt
fc.exe after_interrupt.txt parity.txt
```

**Expect:** identical to the step 1 output. No difference at all.

**What it means:** a pass means the phase bit resynchronised off the TAP reset the host issues at startup. On the original code this run would have failed wholesale, recoverable only by reprogramming.

> Note: the ALU tracefile has 8 input bits, so the widths no longer match while it runs. That does not matter here — the point is to interrupt a scan mid-flight and leave the FPGA's phase inverted. You are testing recovery, not correctness.

**Record:** whether the post-interrupt run matched.

---

## Step 3 — Divider sweep: the one measurable improvement (15 min)

The clock was left at `0x3B` (100 kHz) by the original author, with no recorded justification. This produces the project's only quantitative before/after number. **Done — every divider passed; see the table below and RESULTS.md §5C.** The remaining version of this test is to re-run it with MPSSE `0x8A` in place of `0x8B`, which raises the ceiling from 6 MHz to 30 MHz and is the only way to find where the design actually stops working.

```
python host\scanchain.py -t examples\alu\TRACEFILE.txt -o d3B.txt -d 0x3B
python host\scanchain.py -t examples\alu\TRACEFILE.txt -o d1D.txt -d 0x1D
python host\scanchain.py -t examples\alu\TRACEFILE.txt -o d0E.txt -d 0x0E
python host\scanchain.py -t examples\alu\TRACEFILE.txt -o d06.txt -d 0x06
python host\scanchain.py -t examples\alu\TRACEFILE.txt -o d02.txt -d 0x02
python host\scanchain.py -t examples\alu\TRACEFILE.txt -o d00.txt -d 0x00
```

The ALU must be built and programmed first — do step 4, then come back.

`TCK = 6 MHz / (divider + 1)` as the driver is currently configured — it sends MPSSE `0x8B`, which *enables* the /5 prescaler. (This table read `30 MHz / (n+1)` until 2026-07-31; it was 5x too high. See RESULTS.md §5C.)

| Divider | TCK | Measured 2026-07-31, ALU 256 |
|---|---|---|
| `0x3B` | 100 kHz | PASS 3/3 — 4062 vectors/s |
| `0x1D` | 200 kHz | PASS 3/3 — 8491 |
| `0x0E` | 400 kHz | PASS 3/3 — 14069 |
| `0x06` | 857 kHz | PASS 3/3 — 30099 |
| `0x02` | 2.00 MHz | PASS 3/3 — 63299 |
| `0x01` | 3.00 MHz | PASS 3/3 — 65729 |
| `0x00` | 6.00 MHz | PASS 3/3 — 70276 (**17.3x**) |

**Record for each:** pass/fail count and the `vectors/s` figure from the summary. The fastest divider that still passes 256/256 is the result.

**Interpreting it honestly:**

- If it now runs materially faster than `0x3B`, that is the improvement claim — state the before and after.
- If `0x3B` was already near the ceiling, say so. "Here is the measured safe operating margin, previously undocumented" is a legitimate finding; it just makes this a robustness result rather than a speed one.
- Run the fastest passing setting **three times** before believing it. A marginal clock fails intermittently, which is exactly what issue #2 predicted.

---

## Step 4 — The generated wrapper, end to end (15 min)

Proves `new_lab.py`'s output actually synthesises and works — so far it has only been checked against hand-written wrappers on paper.

```
python scripts\new_lab.py examples\alu\ALU.vhd --patch-toplevel
.\scripts\build.bat examples\alu
.\scripts\program.bat
python host\scanchain.py -t examples\alu\TRACEFILE.txt -o alu.txt
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
python scripts\new_lab.py examples\seq1011\Seq1011.vhd --patch-toplevel
.\scripts\build.bat examples\seq1011
.\scripts\program.bat
python host\scanchain.py -t examples\seq1011\TRACEFILE.txt -o seq.txt
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
