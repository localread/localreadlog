Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
dataDir = scriptDir & "\data"
If Not fso.FolderExists(dataDir) Then
    fso.CreateFolder(dataDir)
End If

portFile = dataDir & "\localreadlog_server_port.txt"
If fso.FileExists(portFile) Then
    On Error Resume Next
    fso.DeleteFile portFile, True
    On Error GoTo 0
End If

cmd = "cmd.exe /c """ & scriptDir & "\core\localreadlog_background.bat" & """"

Set wmi = GetObject("winmgmts:{impersonationLevel=impersonate}!\\.\root\cimv2")
Set startup = wmi.Get("Win32_ProcessStartup").SpawnInstance_
startup.ShowWindow = 0

pid = 0
result = wmi.Get("Win32_Process").Create(cmd, scriptDir, startup, pid)

If result = 0 Then
    Set pidFile = fso.OpenTextFile(dataDir & "\localreadlog_launcher.pid", 2, True)
    pidFile.Write CStr(pid)
    pidFile.Close
Else
    shell.Run "cmd.exe /c echo Failed to start LocalReadLog. Error: " & result & " & pause", 1, True
    WScript.Quit
End If

Function ReadPortFile()
    ReadPortFile = ""
    If fso.FileExists(portFile) Then
        On Error Resume Next
        Set file = fso.OpenTextFile(portFile, 1, False)
        txt = Trim(file.ReadAll)
        file.Close
        If Err.Number = 0 And Len(txt) > 0 Then
            ReadPortFile = txt
        End If
        Err.Clear
        On Error GoTo 0
    End If
End Function

Function FindRunningPort()
    FindRunningPort = ""
    ps1 = scriptDir & "\core\localreadlog_find_server_port.ps1"
    If Not fso.FileExists(ps1) Then Exit Function

    On Error Resume Next
    psCmd = "powershell -NoProfile -ExecutionPolicy Bypass -File """ & ps1 & """ -Root """ & scriptDir & """"
    Set exec = shell.Exec(psCmd)
    outText = Trim(exec.StdOut.ReadAll)
    If Err.Number = 0 And Len(outText) > 0 Then
        lines = Split(outText, vbCrLf)
        firstLine = Trim(lines(0))
        If IsNumeric(firstLine) Then FindRunningPort = firstLine
    End If
    Err.Clear
    On Error GoTo 0
End Function

port = ""
For i = 1 To 180
    port = ReadPortFile()
    If Len(port) > 0 Then Exit For

    If i Mod 3 = 0 Then
        port = FindRunningPort()
        If Len(port) > 0 Then Exit For
    End If

    WScript.Sleep 1000
Next

If Len(port) = 0 Then
    port = "8787"
End If

shell.Run "http://127.0.0.1:" & port, 1, False
