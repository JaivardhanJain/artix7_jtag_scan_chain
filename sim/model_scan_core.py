#!/usr/bin/env python3
"""
Offline reference model of hdl/scan_core.vhd.

Re-implements the RTL's cycle semantics in Python and drives it with the same
sequence tb_scan_core.vhd uses. Runs anywhere, needs no VHDL toolchain, and
finishes in well under a second -- so it is the fastest way to sanity-check a
change to the scan protocol, the bit ordering, or the testbench itself before
paying for a simulator run.

It is a *model*, not a substitute for simulation: it cannot catch VHDL syntax
or elaboration errors, and it assumes the RTL says what this file says it says.
Its value is in checking the protocol logic and in keeping the testbench honest.

It has already earned its keep: it found that the original TEST 4 in
tb_scan_core.vhd used a golden function and a vector for which bit-reversal was
undetectable, so the test would have passed a testbench that was blind to bit
order. TEST 4 is now a sweep.

Usage:  python3 sim/model_scan_core.py
Exit code is non-zero if any check fails.
"""

import sys

NUM_IN = 8
NUM_OUT = 4

# Bit lists are LSB-first: v[0] is bit 0. This mirrors std_logic_vector indexing
# in scan_core, where data(0) is the bit presented on tdo.


def dut_model(v):
    """The DUT the testbench models: low slice xor high slice."""
    return [v[i] ^ v[NUM_IN - NUM_OUT + i] for i in range(NUM_OUT)]


def bits(n, width):
    return [(n >> i) & 1 for i in range(width)]


class ScanCore:
    """Cycle model of scan_core.vhd."""

    def __init__(self, with_fixes=True):
        # with_fixes=False models the ORIGINAL code, where BSCANE2.RESET and
        # SEL were wired to `open` so nothing could ever clear `io`.
        self.with_fixes = with_fixes
        self.data = [0] * NUM_IN     # input shift register
        self.datau = [0] * NUM_OUT   # output shift register
        self.din = [0] * NUM_IN      # latched DUT input
        self.io = 0                  # phase bit
        self.tdo = 0                 # tdo tracks datau[0] combinationally

    def dut_output(self):
        return dut_model(self.din)

    def rising(self, tdi=0, capture=0, shift=0, update=0, jtag_reset=0, sel=1):
        if self.with_fixes:
            if jtag_reset:
                self.io = 0          # asynchronous in the RTL
                return
            if sel == 0:
                self.io = 0
                return
        if update:
            was = self.io
            self.io = 1 - self.io
            if was == 0:
                self.din = list(self.data)
        elif capture:
            if self.io == 1:
                self.datau = list(self.dut_output())
        elif shift:
            if self.io == 0:
                # data <= tdi & data(N-1 downto 1)
                self.data = [self.data[k + 1] for k in range(NUM_IN - 1)] + [tdi]
            else:
                self.datau = [self.datau[k + 1] for k in range(NUM_OUT - 1)] + [0]

    def falling(self):
        # tdo is combinational from datau(0) in the RTL. Sampling it here, at
        # the end of the cycle, is equivalent for a driver that reads before
        # the next rising edge.
        #
        # NOTE: this model CANNOT distinguish a combinational tdo from a
        # falling-edge-registered one -- both produce the same value at this
        # point. Neither can the VHDL testbench. That blind spot is why the
        # falling-edge "fix" for KNOWN_ISSUES #2 passed both and still failed
        # on hardware: BSCANE2's own TDO sampling is the thing being violated,
        # and BSCANE2 is exactly what these substitute for.
        self.tdo = self.datau[0]


class Driver:
    """Plays the role of BSCANE2 / the host, as tb_scan_core.vhd does."""

    def __init__(self, core):
        self.c = core

    def tick(self, **kw):
        self.c.rising(**kw)
        self.c.falling()

    def tap_reset(self):
        # Asynchronous: deliberately no clock edge, matching the RTL.
        self.c.rising(jtag_reset=1)

    def scan_in(self, v, reversed_=False):
        self.tick(capture=1)
        for i in range(NUM_IN):
            self.tick(tdi=(v[NUM_IN - 1 - i] if reversed_ else v[i]), shift=1)
        self.tick(update=1)

    def scan_out(self):
        self.tick(capture=1)
        r = []
        for _ in range(NUM_OUT):
            r.append(self.c.tdo)   # sampled while tck low, before the rising edge
            self.tick(shift=1)
        self.tick(update=1)
        return r


def main():
    errors = 0
    checks = 0

    def chk(cond, msg):
        nonlocal errors, checks
        checks += 1
        if not cond:
            errors += 1
            print(f"  FAIL {msg}")

    core = ScanCore()
    d = Driver(core)

    d.tap_reset()
    chk(core.io == 0, "jtag_reset did not clear io")

    # TEST 1 -- exhaustive
    for n in range(2 ** NUM_IN):
        v = bits(n, NUM_IN)
        d.scan_in(v)
        chk(d.scan_out() == dut_model(v), f"T1 vector {n}")
    print(f"TEST 1 exhaustive scan      : {2**NUM_IN} vectors, {errors} errors")

    # TEST 2 -- desync recovery via TAP reset
    d.scan_in(bits(0xA5, NUM_IN))          # input phase only: io left at 1
    chk(core.io == 1, "T2 setup: io should be 1 after a lone input phase")
    d.tap_reset()
    chk(core.io == 0, "T2: jtag_reset did not clear io")
    v = bits(0x3C, NUM_IN)
    d.scan_in(v)
    chk(d.scan_out() == dut_model(v), "T2 post-reset vector")
    print(f"TEST 2 desync via TAP reset : {errors} errors")

    # TEST 2b -- the same scenario against the ORIGINAL code
    orig = Driver(ScanCore(with_fixes=False))
    orig.scan_in(bits(0xA5, NUM_IN))       # interrupted run
    v = bits(0x3C, NUM_IN)
    orig.scan_in(v)
    got = orig.scan_out()
    desynced = got != dut_model(v)
    chk(desynced, "T2b: original code did NOT desync -- model may be wrong")
    print(f"TEST 2b original code       : after interruption got {got}, "
          f"expected {dut_model(v)} -> {'desynced as expected' if desynced else 'NO DESYNC?!'}")

    # TEST 3 -- desync recovery via deselect
    d.scan_in(bits(0x5A, NUM_IN))
    d.tick(sel=0)
    chk(core.io == 0, "T3: deselect did not clear io")
    v = bits(0x77, NUM_IN)
    d.scan_in(v)
    chk(d.scan_out() == dut_model(v), "T3 post-deselect vector")
    print(f"TEST 3 desync via deselect  : {errors} errors")

    # TEST 4 -- bit-order sensitivity, swept
    d.tap_reset()
    detected = 0
    for n in range(2 ** NUM_IN):
        v = bits(n, NUM_IN)
        d.scan_in(v, reversed_=True)
        if d.scan_out() != dut_model(v):
            detected += 1
    chk(detected > 0, "T4: no reversed vector detected -- blind to bit order")
    print(f"TEST 4 bit-order sensitivity: {detected}/{2**NUM_IN} reversed "
          f"vectors detected as wrong")

    print(f"\n=== {checks} checks, {errors} errors ===")
    print("ALL PASSED" if errors == 0 else "FAILED")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
