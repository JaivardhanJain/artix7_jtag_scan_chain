@echo off
REM ---------------------------------------------------------------------------
REM Run the scan_core testbench under Vivado's simulator (xsim).
REM
REM Just double-click this file, or from any Command Prompt:
REM
REM   cd /d "<repo>\sim"
REM   run_sim.bat
REM
REM You do NOT need a Vivado command prompt -- if the tools aren't on PATH this
REM script looks for settings64.bat in the usual install locations and sources
REM it itself. Set VIVADO_SETTINGS to override the search.
REM
REM This is NOT run from the Vivado GUI's Tcl console; it's a batch file.
REM
REM No unisim library is needed: scan_core.vhd contains no vendor primitives.
REM That is the whole reason it was split out of TopLevel.vhd.
REM
REM Exit code is non-zero if any test fails, so this can gate a build.
REM ---------------------------------------------------------------------------

setlocal enabledelayedexpansion
cd /d "%~dp0"

REM --- Find the Vivado tools -------------------------------------------------
where xvhdl >nul 2>&1
if %errorlevel% equ 0 (
    echo === using Vivado already on PATH ===
    goto :have_tools
)

if defined VIVADO_SETTINGS (
    if exist "%VIVADO_SETTINGS%" (
        echo === sourcing %VIVADO_SETTINGS% ===
        call "%VIVADO_SETTINGS%"
        goto :check_tools
    )
    echo WARNING: VIVADO_SETTINGS is set but "%VIVADO_SETTINGS%" does not exist.
)

REM Search the usual install roots, newest version last so it wins.
set "FOUND="
for %%R in ("C:\Xilinx\Vivado" "D:\Xilinx\Vivado" "C:\Program Files\Xilinx\Vivado" "C:\Xilinx\2024.1\Vivado" "C:\Xilinx\2023.2\Vivado") do (
    if exist %%~R (
        for /d %%V in (%%~R\*) do (
            if exist "%%~V\settings64.bat" set "FOUND=%%~V\settings64.bat"
        )
    )
)

if not defined FOUND (
    echo.
    echo ERROR: could not find Vivado.
    echo.
    echo   Looked for settings64.bat under:
    echo     C:\Xilinx\Vivado\*
    echo     D:\Xilinx\Vivado\*
    echo     C:\Program Files\Xilinx\Vivado\*
    echo.
    echo   Fix it either way:
    echo     1. Open the "Vivado ... Command Prompt" from the Start menu and
    echo        run this script from there, or
    echo     2. set VIVADO_SETTINGS=C:\path\to\Vivado\20XX.X\settings64.bat
    echo        and run this script again.
    echo.
    endlocal
    exit /b 1
)

echo === sourcing !FOUND! ===
call "!FOUND!"

:check_tools
where xvhdl >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ERROR: sourced the Vivado settings but xvhdl is still not on PATH.
    echo        The install may be incomplete.
    endlocal
    exit /b 1
)

:have_tools

REM --- Build and run ---------------------------------------------------------
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
