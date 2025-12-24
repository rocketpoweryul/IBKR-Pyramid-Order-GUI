@echo off
REM Ensure we run from the directory this file lives in
cd /d "%~dp0"

REM Activate the virtual environment
call .venv\Scripts\activate.bat

REM Optional: show which python is being used (debug aid)
REM where python

REM Run the tool
python OrderEntryPyramid.py

REM Keep window open if the script exits or crashes
pause
