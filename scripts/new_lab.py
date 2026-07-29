#!/usr/bin/env python3
"""
Generate a scan chain DUT wrapper from a VHDL entity.

    python3 scripts/new_lab.py examples/seq1011/Seq1011.vhd

Reads the entity's port list, works out a bit layout, and writes `DUT.vhd`
next to it -- the wrapper that flattens the design's ports into the single
`input_vector` / `output_vector` pair the harness needs. Also prints the two
width constants for `hdl/TopLevel.vhd`, and can patch them in directly with
`--patch-toplevel`.

Why this exists
---------------
Adapting the harness to a new design meant hand-writing a wrapper with correct
bit slicing and hand-editing two constants in TopLevel.vhd. Both are mechanical
and both are easy to get subtly wrong -- and a wrong slice produces a run where
every vector fails with no indication of why. That was the real barrier to
anyone else using this, more than any of the defects.

Bit layout convention
---------------------
Chosen to match the wrappers that already existed, so generated and
hand-written wrappers agree:

    input_vector(0)  = clock, if the entity has one
    input_vector(1)  = reset, if the entity has one
    input_vector(N)  = remaining inputs, first-declared occupying the HIGHEST
                       bits, descending in declaration order

    output_vector    = outputs, first-declared occupying the HIGHEST bits

Putting clock at bit 0 matters in practice: a clocked DUT needs vector pairs
that differ only in the clock, and having it as the last character of the line
makes those pairs readable at a glance (`0001000` / `0001001`).

Ports are matched as clock/reset by name (clock, clk, reset, rst, rstn, ...).
Override with --clock/--reset, or use --no-special to lay every port out in
declaration order.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

CLOCK_NAMES = {"clock", "clk", "clock_in", "clk_in", "clki"}
RESET_NAMES = {"reset", "rst", "reset_n", "rstn", "rst_n", "reset_in", "arst"}


class ParseError(Exception):
    pass


@dataclass
class Port:
    name: str
    direction: str          # 'in' or 'out'
    width: int              # 1 for std_logic
    is_vector: bool
    high: int = 0           # for vectors: declared left index
    low: int = 0            # for vectors: declared right index
    descending: bool = True  # True for "downto"


# ---------------------------------------------------------------------------
# VHDL entity parsing
# ---------------------------------------------------------------------------

def strip_comments(text: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


def find_entity(text: str, name: Optional[str]) -> Tuple[str, str]:
    """Return (entity_name, port_clause_body)."""
    entities = re.findall(
        r"\bentity\s+(\w+)\s+is\b(.*?)\bend\b", text, re.S | re.I)
    if not entities:
        raise ParseError("no entity declaration found")

    if name is None:
        if len(entities) > 1:
            names = ", ".join(e[0] for e in entities)
            raise ParseError(
                f"file declares {len(entities)} entities ({names}); "
                f"pick one with --entity")
        ent_name, body = entities[0]
    else:
        matches = [e for e in entities if e[0].lower() == name.lower()]
        if not matches:
            names = ", ".join(e[0] for e in entities)
            raise ParseError(f"entity {name!r} not found; file declares: {names}")
        ent_name, body = matches[0]

    m = re.search(r"\bport\s*\((.*)\)\s*;", body, re.S | re.I)
    if not m:
        raise ParseError(f"entity {ent_name} has no port clause")
    return ent_name, m.group(1)


def parse_ports(port_body: str) -> List[Port]:
    ports: List[Port] = []
    for decl in port_body.split(";"):
        decl = decl.strip()
        if not decl:
            continue
        if ":" not in decl:
            raise ParseError(f"cannot parse port declaration: {decl!r}")

        names_part, type_part = decl.split(":", 1)
        names = [n.strip() for n in names_part.split(",") if n.strip()]
        type_part = type_part.strip()

        m = re.match(r"(in|out|inout|buffer)\s+(.*)", type_part, re.I)
        if not m:
            raise ParseError(f"port {names} has no direction: {type_part!r}")
        direction, type_name = m.group(1).lower(), m.group(2).strip()

        if direction in ("inout", "buffer"):
            raise ParseError(
                f"port {names} is '{direction}'. The scan chain carries inputs "
                f"and outputs separately and cannot represent a bidirectional "
                f"port. Split it into separate in/out ports in your design.")

        vec = re.match(
            r"std_logic_vector\s*\(\s*(\d+)\s+(downto|to)\s+(\d+)\s*\)",
            type_name, re.I)
        if vec:
            a, kw, b = int(vec.group(1)), vec.group(2).lower(), int(vec.group(3))
            desc = (kw == "downto")
            hi, lo = (a, b) if desc else (b, a)
            width = hi - lo + 1
            for n in names:
                ports.append(Port(n, direction, width, True, hi, lo, desc))
            continue

        if re.match(r"std_logic\b|std_ulogic\b", type_name, re.I):
            for n in names:
                ports.append(Port(n, direction, 1, False))
            continue

        raise ParseError(
            f"port {names} has unsupported type {type_name!r}. The wrapper can "
            f"only flatten std_logic and std_logic_vector. Convert integers, "
            f"enums or records to std_logic_vector in your design first.")

    if not ports:
        raise ParseError("port clause is empty")
    return ports


# ---------------------------------------------------------------------------
# Bit layout
# ---------------------------------------------------------------------------

@dataclass
class Field:
    port: Port
    hi: int      # bit position in the flattened vector
    lo: int


def lay_out(ports: List[Port], direction: str, clock: Optional[str],
            reset: Optional[str], special: bool) -> Tuple[List[Field], int]:
    """Assign bit positions. Returns (fields ordered high->low, total width)."""
    sel = [p for p in ports if p.direction == direction]
    if not sel:
        raise ParseError(f"entity has no '{direction}' ports")

    low_first: List[Port] = []      # ports pinned to the bottom, bit 0 upward
    if direction == "in" and special:
        for want in (clock, reset):
            if want is None:
                continue
            match = [p for p in sel if p.name.lower() == want.lower()]
            if match:
                if match[0].width != 1:
                    raise ParseError(
                        f"{match[0].name} is {match[0].width} bits; clock and "
                        f"reset must be single bits. Use --no-special.")
                low_first.append(match[0])

    rest = [p for p in sel if p not in low_first]

    fields: List[Field] = []
    pos = 0
    for p in low_first:                       # clock at 0, reset at 1
        fields.append(Field(p, pos, pos))
        pos += 1
    for p in reversed(rest):                  # last-declared lowest
        fields.append(Field(p, pos + p.width - 1, pos))
        pos += p.width

    fields.sort(key=lambda f: f.hi, reverse=True)
    return fields, pos


def autodetect(ports: List[Port], names: set) -> Optional[str]:
    for p in ports:
        if p.direction == "in" and p.width == 1 and p.name.lower() in names:
            return p.name
    return None


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------

def slice_expr(vec: str, f: Field) -> str:
    if f.hi == f.lo:
        return f"{vec}({f.hi})"
    return f"{vec}({f.hi} downto {f.lo})"


def port_expr(p: Port, f: Field, vec: str) -> str:
    """Map a flattened slice back onto the port's own declared range."""
    if not p.is_vector:
        return slice_expr(vec, f)
    if p.descending:
        return slice_expr(vec, f)
    # Ascending range (0 to N): the wrapper still slices descending, so note it.
    return slice_expr(vec, f)


