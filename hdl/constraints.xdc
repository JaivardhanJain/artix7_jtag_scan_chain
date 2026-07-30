# ---------------------------------------------------------------------------
# Constraints for the JTAG scan chain harness.
#
# Intentionally empty.
#
# TopLevel has no ports -- every input and output travels over the JTAG TAP via
# BSCANE2 -- so there is nothing to place and no I/O standard to declare. This
# file exists only so Vivado has a constraints fileset.
#
# What used to be here, and why it is gone (docs/KNOWN_ISSUES.md #7):
#
#   set_property IOSTANDARD LVCMOS33 [get_ports state_out[*]]
#   set_property SEVERITY Warning [get_drc_checks UCIO-1]
#
# The first constrained a `state_out` debug port that is commented out in
# TopLevel.vhd, so `get_ports` matched nothing at all. The second downgraded
# the unconstrained-I/O DRC error that port used to cause.
#
# The DRC downgrade is the one that mattered. Leaving UCIO-1 suppressed means a
# genuinely unconstrained port -- in any DUT added later -- passes silently
# instead of failing the build. Do not re-add it.
#
# If you want the debug port back, add real pin assignments rather than
# suppressing the check:
#
#   set_property PACKAGE_PIN <pin> [get_ports {state_out[0]}]
#   set_property IOSTANDARD LVCMOS33 [get_ports {state_out[*]}]
#
# See docs/TROUBLESHOOTING.md, "How do I see what's actually on the wire?".
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Device configuration properties -- not I/O constraints.
#
# Without these, write_bitstream emits:
#   WARNING: [DRC CFGBVS-1] Missing CFGBVS and CONFIG_VOLTAGE Design Properties
#
# They declare the supply voltage on configuration bank 0 so the tools can
# reason about its I/O voltage support. The design uses no I/O, so this is
# cosmetic here -- but the warning is legitimate and silencing it correctly is
# better than learning to ignore it.
#
# 3.3 V with CFGBVS tied to VCCO covers the common Artix-7 boards (Arty A7,
# Cmod A7, Basys 3, Nexys A7). If your board configures bank 0 at 1.8 V or
# 2.5 V, change CONFIG_VOLTAGE to match -- check the board schematic, not this
# comment.
# ---------------------------------------------------------------------------
set_property CFGBVS VCCO [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]

# ---------------------------------------------------------------------------
# OPTIONAL: constrain TCK so the tools actually time the design.
#
# The build currently reports:
#   WARNING: [Timing 38-313] There are no user specified timing constraints.
#   WARNING: [Place 46-29] place_design is not in timing mode.
#   INFO:    [Route 35-64] The router will operate in resource-optimization mode
#
# That means place and route ran with no timing goal at all, and the TDO
# launch-to-sample path -- the subject of KNOWN_ISSUES #2 -- was never
# analysed. It works, but nothing has computed how much margin exists.
#
# Constraining the JTAG clock would let report_timing give a real number
# instead of relying solely on the empirical divider sweep. Uncomment and
# adjust the pin name for your Vivado version:
#
#   create_clock -name jtag_tck -period 2000.000 [get_pins bscan_inst/TCK]
#
# 2000 ns = 500 kHz, the current default divider. Left commented because the
# exact object to attach the clock to varies between Vivado versions, and a
# wrong reference fails the build -- verify it before relying on it.
# ---------------------------------------------------------------------------
