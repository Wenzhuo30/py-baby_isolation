@echo off
REM ---------------------------------------------------------------------------
REM tools\run_visual.cmd - Windows equivalent of run_visual.sh
REM
REM run_visual.sh calls "python3", which does not exist on a plain Windows
REM install (and needs bash/WSL to run at all). This wrapper runs the same
REM four worlds of the instructions with this project's virtual environment, so
REM the visual check works on Windows too.
REM
REM It lives in tools\ but always operates on the repository root, so it can be
REM launched from anywhere:
REM
REM     tools\run_visual.cmd                    -> world_easy (like the .sh default)
REM     tools\run_visual.cmd world_medium       -> one named world
REM     tools\run_visual.cmd world_medium hold 5 -> ...window auto-closed after 5s
REM     tools\run_visual.cmd all                -> all four worlds, one window each
REM     tools\run_visual.cmd all hold 5         -> ...each window auto-closed after 5s
REM
REM Each run opens the interactive IR-SIM window; close it to continue with the
REM next world, or add "hold N" to close it automatically after N seconds.
REM For a head-less batch that saves PNG snapshots instead, use:
REM     .venv\Scripts\python.exe tools\run_visual.py
REM ---------------------------------------------------------------------------
setlocal

REM %~dp0 is tools\ ; the repository root is one level up.
set "TOOLS=%~dp0"
for %%I in ("%TOOLS%..") do set "ROOT=%%~fI\"

set "PY=%ROOT%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "VISUAL=%TOOLS%run_visual.py"

if "%~1"=="" (
    set "WORLD=%ROOT%irsim_worlds\world_easy.yaml"
    goto run
)

if /I "%~1"=="all" (
    if /I "%~2"=="hold" (
        echo Running all four worlds, each window auto-closed after %~3s
        "%PY%" "%VISUAL%" --hold %~3
    ) else (
        echo Running all four worlds - close each window to continue
        "%PY%" "%VISUAL%" --show
    )
    goto done
)

REM A named world: accept "world_easy", "world_easy.yaml" or a full path.
REM An optional "hold N" closes the window by itself after N seconds.
set "WORLD=%~1"
if /I "%~2"=="hold" set "HOLD=--hold %~3"
echo %WORLD% | findstr /I "\.yaml$" >nul || set "WORLD=%WORLD%.yaml"
if not exist "%WORLD%" set "WORLD=%ROOT%irsim_worlds\%WORLD%"

:run
if not exist "%WORLD%" (
    echo World file not found: %WORLD%
    echo Available worlds:
    dir /b "%ROOT%irsim_worlds\*.yaml"
    exit /b 1
)
echo Running visual IR-SIM simulation
echo World: %WORLD%
echo Using generated\navigation_logic.py
echo.
if defined HOLD (
    "%PY%" "%VISUAL%" %HOLD% "%WORLD%"
) else (
    "%PY%" "%VISUAL%" --show "%WORLD%"
)

:done
endlocal
