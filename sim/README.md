# Simulation

A self-checking testbench for the scan chain logic. Run it before you touch the board.

```
cd sim
run_sim.bat          # Vivado xsim  (Windows)
./run_sim.sh         # GHDL         (anywhere)
```

Both exit non-zero if any test fails.

## Why this can exist now

`BSCANE2` lives only in Vivado's `unisim` library, and until recently the scan logic sat in the same file as the primitive. Simulating it meant pulling in `unisim` and a primitive model — so in practice nobody simulated, and every question about bit ordering or widths cost a full synthesise → implement → bitstream → program → run cycle.

The logic now lives in `hdl/scan_core.vhd`, which has **no vendor dependency**. The testbench plays the role `BSCANE2` plays on hardware: it drives `tck`, `capture`, `shift`, `update`, `jtag_reset` and `sel`, and reads `tdo`.

Crucially it **samples `tdo` while `tck` is low, immediately before the rising edge** — exactly what the host's MPSSE `0x2C`/`0x2E` reads see. So a launch/sample timing error that would appear on the bench appears here too.

## What it tests

| Test | Covers |
|---|---|
| **1 — Exhaustive scan** | All 256 input vectors shifted in, results shifted out and compared against a golden model. Exercises shift ordering, phase alternation, capture timing, and the falling-edge TDO launch ([#2](../docs/KNOWN_ISSUES.md)). |
| **2 — Desync recovery via TAP reset** | Abandons a vector after its input phase, leaving `io` at `'1'`, then pulses `jtag_reset` and runs a normal vector. **This fails on the original code** — it is the simulation equivalent of the Ctrl-C bench test for [#1](../docs/KNOWN_ISSUES.md). |
| **3 — Desync recovery via deselect** | Same, recovering through `sel = '0'` — the path taken when the TAP moves to another instruction, e.g. Vivado Hardware Manager taking the chain between runs. |
| **4 — Bit-order sensitivity** | Shifts **every** vector in backwards and requires that at least one comes back wrong. Without this, a testbench blind to bit order would look identical to one that works. |

Test 4 is the one that keeps the other three honest. Reversed bit order is the most common mistake when adapting the harness to a new DUT, and a testbench that isn't order-sensitive would never catch it.

It sweeps rather than testing a single vector for a reason. For some vectors the golden model returns the same answer forwards and backwards, so one unlucky choice passes a broken testbench. That is not hypothetical: the first version of this test used a single vector, and `model_scan_core.py` showed it was one of the 64-in-256 that are reversal-blind under this model. The sweep removes the dependence on picking a good vector, and on the model and widths staying as they are. Expect **192/256** detected at the default widths.

## `model_scan_core.py` — the offline reference model

```
python3 sim/model_scan_core.py
```

A Python re-implementation of `scan_core`'s cycle semantics, driven by the same sequence as the VHDL testbench. No toolchain, runs in under a second, exits non-zero on failure.

It is not a substitute for simulation — it cannot catch VHDL syntax or elaboration errors, and it only checks that the protocol logic is right, assuming the RTL does what the model says. Its value is speed, and keeping the testbench honest: it is what caught the Test 4 flaw above.

It also carries a `with_fixes=False` mode that models the **original** code, where `BSCANE2.RESET` and `SEL` were wired to `open`. Test 2b runs the interrupt scenario against it and confirms it desyncs — so the fix is demonstrated against a model of the defect, not just asserted.

## The DUT model

The testbench does not use a real DUT or a tracefile. It models one inline:

```vhdl
function dut_model (v : std_logic_vector(NUM_IN-1 downto 0))
  return std_logic_vector is
begin
  return v(NUM_OUT-1 downto 0) xor v(NUM_IN-1 downto NUM_IN-NUM_OUT);
end function;
```

and computes the expected result with the same function, so it is its own golden model. Mixing both halves of the input means a swapped, reversed or truncated vector cannot coincidentally produce the right answer.

Default widths are 8 in / 4 out, overridable via the `NUM_IN` / `NUM_OUT` generics. Testing a different width is a `xelab -generic_top` away — no tracefile to regenerate.

## What it does *not* cover

Scope discipline matters here, because it would be easy to over-claim what a green simulation proves.

- **`BSCANE2` itself.** The testbench substitutes for it. If the primitive's `CAPTURE`/`SHIFT`/`UPDATE` pulse timing differs from what's modelled here, only hardware will show it.
- **The host driver.** MPSSE command construction, USB batching and response decoding are all untested by this. Host-side unit tests are a separate piece of work ([roadmap](../docs/ROADMAP.md) Phase 3).
- **Real timing.** This is a functional simulation with an idealised clock. It proves the launch edge is *logically* correct; it does not tell you the maximum safe TCK frequency. That still needs the divider sweep on hardware.
- **Synthesis.** Simulating and synthesising are different. `run_sim.bat` passing does not guarantee `build.tcl` will.

A green run means the scan protocol logic is right. It does not mean the board will work.
