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
