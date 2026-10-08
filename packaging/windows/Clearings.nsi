; SPDX-License-Identifier: MIT
; MIT License
;
; Copyright (c) 2026 The Hermit
;
; Permission is hereby granted, free of charge, to any person obtaining a copy
; of this software and associated documentation files (the "Software"), to deal
; in the Software without restriction, including without limitation the rights
; to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
; copies of the Software, and to permit persons to whom the Software is
; furnished to do so, subject to the following conditions:
;
; The above copyright notice and this permission notice shall be included in all
; copies or substantial portions of the Software.
;
; THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
; IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
; FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
; AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
; LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
; OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
; SOFTWARE.
; Build with makensis /DSOURCE_DIR=<native dist> /DOUTPUT_DIR=<artifacts>.
!include "MUI2.nsh"
!define VERSION "0.4.6"

Name "Clearings"
OutFile "${OUTPUT_DIR}\Clearings-Setup-${VERSION}-Windows-x64.exe"
InstallDir "$LOCALAPPDATA\Programs\Clearings"
RequestExecutionLevel user
Unicode true
SetCompressor /SOLID lzma
ShowInstDetails show

!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!define MUI_COMPONENTSPAGE_TEXT_TOP "Choose any shortcuts you want. Both are optional and unchecked by default."
!define MUI_COMPONENTSPAGE_NODESC
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\Clearings.exe"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "-Install Clearings"
  SetShellVarContext current
  IfFileExists "$INSTDIR\Clearings.exe" 0 install_ready
  ; The installed CLI proves the identity of its own running helper.
  ; A different staged version must not authenticate or stop that process.
  IfFileExists "$INSTDIR\ClearingsCLI.exe" 0 install_stop_failed
  ClearErrors
  ExecWait '"$INSTDIR\ClearingsCLI.exe" stop --installation "$INSTDIR\Clearings.exe"' $0
  IfErrors install_stop_failed
  StrCmp $0 0 install_ready
  install_stop_failed:
  MessageBox MB_OK|MB_ICONSTOP "Clearings could not stop the earlier helper. Close it and retry. Your installation and workspace have not been changed." /SD IDOK
  SetErrorLevel 1
  Abort
  install_ready:
  SetOutPath "$INSTDIR"
  File /r "${SOURCE_DIR}\Clearings\*"
  ; Replace the previous installer's shortcut choices on an update.
  Delete "$SMPROGRAMS\Clearings\Clearings.lnk"
  RMDir "$SMPROGRAMS\Clearings"
  Delete "$DESKTOP\Clearings.lnk"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Clearings" "DisplayName" "Clearings"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Clearings" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Clearings" "UninstallString" "$\"$INSTDIR\Uninstall.exe$\""
SectionEnd

Section /o "Start Menu shortcut" SecStartMenu
  SetShellVarContext current
  CreateDirectory "$SMPROGRAMS\Clearings"
  CreateShortCut "$SMPROGRAMS\Clearings\Clearings.lnk" "$INSTDIR\Clearings.exe"
SectionEnd

Section /o "Desktop shortcut" SecDesktop
  SetShellVarContext current
  CreateShortCut "$DESKTOP\Clearings.lnk" "$INSTDIR\Clearings.exe"
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  ClearErrors
  ExecWait '"$INSTDIR\Clearings.exe" stop' $0
  IfErrors uninstall_stop_failed
  StrCmp $0 0 uninstall_ready
  uninstall_stop_failed:
  MessageBox MB_OK|MB_ICONSTOP "Clearings could not stop its helper. Close it and retry. No program files were removed." /SD IDOK
  SetErrorLevel 1
  Abort
  uninstall_ready:
  ClearErrors
  Delete "$SMPROGRAMS\Clearings\Clearings.lnk"
  RMDir "$SMPROGRAMS\Clearings"
  Delete "$DESKTOP\Clearings.lnk"
  ; Only remove the installed program directory. Browser and handoff data live elsewhere.
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\Clearings.exe"
  Delete "$INSTDIR\ClearingsCLI.exe"
  Delete "$INSTDIR\source.zip"
  Delete "$INSTDIR\PYTHON_LICENSE.txt"
  Delete "$INSTDIR\PYINSTALLER_LICENSE.txt"
  IfFileExists "$INSTDIR\Clearings.exe" uninstall_failed
  IfFileExists "$INSTDIR\ClearingsCLI.exe" uninstall_failed
  IfFileExists "$INSTDIR\_internal\*.*" uninstall_failed uninstall_success
  uninstall_failed:
  MessageBox MB_OK|MB_ICONSTOP "Some Clearings program files could not be removed. Your workspace data was kept." /SD IDOK
  SetErrorLevel 1
  Goto uninstall_done
  uninstall_success:
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Clearings"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  uninstall_done:
SectionEnd
