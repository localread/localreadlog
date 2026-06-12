Option Explicit

Dim shell, fso, scriptDir, coreDir, noticePath, ps1, fallbackPs1, cmd
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
coreDir = scriptDir & "\core"
noticePath = coreDir & "\localreadlog_start_notice.html"
ps1 = coreDir & "\localreadlog_start_with_wakeup.ps1"
fallbackPs1 = coreDir & "\localreadlog_start.ps1"

If fso.FileExists(noticePath) Then
    shell.Run "rundll32.exe url.dll,FileProtocolHandler " & Q(noticePath), 0, False
End If

If fso.FileExists(ps1) Then
    cmd = "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File " & Q(ps1) & " -Root " & Q(scriptDir)
    shell.Run cmd, 0, False
ElseIf fso.FileExists(fallbackPs1) Then
    cmd = "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File " & Q(fallbackPs1) & " -Root " & Q(scriptDir)
    shell.Run cmd, 0, False
Else
    shell.Popup "LocalReadLog 시작 파일을 찾지 못했습니다." & vbCrLf & _
                "core\localreadlog_start_with_wakeup.ps1 또는 core\localreadlog_start.ps1을 확인하세요.", _
                5, "LocalReadLog", 48
End If

Function Q(value)
    Q = Chr(34) & value & Chr(34)
End Function
