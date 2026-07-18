; horreum-installer.nsi -- per-user NSIS installer for the frozen Horreum app.
; ASCII-ONLY on purpose (like build.ps1): avoids source-encoding mojibake.
; Visible Polish UI text comes from the MUI Polish language file, not this script.
;
; Pattern mirrors mentor-flux (electron-builder NSIS): one Setup.exe, wizard,
; desktop + Start Menu shortcuts, uninstaller. Differences (hobby OSS, not a
; client deployment): per-user install (RequestExecutionLevel user -> no UAC),
; no bundled runtimes/drivers, distributed via GitHub Releases.
;
; Build: packaging\make-installer.ps1 (passes /DVERSION, runs makensis from the
; electron-builder NSIS cache). Requires dist\horreum\ (run build.ps1 first).

Unicode true

!ifndef VERSION
  !define VERSION "0.0.0"
!endif
; ROOT = repo root (absolute), passed by make-installer.ps1 so File/OutFile paths
; resolve regardless of makensis' working directory (it resolves relative File
; paths against the script's own dir, not the repo).
!ifndef ROOT
  !define ROOT "."
!endif
!define PRODUCT "Horreum"
!define EXE "horreum-gui.exe"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT}"

Name "${PRODUCT} ${VERSION}"
OutFile "${ROOT}\release\Horreum-Setup-${VERSION}.exe"
; Per-user: install under the user's profile, no administrator elevation.
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\Programs\${PRODUCT}"
InstallDirRegKey HKCU "Software\${PRODUCT}" "InstallDir"
SetCompressor /SOLID lzma
ShowInstDetails show
ShowUninstDetails show

!include "MUI2.nsh"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXE}"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Polish"

Section "Horreum" SecMain
  SetOutPath "$INSTDIR"
  ; Whole frozen onedir tree (exe + exe + _internal\), structure preserved.
  File /r "${ROOT}\dist\horreum\*"
  ; User guide alongside the app.
  File "${ROOT}\doc\instrukcja.md"

  CreateShortCut "$DESKTOP\${PRODUCT}.lnk" "$INSTDIR\${EXE}"
  CreateDirectory "$SMPROGRAMS\${PRODUCT}"
  CreateShortCut "$SMPROGRAMS\${PRODUCT}\${PRODUCT}.lnk" "$INSTDIR\${EXE}"
  CreateShortCut "$SMPROGRAMS\${PRODUCT}\Instrukcja.lnk" "$INSTDIR\instrukcja.md"
  CreateShortCut "$SMPROGRAMS\${PRODUCT}\Uninstall.lnk" "$INSTDIR\Uninstall.exe"

  ; Per-user uninstall entry (HKCU -> shows in Settings > Apps for this user).
  WriteRegStr HKCU "Software\${PRODUCT}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${PRODUCT} ${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "Zdzislaw Sabat"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\${EXE}"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
  WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\${PRODUCT}.lnk"
  RMDir /r "$SMPROGRAMS\${PRODUCT}"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegKey HKCU "Software\${PRODUCT}"
SectionEnd
