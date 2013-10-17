;--------------------------------
;Hiveary
;https://hiveary.com
;
;Licensed under Simplified BSD License (see LICENSE)
;(C) Hiveary, LLC 2013 all rights reserved
;--------------------------------

!include "UMUI.nsh"
!include LogicLib.nsh
!include UAC.nsh
!include ProcFunc.nsh

!include "FileFunc.nsh"

# Name the installer
Name "Hiveary Agent"
OutFile "hiveary_setup_win.exe"

# Set the install directory
installDir "$PROGRAMFILES\Hiveary"

;--------------------------------
;Interface Settings

!define MUI_ABORTWARNING
!define UMUI_USE_INSTALLOPTIONSEX

;--------------------------------
;Reserve Files

ReserveFile "authinfo.ini"
!insertmacro MUI_RESERVEFILE_INSTALLOPTIONS

;--------------------------------
;Pages

!insertmacro MUI_PAGE_WELCOME

Page custom AuthInfoPage

!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

;--------------------------------
;Languages

!insertmacro MUI_LANGUAGE "English"

;--------------------------------
;Variables

Var USERNAME
Var OAUTH_SECRET
Var ConsoleParentPID

;--------------------------------
;Macros
!macro InitElevation thing
    uac_tryagain:
    !insertmacro UAC_RunElevated
    ${Switch} $0
    ${Case} 0
        ${IfThen} $1 = 1 ${|} Quit ${|} ;we are the outer process, the inner process has done its work, we are done
        ${If} $3 <> 0 ;if we are admin
            System::Call "kernel32::GetCurrentProcessId()i.r0"
            ${If} ${UAC_IsInnerInstance}
                ; If we are in the elevated process, we need to get our grandparent PID for console
                ${GetProcessParent} $0 $ConsoleParentPID
                ;${Debug} "From elevated $0 process, parent process is $ConsoleParentPID"
                ${GetProcessParent} $ConsoleParentPID $ConsoleParentPID
                ;${Debug} "grand parent process is $ConsoleParentPID"
            ${Else}
                ;${Debug} "We are an already elevated process"
                StrCpy $ConsoleParentPID -1
            ${EndIf}
            ${Break}        ;we are admin (after elevation or not), let the show go on
        ${EndIf}
        ${If} $1 = 3 ;RunAs completed successfully, but with a non-admin user
            MessageBox mb_YesNo|mb_IconExclamation|mb_TopMost|mb_SetForeground "This ${thing} requires admin privileges, try again" /SD IDNO IDYES uac_tryagain IDNO 0
        ${EndIf}
        ;fall-through and die
    ${Case} 1223
        MessageBox mb_IconStop|mb_TopMost|mb_SetForeground "This ${thing} requires admin privileges, aborting!"
        Quit
    ${Case} 1062
        MessageBox mb_IconStop|mb_TopMost|mb_SetForeground "Logon service not running, aborting!"
        Quit
    ${Default}
        MessageBox mb_IconStop|mb_TopMost|mb_SetForeground "Unable to elevate , error $0"
        Quit
    ${EndSwitch}
!macroend

;--------------------------------
;Sections

