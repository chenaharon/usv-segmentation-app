; Inno Setup 6 — packages the *onedir* build from ``SegmentationAppInstaller.spec`` (not the onefile portable).
; Build installer bundle first (``--distpath`` keeps ``dist/`` for the portable one-file EXE only):
;   pyinstaller -y --distpath dist_installer_stage SegmentationAppInstaller.spec
#define InstallerStageRoot "dist_installer_stage"
#define MyAppName "USV Segmentation"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Your Lab"
; Output folder ``name=`` in COLLECT inside ``SegmentationAppInstaller.spec``
#define InstallBuildDir "USV_Segmentation_Install"
; EXE ``name=`` in EXE(...) inside ``SegmentationAppInstaller.spec`` (PyInstaller adds .exe)
#define MyAppExeName "USV_Segmentation.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
SetupIconFile=..\assets\app_icon.ico
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=..\dist_installer
OutputBaseFilename=USV_Segmentation_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\{#InstallerStageRoot}\{#InstallBuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
