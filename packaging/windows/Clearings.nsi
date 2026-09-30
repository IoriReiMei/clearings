; SPDX-License-Identifier: MPL-2.0
; Build with makensis /DSOURCE_DIR=<native dist> /DOUTPUT_DIR=<artifacts>.
!include "MUI2.nsh"
!define VERSION "0.4.4"

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
  ; Use the new helper for old releases that had no stop command.
  InitPluginsDir
  SetOutPath "$PLUGINSDIR\ClearingsStop"
  File /r "${SOURCE_DIR}\Clearings\*"
  ClearErrors
  ExecWait '"$PLUGINSDIR\ClearingsStop\Clearings.exe" stop --installation "$INSTDIR\Clearings.exe"' $0
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
