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
Name: "desktopicon";   Description: "Create a &Desktop shortcut"; \
    GroupDescription: "Additional icons:"; Flags: checked
Name: "installreqs";  Description: "Install Python requirements (litellm, streamlit, etc.)"; \
    GroupDescription: "Dependencies:"; Flags: checked

; ---------------------------------------------------------------------------
[Files]
; ── The compiled standalone EXE (main application) ──────────────────
Source: "..\dist\AetheerAI_Master.exe"; DestDir: "{app}"; Flags: ignoreversion

; ── Environment config ───────────────────────────────────────────────
; .env.example is bundled so users have a template to fill in
Source: "..\\.env.example"; DestDir: "{app}"; Flags: ignoreversion

; ── Python requirements list (used by optional install step) ─────────
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion

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

// Returns True if python.exe is findable on PATH
function IsPythonAvailable(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'), '/c python --version',
                 '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
            and (ResultCode = 0);
end;

// Warn early if Python is missing but don't block the install
procedure InitializeWizard();
begin
  if IsTaskSelected('installreqs') and not IsPythonAvailable() then
    MsgBox(
      'Python 3.10 or newer was not detected on this system.'     + #13#10#13#10 +
      'The "Install Python requirements" option is selected, but' + #13#10 +
      'pip requires Python to be installed first.'                 + #13#10#13#10 +
      'Get Python from:  https://www.python.org/downloads/'       + #13#10 +
      'IMPORTANT: check "Add Python to PATH" during install.'     + #13#10#13#10 +
      'You can uncheck the requirements option and continue, or'  + #13#10 +
      'install Python first, then re-run this installer.',
      mbInformation, MB_OK
    );
end;

// Copy .env.example -> .env on first install only
procedure CopyEnvIfMissing();
var
  EnvFile, ExampleFile: String;
begin
  EnvFile     := ExpandConstant('{app}\.env');
  ExampleFile := ExpandConstant('{app}\.env.example');
  if (not FileExists(EnvFile)) and FileExists(ExampleFile) then
    FileCopy(ExampleFile, EnvFile, False);
end;

// Create the runtime subdirectories the app expects
procedure CreateAppDirs();
begin
  CreateDir(ExpandConstant('{app}\agent_output'));
  CreateDir(ExpandConstant('{app}\agent_output\screenshots'));
  CreateDir(ExpandConstant('{app}\agent_output\images'));
  CreateDir(ExpandConstant('{app}\agent_output\audio'));
  CreateDir(ExpandConstant('{app}\workspace'));
end;

// Install Python requirements via pip
procedure InstallRequirements(AppDir: String);
var
  ResultCode: Integer;
  Ok: Boolean;
begin
  WizardForm.StatusLabel.Caption := 'Installing Python requirements (this may take a few minutes)...';
  Ok := Exec(
    ExpandConstant('{cmd}'),
    '/c pip install -r "' + AppDir + '\requirements.txt" --quiet',
    AppDir, SW_HIDE, ewWaitUntilTerminated, ResultCode
  ) and (ResultCode = 0);

  if Ok then
    MsgBox(
      'Python requirements installed successfully!' + #13#10#13#10 +
      'All dependencies from requirements.txt have been installed.',
      mbInformation, MB_OK
    )
  else
    MsgBox(
      'Requirements installation failed (exit code: ' + IntToStr(ResultCode) + ').' + #13#10#13#10 +
      'You can install them manually by running:'                                    + #13#10 +
      '  pip install -r "' + AppDir + '\requirements.txt"'                         + #13#10#13#10 +
      'Check your internet connection and that Python is on your PATH.',
      mbError, MB_OK
    );
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  AppDir: String;
begin
  if CurStep <> ssPostInstall then Exit;

  AppDir := ExpandConstant('{app}');

  CopyEnvIfMissing();
  CreateAppDirs();

  // Install requirements only if the user kept the checkbox ticked
  if IsTaskSelected('installreqs') then
  begin
    if IsPythonAvailable() then
      InstallRequirements(AppDir)
    else
      MsgBox(
        'Skipping requirements installation — Python was not found on PATH.' + #13#10#13#10 +
        'Install Python 3.10+ from https://www.python.org/downloads/'        + #13#10 +
        'then run:  pip install -r "' + AppDir + '\requirements.txt"',
        mbExclamation, MB_OK
      );
  end;
end;

// After install — remind the user to add their API key
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
