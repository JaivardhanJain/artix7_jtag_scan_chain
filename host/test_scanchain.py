#!/usr/bin/env python3
"""
Offline tests for host/scanchain.py. No board, no FTDI driver required.

    python3 host/test_scanchain.py        # standalone
    pytest host/test_scanchain.py         # or under pytest

The most important group is `test_matches_original_*`. The MPSSE encoding and
decoding in scan_bscane2.py are the part of this project with the strongest
evidence behind them -- 4096/4096 vectors on real hardware -- so the rewrite
must not change them by a single byte. Those tests re-implement the original
algorithm verbatim from scan_bscane2.py and assert the new code produces
identical output across every width from 1 to 64 bits.

The remaining groups cover the behaviour that was actually broken: mask
handling (KNOWN_ISSUES #3) and width validation (KNOWN_ISSUES #4).
"""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scanchain import (  # noqa: E402
    TracefileError,
    compare,
    decode_idcode,
    decode_output,
    encode_input_scan,
    encode_ir,
    encode_output_scan,
    identify_part,
    parse_tracefile,
    reverse_byte,
    split_bytes_bits,
)


# ===========================================================================
# Reference implementation, transcribed from scan_bscane2.py
# ===========================================================================

def ref_encode_input(inputData):
    """The original write loop's input half, byte for byte."""
    send = bytearray()
    inputLen = len(inputData)
    send.extend(b"\x4B\x02\x01")

    if inputLen <= 9 and inputLen > 1:
        inputTemp = int(inputData[1:inputLen], 2)
        lastBit = int(inputData[0], 2)
        tempLen = inputLen - 2
        send.extend(bytearray([0x1B, tempLen, inputTemp]))
    elif inputLen == 1:
        lastBit = int(inputData[0], 2)
    else:
        tempLen = inputLen
        no_of_bytes = (tempLen & (~7)) >> 3
        no_of_bits = tempLen & 7
        if no_of_bits == 0:
            no_of_bits += 8
            no_of_bytes -= 1
        bytesminusOne = no_of_bytes - 1
        bytesL = bytesminusOne & 0xFF
        bytesH = bytesminusOne >> 8
        byteList = [0x19, bytesL, bytesH]
        i = 0
        j = inputLen
        while i < no_of_bytes:
            temp_byte_array = inputData[j - 8:j]
            j -= 8
            i += 1
            byteList.append(int(temp_byte_array, 2))
        send.extend(bytearray(byteList))

        if no_of_bits == 1:
            lastBit = int(inputData[0], 2)
        else:
            tempLen = no_of_bits - 2
            inputTemp = int(inputData[1:no_of_bits], 2)
            lastBit = int(inputData[0], 2)
            send.extend(bytearray([0x1B, tempLen, inputTemp]))

    send.extend(bytearray([0x4B, 0x02, ((lastBit & 0x1) << 7) | 0x03]))
    return send


def ref_encode_output(outputLen):
    """The original write loop's output half, plus its read-byte count."""
    send = bytearray()
    read_cmd = 0
    send.extend(b"\x4B\x02\x01")

    if outputLen <= 9 and outputLen > 1:
        outbitLen = outputLen - 2
        send.extend([0x2E, outbitLen])
        read_cmd += 1
    elif outputLen == 1:
        pass
    else:
        tempLen = outputLen
        no_of_bytes = (tempLen & (~7)) >> 3
        no_of_bits = tempLen & 7
        if no_of_bits == 0:
            no_of_bits += 8
            no_of_bytes -= 1
        bytesminusOne = no_of_bytes - 1
        bytesL = bytesminusOne & 0xFF
        bytesH = bytesminusOne >> 8
        send.extend(bytearray([0x2C, bytesL, bytesH]))
        read_cmd += no_of_bytes
        if no_of_bits > 1:
            send.extend(bytearray([0x2E, no_of_bits - 2]))
            read_cmd += 1

    send.extend(bytearray([0x6B, 0x02, 0x03]))
    read_cmd += 1
    return send, read_cmd


