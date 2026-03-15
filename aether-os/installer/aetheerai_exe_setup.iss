; ===========================================================================
;  AetheerAI -- An AI Master!!   |   Single-EXE Inno Setup Installer
;  Publisher   : Tecbunny
;  Version     : 1.0.0
;
;  HOW TO BUILD:
;    1. Run  build_main_exe.bat  first  (produces dist\AetheerAI_Master.exe)
;    2. Run  build_setup_exe.bat  (produces dist\AetheerAI_Setup_v1.0.0.exe)
;
;  The resulting AetheerAI_Setup_v1.0.0.exe:
;    • Is a SINGLE FILE — no Python required on the target machine
;    • Installs to %LOCALAPPDATA%\AetheerAI  (no admin rights needed)
;    • Creates a Desktop shortcut and a Start Menu entry
;    • Copies .env.example -> .env on first install
;    • Adds an entry to Windows Add/Remove Programs
;    • Provides a clean Uninstaller
; ===========================================================================

#define MyAppName      "AetheerAI"
#define MyAppTitle     "AetheerAI -- An AI Master!!"
#define MyAppVersion   "1.0.0"
#define MyAppPublisher "Tecbunny"
#define MyAppExe       "AetheerAI_Master.exe"
#define MyAppID        "{F4A2C3D1-8B7E-4F9A-B2C3-AE7BCBUNNY02}"

; ---------------------------------------------------------------------------
[Setup]
AppId={#MyAppID}
AppName={#MyAppTitle}
AppVersion={#MyAppVersion}
AppVerName={#MyAppTitle} {#MyAppVersion}
AppPublisher={#MyAppPublisher}

; Install to user's AppData — no admin rights required
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppTitle}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Output — goes to the dist\ folder alongside the compiled EXE
OutputDir=..\dist
OutputBaseFilename=AetheerAI_Setup_v{#MyAppVersion}

; UI
WizardStyle=modern
WizardSizePercent=130
DisableWelcomePage=no
DisableProgramGroupPage=yes
AllowNoIcons=yes

; Compression
Compression=lzma2/ultra64
SolidCompression=yes
InternalCompressLevel=ultra64

; Uninstall
UninstallDisplayName={#MyAppTitle}

; ---------------------------------------------------------------------------
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

; ---------------------------------------------------------------------------
[Tasks]
Name: "desktopicon"; Description: "Create a &Desktop shortcut"; \
    GroupDescription: "Additional icons:"; Flags: checked

; ---------------------------------------------------------------------------
[Files]
; ── The compiled standalone EXE (main application) ──────────────────
Source: "..\dist\AetheerAI_Master.exe"; DestDir: "{app}"; Flags: ignoreversion

; ── Environment config ───────────────────────────────────────────────
; .env.example is bundled so users have a template to fill in
Source: "..\\.env.example"; DestDir: "{app}"; Flags: ignoreversion

; ---------------------------------------------------------------------------
[Icons]
; Start Menu
Name: "{group}\{#MyAppTitle}";                          Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"
Name: "{group}\Edit API Keys (.env)";                   Filename: "notepad.exe"; Parameters: """{app}\.env"""
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}";     Filename: "{uninstallexe}"

; Desktop (optional task)
Name: "{autodesktop}\{#MyAppTitle}";                    Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

; ---------------------------------------------------------------------------
[Registry]
; Store install path for diagnostics / future updates
Root: HKCU; Subkey: "Software\Tecbunny\AetheerAI"; ValueType: string; \
    ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey

; ---------------------------------------------------------------------------
[Run]
; Offer to launch immediately after install
Filename: "{app}\{#MyAppExe}"; \
    Description: "Launch AetheerAI now"; \
    Flags: nowait postinstall skipifsilent

; ---------------------------------------------------------------------------
[Code]
// ========================================================================
//  Pascal script — post-install steps
// ========================================================================

// Copy .env.example -> .env on first install only
procedure CopyEnvIfMissing();
var
  EnvFile, ExampleFile: String;
begin
  EnvFile    := ExpandConstant('{app}\.env');
  ExampleFile := ExpandConstant('{app}\.env.example');
  if (not FileExists(EnvFile)) and FileExists(ExampleFile) then
    FileCopy(ExampleFile, EnvFile, False);
end;

// Create the agent_output and workspace subdirectories the app expects
procedure CreateAppDirs();
begin
  CreateDir(ExpandConstant('{app}\agent_output'));
  CreateDir(ExpandConstant('{app}\agent_output\screenshots'));
  CreateDir(ExpandConstant('{app}\agent_output\images'));
  CreateDir(ExpandConstant('{app}\agent_output\audio'));
  CreateDir(ExpandConstant('{app}\workspace'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep <> ssPostInstall then Exit;
  CopyEnvIfMissing();
  CreateAppDirs();
end;

// After install — show the user where to put their API key
procedure DeinitializeSetup();
var
  EnvPath: String;
begin
  if WizardForm <> nil then Exit;  // installer still running
  EnvPath := ExpandConstant('{app}\.env');
  if FileExists(EnvPath) then
    MsgBox(
      'AetheerAI is installed!'                              + #13#10#13#10 +
      'Before launching, open your .env file and add your'  + #13#10 +
      'AI provider key.  The file is at:'                   + #13#10#13#10 +
      '  ' + EnvPath                                        + #13#10#13#10 +
      'At minimum, add ONE of:'                             + #13#10 +
      '  GITHUB_TOKEN=ghp_...'                              + #13#10 +
      '  OPENAI_API_KEY=sk-...'                             + #13#10 +
      '  ANTHROPIC_API_KEY=sk-ant-...'                      + #13#10#13#10 +
      'Then double-click the desktop shortcut to start.',
      mbInformation, MB_OK
    );
end;
