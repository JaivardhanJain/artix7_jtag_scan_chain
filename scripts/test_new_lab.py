#!/usr/bin/env python3
"""
Offline tests for scripts/new_lab.py.

    python3 scripts/test_new_lab.py        # standalone
    pytest scripts/test_new_lab.py

The load-bearing test is `test_reproduces_committed_wrappers`: the generator is
run against the same entities the committed `DUT.vhd` wrappers were written for
by hand, and the resulting port maps must match. Those wrappers are known-good
-- one of them has 4096 passing hardware vectors behind it -- so agreeing with
them is the strongest available evidence that the generated bit layout is
right, and it will catch any future change to the layout convention.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from new_lab import (  # noqa: E402
    CLOCK_NAMES,
    RESET_NAMES,
    ParseError,
    autodetect,
    emit_wrapper,
    find_entity,
    lay_out,
    parse_ports,
    patch_toplevel,
    strip_comments,
)


def build(src, entity=None, special=True, clock=None, reset=None):
    """Parse and lay out, the way main() does."""
    ent, body = find_entity(strip_comments(src), entity)
    ports = parse_ports(body)
    clk = clock or (autodetect(ports, CLOCK_NAMES) if special else None)
    rst = reset or (autodetect(ports, RESET_NAMES) if special else None)
    ins, n_in = lay_out(ports, "in", clk, rst, special)
    outs, n_out = lay_out(ports, "out", None, None, False)
    return ent, ins, n_in, outs, n_out


def port_pairs(vhdl_text, n_in=None, n_out=None):
    """
    Extract 'name => slice' pairs from a port map, whitespace-insensitive.

    If the vector widths are given, a full-width slice is normalised to the
    bare signal name: `output_vector(4 downto 0)` and `output_vector` denote
    the same signal, and hand-written wrappers vary freely between the two.
    Without this, comparing a generated wrapper against a hand-written one
    reports a difference where there is no difference -- which is exactly
    what happened on the lab 4 BCD adder, whose author wrote the bare form.

    A test that fails on notation rather than meaning is worse than no test:
    it trains you to ignore it.
    """
    import re
    m = re.search(r"port\s*map\s*\((.*?)\)\s*;", vhdl_text, re.S | re.I)
    assert m, "no port map found"
    pairs = {}
    for part in m.group(1).split(","):
        if "=>" not in part:
            continue
        lhs, rhs = part.split("=>", 1)
        rhs = " ".join(rhs.split())
        if n_in:
            rhs = rhs.replace(f"input_vector({n_in - 1} downto 0)", "input_vector")
        if n_out:
            rhs = rhs.replace(f"output_vector({n_out - 1} downto 0)", "output_vector")
        pairs[lhs.strip()] = rhs
    return pairs


SIMPLE = """
library ieee;
use ieee.std_logic_1164.all;
entity Widget is
    port(din  : in  std_logic_vector(3 downto 0);
         en   : in  std_logic;
         reset, clock : in std_logic;
         dout : out std_logic_vector(7 downto 0));
