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
set dut_sources [concat \
    [glob -nocomplain [file join $repo_root $example_dir *.vhd]] \
    [glob -nocomplain [file join $repo_root $example_dir *.vhdl]]]
if {[llength $dut_sources] == 0} {
    puts "ERROR: no .vhd files found in $example_dir"
    exit 1
}
add_files -norecurse $dut_sources
foreach f $dut_sources { puts "=== added   : [file tail $f]" }

# --- Constraints ---------------------------------------------------------
# TopLevel has no ports, so the XDC is expected to be empty. Added only so
# Vivado has a constraints fileset.
#
# NOTE the [list ...] wrapper. Vivado's add_files list-parses its file
# argument, so a bare string containing spaces -- e.g. a repository under
# "Wadhwani Lab Research" -- is split into several nonexistent filenames and
# fails with "File or Directory 'Lab' does not exist". Wrapping in a
# single-element list is what makes paths with spaces work. Every add_files
# call in this file does it for the same reason.
set xdc [file join $repo_root hdl constraints.xdc]
if {[file exists $xdc]} {
    add_files -fileset constrs_1 -norecurse [list $xdc]
}

set_property target_language VHDL [current_project]
set_property top TopLevel [current_fileset]
update_compile_order -fileset sources_1

# --- Verify what actually landed in the project ---------------------------
# The original .xpr had drifted out of sync with the source tree -- TopLevel.vhd
# was not even listed (KNOWN_ISSUES #6). Checking here means a file silently
# failing to be added shows up now, with a useful message, rather than as an
# unbound-entity error several minutes into synthesis.
set expected [expr {2 + [llength $dut_sources]}]
set actual [llength [get_files -of_objects [get_filesets sources_1]]]
if {$actual != $expected} {
    puts "ERROR: expected $expected source files in the project, found $actual."
    puts "       In the project:"
    foreach f [get_files -of_objects [get_filesets sources_1]] {
        puts "         $f"
    }
    puts "       A path containing spaces is the usual cause -- Vivado's"
    puts "       add_files list-parses its argument. Every call here wraps the"
    puts "       path in \[list ...\]; if you added one, do the same."
    exit 1
}
puts "=== sources  : $actual files in the project, as expected"

if {[llength [get_files -of_objects [get_filesets constrs_1]]] == 0} {
    puts "WARNING: no constraints file in the project. Harmless for this design"
    puts "         (TopLevel has no ports) but unexpected."
}

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

# --- Manifest -------------------------------------------------------------
# Record what this bitstream expects, so the host can refuse a tracefile that
# does not match it.
#
# Without this there is nothing anywhere that ties a bitstream to a tracefile.
# Build one example, run another's vectors, and every scan is misaligned --
# the host takes its widths purely from the tracefile and the FPGA has no way
# to object. The result is not an error but a screen of plausible-looking
# failures, which is the worst outcome this project keeps running into.
set toplevel [file join $repo_root hdl TopLevel.vhd]
set n_in  ""
set n_out ""
if {[catch {
    set fh [open $toplevel r]
    set src [read $fh]
    close $fh
    regexp {number_of_inputs\s*:\s*integer\s*:=\s*(\d+)}  $src -> n_in
    regexp {number_of_outputs\s*:\s*integer\s*:=\s*(\d+)} $src -> n_out
} err]} {
    puts "WARNING: could not read widths from $toplevel: $err"
}

if {$n_in eq "" || $n_out eq ""} {
    puts "WARNING: widths not found in TopLevel.vhd -- no manifest written."
    puts "         The host will not be able to check the tracefile against"
    puts "         this bitstream."
} else {
    set manifest [file join $build_dir build_info.json]
    set fh [open $manifest w]
    puts $fh "{"
    puts $fh "  \"example\": \"$example_dir\","
    puts $fh "  \"part\": \"$part\","
    puts $fh "  \"number_of_inputs\": $n_in,"
    puts $fh "  \"number_of_outputs\": $n_out,"
    puts $fh "  \"built\": \"[clock format [clock seconds] -format {%Y-%m-%dT%H:%M:%S}]\""
    puts $fh "}"
    close $fh
    puts "=== manifest : $n_in in / $n_out out -> $manifest"
}

puts "=== SUCCESS: bitstream at $bit"
exit 0
