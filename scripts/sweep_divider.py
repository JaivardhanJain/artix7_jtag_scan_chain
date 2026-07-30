#!/usr/bin/env python3
"""
Sweep the JTAG clock divider and find the fastest setting that still passes.

    python scripts/sweep_divider.py -t examples/alu/TRACEFILE.txt

Runs host/scanchain.py at each divider, several times, and tabulates pass/fail
and throughput. Reports the fastest divider that passed EVERY repeat.

Why repeats matter
------------------
A marginal clock does not fail cleanly -- it fails intermittently. A single
passing run at an aggressive divider is not evidence that the divider is safe;
it is one sample from a distribution. Three passes is still not proof, but it
distinguishes "works" from "worked once", which is the distinction that
matters when picking a default.

Why the vector count matters
----------------------------
At 46 vectors the runtime is dominated by USB round-trip latency, not by TCK.
Observed figures on the same 46-vector work ranged from 2878 to 9234 vectors/s
across identical runs -- that spread is host-side noise. Use a few hundred
vectors at minimum; examples/alu (256, exhaustive) or examples/seq1011 (602)
are the sensible choices.

Context
-------
The design carries no timing constraints, so Vivado never analysed the TDO
path (`place_design is not in timing mode`). That makes this sweep the only
source of information about the real margin -- there is no static-timing number
to compare against. See docs/KNOWN_ISSUES.md #2.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from typing import List, NamedTuple, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, ".."))
DRIVER = os.path.join(REPO, "host", "scanchain.py")

# Effective TCK base: TCK = FTDI_BASE_HZ / (divider + 1).
#
# This was 30_000_000 on the first run of this script, and that was WRONG by a
# factor of 5. The driver sends MPSSE opcode 0x8B, which ENABLES the
# divide-by-5 prescaler (0x8A disables it) -- both the original
# scan_bscane2.py and the rewrite commented it as a disable. So the master is
# 60/5 = 12 MHz and TCK = 12 MHz / (2 * (divider + 1)) = 6 MHz / (divider + 1).
#
# This is not a guess from a datasheet. The sweep's own timing measures it: at
# 24 TCK cycles per vector (counted from the encoders, 8-in/6-out) plus a
# constant ~6 us/vector of host cost, 6 MHz/(n+1) predicts all seven measured
# throughputs. 30 MHz/(n+1) leaves 200 us per vector unaccounted for at 0x3B.
# See docs/RESULTS.md section 5C.
FTDI_BASE_HZ = 6_000_000

# Default ladder, slowest first. 0x3B is the inherited setting.
DEFAULT_DIVIDERS = [0x3B, 0x1D, 0x0E, 0x06, 0x02, 0x01, 0x00]

SUMMARY_RE = re.compile(
    r"(\d+) vectors: (\d+) passed, (\d+) failed, (\d+) skipped")
RATE_RE = re.compile(r"([\d.]+) s elapsed, (\d+) vectors/s")


def tck_hz(divider: int) -> float:
    return FTDI_BASE_HZ / (divider + 1)


def fmt_hz(hz: float) -> str:
    if hz >= 1e6:
        return f"{hz / 1e6:.2f} MHz"
    return f"{hz / 1e3:.0f} kHz"


class Run(NamedTuple):
    ok: bool
    passed: int
    failed: int
    skipped: int
    rate: Optional[int]
    note: str


def run_once(tracefile: str, divider: int, channel: int) -> Run:
    cmd = [sys.executable, DRIVER, "-t", tracefile, "-o", os.devnull,
           "-d", hex(divider), "-c", str(channel)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return Run(False, 0, 0, 0, None, "TIMEOUT")

    out = p.stdout + p.stderr
    m = SUMMARY_RE.search(out)
    if not m:
        first = next((l for l in out.splitlines() if l.strip()), "no output")
        return Run(False, 0, 0, 0, None, f"no summary: {first[:60]}")

    total, passed, failed, skipped = (int(g) for g in m.groups())
    r = RATE_RE.search(out)
    rate = int(r.group(2)) if r else None
    return Run(p.returncode == 0 and failed == 0,
               passed, failed, skipped, rate, "")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Find the fastest reliable JTAG clock divider.")
    ap.add_argument("-t", "--tracefile", required=True)
    ap.add_argument("-c", "--channel", type=int, default=0)
    ap.add_argument("-n", "--repeats", type=int, default=3,
                    help="runs per divider (default 3). A marginal clock "
                         "fails intermittently, so one pass proves little.")
    ap.add_argument("-d", "--dividers", default=None,
                    help="comma-separated, e.g. 0x3B,0x1D,0x0E")
    args = ap.parse_args(argv)

    dividers = ([int(x, 0) for x in args.dividers.split(",")]
                if args.dividers else DEFAULT_DIVIDERS)

    print(f"tracefile : {args.tracefile}")
    print(f"repeats   : {args.repeats} per divider")
    print(f"dividers  : {', '.join(hex(d) for d in dividers)}")
    print()
    print(f"{'divider':>8}  {'TCK':>9}  {'result':>18}  {'vectors/s':>20}")
    print("-" * 64)

    results = {}
    for d in dividers:
        runs = [run_once(args.tracefile, d, args.channel)
                for _ in range(args.repeats)]
        results[d] = runs

        n_ok = sum(1 for r in runs if r.ok)
        rates = [r.rate for r in runs if r.rate is not None]

        if n_ok == len(runs):
            verdict = f"PASS {n_ok}/{len(runs)}"
        elif n_ok == 0:
            verdict = f"FAIL 0/{len(runs)}"
        else:
            verdict = f"INTERMITTENT {n_ok}/{len(runs)}"

        if rates:
            rate_s = (f"{min(rates)}-{max(rates)}" if min(rates) != max(rates)
                      else f"{rates[0]}")
        else:
            rate_s = "-"

        note = next((r.note for r in runs if r.note), "")
        print(f"{hex(d):>8}  {fmt_hz(tck_hz(d)):>9}  {verdict:>18}  "
              f"{rate_s:>20}  {note}")

    # Fastest divider (numerically smallest) that passed every repeat.
    clean = [d for d in dividers if all(r.ok for r in results[d])]
    print()
    if not clean:
        print("No divider passed every repeat. Either the board is not "
              "responding, or\nthe tracefile does not match the programmed "
              "design's widths. Check a single\nrun manually before trusting "
              "this table.")
        return 1

    baseline = 0x3B
    fastest = min(clean)
    print(f"Fastest divider passing all {args.repeats} repeats: "
          f"{hex(fastest)} ({fmt_hz(tck_hz(fastest))})")

    if baseline in results:
        base_rates = [r.rate for r in results[baseline] if r.rate]
        fast_rates = [r.rate for r in results[fastest] if r.rate]
        if base_rates and fast_rates:
            b, f = max(base_rates), max(fast_rates)
            print(f"Throughput at 0x3B (inherited): {b} vectors/s")
            print(f"Throughput at {hex(fastest)}:              {f} vectors/s")
            if f > b:
                print(f"Speed-up: {f / b:.2f}x")
            else:
                print("No throughput gain -- the run is dominated by USB "
                      "round-trip, not TCK.\nUse a larger tracefile, or report "
                      "this as a margin result rather than a speed one.")

    if fastest == baseline:
        print("\nThe inherited 0x3B is already the fastest setting that "
              "passes here.\nThat is a legitimate finding: it documents a "
              "safe operating point that\npreviously had no measurement "
              "behind it at all.")
    else:
        print(f"\nNOTE: {hex(fastest)} passing {args.repeats} times is not a "
              f"guarantee. Before changing\nthe default, run it many more "
              f"times, and prefer one divider step slower\nthan the fastest "
              f"that passes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