end entity Widget;
"""


# ===========================================================================
# The load-bearing test
# ===========================================================================

def test_reproduces_committed_wrappers():
    """
    Generated port maps must match the committed ones, for every example whose
    sources are present. string_detector's sources are gitignored (coursework),
    so it is checked only when available locally -- hence the `checked >= 1`
    guard at the end, which stops this from passing vacuously in a fresh clone.

    The alu case is the one with hardware behind it: that wrapper was generated
    by this script and then passed 256/256 exhaustively on the board
    (docs/RESULTS.md 5C). If the generator's layout ever drifts, this is the
    test that catches it against a known-good result rather than against
    another artefact of the same tool.
    """
    cases = [
        ("examples/seq1011/Seq1011.vhd", "examples/seq1011/DUT.vhd"),
        ("examples/alu/ALU.vhd", "examples/alu/DUT.vhd"),
        ("examples/string_detector/StringDetector.vhdl",
         "examples/string_detector/DUT.vhd"),
        # bcd_adder is the only case whose reference wrapper was written by
        # someone with no knowledge of this generator, for a design it had
        # never seen. It is therefore the only genuinely blind comparison
        # here -- the others check the generator against wrappers that were
        # either written alongside it or produced by it.
        ("examples/bcd_adder/BCDAdder.vhdl", "examples/bcd_adder/DUT.vhd"),
    ]
    checked = 0
    for src_rel, dut_rel in cases:
        src = os.path.join(REPO, src_rel)
        dut = os.path.join(REPO, dut_rel)
        if not (os.path.exists(src) and os.path.exists(dut)):
            continue
        with open(src, encoding="utf-8") as fh:
            ent, ins, n_in, outs, n_out = build(fh.read())
        generated = emit_wrapper(ent, src, ins, n_in, outs, n_out)
        with open(dut, encoding="utf-8") as fh:
            handwritten = fh.read()
        got = port_pairs(generated, n_in, n_out)
        want = port_pairs(handwritten, n_in, n_out)
        assert got == want, (
            f"{src_rel}: generated layout differs from the hand-written "
            f"{dut_rel}\n  generated:   {got}\n"
            f"  hand-written: {want}")
        checked += 1
    assert checked >= 1, "no example sources available to check against"


# ===========================================================================
# Parsing
# ===========================================================================

def test_parses_ports_and_widths():
    ent, ins, n_in, outs, n_out = build(SIMPLE)
    assert ent == "Widget"
    assert n_in == 4 + 1 + 1 + 1
    assert n_out == 8


def test_multiple_names_in_one_declaration():
    ports = parse_ports("a, b, c : in std_logic; y : out std_logic")
    assert [p.name for p in ports] == ["a", "b", "c", "y"]


def test_comments_are_stripped():
    src = SIMPLE.replace("en   : in  std_logic;",
                         "en   : in  std_logic;  -- enable; not a port: fake")
    _, _, n_in, _, _ = build(src)
    assert n_in == 7


def test_ascending_range_supported():
    ports = parse_ports("v : in std_logic_vector(0 to 3); y : out std_logic")
    assert ports[0].width == 4
    assert ports[0].descending is False


# ===========================================================================
# Layout convention
# ===========================================================================

def test_clock_at_bit_zero_reset_at_bit_one():
    _, ins, _, _, _ = build(SIMPLE)
    pos = {f.port.name: (f.hi, f.lo) for f in ins}
    assert pos["clock"] == (0, 0)
    assert pos["reset"] == (1, 1)


def test_first_declared_gets_highest_bits():
    _, ins, n_in, _, _ = build(SIMPLE)
    pos = {f.port.name: (f.hi, f.lo) for f in ins}
    assert pos["din"] == (6, 3), "first-declared port should occupy the top"
    assert pos["en"] == (2, 2)
    assert n_in == 7


def test_fields_tile_the_vector_without_gaps_or_overlap():
    """Every bit assigned exactly once -- a gap or overlap is silent corruption."""
    for special in (True, False):
        _, ins, n_in, outs, n_out = build(SIMPLE, special=special)
        for fields, width in ((ins, n_in), (outs, n_out)):
            covered = []
            for f in fields:
                covered += list(range(f.lo, f.hi + 1))
            assert sorted(covered) == list(range(width)), (
                f"special={special}: bits {sorted(covered)} != 0..{width-1}")


def test_no_special_lays_out_in_declaration_order():
    _, ins, _, _, _ = build(SIMPLE, special=False)
    pos = {f.port.name: (f.hi, f.lo) for f in ins}
    assert pos["din"] == (6, 3)
    assert pos["en"] == (2, 2)
    assert pos["reset"] == (1, 1)
    assert pos["clock"] == (0, 0)


def test_explicit_clock_reset_override_autodetect():
    src = """
    entity E is
      port(tick : in std_logic; clr : in std_logic;
           d : in std_logic_vector(1 downto 0); q : out std_logic);
    end entity E;
    """
    _, ins, _, _, _ = build(src, clock="tick", reset="clr")
    pos = {f.port.name: (f.hi, f.lo) for f in ins}
    assert pos["tick"] == (0, 0)
    assert pos["clr"] == (1, 1)
    assert pos["d"] == (3, 2)


# ===========================================================================
# Errors -- each should say what to do, not just fail
# ===========================================================================

def _expect(fn, needle):
    try:
        fn()
    except ParseError as exc:
        assert needle in str(exc).lower(), f"unhelpful message: {exc}"
    else:
        raise AssertionError(f"expected ParseError mentioning {needle!r}")


def test_rejects_inout_with_explanation():
    _expect(lambda: build("entity E is port(x : inout std_logic); end entity E;"),
            "bidirectional")


def test_rejects_unsupported_type_with_explanation():
    _expect(lambda: build(
        "entity E is port(x : in integer; y : out std_logic); end entity E;"),
        "std_logic_vector")


def test_requires_entity_name_when_ambiguous():
    src = ("entity A is port(x : in std_logic; y : out std_logic); end entity A;"
           "entity B is port(x : in std_logic; y : out std_logic); end entity B;")
    _expect(lambda: build(src), "--entity")


def test_selects_named_entity():
    src = ("entity A is port(a : in std_logic; y : out std_logic); end entity A;"
           "entity B is port(b : in std_logic_vector(2 downto 0);"
           " z : out std_logic); end entity B;")
    ent, _, n_in, _, _ = build(src, entity="B")
    assert ent == "B" and n_in == 3


def test_rejects_entity_with_no_outputs():
    _expect(lambda: build("entity E is port(x : in std_logic); end entity E;"),
            "'out'")


def test_rejects_multibit_clock():
    _expect(lambda: build(
        "entity E is port(clock : in std_logic_vector(1 downto 0);"
        " y : out std_logic); end entity E;", clock="clock"),
        "--no-special")


# ===========================================================================
# Emission and patching
# ===========================================================================

def test_emitted_wrapper_has_expected_structure():
    ent, ins, n_in, outs, n_out = build(SIMPLE)
    text = emit_wrapper(ent, "Widget.vhd", ins, n_in, outs, n_out)
    assert "entity DUT is" in text
    assert f"input_vector  : in  std_logic_vector({n_in - 1} downto 0)" in text
    assert f"output_vector : out std_logic_vector({n_out - 1} downto 0)" in text
    assert "component Widget is" in text
    assert "din            => input_vector(6 downto 3)" in text
    assert "-- Tracefile bit layout" in text, "layout must be documented in-file"


def test_patch_toplevel(tmp_path=None):
    import tempfile
    src = ("  constant number_of_inputs  : integer := 7;\n"
           "  constant number_of_outputs : integer := 1;\n")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "TopLevel.vhd")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(src)
        assert patch_toplevel(p, 3, 5) is True
        out = open(p, encoding="utf-8").read()
        assert "number_of_inputs  : integer := 3" in out
        assert "number_of_outputs : integer := 5" in out


def test_patch_toplevel_reports_failure():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "TopLevel.vhd")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("-- no constants here\n")
        assert patch_toplevel(p, 3, 5) is False


# ===========================================================================

def _run_standalone():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as exc:              # noqa: BLE001
            failures += 1
            print(f"  FAIL  {name}: {exc}")
    print(f"\n{len(tests)} tests, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run_standalone())
