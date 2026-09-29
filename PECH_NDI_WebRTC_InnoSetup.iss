; Inno Setup Script for PECH NDI-to-WebRTC Bridge
[Setup]
AppName=PECH NDI-to-WebRTC Bridge
AppVersion=1.0.16
AppPublisher=PechMedia
DefaultDirName={autopf}\PECH NDI Bridge
DefaultGroupName=PECH NDI Bridge
OutputDir=D:\PECHNDIWEB\dist
OutputBaseFilename=PECH_NDI_Bridge_InnoSetup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "D:\PECHNDIWEB\dist\PECH_NDI_WebRTC.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "D:\PECHNDIWEB\dist\settings.json"; DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "D:\PECHNDIWEB\dist\start_server.bat"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\PECH NDI Bridge"; Filename: "{app}\start_server.bat"
Name: "{autodesktop}\PECH NDI Bridge"; Filename: "{app}\start_server.bat"

[Run]
Filename: "{app}\start_server.bat"; Description: "Launch PECH NDI Bridge"; Flags: nowait postinstall skipifsilent
