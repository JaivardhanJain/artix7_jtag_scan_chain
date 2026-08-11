# Known Issues

Ordered by severity. Issues 1 and 2 can produce results that look fine but aren't.

---

## 1. `io` phase bit has no reset path — silent, permanent desync

**Severity: high.** Can invalidate an entire run with no visible error.

> **STATUS: FIXED — demonstrated on hardware by controlled A/B.**
>
> Two bitstreams differing only in whether `RESET`/`SEL` reach `scan_core`, both given the same injected fault (`--abort-after-input`, which leaves the phase bit inverted). **Fixed build: 44/44, byte-identical to baseline. Pre-fix build: 3 failures, and it stays broken until reprogrammed.** See [RESULTS.md](RESULTS.md) §5B.
>
> **The defect is quieter than originally argued.** The desynced design returns a constant `0`, and only 3 of the 46 vectors expect a `1` — so **41 of 44 unmasked vectors still report `Success`**, a 93% pass rate on a completely broken harness. The visible failures are the detections, which is exactly what a DUT that never asserts its output looks like.
>
> **It may have happened for real, before this project started.** `results/passthrough_4096_output1.txt` — inherited with the original files, and recorded here as a clean duplicate run until 2026-08-11 — is a **captured stuck-at-0 failure**: TDO returned `00000000` on all 4096 vectors, and the 510 `Success` lines are exactly the 510 vectors whose correct answer is `00000000`. That is this defect's signature. It is not proof (a capture cannot separate a desync from a DUT tied low), but the failure mode argued for here was evidently occurring on that bench. See [RESULTS.md §1.1](RESULTS.md).
>
> Earlier detail: `BSCANE2.RESET` and `SEL` are wired into `scan_core`, which clears `io` asynchronously in Test-Logic-Reset and synchronously when the DR is deselected. Confirmed by tb_scan_core tests 2 and 3 under Vivado xsim 2020.2 — recovery works via both paths. **Also confirmed in the synthesised netlist: `io` maps to the design's only `FDCE` (flip-flop with asynchronous clear) among 23 plain `FDRE`s, so the reset path survived into hardware primitives.** Remaining bench test: interrupt a run, rerun **without reprogramming**, expect a full pass. Description below is of the original defect.

`io` selects input phase vs output phase and inverts on every Update-DR. It is initialised only by its signal declaration:

```vhdl
signal io : std_logic := '0';
```

which takes effect at FPGA configuration and never again. `BSCANE2`'s `RESET` and `SEL` outputs are both left `open`.

**Failure mode.** If the host script is Ctrl-C'd, crashes, or drops a USB transfer between the two DR scans of a vector, the FPGA has advanced `io` an odd number of times relative to the host's expectation. From then on the host shifts input vectors during what the FPGA believes is an output phase. Every subsequent comparison is garbage — and there is no error, just failures, or worse, coincidental passes. The only recovery is reprogramming the FPGA.

**Fix.** Drive `io` from the TAP reset. Connect `BSCANE2.RESET` (asserted in Test-Logic-Reset) and clear the phase:

```vhdl
signal jtag_reset : std_logic;
signal sel        : std_logic;
...
  RESET => jtag_reset,
  SEL   => sel,
...
if rising_edge(tck) then
  if jtag_reset = '1' or sel = '0' then
    io <= '0';
  elsif udr = '1' then
    ...
```

Then have the host issue a TAP reset at the start of every run — it already does this before the IDCODE read, so with the HDL fix every invocation self-synchronises. Using `SEL` as well means the phase also resets whenever the TAP leaves the USER1 instruction.

---

## 2. ~~TDO launched and sampled on the same clock edge~~ — NOT A DEFECT

