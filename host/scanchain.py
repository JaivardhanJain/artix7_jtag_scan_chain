#!/usr/bin/env python3
"""
JTAG scan chain test driver for Xilinx 7-series FPGAs.

Shifts test vectors into a DUT through the FPGA's BSCANE2 user data register
and reads the responses back, over FTDI MPSSE. See docs/ARCHITECTURE.md.

    python host/scanchain.py -t examples/string_detector/TRACEFILE.txt -o out.txt

Original implementation by Anubhav Bhura, Wadhwani Electronics Laboratory,
IIT Bombay. This is a restructuring of that code: the MPSSE command encoding
and response decoding are preserved bit-for-bit, because they are the part that
4096/4096 vectors have already validated on hardware. What changed is around
them -- see "Changes from scan_bscane2.py" below.

Changes from scan_bscane2.py
----------------------------
KNOWN_ISSUES #3  The mask column is now applied. It was parsed into a variable
                 that was never read again, so don't-care outputs were compared
                 as hard values. 'x' and '-' in the expected column are also
                 honoured now.
KNOWN_ISSUES #4  Vector widths are computed once when the tracefile is parsed
                 and validated across every line. The old decoder read widths
                 that had leaked out of the final iteration of the write loop,
                 so a ragged tracefile mis-parsed silently instead of erroring.
KNOWN_ISSUES #8  argparse CLI; readable errors for a missing FTDI device and a
                 mismatched IDCODE; a pass/fail/throughput summary; non-zero
                 exit status on failure; named constants; dead imports and the
                 stale "for MAX 10" comment removed.

Structure: everything above `class JtagDevice` is pure -- no hardware, no I/O.
That is deliberate, so host/test_scanchain.py can test the parsing, encoding
and decoding without a board attached. Those are the parts where the bugs were.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# FTDI's write buffer is 64 KiB; 60 KiB leaves headroom for the final vector's
# commands to be appended without overrunning. Vectors are batched up to this
# many command bytes and flushed in one USB transfer -- which is what makes
# thousands of vectors take seconds rather than minutes.
MAX_WRITE_CHUNK = 61440

# MPSSE opcodes (see docs/ARCHITECTURE.md for how they compose into a scan)
CMD_CLOCK_TMS_NOREAD = 0x4B   # clock out TMS bits, no read -- state transitions
CMD_CLOCK_TMS_READ = 0x6B     # clock out TMS while reading TDO -- final bit
CMD_WRITE_BITS = 0x1B         # clock out data bits, LSB first, no read
CMD_WRITE_BYTES = 0x19        # clock out data bytes, no read
CMD_READ_BITS = 0x2E          # clock in data bits
CMD_READ_BYTES = 0x2C         # clock in data bytes
CMD_READ_BYTES_PE = 0x20      # read bytes, +ve edge -- used for IDCODE

# Artix-7 has a 6-bit instruction register.
IR_USER1 = 0x02
IR_IDCODE = 0x09

DEFAULT_DIVIDER = 0x3B        # 6 MHz / (0x3B + 1) = 100 kHz -- see __init__

DONT_CARE_CHARS = "xX-"


# ---------------------------------------------------------------------------
# Tracefile parsing
# ---------------------------------------------------------------------------

class TracefileError(Exception):
    """Raised with a line number so the user knows where to look."""


@dataclass
class Vector:
    line_no: int
    inputs: str      # MSB-first, as written in the file
    expected: str    # MSB-first; may contain don't-care characters
    mask: str        # per-bit '1'/'0', already expanded to output width


@dataclass
class Tracefile:
    vectors: List[Vector]
    input_width: int
    output_width: int


def _expand_mask(mask: str, output_width: int, line_no: int) -> str:
    """
    Normalise the mask column to one character per output bit.

    Two forms are accepted:
      '1' / '0'          a whole-vector enable, broadcast to every bit
      '1011' (n chars)   a per-bit mask, one character per output bit

    The original format used the single-character form; per-bit is a superset
    and costs nothing to support.
    """
    if len(mask) == 1:
        if mask not in "01":
            raise TracefileError(
                f"line {line_no}: mask must be '0' or '1', got {mask!r}")
        return mask * output_width
    if len(mask) != output_width:
        raise TracefileError(
            f"line {line_no}: mask is {len(mask)} bits but the output is "
            f"{output_width} bits; use a single '0'/'1' or one character per bit")
    bad = set(mask) - set("01")
    if bad:
        raise TracefileError(
            f"line {line_no}: mask contains {sorted(bad)}; expected only 0/1")
    return mask


def parse_tracefile(text: str) -> Tracefile:
    """
    Parse tracefile text into vectors, validating as we go.

    Tolerates CRLF, blank lines, '#' comments, and any run of whitespace
    between columns. The old parser used a bare `split(' ')` and indexed
    `[2]` without checking, so a two-column line raised a bare IndexError
    with no line number, and inconsistent widths were never detected at all.
    """
    vectors: List[Vector] = []
    input_width: Optional[int] = None
    output_width: Optional[int] = None
    first_line_no = 0

    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        if len(parts) < 2:
            raise TracefileError(
                f"line {line_no}: expected at least 2 columns "
                f"(input expected [mask]), got {len(parts)}: {raw!r}")
        if len(parts) > 3:
            raise TracefileError(
                f"line {line_no}: expected at most 3 columns, got {len(parts)}: "
                f"{raw!r}")

        inputs, expected = parts[0], parts[1]
        mask = parts[2] if len(parts) == 3 else "1"

        bad = set(inputs) - set("01")
        if bad:
            raise TracefileError(
                f"line {line_no}: input contains {sorted(bad)}; expected only 0/1")
        bad = set(expected) - set("01" + DONT_CARE_CHARS)
        if bad:
            raise TracefileError(
                f"line {line_no}: expected-output contains {sorted(bad)}; "
                f"allowed are 0, 1 and don't-care ({DONT_CARE_CHARS})")

        # KNOWN_ISSUES #4: widths are fixed by the first vector and every
        # later line must agree. The old code never checked, and the decoder
        # then reused whatever width the last write-loop iteration left behind.
        if input_width is None:
            input_width, output_width = len(inputs), len(expected)
            first_line_no = line_no
        else:
            if len(inputs) != input_width:
                raise TracefileError(
                    f"line {line_no}: input is {len(inputs)} bits but line "
                    f"{first_line_no} set the width to {input_width}")
            if len(expected) != output_width:
                raise TracefileError(
                    f"line {line_no}: expected-output is {len(expected)} bits "
                    f"but line {first_line_no} set the width to {output_width}")

        # Don't-care characters in the expected column are folded into the mask
        # so there is exactly one comparison mechanism downstream.
        bits = _expand_mask(mask, output_width, line_no)
        merged = "".join(
            "0" if e in DONT_CARE_CHARS else m for e, m in zip(expected, bits))
        cleaned = "".join("0" if c in DONT_CARE_CHARS else c for c in expected)

        vectors.append(Vector(line_no, inputs, cleaned, merged))

    if not vectors:
        raise TracefileError("tracefile contains no vectors")

    assert input_width is not None and output_width is not None
    return Tracefile(vectors, input_width, output_width)


def compare(got: str, expected: str, mask: str) -> bool:
    """Compare only the bits the mask enables. KNOWN_ISSUES #3."""
    if len(got) != len(expected):
        return False
    return all(g == e for g, e, m in zip(got, expected, mask) if m == "1")


