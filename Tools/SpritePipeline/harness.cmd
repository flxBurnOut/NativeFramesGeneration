@echo off
setlocal

set "HARNESS_PYTHON=%SPRITE_PIPELINE_PYTHON%"

if not defined HARNESS_PYTHON if exist "%~dp0.venv\Scripts\python.exe" set "HARNESS_PYTHON=%~dp0.venv\Scripts\python.exe"
if not defined HARNESS_PYTHON for %%I in (python.exe) do set "HARNESS_PYTHON=%%~$PATH:I"
if not defined HARNESS_PYTHON if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" set "HARNESS_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if not defined HARNESS_PYTHON (
  >&2 echo Python 3.11+ was not found. Create .venv or set SPRITE_PIPELINE_PYTHON.
  exit /b 2
)

"%HARNESS_PYTHON%" "%~dp0cli.py" %*
exit /b %ERRORLEVEL%