def ref_decode(usb_read_data, j, outputLen):
    """The original decode loop, for one vector."""
    no_of_bytes = 0
    no_of_bits = 0
    if outputLen > 9:
        tempLen = outputLen
        no_of_bytes = (tempLen & (~7)) >> 3
        no_of_bits = tempLen & 7
        if no_of_bits == 0:
            no_of_bits += 8
            no_of_bytes -= 1

    if outputLen <= 9 and outputLen > 1:
        read_data = usb_read_data[j]
        read_str = format(read_data, "08b")[:outputLen - 1]
        j += 1
        read_data = usb_read_data[j]
        lastBitStr = format(read_data, "08b")[2]
        read_str = lastBitStr + read_str
        j += 1
    elif outputLen == 1:
        read_data = usb_read_data[j]
        read_str = format(read_data, "08b")[2]
        j += 1
    else:
        read_bytes_str = ""
        l = 0
        while l < no_of_bytes:
            read_bytes_str = "{0:08b}".format(usb_read_data[j]) + read_bytes_str
            l += 1
            j += 1
        if no_of_bits > 1:
            read_bits_data = usb_read_data[j]
            read_bits_str = format(read_bits_data, "08b")
            read_str = read_bits_str[:no_of_bits - 1] + read_bytes_str
            j += 1
            read_data = usb_read_data[j]
            lastBitStr = format(read_data, "08b")[2]
            read_str = lastBitStr + read_str
            j += 1
        else:
            read_str = read_bytes_str
            read_data = usb_read_data[j]
            lastBitStr = format(read_data, "08b")[2]
            read_str = lastBitStr + read_str
            j += 1

    return read_str, j


# ===========================================================================
# Equivalence with the original
# ===========================================================================

WIDTHS = list(range(1, 65))


def test_matches_original_input_encoding():
    rng = random.Random(20260729)
    for width in WIDTHS:
        for _ in range(20):
            vec = "".join(rng.choice("01") for _ in range(width))
            assert bytes(encode_input_scan(vec)) == bytes(ref_encode_input(vec)), (
                f"input encoding diverged at width {width}, vector {vec}")


def test_matches_original_output_encoding():
    for width in WIDTHS:
        got_cmds, got_n = encode_output_scan(width)
        ref_cmds, ref_n = ref_encode_output(width)
        assert bytes(got_cmds) == bytes(ref_cmds), \
            f"output encoding diverged at width {width}"
        assert got_n == ref_n, \
            f"read-byte count diverged at width {width}: {got_n} vs {ref_n}"


def test_matches_original_decoding():
    rng = random.Random(4096)
    for width in WIDTHS:
        _, n_read = encode_output_scan(width)
        for _ in range(20):
            buf = bytes(rng.randrange(256) for _ in range(n_read + 4))
            got, got_j = decode_output(buf, 0, width)
            ref, ref_j = ref_decode(buf, 0, width)
            assert got == ref, f"decode diverged at width {width}"
            assert got_j == ref_j, f"offset diverged at width {width}"


def test_decoded_width_matches_requested():
    """A decoded response must be exactly as wide as the tracefile says."""
    rng = random.Random(7)
    for width in WIDTHS:
        _, n_read = encode_output_scan(width)
        buf = bytes(rng.randrange(256) for _ in range(n_read))
        bits, _ = decode_output(buf, 0, width)
        assert len(bits) == width, \
            f"width {width}: decoded {len(bits)} bits"


def test_decode_consumes_exactly_the_read_bytes():
    """
    The bytes consumed by the decoder must equal the bytes the encoder told the
    device to send. A mismatch here would desynchronise every later vector in
    the batch -- the failure mode is silent and total.
    """
    for width in WIDTHS:
        _, n_read = encode_output_scan(width)
        buf = bytes(n_read)
        _, offset = decode_output(buf, 0, width)
        assert offset == n_read, \
            f"width {width}: decoder consumed {offset} bytes, encoder expected {n_read}"


def test_split_bytes_bits_never_returns_zero_remainder():
    """The final bit must always be available to clock out with TMS."""
    for n in range(9, 200):
        n_bytes, n_bits = split_bytes_bits(n)
        assert n_bits >= 1
        assert n_bytes * 8 + n_bits == n


# ===========================================================================
# IDCODE decoding -- regression tests from real hardware
# ===========================================================================

def test_decode_idcode_from_real_hardware():
    """
    Captured from an actual Artix-7 board, 2026-07-31.

    The device returned these four bytes for an IDCODE scan, and the part is
    known independently: Vivado enumerated it as xc7a35t, whose IDCODE is
    0x0362D093.

    The first version of decode_idcode applied only the little-endian
    assembly and not the per-byte bit reversal, returning 0xC0460BC9 -- a
    plausible-looking wrong number, which is the dangerous kind.
    """
    raw = bytes.fromhex("c90b46c0")
    assert decode_idcode(raw) == 0x0362D093, \
        f"got 0x{decode_idcode(raw):08X}, expected 0x0362D093 (xc7a35t)"
    assert identify_part(decode_idcode(raw)) == "xc7a35t"


