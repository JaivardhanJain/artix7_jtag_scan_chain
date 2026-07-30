@echo off
REM ---------------------------------------------------------------------------
REM Run the scan_core testbench under Vivado's simulator (xsim).
REM
REM Just double-click this file, or from any Command Prompt:
REM
REM   cd /d "<repo>\sim"
REM   run_sim.bat
REM
REM From PowerShell:  .\run_sim.bat
REM
REM You do NOT need a Vivado command prompt -- scripts\find_vivado.bat locates
REM the install and sources settings64.bat. Set VIVADO_SETTINGS to override.
REM
REM This is NOT run from the Vivado GUI's Tcl console; it's a batch file.
REM
REM No unisim library is needed: scan_core.vhd contains no vendor primitives.
REM That is the whole reason it was split out of TopLevel.vhd.
REM
REM Exit code is non-zero if any test fails, so this can gate a build.
REM ---------------------------------------------------------------------------

setlocal
cd /d "%~dp0"

call "%~dp0..\scripts\find_vivado.bat"
if errorlevel 1 (
    endlocal
    exit /b 1
)

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
echo Expect: 4 tests, 0 errors, and "192 of 256 reversed vectors detected".
endlocal
exit /b 0

:fail
echo.
echo === SIMULATION FAILED ===
echo See the messages above. Compile errors point at hdl\scan_core.vhd or
echo tb_scan_core.vhd; assertion failures mean the logic disagrees with the
echo model in sim\model_scan_core.py.
endlocal
exit /b 1
