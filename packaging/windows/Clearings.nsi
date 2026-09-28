; SPDX-License-Identifier: MPL-2.0
; Build with makensis /DSOURCE_DIR=<native dist> /DOUTPUT_DIR=<artifacts>.
!include "MUI2.nsh"
!define VERSION "0.4.2"

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
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\Clearings.exe"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "Install"
  SetShellVarContext current
  SetOutPath "$INSTDIR"
  File /r "${SOURCE_DIR}\Clearings\*"
  CreateDirectory "$SMPROGRAMS\Clearings"
  CreateShortCut "$SMPROGRAMS\Clearings\Clearings.lnk" "$INSTDIR\Clearings.exe"
  CreateShortCut "$DESKTOP\Clearings.lnk" "$INSTDIR\Clearings.exe"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Clearings" "DisplayName" "Clearings"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Clearings" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Clearings" "UninstallString" '$"$INSTDIR\Uninstall.exe$"'
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  Delete "$SMPROGRAMS\Clearings\Clearings.lnk"
  RMDir "$SMPROGRAMS\Clearings"
  Delete "$DESKTOP\Clearings.lnk"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Clearings"
  ; Only remove the installed program directory. Browser and handoff data live elsewhere.
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\Clearings.exe"
  Delete "$INSTDIR\source.zip"
  Delete "$INSTDIR\PYTHON_LICENSE.txt"
  Delete "$INSTDIR\PYINSTALLER_LICENSE.txt"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
SectionEnd
