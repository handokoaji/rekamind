; packaging/installer.iss
[Setup]
AppName=Meeting Recorder
AppVersion=0.1.0
DefaultDirName={autopf}\MeetingRecorder
DefaultGroupName=Meeting Recorder
OutputBaseFilename=MeetingRecorderSetup-0.1.0
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\MeetingRecorder.exe

[Files]
Source: "dist\MeetingRecorder\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{group}\Meeting Recorder"; Filename: "{app}\MeetingRecorder.exe"
Name: "{group}\Uninstall Meeting Recorder"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\MeetingRecorder.exe"; Description: "Jalankan Meeting Recorder"; Flags: postinstall nowait skipifsilent
