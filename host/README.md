# Host driver

| File | Status |
|---|---|
| `scanchain.py` | Current driver. **Hardware-validated** — 44/44 unmasked vectors, parity with the pre-change capture. |
| `scan_bscane2.py` | The original, unchanged. Kept as the reference — it is what located the IR bug by bisection. |
| `test_scanchain.py` | 30 offline tests. No board required. |

```
python host/scanchain.py -t examples/string_detector/TRACEFILE.txt -o output.txt
python host/scanchain.py --dry-run -t examples/string_detector/TRACEFILE.txt
python3 host/test_scanchain.py
```

## Options

| Flag | Purpose |
|---|---|
| `-t, --tracefile` | Test vectors. Required. |
| `-o, --out` | Per-vector report (default `output.txt`). |
| `-c, --channel` | FTDI channel, 0 = A, 1 = B. |
| `-d, --divider` | Clock divider; TCK = 6 MHz / (n+1). Default `0x3B` = 100 kHz. `0x02` (2 MHz) is ~15x faster and passed 3/3 on hardware — see RESULTS.md §5C. |
| `--expect-idcode` | Abort unless the TAP reports this IDCODE. |
| `--dry-run` | Parse and validate the tracefile, then exit. No hardware. |

Exit status is 0 only if every unmasked vector passed, so it can gate a script.

## What changed from `scan_bscane2.py`

**The MPSSE encoding and decoding did not change — by design.** That code has 4096/4096 vectors of hardware evidence behind it, which is more than anything else in this project. `test_scanchain.py` re-implements the original algorithm verbatim and asserts the new code emits identical bytes for every width from 1 to 64 bits, and decodes identically. If those tests pass, the wire protocol is untouched.

What changed is everything around it:

| # | Was | Now |
|---|---|---|
| [#3](../docs/KNOWN_ISSUES.md) | `maskbits` parsed into a variable that was never read again — every vector compared as an exact match | Mask applied per bit. `x`/`-` in the expected column supported and folded into the mask. |
| [#4](../docs/KNOWN_ISSUES.md) | Decoder read widths left over from the last iteration of the *write* loop; ragged tracefiles mis-parsed silently | Widths fixed by the first vector, validated on every line, passed explicitly into the decoder. |
| [#8](../docs/KNOWN_ISSUES.md) | Positional `sys.argv`; raw `ftd2xx` traceback with no board; IDCODE printed but never checked; magic `61440`; no summary; always exit 0 | argparse; actionable errors; IDCODE validated; named constant; pass/fail/throughput summary; non-zero exit on failure. Dead imports and the stale "for MAX 10" comment gone. |

## One deliberate difference in the output file

Fully masked vectors are now reported `Skipped` rather than `Success`.

This means a diff against `results/string_detector_output.txt` will show **exactly two changed lines** — the first two vectors of the bundled tracefile, which carry `mask = 0`:

```
- 0000010 0 Success
- 0000011 0 Success
+ 0000010 0 Skipped
+ 0000011 0 Skipped
```

Those two lines are the visible proof that the mask fix works. Any *other* difference in that diff is a real regression and should be investigated before anything else.

## Structure

Everything above `class JtagDevice` is pure — no hardware, no I/O. That split is what makes the tests possible, and it is not incidental: parsing, encoding and decoding are exactly where the defects were, and they are now the parts that can be checked without a board.

## Testing

`python3 host/test_scanchain.py` (or under `pytest`). Six groups:

- **Equivalence with the original** — encoding, decoding and read-byte counts, across widths 1–64.
- **Read-count consistency** — the bytes the decoder consumes must equal the bytes the encoder told the device to send. A mismatch would desynchronise every later vector in the batch, silently.
- **Tracefile parsing** — CRLF, comments, optional mask column, and rejection of ragged widths with a line number in the message.
- **Mask handling** — whole-vector and per-bit masks, don't-cares.
- **IDCODE decoding** — pinned to bytes captured from a real board, whose part is known independently. See below.
- **Write types** — the encoders must return `bytes`; `ftd2xx` rejects a `bytearray` with an unhelpful `ctypes.ArgumentError`.

## Three bugs the hardware runs found

All three were in code paths the offline tests structurally could not reach — the boundary with the FTDI device. The third took two wrong diagnoses to find.

**`encode_ir` returned a `bytearray`.** `ftd2xx.write()` accepts `bytes` only and rejects anything else with a bare `ctypes.ArgumentError: argument 2: wrong type` — no mention of the type it wanted, or which call. Now returns `bytes`, with a test asserting it.

**The IDCODE decode applied one reversal instead of two.** Two are needed:

- FTDI's read commands shift each incoming bit in at the *MSB* end, so every byte arrives bit-reversed.
- The IDCODE shifts out LSB-first, so the first byte received is the least significant.

Doing only the second returned `0xC0460BC9` for a part whose IDCODE is `0x0362D093`. That is the dangerous kind of wrong — it looks like a number, not like an error. The original `scan_bscane2.py` sidestepped it by printing raw hex and leaving the reader to interpret, so the bug is new to this rewrite.

`test_decode_idcode_from_real_hardware` pins the fix to the actual bytes the board returned, cross-checked against the part Vivado independently reported. The driver now also names the part:

```
IDCODE: 0x0362D093  (xc7a35t)
```

**`encode_ir` sent TMS=0 instead of TMS=1 leaving Shift-IR.** The payload byte of a `0x4B` command is not a data value — bits 6..0 are TMS levels, bit 7 is TDI. I read it as a value, so for USER1 (`0x02`, top bit 0) it emitted `0x00`: TMS=0. The TAP stayed in Shift-IR, the instruction never latched, USER1 was never selected, and TDO read `1` on every vector.

Two things made this hard. The IDCODE read kept working, because it runs before `select_user1` and never touched the broken byte — so the board looked alive. And I had written the same misunderstanding into a test, asserting `out[8] == 0`; **a test written from the same wrong model as the code confirms the model, not the code.**

It was found by bisection: running the untouched `scan_bscane2.py` against the same bitstream. It passed 46/46, which located the bug in the host in one command. `encode_ir` is now pinned to the original's literal bytes, the way the other encoders always were.

What these tests do **not** cover: anything involving the FTDI device, the USB batching path, or whether the FPGA responds correctly. Those need hardware.
