# ---------------------------------------------------------------------------
# Headless Hardware Manager programming.
#
#   scripts\program.bat                    (finds Vivado itself)
#   vivado -mode batch -source scripts/program.tcl [-tclargs <path_to_bit>]
#
# Defaults to the bitstream produced by scripts/build.tcl.
#
# RELEASING THE CABLE IS THE WHOLE POINT.
# Vivado holds the FTDI channel while a hardware target is open, and it also
# leaves hw_server / cs_server running in the background. Only one process can
# own the channel, so if this script exits without closing down, the host scan
# script fails with DEVICE_NOT_OPENED and the cause is not obvious.
#
# Every exit path therefore runs `shutdown`, including error paths -- an early
# version returned via `exit 1` on failure, left the cable held, and produced
# exactly that confusing failure one command later.
# ---------------------------------------------------------------------------

set repo_root [file normalize [file join [file dirname [info script]] ..]]
set default_bit [file join $repo_root vivado build TopLevel.runs impl_1 TopLevel.bit]
set bitfile [expr {$argc > 0 ? [lindex $argv 0] : $default_bit}]

# Release everything we opened. Each step is wrapped because the failure may
# have happened before that resource existed, and a cleanup error must not mask
# the original problem.
proc shutdown {} {
    catch {close_hw_target}
    catch {disconnect_hw_server}
    catch {close_hw_manager}
}

proc die {msg} {
    puts "ERROR: $msg"
    shutdown
    exit 1
}

if {![file exists $bitfile]} {
    puts "ERROR: bitstream not found: $bitfile"
    puts "       run scripts\\build.bat <example_dir> first,"
    puts "       or pass a path: scripts\\program.bat path\\to\\file.bit"
    exit 1
}

puts "=== bitstream: $bitfile"

open_hw_manager
connect_hw_server
open_hw_target

set dev [lindex [get_hw_devices] 0]
if {$dev eq ""} {
    die "no JTAG device detected. Check the board is powered and the cable seated."
}
puts "=== device   : $dev"

current_hw_device $dev
refresh_hw_device -update_hw_probes false $dev

# The device's IDCODE is deliberately NOT read here. The property that exposes
# it differs between Vivado versions and is only populated after a refresh --
# reading it too early is what broke the first version of this script. The host
# driver reads and prints the IDCODE itself over its own JTAG connection, which
# is both version-independent and a more meaningful check, since it exercises
# the same path the vectors will use.

set_property PROGRAM.FILE $bitfile $dev

# Read it back. A path containing spaces is the recurring hazard in this flow
# (see the note in build.tcl); programming a truncated path would surface as
# unexplained vector failures rather than an error.
set assigned [get_property PROGRAM.FILE $dev]
if {$assigned ne $bitfile} {
    puts "       wanted: $bitfile"
    puts "       got   : $assigned"
    die "PROGRAM.FILE did not take the value given."
}

if {[catch {program_hw_devices $dev} err]} {
    die "programming failed: $err"
}
refresh_hw_device $dev

shutdown

# --- Record what is now on the device ------------------------------------
# build.tcl writes a manifest describing what the bitstream expects. Copy it
# to a well-known path once the device has actually been programmed, so the
# host driver can refuse a tracefile whose widths disagree with the design
# currently loaded. The build manifest alone is not enough -- it describes the
# most recent *build*, which is not necessarily what is on the chip.
set src_manifest [file join $repo_root vivado build build_info.json]
set dst_manifest [file join $repo_root .programmed.json]
if {[file exists $src_manifest]} {
    # Assemble first, write once -- a partial write leaves invalid JSON, which
    # silently disables the host's check rather than reporting a problem.
    if {[catch {
        set in [open $src_manifest r]; set body [read $in]; close $in
        set body [string trimright $body]
        set body [string range $body 0 end-1]        ;# drop closing brace
        set body [string trimright $body]

        set when "unknown"
        catch {set when [clock format [clock seconds] -format {%Y-%m-%dT%H:%M:%S}]}

        set doc "$body,\n"
        append doc "  \"bitstream\": \"[string map {\\ /} $bitfile]\",\n"
        append doc "  \"programmed\": \"$when\"\n"
        append doc "}\n"

        set out [open $dst_manifest w]
        puts -nonewline $out $doc
        close $out
        puts "=== recorded : $dst_manifest"
    } err]} {
        puts "WARNING: could not write $dst_manifest: $err"
        puts "         The host will not be able to check tracefile widths."
    }
} else {
    puts "WARNING: no build manifest found at $src_manifest."
    puts "         Programming a bitstream this script did not build; the host"
    puts "         cannot check tracefile widths against it."
    catch {file delete $dst_manifest}
}

puts ""
puts "=== SUCCESS: device programmed, JTAG cable released"
puts "Next: python host\\scanchain.py -t <tracefile> -o output.txt"
exit 0
