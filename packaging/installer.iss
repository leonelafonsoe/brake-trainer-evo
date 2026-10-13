; Inno Setup script for the Windows installer (https://jrsoftware.org/isinfo.php).
;
; Build the folder version first (py scripts/build_exe.py), then:
;   ISCC.exe /DAppVersion=0.3.8 packaging\installer.iss
; The installer is written to dist\BrakeTrainerEvo-<version>-setup.exe.
; The GitHub release workflow does both steps for you.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; Never change AppId: it is how Windows recognises an upgrade of the same program.
AppId={{57936BBA-B965-405A-AEBF-F970FB38F14E}
AppName=Brake Trainer EVO
AppVersion={#AppVersion}
AppPublisher=Brake Trainer EVO contributors
DefaultDirName={autopf}\Brake Trainer EVO
DefaultGroupName=Brake Trainer EVO
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=BrakeTrainerEvo-{#AppVersion}-setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\BrakeTrainerEvo.exe
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\BrakeTrainerEvo\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Brake Trainer EVO"; Filename: "{app}\BrakeTrainerEvo.exe"
Name: "{autodesktop}\Brake Trainer EVO"; Filename: "{app}\BrakeTrainerEvo.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\BrakeTrainerEvo.exe"; Description: "Start Brake Trainer EVO"; Flags: nowait postinstall skipifsilent
