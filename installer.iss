; Inno Setup script for Allowlist Guard
; Build:  iscc installer.iss     -> Output\AllowlistGuardSetup.exe
; Requires dist\AllowlistGuard.exe (run build.bat first).

#define MyAppName "Allowlist Guard"
#define MyAppVersion "1.0.0"
#define MyAppExe "AllowlistGuard.exe"

[Setup]
AppId={{8C2F1E64-3A7B-4D19-9C55-1F0B7E2A44D1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\AllowlistGuard
DefaultGroupName={#MyAppName}
OutputBaseFilename=AllowlistGuardSetup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
MinVersion=10.0
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExe}
WizardStyle=modern
; Mascot on the setup executable itself; the app exe carries it via PyInstaller.
SetupIconFile=assets\mascot.ico

[Files]
Source: "dist\{#MyAppExe}"; DestDir: "{app}"; Flags: ignoreversion
; Ships the starting allowlist; only copied if the machine has no config yet.
Source: "default_allowlist.json"; DestDir: "{commonappdata}\AllowlistGuard"; \
    DestName: "allowlist.json"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "logontask"; Description: "Start enforcement at logon"; Flags: unchecked

[Run]
Filename: "schtasks"; Parameters: "/Create /F /TN AllowlistGuard /SC ONLOGON /RL HIGHEST /TR """"{app}\{#MyAppExe}"""" --enforce"; \
    Flags: runhidden; Tasks: logontask
Filename: "{app}\{#MyAppExe}"; Description: "Launch {#MyAppName}"; Flags: postinstall nowait skipifsilent

[UninstallRun]
; Clean up so the machine isn't left locked down after removal.
Filename: "schtasks"; Parameters: "/Delete /F /TN AllowlistGuard"; Flags: runhidden; RunOnceId: "DelTask"
Filename: "reg"; Parameters: "delete ""HKLM\SOFTWARE\Policies\Google\Chrome\URLBlocklist"" /f"; Flags: runhidden; RunOnceId: "ChromeBlock"
Filename: "reg"; Parameters: "delete ""HKLM\SOFTWARE\Policies\Google\Chrome\URLAllowlist"" /f"; Flags: runhidden; RunOnceId: "ChromeAllow"
Filename: "reg"; Parameters: "delete ""HKLM\SOFTWARE\Policies\Microsoft\Edge\URLBlocklist"" /f"; Flags: runhidden; RunOnceId: "EdgeBlock"
Filename: "reg"; Parameters: "delete ""HKLM\SOFTWARE\Policies\Microsoft\Edge\URLAllowlist"" /f"; Flags: runhidden; RunOnceId: "EdgeAllow"
