@echo off
REM ---------------------------------------------------------------------------
REM Run the scan_core testbench under Vivado's simulator.
REM
REM   cd sim
REM   run_sim.bat
REM
REM Requires the Vivado tools on PATH (run from a Vivado command prompt, or
REM source settings64.bat first). Nothing else -- scan_core has no vendor
REM primitives, so no unisim library is needed.
REM
REM Exit code is non-zero if any test fails, so this can gate a build.
REM ---------------------------------------------------------------------------

setlocal
cd /d "%~dp0"

echo === analysing ===
call xvhdl ..\hdl\scan_core.vhd tb_scan_core.vhd
if errorlevel 1 goto :fail

echo === elaborating ===
call xelab -debug typical tb_scan_core -s tb_snapshot
if errorlevel 1 goto :fail

echo === simulating ===
call xsim tb_snapshot -runall
if errorlevel 1 goto :fail

echo.
echo === SIMULATION PASSED ===
endlocal
exit /b 0

:fail
echo.
echo === SIMULATION FAILED ===
endlocal
exit /b 1
