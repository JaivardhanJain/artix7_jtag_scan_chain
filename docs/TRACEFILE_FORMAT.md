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
| 3 | Mask. Optional. Either a single `1`/`0` (whole-vector enable) or one character per output bit (per-bit mask). Applied by `scanchain.py`; **ignored by the original `scan_bscane2.py` — see Known Issues #3.** |

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

`scanchain.py` is tolerant of formatting; the original `scan_bscane2.py` was not. Rules for the current parser:

- Any run of whitespace separates columns. (The old parser used `split(' ')`, so two spaces produced an empty field.)
- CRLF and trailing whitespace are handled. The bundled file has both, inconsistently.
- Blank lines are skipped; lines beginning with `#` are comments.
- The mask column is optional and defaults to `1`.
- Don't-care characters `x`, `X` and `-` are allowed in the expected-output column and are folded into the mask.
- **Every line must have the same input width and the same output width.** This is now enforced, with the offending line number in the error message. Previously ragged files were not detected and mis-parsed silently — Known Issues #4.

Validate a tracefile without a board attached:

```
python host/scanchain.py --dry-run -t path/to/TRACEFILE.txt
```

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
<input_bits> <bits_read_back> <Success|Failure|Skipped>
```

```
0000010 0 Skipped
0001000 0 Success
```

`Skipped` means the vector was fully masked. The original script had no such verdict — it reported masked vectors as `Success` — so a diff between old and new output shows exactly the masked lines changing.

`scanchain.py` also prints a summary and returns a non-zero exit status if any unmasked vector failed:

```
46 vectors: 44 passed, 0 failed, 2 skipped (masked)
0.31 s elapsed, 148 vectors/s
```