> **STATUS: unproven in both directions. Reverted to the original combinational assignment.**
>
> This entry has been wrong twice and the correction matters more than the conclusion.
>
> **First** it claimed the combinational assignment was a defect. **Then**, when the first hardware run showed TDO stuck at 1, it claimed the falling-edge register was the cause and that the original was vindicated.
>
> **That second claim was also unfounded.** The stuck-at-1 was caused by a bug in `host/scanchain.py` — `encode_ir` sent TMS=0 instead of TMS=1 when leaving Shift-IR, so USER1 was never latched and the user data register was never in the scan path. That fully explains the symptom, and it means the falling-edge register was **never actually tested against a working host**. The evidence used to withdraw this issue was contaminated by an unrelated defect.
>
> **Where that leaves it.** There is no evidence the falling-edge register is harmful, and no evidence the original assignment is defective. The combinational version is retained because it is the configuration with 46/46 and one clean 4096/4096 sweep behind it — a "don't change what has hardware evidence" argument, not a demonstration.
>
> **This is now cheaply testable.** With the host fixed, reinstating the falling-edge register, rebuilding and rerunning would settle it in one cycle. Until someone does, treat the original 1149.1 analysis below as an open question rather than either a defect or a debunked one.
>
> **What simulation genuinely cannot tell you here.** `tb_scan_core` and `model_scan_core.py` both stand in for `BSCANE2`, so neither can distinguish a combinational `tdo` from a registered one — both produce the same value where they sample. Whatever the answer turns out to be, simulation will not provide it.
>
> **Update 2026-07-31 — a bound exists now, and it is too loose to decide anything.** The divider sweep ran the combinational version at every setting down to the fastest available, 3 repeats each: **all passed**, including 3×256 vectors at a 167 ns TCK period. So the launch-to-sample path settles in well under 83 ns. That is the first timing evidence this design has ever had — Vivado never analysed it (see RESULTS.md §4.2).
>
> It does not settle the issue, for two reasons. The sweep never found a failure, so it located the top of the FTDI's range rather than the top of the design's margin. And the frequency turned out to be 5x lower than believed — **6 MHz, not 30 MHz** — which is roughly where the 1149.1 argument below would expect the combinational version to be fine anyway.
>
> **The deciding experiment.** The driver sends MPSSE `0x8B`, which *enables* the divide-by-5 prescaler, while the comment claims it disables it. Sending `0x8A` instead raises the ceiling to 30 MHz — five times faster than anything tested — and this issue predicts the combinational `tdo` is precisely what fails first. Re-sweep with `0x8A`; if a divider fails, that is the answer, measured. See RESULTS.md §5C.

`tdo <= datau(0)` is combinational, and `datau` is registered on the **rising** edge of TCK. The host reads with MPSSE opcodes `0x2C` and `0x2E`, both of which sample TDO on the **rising** edge. So the FPGA changes TDO on the same edge the host latches it.

IEEE 1149.1 requires TDO to change on the falling edge of TCK precisely to avoid this. It survives today because the clock divider (`\x86\x3B\x00`, **100 kHz** — not 500 kHz; see the update above) leaves enough slack that the FTDI's sample point lands after the FPGA's output has settled.

**Fix — either side works, don't do both:**

- *FPGA side (preferred, spec-compliant):* register TDO on the falling edge of TCK.

  ```vhdl
  tdo_reg : process(tck)
  begin
    if falling_edge(tck) then
      tdo <= datau(0);
    end if;
  end process;
  ```

- *Host side:* switch reads to the negative-edge opcodes `0x2D` / `0x2F`.

**Then measure.** `scripts/sweep_divider.py` does this. Divider `n` gives `6 MHz / (n+1)` as the driver is currently configured, so `0x3B` = 59 → 100 kHz. (This originally read `30 MHz / (n+1)` → 500 kHz. That was wrong by 5x — the prescaler is enabled, not disabled.) Measured 2026-07-31: every divider passes, 17.3x throughput at `0x00`, no ceiling found.

---

## 3. Mask column parsed but never applied

**Severity: medium.** Produces false failures on legitimate don't-cares.

