; packaging/installer.iss
[Setup]
AppName=Rekamind
AppVersion=0.1.0
DefaultDirName={autopf}\Rekamind
DefaultGroupName=Rekamind
OutputBaseFilename=rekamind-0.1.0
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\Rekamind.exe

[Files]
Source: "dist\Rekamind\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{group}\Rekamind"; Filename: "{app}\Rekamind.exe"
Name: "{group}\Uninstall Rekamind"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\Rekamind.exe"; Description: "Jalankan Rekamind"; Flags: postinstall nowait skipifsilent
