# Architecture

## 1. The problem

A DUT with 7 inputs and 1 output needs 8 board pins to test by hand. A 4096-vector regression needs 4096 manual toggles. Neither scales.

Every Xilinx 7-series FPGA already has a JTAG TAP controller wired to the USB programming interface. The `BSCANE2` primitive exposes that TAP's user data registers to your own logic. So the DUT can be reached over the same cable used to program it, consuming zero board I/O.

## 2. FPGA side — `hdl/TopLevel.vhd`

`TopLevel` has **no ports at all**. Everything enters and leaves through JTAG.

### BSCANE2

```vhdl
bscan_inst : BSCANE2
  generic map ( JTAG_CHAIN => 1 )   -- USER1 instruction
  port map (
    TCK => tck, TDI => tdi, TDO => tdo,
    SHIFT => sdr, CAPTURE => cdr, UPDATE => udr,
    RESET => open, RUNTEST => open, DRCK => open, SEL => open );
```

`JTAG_CHAIN => 1` binds this instance to the **USER1** instruction. When the host loads USER1 into the 6-bit instruction register, this primitive's data register is placed between TDI and TDO.

Signal meanings:

| Signal | Direction (from user logic's view) | Meaning |
|---|---|---|
| `TCK` | in | JTAG test clock, driven by the host |
| `TDI` | in | serial data from host |
| `TDO` | out | serial data to host — **combinational or falling-edge only** |
| `CAPTURE` | in | high during TAP state Capture-DR |
| `SHIFT` | in | high during TAP state Shift-DR |
| `UPDATE` | in | one-cycle pulse in TAP state Update-DR |
| `RESET` | in | high in Test-Logic-Reset — **currently unused, see Known Issues #1** |
| `SEL` | in | high while USER1 is the active instruction |

### The scan register and the `io` phase bit

There is one shift path but two things to move: inputs going in, outputs coming out. Rather than build two separate data registers, the design multiplexes them in time using a single-bit state variable, `io`:

- `io = '0'` → **input phase**. Shifting fills `data`. Update-DR latches `data` into `dut_input`.
- `io = '1'` → **output phase**. Capture-DR loads `dut_output` into `datau`. Shifting streams it out on TDO.

`io` inverts on every Update-DR, so the host and the FPGA alternate phases in lockstep. **This lockstep is the design's one fragile assumption** — see Known Issues #1.

```vhdl
shift_reg : process(tck)
begin
  if rising_edge(tck) then
    if udr = '1' then                 -- Update-DR
      io <= not io;
      if io = '0' then
        dut_input <= data;            -- present new inputs
      end if;
    elsif cdr = '1' then              -- Capture-DR
      if io = '1' then
        datau <= dut_output;          -- sample DUT response
      end if;
    elsif sdr = '1' then              -- Shift-DR
      if io = '0' then
        data  <= tdi & data(number_of_inputs-1 downto 1);   -- LSB-first out, MSB-first in
      else
        datau <= '0' & datau(number_of_outputs-1 downto 1);
      end if;
    end if;
  end if;
end process;

tdo <= datau(0);
```

The `if / elsif / elsif` chain is correct, not a bug: Update-DR, Capture-DR and Shift-DR are mutually exclusive TAP states, so only one branch can ever be eligible in a given cycle. Priority ordering between them is irrelevant.

### Timing note

`tdo` is combinational from `datau(0)`, and `datau` is clocked on the **rising** edge of TCK. IEEE 1149.1 specifies that TDO changes on the falling edge of TCK so the host can sample it safely on the rising edge. The host currently reads on the rising edge too, which means launch and sample coincide. See Known Issues #2.

## 3. Host side — `host/scan_bscane2.py`

The host does not use Vivado's JTAG API. It talks to the FTDI chip directly in **MPSSE** mode and hand-builds JTAG state transitions. This is what makes the flow fast: hundreds of vectors are batched into a single USB transfer.

### Initialisation sequence

```python
dev.setBitMode(0, 0x02)     # MPSSE mode
dev.write(b"\x8B")          # disable /5 clock prescaler
dev.write(b"\x86\x3B\x00")  # clock divider -> ~500 kHz
dev.write(b"\x80\x00\x0B")  # set initial JTAG pin states/directions
```

Then a TAP reset, an **IDCODE** read to prove the board is alive, and finally the **USER1** instruction is loaded:

```python
dev.write(b"\x4B\x05\x3F")  # 6 TMS=1 clocks -> Test-Logic-Reset
dev.write(b"\x4B\x03\x03")  # -> Shift-IR
dev.write(b"\x1B\x04\x02")  # shift 5 bits of USER1 (0x02)
dev.write(b"\x4B\x00\x01")  # last bit + Exit1-IR
```

Artix-7 has a **6-bit** IR; USER1 is `0x02`. (MAX 10 had a 10-bit IR with different codes.)

### MPSSE opcodes used

| Opcode | Meaning |
|---|---|
| `0x4B` | Clock out TMS bits, no read — used for all state transitions |
| `0x1B` | Clock out data bits (LSB first, −ve edge), no read |
| `0x19` | Clock out data bytes, no read |
| `0x2C` / `0x2E` | Clock in data bytes / bits (+ve edge) |
| `0x6B` | Clock out TMS and read TDO simultaneously — captures the final bit |
| `0x20` | Read bytes, used for the 32-bit IDCODE |

### Per-vector command stream

For each tracefile line the script appends to one big buffer:

1. `0x4B 0x02 0x01` — Run-Test/Idle → Shift-DR
2. all input bits except the MSB, via `0x1B` (bits) or `0x19` (bytes)
3. `0x4B 0x02 (msb<<7)|0x03` — last input bit *while* leaving Shift-DR, so the MSB and the state change share a clock
4. `0x4B 0x02 0x01` — back into Shift-DR for the output phase
5. `0x2C` / `0x2E` reads for the output bits
6. `0x6B 0x02 0x03` — exit Shift-DR while reading the final output bit

That last-bit-with-TMS trick is why the code splits MSB from the rest everywhere. In Shift-DR the final bit must be clocked simultaneously with TMS going high, otherwise you shift one bit too many.

### Batching

Commands accumulate until `write_cmd` reaches **61440** bytes (a safe fraction of the FTDI transfer limit), then the whole block is written and the responses read back in one go. The outer `while exit != 1` loop repeats for tracefiles longer than one batch. This is where the throughput comes from — one USB round-trip per ~hundreds of vectors instead of per vector.

### Response decoding

Read bytes come back bit-reversed relative to how they were written, so decoding reassembles them MSB-last:

```python
read_bytes_str = "{0:08b}".format(int(usb_read_data[j:j+1].hex(),16)) + read_bytes_str
```

and the final bit — the one captured by `0x6B` — arrives in bit position 2 of its byte:

```python
lastBitStr = format(read_data, '08b')[2]
```

Decoded strings are compared against the expected column and each vector gets `Success` or `Failure`.

> The decode loop reuses `outputLen`, `no_of_bytes` and `no_of_bits` left over from the final iteration of the *write* loop. Correct only while all vectors share one width. See Known Issues #4.

## 4. Data flow for one vector

```
host: TMS -> Shift-DR
host: shift 7 input bits ────────► data
host: TMS -> Update-DR
                          fpga: io 0->1, dut_input <= data
                          fpga: DUT combinationally settles
host: TMS -> Capture-DR
                          fpga: datau <= dut_output
host: TMS -> Shift-DR
host: read 1 output bit  ◄──────── tdo = datau(0)
host: TMS -> Update-DR
                          fpga: io 1->0
host: compare against expected
```

## 5. Constraints

`hdl/constraints.xdc` currently contains only:

```tcl
set_property IOSTANDARD LVCMOS33 [get_ports state_out[*]]
set_property SEVERITY Warning [get_drc_checks UCIO-1]
```

Both lines are vestigial. `state_out` was a debug port that is now commented out in `TopLevel.vhd`, so `get_ports` matches nothing. The `UCIO-1` downgrade suppressed the unconstrained-I/O DRC error that the port used to cause. A top level with no ports needs **no** I/O constraints and no DRC suppression — this file should be empty. Roadmap Phase 1.