# ---------------------------------------------------------------------------
# MPSSE command encoding -- preserved bit-for-bit from scan_bscane2.py
# ---------------------------------------------------------------------------

def split_bytes_bits(n: int) -> Tuple[int, int]:
    """
    Split a bit count into (whole bytes, remaining bits) the way the original
    code does, where the remainder is always at least 1 so the final bit can be
    clocked together with TMS on the way out of Shift-DR.

    n = 16 gives (1, 8), not (2, 0).
    """
    n_bytes = (n & ~7) >> 3
    n_bits = n & 7
    if n_bits == 0:
        n_bits += 8
        n_bytes -= 1
    return n_bytes, n_bits


def encode_input_scan(inputs: str) -> bytearray:
    """
    Build the MPSSE commands that shift one input vector through Shift-DR.

    `inputs` is MSB-first as written in the tracefile. The MSB is split off and
    clocked last, simultaneously with TMS rising to leave Shift-DR -- otherwise
    one bit too many gets shifted. Everything before it goes out LSB-first,
    which is the order scan_core expects.
    """
    out = bytearray()
    n = len(inputs)

    out += bytes([CMD_CLOCK_TMS_NOREAD, 0x02, 0x01])   # Idle -> Shift-DR

    if n == 1:
        last_bit = int(inputs[0], 2)
    elif n <= 9:
        out += bytes([CMD_WRITE_BITS, n - 2, int(inputs[1:n], 2)])
        last_bit = int(inputs[0], 2)
    else:
        n_bytes, n_bits = split_bytes_bits(n)
        minus_one = n_bytes - 1
        cmd = [CMD_WRITE_BYTES, minus_one & 0xFF, minus_one >> 8]
        j = n
        for _ in range(n_bytes):
            cmd.append(int(inputs[j - 8:j], 2))
            j -= 8
        out += bytes(cmd)
        if n_bits == 1:
            last_bit = int(inputs[0], 2)
        else:
            out += bytes([CMD_WRITE_BITS, n_bits - 2, int(inputs[1:n_bits], 2)])
            last_bit = int(inputs[0], 2)

    # Final bit clocked while TMS leaves Shift-DR
    out += bytes([CMD_CLOCK_TMS_NOREAD, 0x02, ((last_bit & 1) << 7) | 0x03])
    return out


