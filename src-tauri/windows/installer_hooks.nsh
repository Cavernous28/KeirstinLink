; Custom NSIS hooks for KeirstinLink installer.
; Tauri includes this file automatically if it exists at
; src-tauri/windows/installer_hooks.nsh
;
; We define the PREINSTALL hook to kill any running KeirstinLink processes
; and to delete the old backend EXE if it is locked, so upgrades don't fail
; with "Error opening file for writing".

!include LogicLib.nsh

; _KillIfRunning <image_name>
; Uses taskkill /F /IM to force-terminate a process by image name.
; Waits a short moment afterward so handles are released before we try to
; overwrite files.
!macro _KillIfRunning image_name
  DetailPrint "Stopping ${image_name} if running..."
  nsExec::Exec '"taskkill" /F /IM "${image_name}" /FI "STATUS eq RUNNING"'
  Pop $0
!macroend

!macro NSIS_HOOK_PREINSTALL
  ; Kill the main app and bundled backend if they are running.
  !insertmacro _KillIfRunning "keirstinlink.exe"
  !insertmacro _KillIfRunning "keirstinlink_backend.exe"
  Sleep 1500

  ; If a previous install exists and the backend exe is locked, try to remove
  ; it before the file extraction step.
  ${If} ${FileExists} "$INSTDIR\keirstinlink_backend.exe"
    ClearErrors
    Delete "$INSTDIR\keirstinlink_backend.exe"
    ${If} ${Errors}
      DetailPrint "Backend file locked; retrying after delay..."
      Sleep 2000
      !insertmacro _KillIfRunning "keirstinlink_backend.exe"
      Delete "$INSTDIR\keirstinlink_backend.exe"
    ${EndIf}
  ${EndIf}
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; Nothing extra after install.
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro _KillIfRunning "keirstinlink.exe"
  !insertmacro _KillIfRunning "keirstinlink_backend.exe"
  Sleep 1500
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  ; Nothing extra after uninstall.
!macroend