> **STATUS: FIXED — confirmed on hardware.** Mask applied per bit; `x`/`-` don't-cares supported and folded into the mask. Fully masked vectors report `Skipped`. **Confirmed on the board 2026-07-31:** the two `mask = 0` vectors in the bundled tracefile report `Skipped`, where the original reported them `Success` — the only two lines differing from the pre-change capture, exactly as predicted in advance. Description below is of the original defect.

```python
maskbits = lineContent[2]    # assigned, never read again
```

The tracefile's third column is intended to mark which output bits matter. It's extracted and dropped, so the comparison is always a full exact match:

```python
if read_str == expectedData_List[k]:
```

Any output bit that is legitimately unknown — a registered output during a reset vector, an uninitialised state machine on the first cycle — is compared as a hard value and reported as `Failure`. Note that the bundled `TRACEFILE.txt` has `mask = 0` on its first two lines, i.e. those two vectors are *meant* to be skipped and currently are not.

**Fix.** Apply the mask per bit before comparing, and support `x`/`-` characters in the expected column.

**Related fragility:** `lineContent[2]` raises a bare `IndexError` on any line with fewer than three columns. There is no line-number context in the traceback.

---

## 4. Read parser depends on variables leaking from the write loop

**Severity: medium.** Mis-parses instead of erroring.

> **STATUS: FIXED — offline-tested, hardware-exercised.** Widths are fixed by the first vector, validated on every line with the offending line number, and passed explicitly into the decoder. Covered by `test_rejects_ragged_*` and `test_decode_consumes_exactly_the_read_bytes`, and exercised end to end by the passing 46-vector run. Description below is of the original defect.

The response-decoding loop reads `outputLen`, `no_of_bytes` and `no_of_bits`, none of which it computes — they hold whatever the final iteration of the *write* loop left behind. This is correct only while every vector in the file has identical input and output widths.

A tracefile with a ragged line silently decodes at the wrong width and reports plausible-looking wrong values. There is no width validation on load.

**Fix.** Determine widths once when the tracefile is parsed, assert that every line matches, and pass the widths explicitly into the decoder.

---

## 5. `StringDetector.vhd` is missing from the repository

**Severity: was blocking for that example.**

> **STATUS: resolved.** The sources were recovered from the original MAX 10 lab material and verified — replaying all 46 tracefile vectors through a model of the recovered FSMs reproduces the expected column exactly (0 mismatches on the 44 unmasked vectors). They are installed locally but **gitignored**, being filled-in coursework solutions; `examples/seq1011` was added as a complete, publishable substitute so a fresh clone still has a working example. Description below is of the original state.

`examples/string_detector/DUT.vhd` instantiates:

```vhdl
component StringDetector is
    port(inp : in std_logic_vector(4 downto 0);
         reset, clock : in std_logic;
         outp : out std_logic);
end component;
```

No such file exists anywhere in the project. `examples/alu/ALU.vhd` is an unrelated leftover (a 4-bit ALU, formerly `FSM.vhd`) and does not provide it. The example will not elaborate until the file is recovered from the original lab or rewritten from the spec.

---

## 6. Vivado project hygiene

**Severity: blocking for reproducibility.**

- The original `Artix7test.xpr` listed `DUT.vhd`, `FSM.vhd` and `constraints.xdc` — **`Toplevel.vhd` was not in the source list at all.** Synthesis could not have used the file that is the actual top level.
- Two parallel projects existed for different parts: `Artix7test` (**xc7a35tftg256**) and `Artix7test_2020` (**xc7a15tftg256**). Unclear which matches the physical board.
- Both are now under the untracked `vivado/` directory. The fix is to stop committing project state entirely and generate it from `scripts/build.tcl`.

> **STATUS: RESOLVED.** Project state is no longer committed; `scripts/build.tcl` generates it and verifies the source count after adding. **The part question is settled: the board is an `xc7a35t`** — Vivado enumerates it as `xc7a35t_0` and the TAP reports IDCODE `0x0362D093`, agreeing with `build.tcl`'s default.