def layout_comment(fields: List[Field], vec: str) -> List[str]:
    out = []
    for f in fields:
        left = slice_expr(vec, f)
        note = ""
        if f.port.is_vector and not f.port.descending:
            note = f"   [declared '{f.port.low} to {f.port.high}' -- ascending]"
        out.append(f"--   {left:<28} = {f.port.name}{note}")
    return out


def emit_wrapper(entity: str, src_file: str,
                 in_fields: List[Field], n_in: int,
                 out_fields: List[Field], n_out: int) -> str:
    lines = []
    lines.append("library ieee;")
    lines.append("use ieee.std_logic_1164.all;")
    lines.append("")
    lines.append("-" * 80)
    lines.append(f"-- DUT wrapper for scan chain testing -- generated by scripts/new_lab.py")
    lines.append(f"-- from {os.path.basename(src_file)}, entity {entity}.")
    lines.append("--")
    lines.append("-- Tracefile bit layout, MSB-first as written in the file:")
    lines.append("--")
    lines += layout_comment(in_fields, "input_vector")
    lines.append("--")
    lines += layout_comment(out_fields, "output_vector")
    lines.append("--")
    lines.append("-- Set in hdl/TopLevel.vhd:")
    lines.append(f"--   number_of_inputs  := {n_in}")
    lines.append(f"--   number_of_outputs := {n_out}")
    lines.append("--")
    lines.append("-- This comment is the only record of the bit mapping -- it cannot be")
    lines.append("-- recovered from the tracefile. Keep it with the file.")
    lines.append("-" * 80)
    lines.append("")
    lines.append("entity DUT is")
    lines.append("  port (")
    lines.append(f"    input_vector  : in  std_logic_vector({n_in - 1} downto 0);")
    lines.append(f"    output_vector : out std_logic_vector({n_out - 1} downto 0)")
    lines.append("  );")
    lines.append("end entity DUT;")
    lines.append("")
    lines.append("architecture Structural of DUT is")
    lines.append("")
    lines.append(f"  component {entity} is")
    lines.append("    port (")
    decls = []
    for f in in_fields + out_fields:
        p = f.port
        if p.is_vector:
            rng = (f"({p.high} downto {p.low})" if p.descending
                   else f"({p.low} to {p.high})")
            t = f"std_logic_vector{rng}"
        else:
            t = "std_logic"
        decls.append(f"      {p.name:<14}: {p.direction:<3} {t}")
    lines.append(";\n".join(decls))
    lines.append("    );")
    lines.append("  end component;")
    lines.append("")
    lines.append("begin")
    lines.append("")
    lines.append(f"  uut : {entity}")
    lines.append("    port map (")
    maps = []
    for f in in_fields:
        maps.append(f"      {f.port.name:<14} => {port_expr(f.port, f, 'input_vector')}")
    for f in out_fields:
        maps.append(f"      {f.port.name:<14} => {port_expr(f.port, f, 'output_vector')}")
    lines.append(",\n".join(maps))
    lines.append("    );")
    lines.append("")
    lines.append("end architecture Structural;")
    return "\n".join(lines) + "\n"


