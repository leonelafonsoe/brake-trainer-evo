; Inno Setup script for the Windows installer (https://jrsoftware.org/isinfo.php).
;
; Build the folder version first (py scripts/build_exe.py), then:
;   ISCC.exe /DAppVersion=0.4.0 packaging\installer.iss
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
AppPublisherURL=https://github.com/leonelafonsoe/brake-trainer-evo
AppSupportURL=https://github.com/leonelafonsoe/brake-trainer-evo/issues
AppUpdatesURL=https://github.com/leonelafonsoe/brake-trainer-evo/releases
AppMutex=BrakeTrainerEvo.App
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
CloseApplications=yes
RestartApplications=no
VersionInfoCompany=Brake Trainer EVO contributors
VersionInfoDescription=Brake Trainer EVO
VersionInfoProductName=Brake Trainer EVO
VersionInfoProductVersion={#AppVersion}

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked

[Files]
; A self-contained folder: always replace the files, even on a downgrade.
Source: "..\dist\BrakeTrainerEvo\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Brake Trainer EVO"; Filename: "{app}\BrakeTrainerEvo.exe"
Name: "{autodesktop}\Brake Trainer EVO"; Filename: "{app}\BrakeTrainerEvo.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\BrakeTrainerEvo.exe"; Description: "Start Brake Trainer EVO"; Flags: nowait postinstall skipifsilent