---

## 7. Vestigial constraints file

**Severity: low, but it hides future errors.**

> **STATUS: resolved and confirmed.** `hdl/constraints.xdc` no longer constrains anything — a portless top level needs no I/O constraints. Both the dead `state_out` assignment and the `UCIO-1` DRC downgrade are gone. **Confirmed by a full build (Vivado 2020.2): `DRC finished with 0 Errors` and no `UCIO-1` message at all, with the check no longer suppressed.** The file now also sets `CFGBVS`/`CONFIG_VOLTAGE` to silence a legitimate device-property warning, and documents an optional `create_clock` on TCK. Description below is of the original state.

`hdl/constraints.xdc` contains exactly two lines:

```tcl
set_property IOSTANDARD LVCMOS33 [get_ports state_out[*]]
set_property SEVERITY Warning [get_drc_checks UCIO-1]
```

Both are dead. `state_out` was a debug port that is now commented out in `TopLevel.vhd`, so `get_ports state_out[*]` matches nothing. The `UCIO-1` downgrade existed to suppress the unconstrained-I/O DRC error that port used to cause.

`TopLevel` has no ports at all, so the correct XDC is **empty** — no I/O constraints and no DRC suppression. Leaving `UCIO-1` downgraded is the real problem: it will silently hide genuine unconstrained-port errors in any DUT added later.

---

## 8. Host script hygiene

**Severity: low each, but they add up.**

> **STATUS: FIXED — hardware-exercised.** argparse CLI; actionable FTDI-open and IDCODE-mismatch errors; `MAX_WRITE_CHUNK` named; pass/fail/throughput summary; non-zero exit on failure; dead imports and the stale MAX 10 comment removed. The IDCODE is now decoded and the part named (`0x0362D093 (xc7a35t)`), which also settles #6. Table below describes the original.

| Item | Detail |
|---|---|
| Stale comment | `#Reduce clock frequency for MAX 10 due to pin sharing with JTAG` — copy-paste residue from the Altera version. |
| No error handling | `dev = ftd.open(0)` raises a raw `ftd2xx` traceback if no board is attached. |
| IDCODE unvalidated | Read and printed, never checked. A wrong or unresponsive board is not detected. |
| Hardcoded channel | `ftd.open(0)` — channel A only, not configurable. |
| Magic number | `61440` appears twice with no named constant or explanation. |
| No summary | 4096 lines of `Success`/`Failure` with no counts. You must grep to know if the run passed. |
| No exit code | Always exits 0, so it cannot gate a script or CI job. |
| CRLF tracefiles | `TRACEFILE.txt` has CRLF endings and inconsistent trailing spaces; `split(' ')` tolerates it by luck. A `.gitattributes` now normalises this, but the parser should be robust regardless. |
| Unused imports | `time`, `math`, `bitstring` are imported and never used. |

---

## 9. Missing: any way to test without hardware

> **STATUS: resolved.** The scan logic lives in `hdl/scan_core.vhd` (no vendor primitives) and `sim/tb_scan_core.vhd` exercises it — exhaustive scan, desync recovery via reset and via deselect, and a bit-order sweep. Verified under Vivado xsim 2020.2: **259 checks, 0 errors**, in about 8 seconds. `sim/model_scan_core.py` runs the same sequence with no toolchain at all and agrees, including on the 192/256 bit-order figure.

There is no testbench. Every change to the scan logic or a tracefile requires a full synthesis, implementation, bitstream and program cycle before you learn whether the bit ordering was right.

A behavioural testbench that drives the CAPTURE/SHIFT/UPDATE handshake directly against the real `TopLevel` would turn a 10-minute hardware round-trip into a few seconds of simulation. This is roadmap Phase 5 and is the single highest-value addition to the project.
