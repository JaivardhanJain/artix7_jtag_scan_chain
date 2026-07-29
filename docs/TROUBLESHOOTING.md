# Troubleshooting

## The script crashes immediately with an `ftd2xx` error

```
ftd2xx.ftd2xx.DeviceError: DEVICE_NOT_OPENED
```

The FTDI device isn't reachable. In order of likelihood:

1. **Vivado Hardware Manager still has the cable open.** Only one process can own the FTDI channel. Close the hardware target in Vivado (or close Vivado) before running the script.
2. **VCP driver is bound instead of D2XX.** On Windows the FTDI VCP driver claims the device as a COM port and `ftd2xx` can't open it. In Device Manager, find the interface, Properties → Advanced, and uncheck *Load VCP*. Then replug.
3. **Wrong channel.** `ftd.open(0)` opens channel A. Some boards expose JTAG on channel B — try `ftd.open(1)`.
4. **Board not powered or cable not seated.**

There is no friendly error message for this yet (Known Issues #8).

## IDCODE prints as all `f`s or all `0`s

```
IDCODE: ffffffff
IDCODE: 00000000
```

The TAP isn't responding. `ffffffff` usually means TDO is floating — the FTDI is talking but nothing is driving back. `00000000` means TDO is stuck low.

- Confirm the board is powered and configured.
- Confirm you're on the right FTDI channel.
- Check that the JTAG pin initialisation (`\x80\x00\x0B`) matches your board's FTDI pin assignment. This byte sets initial values and directions for TCK/TDI/TMS; a board with a different wiring needs a different value.

Expected values are part-specific — read them from the BSDL for your device. 7-series IDCODEs follow the pattern `0xnnnnn093`.

## IDCODE looks valid but every vector fails

Most likely one of three things:

1. **Phase desync.** If a previous run was interrupted, the FPGA's `io` bit is inverted relative to the host. This should no longer happen — `scan_core` now clears `io` on TAP reset, and the host issues one at startup (Known Issues #1). If it *does* happen, reprogram the FPGA to confirm, then check that `BSCANE2.RESET`/`SEL` are actually wired through to `scan_core` in your build and that you rebuilt after the fix.
2. **Width mismatch.** `number_of_inputs` / `number_of_outputs` in `TopLevel.vhd` don't match the tracefile's column widths. There's no check for this; it just shifts the wrong number of bits.
3. **`TopLevel` isn't actually the top.** Confirm Vivado's top module is `TopLevel` and that `TopLevel.vhd` is in the project's source list. The original `.xpr` did **not** include it (Known Issues #6).

## Every vector fails but the values look bit-reversed

Your DUT wrapper's bit mapping is inverted relative to the tracefile. The tracefile is MSB-first as written — leftmost character is the highest vector index. See [TRACEFILE_FORMAT.md](TRACEFILE_FORMAT.md).

## Results are intermittent — passes and failures vary run to run

This was the TDO edge race (Known Issues #2), now fixed by launching TDO on the falling edge of TCK. If you still see it, first confirm you rebuilt after the fix, then raise the clock divider (larger value = slower) to check whether it's timing-related at all:

```python
dev.write(b"\x86\x7F\x00")   # ~234 kHz
```

If slowing down fixes it on a post-fix build, the cause is elsewhere — signal integrity on the JTAG cable, or an FTDI channel shared with something else.

## Vivado: `[DRC UCIO-1] Unconstrained Logical Port`

The `state_out` debug port is enabled in `TopLevel.vhd` but has no pin assignment. Either leave it commented out (the default) or assign real pins in `constraints.xdc`.

Do **not** re-add `set_property SEVERITY Warning [get_drc_checks UCIO-1]`. Suppressing the check hides genuine unconstrained-port problems in any DUT you add later.

## Vivado: `Entity StringDetector is not bound`

`StringDetector.vhd` is not in this repository (Known Issues #5). Supply it, or use a different example.

## Only the first N vectors are tested

The batching threshold is 61440 command bytes. Beyond that the outer loop re-batches — if your run stops early, check that the loop is actually re-entering rather than a partial read returning short. `read_cmd` must exactly match the number of bytes the FPGA will return, or `dev.read()` blocks until it times out.

## A sequential DUT gives the right answer one vector late

Expected. The output is captured after the vector is applied, so a registered output reflects the state after that clock edge. Write your expected values accordingly, or add a leading padding vector. See the clocked-designs section of [TRACEFILE_FORMAT.md](TRACEFILE_FORMAT.md).

## How do I see what's actually on the wire?

The commented-out `state_out` port in `TopLevel.vhd` exists for this:

```vhdl
state_out <= sdr & cdr & udr & io & dut_output(number_of_outputs-1);
```

Uncomment it, add the port to the entity, assign five pins in `constraints.xdc`, and probe with a logic analyser. `io` is the one worth watching — if it isn't alternating cleanly with each vector, you have a desync.
