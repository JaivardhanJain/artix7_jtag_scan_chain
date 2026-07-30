@echo off
REM ---------------------------------------------------------------------------
REM Locate Vivado and put its tools on PATH. Shared by build.bat, program.bat
REM and sim/run_sim.bat so the search logic exists once.
REM
REM   call scripts\find_vivado.bat
REM   if errorlevel 1 exit /b 1
REM
REM Order: already on PATH -> %VIVADO_SETTINGS% -> search the usual roots.
REM ---------------------------------------------------------------------------

where vivado >nul 2>&1
if %errorlevel% equ 0 exit /b 0

where xvhdl >nul 2>&1
if %errorlevel% equ 0 exit /b 0

if defined VIVADO_SETTINGS (
    if exist "%VIVADO_SETTINGS%" (
        echo === sourcing %VIVADO_SETTINGS% ===
        call "%VIVADO_SETTINGS%"
        goto :verify
    )
    echo WARNING: VIVADO_SETTINGS points at "%VIVADO_SETTINGS%", which does not exist.
)

set "_FOUND="
for %%R in ("C:\Xilinx\Vivado" "D:\Xilinx\Vivado" "E:\Xilinx\Vivado" "C:\Program Files\Xilinx\Vivado" "C:\tools\Xilinx\Vivado") do (
    if exist %%~R (
        for /d %%V in (%%~R\*) do (
            if exist "%%~V\settings64.bat" set "_FOUND=%%~V\settings64.bat"
        )
    )
)

if not defined _FOUND (
    echo.
    echo ERROR: could not find Vivado.
    echo.
    echo   Searched for settings64.bat under:
    echo     C:\Xilinx\Vivado\*        D:\Xilinx\Vivado\*
    echo     E:\Xilinx\Vivado\*        C:\Program Files\Xilinx\Vivado\*
    echo     C:\tools\Xilinx\Vivado\*
    echo.
    echo   Point it at your install and try again:
    echo     set VIVADO_SETTINGS=C:\path\to\Vivado\20XX.X\settings64.bat
    echo.
    exit /b 1
)

echo === sourcing %_FOUND% ===
call "%_FOUND%"

:verify
where vivado >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ERROR: sourced the Vivado settings but 'vivado' is still not on PATH.
    echo        The installation may be incomplete.
    exit /b 1
)
exit /b 0
