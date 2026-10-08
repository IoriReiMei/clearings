@echo off
rem SPDX-License-Identifier: MIT
rem MIT License
rem
rem Copyright (c) 2026 The Hermit
rem
rem Permission is hereby granted, free of charge, to any person obtaining a copy
rem of this software and associated documentation files (the "Software"), to deal
rem in the Software without restriction, including without limitation the rights
rem to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
rem copies of the Software, and to permit persons to whom the Software is
rem furnished to do so, subject to the following conditions:
rem
rem The above copyright notice and this permission notice shall be included in all
rem copies or substantial portions of the Software.
rem
rem THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
rem IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
rem FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
rem AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
rem LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
rem OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
rem SOFTWARE.
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
