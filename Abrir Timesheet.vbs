Option Explicit

Dim shell, fileSystem, projectDir, launcherPath, exitCode

Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

projectDir = fileSystem.GetParentFolderName(WScript.ScriptFullName)
launcherPath = projectDir & "\INICIAR_TIMESHEET.cmd"

If Not fileSystem.FileExists(launcherPath) Then
    MsgBox "O inicializador INICIAR_TIMESHEET.cmd nao foi encontrado.", _
        vbCritical, "Timesheet CCEE"
    WScript.Quit 1
End If

shell.CurrentDirectory = projectDir
shell.Environment("Process")("TIMESHEET_SILENT") = "1"

On Error Resume Next
exitCode = shell.Run(Chr(34) & launcherPath & Chr(34), 0, True)
If Err.Number <> 0 Then
    MsgBox "Nao foi possivel executar o inicializador do Timesheet CCEE." & _
        vbCrLf & vbCrLf & Err.Description, vbCritical, "Timesheet CCEE"
    WScript.Quit 1
End If
On Error GoTo 0

If exitCode <> 0 Then
    MsgBox "Nao foi possivel abrir o Timesheet CCEE." & vbCrLf & vbCrLf & _
        "Execute INICIAR_TIMESHEET.cmd para consultar os detalhes.", _
        vbCritical, "Timesheet CCEE"
End If
