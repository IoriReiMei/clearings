@echo off
rem SPDX-License-Identifier: MPL-2.0
rem Optional Windows handoff. index.html works without Python.
setlocal
set "CLEARINGS_SCRIPT=%~dp0tools\clearings_local.py"
if not exist "%CLEARINGS_SCRIPT%" (
  echo Clearings local helper is missing.
  pause
  exit /b 1
)
where py.exe >nul 2>&1
if not errorlevel 1 (
  py.exe -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
  if not errorlevel 1 (
    start "" pyw.exe -3 -B "%CLEARINGS_SCRIPT%" serve
    exit /b 0
  )
)
where python.exe >nul 2>&1
if not errorlevel 1 (
  python.exe -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
  if not errorlevel 1 (
    where pythonw.exe >nul 2>&1
    if not errorlevel 1 (
      start "" pythonw.exe -B "%CLEARINGS_SCRIPT%" serve
      exit /b 0
    )
  )
)
echo The optional local handoff needs Python 3.10 or newer on Windows.
echo Install Python or open index.html directly without the helper.
pause
exit /b 1
