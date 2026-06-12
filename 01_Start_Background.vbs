Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
ps1 = scriptDir & "\core\localreadlog_start.ps1"

If fso.FileExists(ps1) Then
    cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & ps1 & """ -Root """ & scriptDir & """"
    shell.Run cmd, 0, False
Else
    shell.Run "cmd.exe /c echo Start script not found: " & ps1 & " & pause", 1, True
End If