def encode_output_scan(output_width: int) -> Tuple[bytearray, int]:
    """
    Build the commands that shift one response out, and return how many bytes
    the device will send back for them.

    The returned count must be exact: `dev.read()` blocks until it has that
    many bytes, so an over-count hangs until timeout and an under-count
    desynchronises every following vector.
    """
    out = bytearray()
    n = output_width
    n_read = 0

    out += bytes([CMD_CLOCK_TMS_NOREAD, 0x02, 0x01])   # Idle -> Shift-DR

    if n == 1:
        pass                                            # only the TMS read below
    elif n <= 9:
        out += bytes([CMD_READ_BITS, n - 2])
        n_read += 1
    else:
        n_bytes, n_bits = split_bytes_bits(n)
        minus_one = n_bytes - 1
        out += bytes([CMD_READ_BYTES, minus_one & 0xFF, minus_one >> 8])
        n_read += n_bytes
        if n_bits > 1:
            out += bytes([CMD_READ_BITS, n_bits - 2])
            n_read += 1

    out += bytes([CMD_CLOCK_TMS_READ, 0x02, 0x03])      # final bit + leave
    n_read += 1
    return out, n_read


def decode_output(buf: Sequence[int], offset: int, output_width: int) -> Tuple[str, int]:
    """
    Decode one response from the device buffer.

    Returns (bits MSB-first, new offset). Byte reads come back in the reverse
    of the order they were requested, and the final bit -- clocked by the
    TMS-with-read command -- lands in bit position 2 of its own byte.

    This is the original decoder's logic verbatim, with the widths passed in
    explicitly instead of leaking from the write loop (KNOWN_ISSUES #4).
    """
    n = output_width
    j = offset

    if n == 1:
        bits = format(buf[j], "08b")[2]
        j += 1
        return bits, j

    if n <= 9:
        head = format(buf[j], "08b")[:n - 1]
        j += 1
        last = format(buf[j], "08b")[2]
        j += 1
        return last + head, j

    n_bytes, n_bits = split_bytes_bits(n)
    byte_str = ""
    for _ in range(n_bytes):
        byte_str = format(buf[j], "08b") + byte_str
        j += 1

    if n_bits > 1:
        bits_str = format(buf[j], "08b")
        j += 1
        result = bits_str[:n_bits - 1] + byte_str
        last = format(buf[j], "08b")[2]
        j += 1
        return last + result, j

    last = format(buf[j], "08b")[2]
    j += 1
    return last + byte_str, j


