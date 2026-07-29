# Example: ALU — exhaustive combinational test

A 4-bit ALU, purely combinational. Included as the **combinational** counterpart to `seq1011`, and because its whole input space is only 256 vectors — so this example is genuinely exhaustive. Nothing is sampled and there is no seed.

That is the case this harness is best at. 256 vectors by hand is not going to happen; over JTAG it takes about a second.

## Interface

```
input_vector(7 downto 4) = A
input_vector(3 downto 0) = B
output_vector(5 downto 0) = Y
```

Set in `hdl/TopLevel.vhd`:

```vhdl
constant number_of_inputs  : integer := 8;
constant number_of_outputs : integer := 6;
```

Note there is no clock and no reset — `new_lab.py` detected neither and laid the ports out in declaration order, first-declared in the high bits.

## The operation

Selected by the top bit of each operand:

| A(3) | B(3) | Operation |
|---|---|---|
| 0 | 0 | `MAX` — the larger operand, or `0000` if equal |
| 1 | 0 | `AND` |
| 0 | 1 | `ROTATE` by `B(1 downto 0)` |
| 1 | 1 | `EQUATE` — A if A = B, else `0000` |

Two quirks worth knowing, since they look like bugs in a test report but are what the design says:

- **`MAX` returns `0000` when the operands are equal**, not the operand value.
- **`Y(5 downto 4)` is never written** by any branch, so the top two bits are always `00`. The output is declared 6 bits wide but only 4 carry information.

`ROTATOR` also contains dead code: the branch is only reached when `B(3) = '1'`, and the function then tests `B(3)` again to pick a direction — so the rotate-left arm is unreachable and every rotation is a rotate right.

## Generating

```
python3 examples/alu/gen_tracefile.py
```

## Verification status

The tracefile is cross-checked against a transcription of `ALU.vhd`'s four functions, read from the VHDL rather than from the generator's model: **256 vectors, 0 mismatches**.

The `DUT.vhd` wrapper here was **generated** by `scripts/new_lab.py`, not hand-written.

Neither the ALU nor its wrapper has been through a VHDL toolchain or run on hardware.

## Provenance

This is the entity that arrived as `FSM.vhd` — a filename that did not match its contents, and a design unrelated to the `DUT.vhd` sitting beside it. It was renamed and kept as a worked example rather than deleted.

## Run

```
python3 scripts/new_lab.py examples/alu/ALU.vhd --patch-toplevel
vivado -mode batch -source scripts/build.tcl -tclargs examples/alu
vivado -mode batch -source scripts/program.tcl
python host/scanchain.py -t examples/alu/TRACEFILE.txt -o output.txt
```
