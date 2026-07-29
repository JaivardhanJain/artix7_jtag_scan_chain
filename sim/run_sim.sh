#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# Run the scan_core testbench under GHDL.
#
#   cd sim && ./run_sim.sh
#
# GHDL is the lighter option if you don't want to start Vivado just to check a
# change. Install: apt install ghdl  /  brew install ghdl.
#
# Exits non-zero if any test fails.
# ----------------------------------------------------------------------------
set -e
cd "$(dirname "$0")"

WORK=./work
mkdir -p "$WORK"

echo "=== analysing ==="
ghdl -a --workdir="$WORK" ../hdl/scan_core.vhd tb_scan_core.vhd

echo "=== elaborating ==="
ghdl -e --workdir="$WORK" -o "$WORK/tb_scan_core" tb_scan_core

echo "=== simulating ==="
"$WORK/tb_scan_core" --assert-level=error

echo
echo "=== SIMULATION PASSED ==="