def encode_ir(instruction: int) -> bytes:
    """
    Load a 6-bit instruction: 5 bits in Shift-IR, the 6th on the way out.

    Returns `bytes`, not `bytearray` -- ftd2xx's write() rejects a bytearray
    with a bare `ctypes.ArgumentError: argument 2: wrong type`, which is an
    unhelpful thing to discover with a board on the bench.
    """
    out = bytearray()
    out += bytes([CMD_CLOCK_TMS_NOREAD, 0x03, 0x03])          # -> Shift-IR
    out += bytes([CMD_WRITE_BITS, 0x04, instruction & 0x1F])  # low 5 bits

    # The 6th (top) instruction bit is clocked out at the same time TMS rises to
    # leave Shift-IR -- the same trick used for the last bit of a DR scan.
    #
    # The payload byte of a 0x4B command is NOT a data value. Its layout is:
    #
    #   bits 6..0  the TMS values to clock out, LSB first
    #   bit 7      the TDI level, held constant for the whole command
    #
    # So the byte is (top_bit << 7) | 0x01: TDI carries the instruction bit,
    # and the 0x01 is TMS=1, which is what actually leaves Shift-IR.
    #
    # An earlier version of this function read the byte as a plain value and
    # emitted `(instruction >> 5) & 1`. For USER1 (0x02) the top bit is 0, so it
    # sent TMS=0 -- the TAP stayed in Shift-IR, the instruction was never
    # latched, USER1 was never selected, and TDO read back as 1 on every vector.
    # 41 of 44 vectors failed while the IDCODE read still worked, because the
    # IDCODE path happens before this and never depended on it.
    out += bytes([CMD_CLOCK_TMS_NOREAD, 0x00,
                  (((instruction >> 5) & 1) << 7) | 0x01])
    return bytes(out)


def reverse_byte(b: int) -> int:
    """Reverse the bit order within one byte."""
    b = ((b & 0xF0) >> 4) | ((b & 0x0F) << 4)
    b = ((b & 0xCC) >> 2) | ((b & 0x33) << 2)
    b = ((b & 0xAA) >> 1) | ((b & 0x55) << 1)
    return b


def decode_idcode(raw: bytes) -> int:
    """
    Turn the 4 bytes read back from an IDCODE scan into the 32-bit value.

    Two reversals are involved and it is easy to apply only one:

      * FTDI's read commands shift each incoming bit in at the MSB end, so
        after 8 bits the *first* bit received sits in bit 7. Each byte
        therefore arrives bit-reversed and has to be flipped back.
      * The IDCODE shifts out LSB-first, so the first byte received is the
        least significant -- little-endian assembly.

    Getting only the second right produces a plausible-looking but wrong
    number: this returned 0xC0460BC9 for a part whose IDCODE is 0x0362D093.
    Plausible-looking is the dangerous part -- it does not look like an error.

    The original scan_bscane2.py sidestepped this by printing the raw hex and
    leaving the reader to interpret it, so the bug is new to this rewrite.
    """
    value = 0
    for i, byte in enumerate(raw):
        value |= reverse_byte(byte) << (8 * i)
    return value


# IDCODE -> part, version nibble (bits 31:28) masked off.
KNOWN_PARTS = {
    0x0362D093: "xc7a35t",
    0x0362C093: "xc7a50t",
    0x03631093: "xc7a100t",
    0x03636093: "xc7a200t",
    0x0362F093: "xc7a75t",
}


def identify_part(idcode: int) -> Optional[str]:
    return KNOWN_PARTS.get(idcode & 0x0FFFFFFF)


# ---------------------------------------------------------------------------
# Hardware transport
# ---------------------------------------------------------------------------

class DeviceError(Exception):
    """Raised with an actionable message rather than a raw ftd2xx traceback."""