def test_reverse_byte_is_an_involution():
    for b in range(256):
        assert reverse_byte(reverse_byte(b)) == b
    assert reverse_byte(0b00000001) == 0b10000000
    assert reverse_byte(0b11001001) == 0b10010011


def test_idcode_lsb_is_always_one():
    """IEEE 1149.1 requires bit 0 of IDCODE to be 1; a decode that loses it
    is reversed or shifted."""
    assert decode_idcode(bytes.fromhex("c90b46c0")) & 1 == 1


def test_identify_part_ignores_the_version_nibble():
    """Bits 31:28 are a silicon revision and vary between parts of the same
    type, so they must not affect identification."""
    assert identify_part(0x0362D093) == "xc7a35t"
    assert identify_part(0x1362D093) == "xc7a35t"
    assert identify_part(0xA362D093) == "xc7a35t"
    assert identify_part(0xDEADBEEF) is None


# ===========================================================================
# Writes must be `bytes`, not `bytearray`
# ===========================================================================

def test_encoders_return_bytes_not_bytearray():
    """
    ftd2xx's write() rejects a bytearray with a bare
    `ctypes.ArgumentError: argument 2: wrong type`, giving no hint about the
    cause. encode_ir originally returned a bytearray and crashed the first
    hardware run at exactly that line.
    """
    assert isinstance(encode_ir(0x02), bytes)
    assert not isinstance(encode_ir(0x02), bytearray)


def test_encode_ir_matches_the_original_byte_for_byte():
    """
    Pinned to the literal bytes scan_bscane2.py sends. This is the test that
    was missing: the equivalence suite covered the per-vector encoders but not
    the initialisation sequence, and the bug that broke the first hardware run
    lived exactly there.

    Transcribed from the original:

        dev.write(b"\x4B\x03\x03")   # -> Shift-IR
        dev.write(b"\x1B\x04\x02")   # 5 bits of USER1 (0x02)
        dev.write(b"\x4B\x00\x01")   # 6th bit + Exit1-IR
    """
    assert encode_ir(0x02) == b"\x4B\x03\x03\x1B\x04\x02\x4B\x00\x01"


def test_encode_ir_payload_is_tms_not_a_value():
    """
    The payload byte of a 0x4B command is bits 6..0 = TMS values, bit 7 = TDI.
    It is not a data value.

    Reading it as a value produced `0x00` for USER1 -- TMS=0, so the TAP never
    left Shift-IR, the instruction was never latched, and every vector read
    back 1. The low bit must always be 1 (TMS=1, leave Shift-IR); the top
    instruction bit rides in bit 7.
    """
    for instruction in range(64):
        last = encode_ir(instruction)[8]
        assert last & 0x01 == 1, \
            f"instruction 0x{instruction:02X}: TMS bit missing, TAP will not " \
            f"leave Shift-IR"
        assert (last >> 7) & 1 == (instruction >> 5) & 1, \
            f"instruction 0x{instruction:02X}: bit 5 not carried on TDI"


def test_encode_ir_shape():
    """6-bit IR: 5 bits shifted in Shift-IR, the 6th clocked with TMS."""
    out = encode_ir(0x02)
    assert out[0] == 0x4B and out[1] == 0x03 and out[2] == 0x03   # -> Shift-IR
    assert out[3] == 0x1B and out[4] == 0x04 and out[5] == 0x02   # low 5 bits
    assert out[6] == 0x4B and out[7] == 0x00                      # 1 TMS clock
    assert encode_ir(0x22)[8] == 0x81, "bit 5 set -> TDI high, TMS still 1"


# ===========================================================================
# Tracefile parsing -- KNOWN_ISSUES #4
# ===========================================================================

def test_parses_basic_tracefile():
    t = parse_tracefile("0000010 0 0\n0001000 0 1\n")
    assert len(t.vectors) == 2
    assert t.input_width == 7
    assert t.output_width == 1


def test_tolerates_crlf_and_trailing_space():
    """The bundled TRACEFILE.txt has CRLF and inconsistent trailing spaces."""
    t = parse_tracefile("0000010 0 0\r\n0001000 0 1 \r\n1001000 0 1\r\n")
    assert len(t.vectors) == 3


