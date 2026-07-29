# Known Issues

Ordered by severity. Issues 1 and 2 can produce results that look fine but aren't.

---

## 1. `io` phase bit has no reset path — silent, permanent desync

**Severity: high.** Can invalidate an entire run with no visible error.

> **STATUS: fixed, verified in simulation, pending hardware.** `BSCANE2.RESET` and `SEL` are wired into `scan_core`, which clears `io` asynchronously in Test-Logic-Reset and synchronously when the DR is deselected. Confirmed by tb_scan_core tests 2 and 3 under Vivado xsim 2020.2 — recovery works via both paths. Remaining bench test: interrupt a run, rerun **without reprogramming**, expect a full pass. Description below is of the original defect.

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

## 2. TDO launched and sampled on the same clock edge

**Severity: high.** Currently works, but by timing margin rather than by design.

> **STATUS: fixed, verified in simulation, pending hardware.** `tdo` is registered on the falling edge of `tck` in `scan_core`. The host was deliberately left on its rising-edge `0x2C`/`0x2E` reads — moving the launch edge does not shift the data, confirmed by tb_scan_core test 1 (256 vectors, 0 errors) under Vivado xsim 2020.2, which samples tdo exactly as an MPSSE read does. Real timing margin is still unmeasured: sweep the divider on hardware. Description below is of the original defect.

`tdo <= datau(0)` is combinational, and `datau` is registered on the **rising** edge of TCK. The host reads with MPSSE opcodes `0x2C` and `0x2E`, both of which sample TDO on the **rising** edge. So the FPGA changes TDO on the same edge the host latches it.

IEEE 1149.1 requires TDO to change on the falling edge of TCK precisely to avoid this. It survives today because the clock divider (`\x86\x3B\x00`, ~500 kHz) leaves enough slack that the FTDI's sample point lands after the FPGA's output has settled.

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

**Then measure.** After fixing, sweep the divider from `0x3B` downward and record the fastest reliable setting. Divider `n` gives `30 MHz / (n+1)`, so `0x3B` = 60 → 500 kHz. The safe maximum, and the resulting vectors/second, is a concrete result worth reporting.

---

## 3. Mask column parsed but never applied

**Severity: medium.** Produces false failures on legitimate don't-cares.

> **STATUS: fixed in `host/scanchain.py`, offline-tested.** Mask applied per bit; `x`/`-` don't-cares supported and folded into the mask. Fully masked vectors now report `Skipped`. Covered by `test_mask_*` and `test_dont_care_in_expected_column`. Description below is of the original defect.

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

> **STATUS: fixed in `host/scanchain.py`, offline-tested.** Widths are fixed by the first vector, validated on every line with the offending line number in the error, and passed explicitly into the decoder. Covered by `test_rejects_ragged_*` and `test_decode_consumes_exactly_the_read_bytes`. Description below is of the original defect.

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

---

## 7. Vestigial constraints file

**Severity: low, but it hides future errors.**

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

> **STATUS: fixed in `host/scanchain.py`.** argparse CLI; actionable FTDI-open and IDCODE-mismatch errors; `MAX_WRITE_CHUNK` named; pass/fail/throughput summary; non-zero exit on failure; dead imports and the stale MAX 10 comment removed. Table below describes the original.

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
