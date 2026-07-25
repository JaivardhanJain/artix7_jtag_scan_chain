# ---------------------------------------------------------------------------
# Headless Hardware Manager programming.
#
#   vivado -mode batch -source scripts/program.tcl [-tclargs <path_to_bit>]
#
# Defaults to the bitstream produced by scripts/build.tcl.
#
# IMPORTANT: Vivado holds the FTDI cable open while the hardware target is
# open. This script closes the target on exit -- if you skip that, the host
# scan script cannot open the device. See docs/TROUBLESHOOTING.md.
#
# STATUS: not yet validated on hardware. Roadmap Phase 4.
# ---------------------------------------------------------------------------

set repo_root [file normalize [file join [file dirname [info script]] ..]]
set default_bit [file join $repo_root vivado build TopLevel.runs impl_1 TopLevel.bit]
set bitfile [expr {$argc > 0 ? [lindex $argv 0] : $default_bit}]

if {![file exists $bitfile]} {
    puts "ERROR: bitstream not found: $bitfile"
    puts "       run scripts/build.tcl first, or pass the path with -tclargs"
    exit 1
}

puts "=== bitstream: $bitfile"

open_hw_manager
connect_hw_server
open_hw_target

set dev [lindex [get_hw_devices] 0]
if {$dev eq ""} {
    puts "ERROR: no JTAG device detected. Check power and cable."
    close_hw_target
    exit 1
}
puts "=== device: $dev"
puts "=== idcode: [get_property REGISTER.IDCODE.BIT_STREAM $dev]"

current_hw_device $dev
refresh_hw_device -update_hw_probes false $dev
set_property PROGRAM.FILE $bitfile $dev
program_hw_devices $dev
refresh_hw_device $dev

# Release the cable so the host script can claim the FTDI channel.
close_hw_target
disconnect_hw_server
close_hw_manager

puts "=== SUCCESS: device programmed, JTAG cable released"
exit 0
