@echo off
cd /d "%~dp0"
title VySol
py -3.12 launcher\start.py
echo.
echo The launcher has stopped. Close this window when you are ready.
:wait
pause >nul
goto wait
