Option Explicit
Dim shell, files, folder, command, result
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
command = Chr(34) & shell.ExpandEnvironmentStrings("%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe") & Chr(34)
command = command & " -NoProfile -NonInteractive -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File " & Chr(34) & folder & "\wizard.ps1" & Chr(34)
On Error Resume Next
result = shell.Run(command, 0, True)
If Err.Number <> 0 Then
    MsgBox "Nao foi possivel iniciar o wizard. Verifique se os scripts sao permitidos neste computador.", 16, "Orquestrador"
    WScript.Quit 2
End If
On Error GoTo 0
If result <> 0 And result <> 3 Then MsgBox "O wizard nao concluiu a operacao. Verifique o diagnostico exibido e as politicas da organizacao.", 48, "Orquestrador"
WScript.Quit result