class JtagDevice:
    """Thin wrapper over an FTDI channel in MPSSE mode."""

    def __init__(self, channel: int = 0, divider: int = DEFAULT_DIVIDER):
        try:
            import ftd2xx
        except ImportError as exc:
            raise DeviceError(
                "the ftd2xx module is not installed.\n"
                "  pip install -r host/requirements.txt\n"
                "It also needs the FTDI D2XX driver at OS level."
            ) from exc

        self._ftd = ftd2xx
        try:
            self.dev = ftd2xx.open(channel)
        except Exception as exc:
            raise DeviceError(
                f"could not open FTDI channel {channel}: {exc}\n"
                "Most likely causes, in order:\n"
                "  1. Vivado Hardware Manager still has the cable open. Close "
                "the hardware target.\n"
                "  2. The VCP driver is bound instead of D2XX (Windows: "
                "Device Manager -> Properties -> Advanced -> uncheck Load VCP).\n"
                "  3. Wrong channel -- try --channel 1.\n"
                "  4. Board not powered, or cable not seated."
            ) from exc

        self.dev.setBitMode(0, 0x02)                  # MPSSE
        # 0x8B ENABLES the divide-by-5 prescaler (0x8A disables it). Inherited
        # from scan_bscane2.py, where it was commented as a disable -- it is
        # not. With /5 on, the MPSSE master is 60/5 = 12 MHz and
        #     TCK = 12 MHz / (2 * (divider + 1)) = 6 MHz / (divider + 1)
        # so every frequency this project ever quoted was 5x too high. See
        # docs/RESULTS.md 5C: the divider sweep's timing fits 6 MHz/(n+1) to
        # within a few microseconds per vector and does not fit 30 MHz/(n+1).
        # Left as-is deliberately: every hardware result on record was taken
        # with the prescaler on, and switching it is a change to test, not to
        # slip in. See docs/KNOWN_ISSUES.md #2.
        self.dev.write(b"\x8B")                       # ENABLE /5 prescaler
        self.dev.write(bytes([0x86, divider & 0xFF, (divider >> 8) & 0xFF]))
        self.dev.write(b"\x80\x00\x0B")               # initial JTAG pin state

    def close(self) -> None:
        try:
            self.dev.setBitMode(0, 0)
        finally:
            self.dev.close()

    def tap_reset(self) -> None:
        """
        Six TMS=1 clocks reach Test-Logic-Reset from any state.

        With the scan_core fix this also clears the FPGA's io phase bit, so
        every run self-synchronises even after a previous run was interrupted
        (KNOWN_ISSUES #1).
        """
        self.dev.write(bytes([CMD_CLOCK_TMS_NOREAD, 0x05, 0x3F]))
        self.dev.write(bytes([CMD_CLOCK_TMS_NOREAD, 0x05, 0x00]))

    def read_idcode(self) -> int:
        self.tap_reset()
        self.dev.write(bytes([CMD_CLOCK_TMS_NOREAD, 0x03, 0x03]))   # -> Shift-IR
        self.dev.write(bytes([CMD_WRITE_BITS, 0x04, IR_IDCODE]))
        self.dev.write(bytes([CMD_CLOCK_TMS_NOREAD, 0x00, 0x01]))
        self.dev.write(bytes([CMD_CLOCK_TMS_NOREAD, 0x03, 0x03]))   # -> Shift-DR
        self.dev.write(bytes([CMD_READ_BYTES_PE, 0x03, 0x00]))
        raw = self.dev.read(4)
        if len(raw) != 4:
            raise DeviceError(
                "timed out reading the IDCODE -- the TAP is not responding. "
                "Check power, cable and channel."
            )
        self.dev.write(bytes([CMD_CLOCK_TMS_NOREAD, 0x02, 0x03]))
        return decode_idcode(raw)

    def select_user1(self) -> None:
        self.dev.write(encode_ir(IR_USER1))
        self.dev.write(bytes([CMD_CLOCK_TMS_NOREAD, 0x01, 0x01]))

    def transfer(self, commands: bytes, n_read: int) -> bytes:
        self.dev.write(bytes(commands))
        if n_read == 0:
            return b""
        data = self.dev.read(n_read)
        if len(data) != n_read:
            raise DeviceError(
                f"short read from the device: expected {n_read} bytes, got "
                f"{len(data)}. The command stream and the expected read count "
                f"have diverged; results after this point would be meaningless."
            )
        return data


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

