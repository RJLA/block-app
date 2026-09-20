; Inno Setup script for Block Guard
; Build:  iscc installer.iss     -> Output\BlockGuardSetup.exe
; Requires dist\BlockGuard.exe (run build.bat first).

#define MyAppName "Block Guard"
#define MyAppVersion "2.1.0"
#define MyAppExe "BlockGuard.exe"

[Setup]
AppId={{3F6A9D21-77C4-4B8E-A0D3-5E9C41B8F27A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\BlockGuard
DefaultGroupName={#MyAppName}
OutputBaseFilename=BlockGuardSetup
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
; Ships the starting blocklist; only copied if the machine has no config yet.
Source: "default_blocklist.json"; DestDir: "{commonappdata}\BlockGuard"; \
    DestName: "blocklist.json"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "logontask"; Description: "Start Block Guard at logon (runs in the background, no window)"; Flags: unchecked

[Run]
Filename: "schtasks"; Parameters: "/Create /F /TN BlockGuard /SC ONLOGON /RL HIGHEST /TR """"{app}\{#MyAppExe}"""" --background"; \
    Flags: runhidden; Tasks: logontask
Filename: "{app}\{#MyAppExe}"; Description: "Launch {#MyAppName}"; Flags: postinstall nowait skipifsilent

[UninstallRun]
; Clean up so the machine isn't left with blocked sites after removal.
Filename: "schtasks"; Parameters: "/Delete /F /TN BlockGuard"; Flags: runhidden; RunOnceId: "DelTask"
Filename: "reg"; Parameters: "delete ""HKLM\SOFTWARE\Policies\Google\Chrome\URLBlocklist"" /f"; Flags: runhidden; RunOnceId: "ChromeBlock"
Filename: "reg"; Parameters: "delete ""HKLM\SOFTWARE\Policies\Google\Chrome\URLAllowlist"" /f"; Flags: runhidden; RunOnceId: "ChromeAllow"
Filename: "reg"; Parameters: "delete ""HKLM\SOFTWARE\Policies\Microsoft\Edge\URLBlocklist"" /f"; Flags: runhidden; RunOnceId: "EdgeBlock"
Filename: "reg"; Parameters: "delete ""HKLM\SOFTWARE\Policies\Microsoft\Edge\URLAllowlist"" /f"; Flags: runhidden; RunOnceId: "EdgeAllow"
