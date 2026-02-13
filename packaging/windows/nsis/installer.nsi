; Yoto-UP Windows Installer
!include "MUI2.nsh"

Name "Yoto-UP"
OutFile "YotoUP-Setup.exe"
InstallDir "$PROGRAMFILES64\YotoUP"
RequestExecutionLevel admin

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_LANGUAGE "English"

Section "Install"
    SetOutPath "$INSTDIR"
    File /r "dist\yoto-up\*.*"

    CreateDirectory "$SMPROGRAMS\Yoto-UP"
    CreateShortCut "$SMPROGRAMS\Yoto-UP\Yoto-UP.lnk" "$INSTDIR\yoto-up.exe"
    CreateShortCut "$DESKTOP\Yoto-UP.lnk" "$INSTDIR\yoto-up.exe"

    WriteUninstaller "$INSTDIR\Uninstall.exe"

    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\YotoUP" "DisplayName" "Yoto-UP"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\YotoUP" "UninstallString" "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Uninstall"
    RMDir /r "$INSTDIR"
    Delete "$SMPROGRAMS\Yoto-UP\Yoto-UP.lnk"
    RMDir "$SMPROGRAMS\Yoto-UP"
    Delete "$DESKTOP\Yoto-UP.lnk"
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\YotoUP"
SectionEnd
