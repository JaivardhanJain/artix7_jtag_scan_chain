# ---------------------------------------------------------------------------
# Headless Vivado build for the Artix-7 JTAG scan chain.
#
#   vivado -mode batch -source scripts/build.tcl -tclargs <example_dir> [part]
#
# Example:
#   vivado -mode batch -source scripts/build.tcl -tclargs examples/string_detector
#
# Creates a throwaway project under vivado/build/, runs synthesis and
# implementation, and writes the bitstream to vivado/build/TopLevel.bit.
#
# STATUS: not yet validated on hardware. Roadmap Phase 4.
# ---------------------------------------------------------------------------

if {$argc < 1} {
    puts "ERROR: usage: vivado -mode batch -source scripts/build.tcl -tclargs <example_dir> \[part\]"
    exit 1
}

set example_dir [lindex $argv 0]
set part        [expr {$argc > 1 ? [lindex $argv 1] : "xc7a35tftg256-1"}]

# Repo root is the parent of this script's directory.
set repo_root [file normalize [file join [file dirname [info script]] ..]]
set build_dir [file join $repo_root vivado build]

if {![file isdirectory [file join $repo_root $example_dir]]} {
    puts "ERROR: example directory not found: $example_dir"
    exit 1
}

puts "=== repo    : $repo_root"
puts "=== example : $example_dir"
puts "=== part    : $part"

file mkdir $build_dir
create_project -force TopLevel $build_dir -part $part

# --- Harness -------------------------------------------------------------
add_files -norecurse [list \
    [file join $repo_root hdl scan_core.vhd] \
    [file join $repo_root hdl TopLevel.vhd]]

# --- DUT and its sources -------------------------------------------------
set dut_sources [glob -nocomplain [file join $repo_root $example_dir *.vhd]]
if {[llength $dut_sources] == 0} {
    puts "ERROR: no .vhd files found in $example_dir"
    exit 1
}
add_files -norecurse $dut_sources
foreach f $dut_sources { puts "=== added   : [file tail $f]" }

# --- Constraints ---------------------------------------------------------
# TopLevel has no ports, so the XDC is expected to be empty. Added only so
# Vivado has a constraints fileset.
set xdc [file join $repo_root hdl constraints.xdc]
if {[file exists $xdc]} {
    add_files -fileset constrs_1 -norecurse $xdc
}

set_property target_language VHDL [current_project]
set_property top TopLevel [current_fileset]
update_compile_order -fileset sources_1

# --- Build ---------------------------------------------------------------
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] != "100%"} {
    puts "ERROR: synthesis failed. See [file join $build_dir TopLevel.runs synth_1 runme.log]"
    exit 1
}

launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] != "100%"} {
    puts "ERROR: implementation failed. See [file join $build_dir TopLevel.runs impl_1 runme.log]"
    exit 1
}

set bit [file join $build_dir TopLevel.runs impl_1 TopLevel.bit]
puts "=== SUCCESS: bitstream at $bit"
exit 0
