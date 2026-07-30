@echo off
REM ---------------------------------------------------------------------------
REM Build a bitstream. Finds Vivado itself -- no Vivado command prompt needed,
REM and it works the same from cmd or PowerShell.
REM
REM   scripts\build.bat examples\seq1011
REM   scripts\build.bat examples\alu xc7a15tftg256-1
REM
REM From PowerShell, prefix with .\ if you are in the scripts directory.
REM ---------------------------------------------------------------------------

setlocal
set "REPO=%~dp0.."

if "%~1"=="" (
    echo usage: scripts\build.bat ^<example_dir^> [part]
    echo.
    echo   scripts\build.bat examples\seq1011
    echo   scripts\build.bat examples\string_detector
    echo   scripts\build.bat examples\alu
    endlocal
    exit /b 1
)

call "%~dp0find_vivado.bat"
if errorlevel 1 (
    endlocal
    exit /b 1
)

REM Tcl wants forward slashes; accept either from the caller.
set "EXDIR=%~1"
set "EXDIR=%EXDIR:\=/%"

echo === building %EXDIR% ===
pushd "%REPO%"
if "%~2"=="" (
    call vivado -mode batch -source scripts/build.tcl -tclargs "%EXDIR%"
) else (
    call vivado -mode batch -source scripts/build.tcl -tclargs "%EXDIR%" "%~2"
)
set "RC=%errorlevel%"
popd

if %RC% neq 0 (
    echo.
    echo === BUILD FAILED ===
    echo See vivado.log in the repository root, and the runme.log under
    echo vivado\build\TopLevel.runs\ for the failing stage.
    endlocal
    exit /b 1
)

echo.
echo === BUILD OK ===
echo Bitstream: vivado\build\TopLevel.runs\impl_1\TopLevel.bit
echo Next: scripts\program.bat
endlocal
exit /b 0