# Default section
section "Default Section" SecDefault
  # Copy the installable files
  setOutPath $INSTDIR
  File "/oname=$TEMP\hiveary-agent.zip" "dist\hiveary-agent-*.win32.zip"
  File "dist\*.pyd"
  File "dist\*.dll"
  File "dist\library.zip"
  File "dist\HivearyService.exe"
  nsisunz::Unzip "$TEMP\hiveary-agent.zip" $INSTDIR

  # Create the crash log in advance so we can make it writeable
  FileOpen $0 "$TEMP\agent.exe.log" w
  FileClose $0

  # This is important to have $APPDATA variable
  # point to ProgramData folder
  # instead of current user's Roaming folder
  SetShellVarContext all

  # Read the input values
  ${If} ${Silent}
    ${GetParameters} $R0
    ${GetOptions} $R0 /USERNAME= $USERNAME
    ${GetOptions} $R0 /TOKEN= $OAUTH_SECRET
  ${Else}
    !insertmacro MUI_INSTALLOPTIONS_READ $USERNAME "authinfo.ini" "Field 2" "State"
    !insertmacro MUI_INSTALLOPTIONS_READ $OAUTH_SECRET "authinfo.ini" "Field 5" "State"
  ${EndIf}

  # Open the configuration JSON file and write to it
  CreateDirectory "$APPDATA\Hiveary"
  CreateDirectory "$APPDATA\Hiveary\logs"
  fileOpen $0 "$APPDATA\Hiveary\hiveary.conf" w
  fileWrite $0 '{"username": "$USERNAME", "access_token": "$OAUTH_SECRET"}'
  fileClose $0

  # Create the uninstaller
  WriteUninstaller "uninstall.exe"

  # Add to "Add/Remove Programs"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Hiveary" \
      "DisplayName" "Hiveary Agent"

  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Hiveary" \
      "UninstallString" "$\"$INSTDIR\uninstall.exe$\""
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Hiveary" \
      QuietUninstallString" "$\"$INSTDIR\uninstall.exe$\" /S"

  # Install a service - ServiceType own process - StartType automatic - NoDependencies - Logon as System Account
  SimpleSC::InstallService "HivearyAgent" "Hiveary Agent" "16" "2" "$INSTDIR\HivearyService.exe" "" "" ""
  Pop $0  # returns an errorcode (<>0) otherwise success (0)
  IntCmp $0 0 InstallServiceDone +1 +1
    Push $0
    SimpleSC::GetErrorMessage
    Pop $0
    MessageBox MB_OK|MB_ICONSTOP "Service installation failed - Reason: $0"
  InstallServiceDone:

  # Start the service with the argument "/param1=true"
  SimpleSC::StartService "HivearyAgent" "-d" 30
  Pop $0 ; returns an errorcode (<>0) otherwise success (0)
  IntCmp $0 0 StartServiceDone +1 +1
    Push $0
    SimpleSC::GetErrorMessage
    Pop $0
    MessageBox MB_OK|MB_ICONSTOP "Service start failed - Reason: $0"
  StartServiceDone:

sectionEnd


section "uninstall"

  # Stops the service and waits for file release
  SimpleSC::StopService "HivearyAgent" 1 30
  Pop $0 ; returns an errorcode (<>0) otherwise success (0)

  # Remove the service
  SimpleSC::RemoveService "HivearyAgent"
  Pop $0 ; returns an errorcode (<>0) otherwise success (0)

  # Remove subfolders
  RMDir /REBOOTOK /r $INSTDIR\appdata
  RMDir /r $INSTDIR\updates
  RMDir /REBOOTOK /r $INSTDIR\Microsoft.VC90.CRT

  # Unknown version number could be in the root dir
  FindFirst $0 $1 $INSTDIR\hiveary-agent-*.win32
  ${If} $1 != ""
    RMDir /REBOOTOK /r $INSTDIR\$1
  ${EndIf}
  FindClose $1

  # Remove files
  Delete /REBOOTOK $INSTDIR\agent.exe
  Delete $INSTDIR\agent.*.exe
  Delete /REBOOTOK $INSTDIR\python27.dll
  Delete /REBOOTOK $INSTDIR\pywintypes27.dll
  Delete /REBOOTOK $INSTDIR\*.pyd
  Delete /REBOOTOK $INSTDIR\library.zip
  Delete /REBOOTOK $INSTDIR\HivearyService.exe
  Delete /REBOOTOK $INSTDIR\HivearyService.log

  # Always delete uninstaller as the last action
  Delete $INSTDIR\uninstall.exe

  # Try to remove the install directory - this will only happen if it is empty
  RMDir $INSTDIR

  # Remove the registry keys
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Hiveary"

sectionEnd


;--------------------------------
;Installer Functions

Function .onInit
  # Require admin rights on NT4+
  ;abort if not started by administrator
  !insertmacro InitElevation "installer"

  ${If} ${UAC_IsInnerInstance}
  ${AndIfNot} ${UAC_IsAdmin}
      SetErrorLevel 0x666666 ;special return value for outer instance so it knows we did not have admin rights
      Quit
  ${EndIf}

  ;Extract InstallOptions INI files
  !insertmacro MUI_INSTALLOPTIONS_EXTRACT "authinfo.ini"
FunctionEnd

LangString TEXT_IO_TITLE ${LANG_ENGLISH} "Authentication"
LangString TEXT_IO_SUBTITLE ${LANG_ENGLISH} "Please enter the host authentication information."

Function AuthInfoPage
  !insertmacro MUI_HEADER_TEXT "$(TEXT_IO_TITLE)" "$(TEXT_IO_SUBTITLE)"
  !insertmacro INSTALLOPTIONS_DISPLAY "authinfo.ini"
FunctionEnd



