@echo off
REM ---------------------------------------------------------------------------
REM Program the board. Finds Vivado itself.
REM
REM   scripts\program.bat
REM   scripts\program.bat path\to\some.bit
REM
REM Releases the JTAG cable on exit so the host scan script can claim the FTDI
REM channel afterwards. The Vivado GUI does not do that -- if Hardware Manager
REM is open, close it first.
REM ---------------------------------------------------------------------------

setlocal
set "REPO=%~dp0.."

call "%~dp0find_vivado.bat"
if errorlevel 1 (
    endlocal
    exit /b 1
)

pushd "%REPO%"
if "%~1"=="" (
    call vivado -mode batch -source scripts/program.tcl
) else (
    call vivado -mode batch -source scripts/program.tcl -tclargs "%~1"
)
set "RC=%errorlevel%"
popd

if %RC% neq 0 (
    echo.
    echo === PROGRAMMING FAILED ===
    echo Common causes:
    echo   - board not connected or not powered
    echo   - Vivado GUI has the cable open ^(close Hardware Manager^)
    echo   - no bitstream yet: run scripts\build.bat first
    endlocal
    exit /b 1
)

echo.
echo === PROGRAMMED OK, cable released ===
echo Next: python host\scanchain.py -t ^<tracefile^> -o output.txt
endlocal
exit /b 0