@dataclass
class Result:
    vector: Vector
    got: str
    passed: bool
    masked: bool


class AbortedRun(Exception):
    """Raised by the deliberate mid-vector abort used to test KNOWN_ISSUES #1."""


def run_vectors(dev: JtagDevice, trace: Tracefile, verbose: bool = False,
                abort_after_input: Optional[int] = None) -> List[Result]:
    """Batch vectors into USB transfers, then decode and compare the responses."""
    results: List[Result] = []
    pending: List[Vector] = []
    buf = bytearray()
    n_read = 0

    def flush() -> None:
        nonlocal buf, n_read, pending
        if not pending:
            return
        data = dev.transfer(buf, n_read)
        offset = 0
        for vec in pending:
            got, offset = decode_output(data, offset, trace.output_width)
            masked = "1" not in vec.mask
            ok = True if masked else compare(got, vec.expected, vec.mask)
            results.append(Result(vec, got, ok, masked))
        buf = bytearray()
        n_read = 0
        pending = []

    for i, vec in enumerate(trace.vectors):
        # --- fault injection for the KNOWN_ISSUES #1 test ----------------
        # Send only the INPUT phase of this vector, then stop. That leaves the
        # FPGA's `io` phase bit at '1' while the host walks away, which is
        # exactly the state a crash or a dropped USB transfer produces.
        #
        # This exists because the failure cannot be triggered by hand. A run
        # completes in under a tenth of a second, so Ctrl-C never lands in the
        # window; and interrupting *between* vectors proves nothing, because a
        # complete vector performs both phases and leaves `io` back at '0'
        # whether or not the reset path exists. The desync needs a run that
        # dies partway through a single vector.
        if abort_after_input is not None and i == abort_after_input:
            flush()
            dev.transfer(encode_input_scan(vec.inputs), 0)
            raise AbortedRun(
                f"aborted after the input phase of vector {i} "
                f"(line {vec.line_no}); the FPGA's phase bit is now inverted")

        cmds = encode_input_scan(vec.inputs)
        out_cmds, out_read = encode_output_scan(trace.output_width)
        cmds += out_cmds

        if buf and len(buf) + len(cmds) > MAX_WRITE_CHUNK:
            flush()

        buf += cmds
        n_read += out_read
        pending.append(vec)

    flush()
    return results


def write_report(path: str, results: List[Result]) -> None:
    """
    One line per vector, in the original format so existing committed results
    stay diffable:  <input> <bits read back> <Success|Failure>
    Masked vectors are marked Skipped rather than silently passed.
    """
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in results:
            if r.masked:
                verdict = "Skipped"
            else:
                verdict = "Success" if r.passed else "Failure"
            fh.write(f"{r.vector.inputs} {r.got} {verdict}\n")


