# Porting the Scan Chain from MAX 10 to Artix-7

The MAX 10 flow and this one are the same architecture. The FTDI MPSSE layer, the DR-scan structure, the tracefile format and the comparison logic are unchanged. What differs is the vendor JTAG primitive, the instruction register, and the programming step.

## Summary of changes

| Area | MAX 10 (Intel/Altera) | Artix-7 (Xilinx) |
|---|---|---|
| JTAG access | Virtual JTAG IP (`v_jtag`), a generated megafunction with ~30 ports | `BSCANE2` primitive, 10 ports, instantiated directly |
| Wrapper needed | `v_jtag.vhdl` wrapper around the IP | None — the primitive drops straight into `TopLevel` |
| Instruction register | 10 bits | **6 bits** |
| User instruction | `USER1 = 0x0E`, `USER0 = 0x0C` (two-instruction sequence) | **`USER1 = 0x02`** (single instruction) |
| Instruction selection | Virtual IR inside the IP | `JTAG_CHAIN` generic: `1` = USER1, `2` = USER2, `3`/`4` = USER3/4 |
| Clock divider | `\x86\x02\x00` | `\x86\x3B\x00` (100 kHz, 20x slower) |
| Startup check | none | 32-bit IDCODE read before testing |
| Programming | UrJTAG + pre-built `.svf` | Vivado Hardware Manager (`.bit`) |
| Host script | `scan_vjtag.py` | `scan_bscane2.py` |

## 1. Primitive substitution

Altera's Virtual JTAG exposes decoded TAP states as separate `virtual_state_*` signals. Xilinx's `BSCANE2` exposes them as plain named outputs. The correspondence is direct:

| `v_jtag` port | `BSCANE2` port |
|---|---|
| `tck_clk` | `TCK` |
| `virtual_jtag_tdi` | `TDI` |
| `virtual_jtag_tdo` | `TDO` |
| `virtual_jtag_virtual_state_cdr` | `CAPTURE` |
| `virtual_jtag_virtual_state_sdr` | `SHIFT` |
| `virtual_jtag_virtual_state_udr` | `UPDATE` |
| `virtual_jtag_tms` | *(not exposed; not needed)* |
| everything else | tie `'0'` or leave `open` |

Because the mapping is one-to-one, the original plan of writing a `v_jtag.vhdl` shim with the Altera port names was unnecessary. `BSCANE2` is instantiated directly in `TopLevel.vhd` and the surrounding scan logic is untouched.

One real difference: `BSCANE2` also provides `RESET` and `SEL`, which Virtual JTAG does not expose the same way. **Use them** — they are the fix for the phase-desync bug (Known Issues #1). The current code leaves both `open`, which is a missed opportunity rather than a port-mapping requirement.

## 2. Instruction register

MAX 10's IR is 10 bits and the Virtual JTAG flow needs two instructions: `USER1` to select the virtual IR, then `USER0` to access the virtual DR.

Artix-7's IR is 6 bits and `BSCANE2` needs one instruction. Loading `USER1 = 0x02` places the primitive's DR directly in the scan path. The host code shortens accordingly:

```python
dev.write(b"\x4B\x03\x03")  # -> Shift-IR
dev.write(b"\x1B\x04\x02")  # 5 bits of USER1
dev.write(b"\x4B\x00\x01")  # 6th bit + Exit1-IR
```

`0x1B 0x04 0x02` clocks out 5 bits (`length-1 = 4`) of value `0x02`; the sixth is clocked by the TMS command that leaves the state.

Authoritative IR codes come from the BSDL file for your exact part (`xc7a35tftg256`). Standard 7-series values: `IDCODE = 0x09`, `USER1 = 0x02`, `USER2 = 0x03`, `BYPASS = 0x3F`.

## 3. Clock rate

The MAX 10 divider was `0x02`; the Artix-7 code uses `0x3B` (59 → 100 kHz; the frequency formula in this project was 5x too high until 2026-07-31 — see RESULTS.md §5C). The accompanying comment still reads *"Reduce clock frequency for MAX 10 due to pin sharing with JTAG"*, which is copy-paste residue — pin sharing is not the reason here.

The slow rate has not been justified by measurement. Given that TDO is currently launched and sampled on the same edge (Known Issues #2), the low rate may well be what's hiding that race. Fix the edge first, then sweep the divider and record the real limit.

## 4. Programming

MAX 10 shipped a pre-built `scan-25k.svf` that UrJTAG could push to the board with no vendor tools installed. There is no equivalent here yet — you need Vivado.

Two options for restoring that convenience:

- Commit a `TopLevel.bit` per example and program with `scripts/program.tcl` (still needs Vivado, but no GUI).
- Use `openFPGALoader`, which programs 7-series parts from a `.bit` with no Xilinx tools at all. This is the closer analogue to the SVF flow and is roadmap Phase 5.

## 5. Constraints

MAX 10 used a `.qsf`; Artix-7 uses `.xdc`. Since `TopLevel` has no ports, the correct XDC is **empty**. The current file constrains a `state_out` port that no longer exists and downgrades the `UCIO-1` DRC to a warning to work around it — both lines should go.

## 6. What did not change

Worth stating explicitly, because it's most of the code:

- The entire FTDI MPSSE bit-banging layer
- The two-phase DR-scan protocol and the `io` phase bit
- The split-the-MSB-off trick for the last bit in Shift-DR
- The 61440-byte batching strategy
- Tracefile format and bit ordering
- Response decode and byte-reversal logic
- The `Success` / `Failure` output format

The main loop of `scan_bscane2.py` is effectively identical to `scan_vjtag.py`. All the differences live in the first ~30 lines.
