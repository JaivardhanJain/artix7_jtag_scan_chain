# Tracefile Format

A tracefile is the test vector set. One vector per line, three space-separated columns, no header.

```
<input_bits> <expected_output_bits> <mask>
```

Example (`examples/string_detector/TRACEFILE.txt`):

```
0000010 0 0
0000011 0 0
0001000 0 1
0001001 0 1
1001000 0 1
```

## Columns

| Column | Meaning |
|---|---|
| 1 | Input vector. One `0`/`1` per bit of `input_vector`, width must equal `number_of_inputs`. |
| 2 | Expected output. One `0`/`1` per bit of `output_vector`, width must equal `number_of_outputs`. |
| 3 | Mask. `1` = compare this vector, `0` = ignore the result. **Currently parsed and discarded — see Known Issues #3.** |

## Bit ordering

**MSB-first as written.** The leftmost character maps to the highest index of the vector:

```
input line:      1 0 0 1 0 0 0
                 │ │ │ │ │ │ └── input_vector(0)
                 │ │ │ │ │ └──── input_vector(1)
                 │ │ │ │ └────── input_vector(2)
                 │ │ │ └──────── input_vector(3)
                 │ │ └────────── input_vector(4)
                 │ └──────────── input_vector(5)
                 └────────────── input_vector(6)
```

The host script splits the MSB off and shifts it last, because in Shift-DR the final bit must be clocked at the same time TMS rises to leave the state. On the FPGA side the register shifts LSB-first (`data <= tdi & data(N-1 downto 1)`), so the two conventions meet correctly at the end of the scan. If your results come back bit-reversed, this is where to look.

## Mapping bits to your design

The mapping is defined entirely by your DUT wrapper. For the string detector:

```vhdl
-- input_vector(6 downto 2) = inp   (5-bit character)
-- input_vector(1)          = reset
-- input_vector(0)          = clock
-- output_vector(0)         = outp
```

So `0001000` means `inp = "00010"`, `reset = '0'`, `clock = '0'`, and the next line `0001001` is the same input with `clock = '1'`.

**Always document the mapping in a comment at the top of your DUT wrapper.** It is not recoverable from the tracefile alone, and getting it wrong produces a run where everything fails for no visible reason.

## Clocked designs

The harness is combinational by nature — one input vector in, one output vector out. A sequential DUT is tested by exposing its clock as an input bit and writing vector pairs that toggle it:

```
0001000 0 1     <- clock = 0, inputs set up
0001001 0 1     <- clock = 1, edge occurs, output sampled
```

Each pair is one clock cycle. Note that the output is captured after the rising-edge vector, so it reflects the state *after* the edge. A reset vector looks like:

```
0111000 1 1     <- reset = 1
0111001 0 1
```

## Formatting rules

- Exactly one space between columns. The parser uses `split(' ')`, so multiple consecutive spaces create empty fields.
- Trailing whitespace is tolerated but inconsistent in the bundled file — don't rely on it.
- Line endings: **LF**. The repo's `.gitattributes` normalises these on checkout. The original file was CRLF and worked only incidentally.
- Every line must have the same input width and the same output width. Ragged files are not detected and will mis-parse — see Known Issues #4.

## Generating tracefiles

For anything past a few dozen vectors, generate the file rather than typing it. Exhaustive test of a 4-bit + 4-bit combinational DUT:

```python
with open("TRACEFILE.txt", "w") as f:
    for a in range(16):
        for b in range(16):
            inp = f"{a:04b}{b:04b}"
            exp = f"{expected_model(a, b):06b}"   # your golden model
            f.write(f"{inp} {exp} 1\n")
```

The bundled `results/passthrough_4096_out.txt` is exactly this kind of exhaustive sweep — 4096 vectors of a 12-bit input against an 8-bit output, all passing. It is the evidence that the protocol and batching work at scale.

## Output file

The script writes one line per vector:

```
<input_bits> <bits_read_back> <Success|Failure>
```

```
0000010 0 Success
0001000 0 Success
```

There is currently no summary line and no non-zero exit code on failure — see Known Issues #8.