def print_summary(results: List[Result], elapsed: float, max_failures: int = 20) -> int:
    total = len(results)
    skipped = sum(1 for r in results if r.masked)
    failed = [r for r in results if not r.masked and not r.passed]
    passed = total - skipped - len(failed)

    if failed:
        print("\nFailures:")
        print(f"  {'line':>6}  {'input':<20} {'expected':<12} {'got':<12}")
        for r in failed[:max_failures]:
            print(f"  {r.vector.line_no:>6}  {r.vector.inputs:<20} "
                  f"{r.vector.expected:<12} {r.got:<12}")
        if len(failed) > max_failures:
            print(f"  ... and {len(failed) - max_failures} more")

    rate = total / elapsed if elapsed > 0 else 0.0
    print()
    print(f"{total} vectors: {passed} passed, {len(failed)} failed, "
          f"{skipped} skipped (masked)")
    print(f"{elapsed:.2f} s elapsed, {rate:.0f} vectors/s")
    return 1 if failed else 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run test vectors against a DUT over JTAG.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit status is 0 only if every unmasked vector passed.")
    ap.add_argument("-t", "--tracefile", required=True,
                    help="test vector file; see docs/TRACEFILE_FORMAT.md")
    ap.add_argument("-o", "--out", default="output.txt",
                    help="per-vector report (default: output.txt)")
    ap.add_argument("-c", "--channel", type=int, default=0,
                    help="FTDI channel: 0 = A, 1 = B (default: 0)")
    ap.add_argument("-d", "--divider", type=lambda s: int(s, 0),
                    default=DEFAULT_DIVIDER,
                    help=f"clock divider; TCK = 6 MHz / (n+1) "
                         f"(default: 0x{DEFAULT_DIVIDER:02X} = 100 kHz). "
                         f"0x02 (2 MHz) is ~15x faster and has passed on "
                         f"hardware; see docs/RESULTS.md 5C")
    ap.add_argument("--expect-idcode", type=lambda s: int(s, 0), default=None,
                    help="abort unless the TAP reports this IDCODE, e.g. 0x0362D093")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse and validate the tracefile, then exit. "
                         "No hardware needed.")
    ap.add_argument("--abort-after-input", type=int, metavar="N", default=None,
                    help="FAULT INJECTION for the KNOWN_ISSUES #1 test: send "
                         "only the input phase of vector N, then exit, leaving "
                         "the FPGA's phase bit inverted. Rerun normally "
                         "afterwards WITHOUT reprogramming -- it should pass. "
                         "On the pre-fix design it does not.")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    try:
        with open(args.tracefile, encoding="utf-8") as fh:
            trace = parse_tracefile(fh.read())
    except OSError as exc:
        print(f"error: cannot read tracefile: {exc}", file=sys.stderr)
        return 2
    except TracefileError as exc:
        print(f"error: {args.tracefile}: {exc}", file=sys.stderr)
        return 2

    print(f"{args.tracefile}: {len(trace.vectors)} vectors, "
          f"{trace.input_width} in / {trace.output_width} out")

    if args.dry_run:
        masked = sum(1 for v in trace.vectors if "1" not in v.mask)
        print(f"tracefile is valid ({masked} vectors fully masked). "
              f"--dry-run: not touching hardware.")
        return 0

    try:
        dev = JtagDevice(args.channel, args.divider)
    except DeviceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        idcode = dev.read_idcode()
        part = identify_part(idcode)
        print(f"IDCODE: 0x{idcode:08X}" + (f"  ({part})" if part else "  (part not in the known table)"))
        if idcode in (0x00000000, 0xFFFFFFFF):
            print("error: the TAP is not responding (IDCODE is all zeros or all "
                  "ones). See docs/TROUBLESHOOTING.md.", file=sys.stderr)
            return 2
        if args.expect_idcode is not None and idcode != args.expect_idcode:
            print(f"error: IDCODE mismatch -- expected "
                  f"0x{args.expect_idcode:08X}, got 0x{idcode:08X}. Wrong board "
                  f"or wrong part.", file=sys.stderr)
            return 2

        dev.select_user1()

        start = time.time()
        try:
            results = run_vectors(dev, trace, args.verbose,
                                  args.abort_after_input)
        except AbortedRun as exc:
            print(f"\nABORTED ON PURPOSE: {exc}")
            print("The FPGA is now mid-vector, phase bit inverted.")
            print("Now rerun WITHOUT reprogramming:")
            print(f"  python host/scanchain.py -t {args.tracefile} -o after.txt")
            print("A full pass proves the TAP-reset recovery path works "
                  "(KNOWN_ISSUES #1).")
            return 3
        elapsed = time.time() - start
    except DeviceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        # KNOWN_ISSUES #1: with the scan_core reset path, an interrupted run no
        # longer leaves the FPGA's phase bit inverted -- the next run's TAP
        # reset clears it. No reprogramming needed.
        print("\ninterrupted. The next run will resynchronise on its TAP reset.",
              file=sys.stderr)
        return 130
    finally:
        dev.close()

    write_report(args.out, results)
    print(f"report written to {args.out}")
    return print_summary(results, elapsed)


if __name__ == "__main__":
    sys.exit(main())
