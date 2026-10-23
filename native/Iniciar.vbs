Option Explicit
Dim shell, files, folder, command, mode, result
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
mode = ""
If WScript.Arguments.Count > 0 Then
    If WScript.Arguments.Item(0) = "--agent" Then mode = " -Agent"
End If
command = Chr(34) & shell.ExpandEnvironmentStrings("%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe") & Chr(34)
command = command & " -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File " & Chr(34) & folder & "\Abrir.ps1" & Chr(34) & mode
On Error Resume Next
result = shell.Run(command, 0, True)
If Err.Number <> 0 Then
    If mode = "" Then MsgBox "Falha ao iniciar o aplicativo. Verifique o Windows Script Host e as politicas deste computador.", 16, "Orquestrador"
    WScript.Quit 2
End If
On Error GoTo 0
WScript.Quit result
