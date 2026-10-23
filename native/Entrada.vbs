' CAIO managed entry v1
Option Explicit
Dim shell, files, folder, script, command, dataRoot, result
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
script = folder & "\launch\Entrada.ps1"
If Not files.FileExists(script) Then script = folder & "\payload\native\Entrada.ps1"
dataRoot = ""
If files.FileExists(folder & "\instalacao-teste.json") Then dataRoot = " -DataRoot " & Chr(34) & folder & Chr(34)
command = Chr(34) & shell.ExpandEnvironmentStrings("%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe") & Chr(34)
command = command & " -NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File " & Chr(34) & script & Chr(34) & " -Action __ACTION__" & dataRoot
On Error Resume Next
result = shell.Run(command, 0, True)
If Err.Number <> 0 Then
    MsgBox "Nao foi possivel abrir o CAIO. Extraia todo o pacote e verifique os iniciadores.", 16, "CAIO"
    WScript.Quit 2
End If
On Error GoTo 0
WScript.Quit result