def test_tolerates_blank_lines_and_comments():
    t = parse_tracefile("# header\n\n0000010 0 1\n\n# mid\n0001000 0 1\n")
    assert len(t.vectors) == 2


def test_mask_column_is_optional():
    t = parse_tracefile("0000010 0\n0001000 0\n")
    assert all(v.mask == "1" for v in t.vectors)


def test_rejects_ragged_input_width():
    """This is KNOWN_ISSUES #4: the old code mis-parsed instead of erroring."""
    try:
        parse_tracefile("0000010 0 1\n00010 0 1\n")
    except TracefileError as exc:
        assert "line 2" in str(exc), f"error lacks a line number: {exc}"
        assert "5 bits" in str(exc) and "7" in str(exc)
    else:
        raise AssertionError("ragged input width was not rejected")


def test_rejects_ragged_output_width():
    try:
        parse_tracefile("0000010 00 1\n0001000 0 1\n")
    except TracefileError as exc:
        assert "line 2" in str(exc)
    else:
        raise AssertionError("ragged output width was not rejected")


def test_rejects_single_column():
    try:
        parse_tracefile("0000010\n")
    except TracefileError as exc:
        assert "line 1" in str(exc)
    else:
        raise AssertionError("a one-column line was not rejected")


def test_rejects_non_binary_input():
    try:
        parse_tracefile("00000x0 0 1\n")
    except TracefileError as exc:
        assert "line 1" in str(exc)
    else:
        raise AssertionError("non-binary input was not rejected")


def test_rejects_empty_tracefile():
    try:
        parse_tracefile("# nothing but comments\n")
    except TracefileError:
        pass
    else:
        raise AssertionError("an empty tracefile was not rejected")


# ===========================================================================
# Mask handling -- KNOWN_ISSUES #3
# ===========================================================================

def test_mask_zero_disables_comparison():
    t = parse_tracefile("0000010 0 0\n")
    v = t.vectors[0]
    assert "1" not in v.mask, "mask '0' should disable every bit"
    assert compare("1", v.expected, v.mask), \
        "a fully masked vector must pass regardless of what came back"


def test_mask_one_enables_comparison():
    t = parse_tracefile("0000010 0 1\n")
    v = t.vectors[0]
    assert compare("0", v.expected, v.mask)
    assert not compare("1", v.expected, v.mask)


def test_per_bit_mask():
    t = parse_tracefile("00000001 1010 1001\n")
    v = t.vectors[0]
    assert v.mask == "1001"
    assert compare("1010", v.expected, v.mask)
    assert compare("1110", v.expected, v.mask), "bits 1-2 are masked out"
    assert not compare("0010", v.expected, v.mask), "bit 3 is compared"
    assert not compare("1011", v.expected, v.mask), "bit 0 is compared"


def test_dont_care_in_expected_column():
    t = parse_tracefile("00000001 1x1x 1111\n")
    v = t.vectors[0]
    assert v.mask == "1010", "don't-cares should be folded into the mask"
    assert compare("1010", v.expected, v.mask)
    assert compare("1111", v.expected, v.mask)
    assert not compare("0010", v.expected, v.mask)


def test_rejects_bad_mask_width():
    try:
        parse_tracefile("00000001 1010 101\n")
    except TracefileError as exc:
        assert "line 1" in str(exc)
    else:
        raise AssertionError("a wrong-width mask was not rejected")


def test_compare_rejects_width_mismatch():
    assert not compare("101", "1010", "1111")


# ===========================================================================
# Regression against the file actually in the repo
# ===========================================================================

def test_bundled_tracefile_parses():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "examples", "string_detector", "TRACEFILE.txt")
    path = os.path.normpath(path)
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        t = parse_tracefile(fh.read())
    assert len(t.vectors) == 46, f"expected 46 vectors, got {len(t.vectors)}"
    assert t.input_width == 7
    assert t.output_width == 1
    masked = [v for v in t.vectors if "1" not in v.mask]
    assert len(masked) == 2, \
        f"expected the first 2 vectors to be masked, found {len(masked)}"
    assert [v.line_no for v in masked] == [1, 2]


# ===========================================================================

def _run_standalone():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as exc:               # noqa: BLE001
            failures += 1
            print(f"  FAIL  {name}: {exc}")
    print(f"\n{len(tests)} tests, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run_standalone())