def patch_toplevel(path: str, n_in: int, n_out: int) -> bool:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    new, a = re.subn(r"(constant\s+number_of_inputs\s*:\s*integer\s*:=\s*)\d+",
                     rf"\g<1>{n_in}", text)
    new, b = re.subn(r"(constant\s+number_of_outputs\s*:\s*integer\s*:=\s*)\d+",
                     rf"\g<1>{n_out}", new)
    if not (a and b):
        return False
    if new != text:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new)
    return True


# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Generate a scan chain DUT wrapper from a VHDL entity.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Bit layout: clock at bit 0, reset at bit 1, remaining inputs\n"
               "above them with the first-declared port in the highest bits.")
    ap.add_argument("source", help="VHDL file containing the DUT entity")
    ap.add_argument("-e", "--entity", default=None,
                    help="entity name, if the file declares more than one")
    ap.add_argument("-o", "--out", default=None,
                    help="output path (default: DUT.vhd beside the source)")
    ap.add_argument("--clock", default=None, help="name of the clock port")
    ap.add_argument("--reset", default=None, help="name of the reset port")
    ap.add_argument("--no-special", action="store_true",
                    help="do not pin clock/reset to the low bits; lay every "
                         "port out in declaration order")
    ap.add_argument("--patch-toplevel", metavar="PATH", nargs="?",
                    const="hdl/TopLevel.vhd", default=None,
                    help="also update the width constants in TopLevel.vhd")
    ap.add_argument("-n", "--dry-run", action="store_true",
                    help="print the wrapper instead of writing it")
    args = ap.parse_args(argv)

    try:
        with open(args.source, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        entity, body = find_entity(strip_comments(raw), args.entity)
        ports = parse_ports(body)

        special = not args.no_special
        clock = args.clock or (autodetect(ports, CLOCK_NAMES) if special else None)
        reset = args.reset or (autodetect(ports, RESET_NAMES) if special else None)

        in_fields, n_in = lay_out(ports, "in", clock, reset, special)
        out_fields, n_out = lay_out(ports, "out", None, None, False)
    except ParseError as exc:
        print(f"error: {args.source}: {exc}", file=sys.stderr)
        return 2

    text = emit_wrapper(entity, args.source, in_fields, n_in, out_fields, n_out)

    print(f"entity {entity}: {n_in} input bits, {n_out} output bits")
    if clock:
        print(f"  clock = {clock} (bit 0)")
    if reset:
        print(f"  reset = {reset} (bit {1 if clock else 0})")
    print("  layout:")
    for f in in_fields:
        print(f"    input_vector[{f.hi}:{f.lo}]".ljust(26) + f"= {f.port.name}")
    for f in out_fields:
        print(f"    output_vector[{f.hi}:{f.lo}]".ljust(26) + f"= {f.port.name}")

    if args.dry_run:
        print("\n" + text)
        return 0

    out_path = args.out or os.path.join(os.path.dirname(
        os.path.abspath(args.source)), "DUT.vhd")
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(f"\nwrote {out_path}")

    if args.patch_toplevel:
        if patch_toplevel(args.patch_toplevel, n_in, n_out):
            print(f"patched {args.patch_toplevel}: "
                  f"number_of_inputs = {n_in}, number_of_outputs = {n_out}")
        else:
            print(f"warning: could not find the width constants in "
                  f"{args.patch_toplevel}; set them by hand", file=sys.stderr)
    else:
        print("\nNow set these in hdl/TopLevel.vhd (or rerun with "
              "--patch-toplevel):")
        print(f"  constant number_of_inputs  : integer := {n_in};")
        print(f"  constant number_of_outputs : integer := {n_out};")

    return 0


if __name__ == "__main__":
    sys.exit(main())
