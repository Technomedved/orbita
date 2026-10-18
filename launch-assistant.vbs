Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
exe = folder & "\Orbita.exe"
If Not fso.FileExists(exe) Then exe = folder & "\dist\Orbita\Orbita.exe"
args = ""
If WScript.Arguments.Count > 0 Then
    If WScript.Arguments(0) = "--background" Then args = " --background"
End If
If fso.FileExists(exe) Then
    shell.Run Chr(34) & exe & Chr(34) & args, 1, False
    WScript.Quit
End If
python = shell.Environment("Process")("ORBITA_PYTHON")
If python = "" Then python = folder & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(python) Then
    MsgBox "Orbita.exe is missing. Build the app or create .venv and install requirements-desktop.txt.", 48, "Orbita"
    WScript.Quit 1
End If
shell.Environment("Process")("PYTHONPATH") = folder & "\.ui-runtime"
shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & folder & "\orbita_entry.py" & Chr(34) & args, 0, False
