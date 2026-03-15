; ===========================================================================
;  AetheerAI -- An AI Master!!   |   Inno Setup Installer Script
;  Publisher   : Tecbunny
;  Version     : 1.0.0
;
;  HOW TO BUILD:
;    Run  installer\build_installer.bat
;    (Requires Inno Setup 6 — free from https://jrsoftware.org/isinfo.php)
;
;  OUTPUT:
;    dist\AetheerAI_Setup_v1.0.0.exe
;
;  NOTES:
;  - Source code is distributed as-is (not compiled/obfuscated).
;  - The installer creates a Python venv and installs requirements.txt.
;  - Users must supply their own AI provider API key in the .env file.
;  - All files written to the user's %LOCALAPPDATA%\AetheerAI  (no admin).
; ===========================================================================

#define MyAppName      "AetheerAI"
#define MyAppTitle     "AetheerAI -- An AI Master!!"
#define MyAppVersion   "1.0.0"
#define MyAppPublisher "Tecbunny"
#define MyAppID        "{F4A2C3D1-8B7E-4F9A-B2C3-AE7BCBUNNY01}"

; ---------------------------------------------------------------------------
[Setup]
AppId={#MyAppID}
AppName={#MyAppTitle}
AppVersion={#MyAppVersion}
AppVerName={#MyAppTitle} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/tecbunny/aetheerai
AppSupportURL=https://github.com/tecbunny/aetheerai/issues
AppUpdatesURL=https://github.com/tecbunny/aetheerai/releases

; Install to user's AppData (no admin rights required)
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppTitle}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Output
OutputDir=..\dist
OutputBaseFilename=AetheerAI_Setup_v{#MyAppVersion}

; UI
WizardStyle=modern
DisableWelcomePage=no
DisableProgramGroupPage=yes
AllowNoIcons=yes

; Compression (lzma2 gives best size)
Compression=lzma2/ultra64
SolidCompression=yes
InternalCompressLevel=ultra64

; Uninstall
UninstallDisplayName={#MyAppTitle}
UninstallDisplayIcon={app}\aether_icon.svg

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
;  FILES — sources are relative to the .iss file location (installer\)
;  Excludes:  caches, build artefacts, private keys, IDE config, this folder
; ---------------------------------------------------------------------------
[Files]
; Root-level files
Source: "..\*.py";       DestDir: "{app}"; Flags: ignoreversion
Source: "..\*.bat";      DestDir: "{app}"; Flags: ignoreversion
Source: "..\*.txt";      DestDir: "{app}"; Flags: ignoreversion
Source: "..\*.md";       DestDir: "{app}"; Flags: ignoreversion
Source: "..\*.svg";      DestDir: "{app}"; Flags: ignoreversion
Source: "..\*.example";  DestDir: "{app}"; Flags: ignoreversion

; Source packages (excluding caches and runtime data)
Source: ".\..\agents\*";   DestDir: "{app}\agents";   Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc,__pycache__"
Source: ".\..\ai\*";       DestDir: "{app}\ai";       Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc,__pycache__"
Source: ".\..\cli\*";      DestDir: "{app}\cli";      Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc,__pycache__"
Source: ".\..\core\*";     DestDir: "{app}\core";     Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc,__pycache__"
Source: ".\..\factory\*";  DestDir: "{app}\factory";  Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc,__pycache__"
Source: ".\..\security\*"; DestDir: "{app}\security"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc,__pycache__"
Source: ".\..\skills\*";   DestDir: "{app}\skills";   Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc,__pycache__"
Source: ".\..\tools\*";    DestDir: "{app}\tools";    Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc,__pycache__"
Source: ".\..\utils\*";    DestDir: "{app}\utils";    Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc,__pycache__"

; Shared agent workspace (created at runtime if missing — bundle placeholder)
Source: ".\..\workspace\*";      DestDir: "{app}\workspace";      Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist; Excludes: "*.pyc,__pycache__"

; Agent output directories (created at runtime — bundle as empty placeholders)
Source: ".\..\agent_output\*";   DestDir: "{app}\agent_output";   Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist; Excludes: "*.pyc,__pycache__"

; Memory & registry — exclude runtime data files (they are created on first run)
Source: ".\..\memory\*.py";        DestDir: "{app}\memory";   Flags: ignoreversion
Source: ".\..\registry\*.py";      DestDir: "{app}\registry"; Flags: ignoreversion

; ---------------------------------------------------------------------------
[Icons]
; Start Menu
Name: "{group}\{#MyAppTitle}";              Filename: "{app}\Launch_AetheerAI.bat"; WorkingDir: "{app}"
Name: "{group}\Edit API Keys (.env)";       Filename: "notepad.exe"; Parameters: """{app}\.env"""
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

; Desktop (optional task)
Name: "{autodesktop}\{#MyAppTitle}";        Filename: "{app}\Launch_AetheerAI.bat"; WorkingDir: "{app}"; Tasks: desktopicon

; ---------------------------------------------------------------------------
[Registry]
; Store install path for future reference
Root: HKCU; Subkey: "Software\Tecbunny\AetheerAI"; ValueType: string; \
    ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey

; ---------------------------------------------------------------------------
;  POST-INSTALL STEPS
;  Note: heavy steps (pip install) are handled in the [Code] section below
;        so that a proper progress page is shown.
; ---------------------------------------------------------------------------
[Run]
; Offer to launch after install finishes
Filename: "{app}\Launch_AetheerAI.bat"; \
    Description: "Launch AetheerAI now"; \
    Flags: nowait postinstall skipifsilent shellexec

; ---------------------------------------------------------------------------
[Code]
// =========================================================================
//  Pascal script — runs during installation
// =========================================================================

// Check whether "python" is on PATH and returns success/failure
function IsPythonAvailable(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'), '/c python --version', '',
                 SW_HIDE, ewWaitUntilTerminated, ResultCode)
            and (ResultCode = 0);
end;

// Warn early if Python is missing but don't block the install
procedure InitializeWizard();
begin
  if not IsPythonAvailable() then
    MsgBox(
      'Python 3.10 or newer was not detected on this system.'         + #13#10#13#10 +
      'AetheerAI requires Python 3.10+.'                              + #13#10 +
      'Please install it from:'                                       + #13#10 +
      '  https://www.python.org/downloads/'                           + #13#10#13#10 +
      'IMPORTANT: Tick "Add Python to PATH" during installation.'     + #13#10#13#10 +
      'You can finish this installer now, but AetheerAI will not run' + #13#10 +
      'until Python is installed and requirements are installed.',
      mbInformation, MB_OK
    );
end;

// Write a venv-aware launcher batch file with the real install path baked in
procedure CreateLauncher(AppDir: String);
var
  Lines: TStringList;
begin
  Lines := TStringList.Create;
  try
    Lines.Add('@echo off');
    Lines.Add('title AetheerAI -- An AI Master!!');
    Lines.Add('color 0B');
    Lines.Add('cd /d "' + AppDir + '"');
    Lines.Add('call "' + AppDir + '\venv\Scripts\activate.bat"');
    Lines.Add('echo.');
    Lines.Add('echo  Starting AetheerAI -- An AI Master!! ...');
    Lines.Add('echo  Open http://localhost:8501 if the browser does not open automatically.');
    Lines.Add('echo.');
    Lines.Add('python -m streamlit run app.py --server.headless false --browser.gatherUsageStats false');
    Lines.Add('pause');
    Lines.SaveToFile(AppDir + '\Launch_AetheerAI.bat');
  finally
    Lines.Free;
  end;
end;

// Copy .env.example -> .env on first install
procedure CreateEnvIfMissing(AppDir: String);
var
  EnvFile, ExampleFile: String;
begin
  EnvFile    := AppDir + '\.env';
  ExampleFile := AppDir + '\.env.example';
  if (not FileExists(EnvFile)) and FileExists(ExampleFile) then
    FileCopy(ExampleFile, EnvFile, False);
end;

// Run a shell command and wait; show progress label
function RunCmd(Cmd, Params, WorkDir, StatusMsg: String): Boolean;
var
  ResultCode: Integer;
begin
  WizardForm.StatusLabel.Caption := StatusMsg;
  Result := Exec(Cmd, Params, WorkDir, SW_HIDE, ewWaitUntilTerminated, ResultCode)
            and (ResultCode = 0);
end;

// Called after file extraction completes
procedure CurStepChanged(CurStep: TSetupStep);
var
  AppDir, VenvPip: String;
  Ok: Boolean;
begin
  if CurStep <> ssPostInstall then Exit;

  AppDir  := ExpandConstant('{app}');
  VenvPip := AppDir + '\venv\Scripts\pip.exe';

  // 1. Write launcher
  WizardForm.StatusLabel.Caption := 'Creating launcher...';
  CreateLauncher(AppDir);

  // 2. Write .env
  WizardForm.StatusLabel.Caption := 'Writing .env configuration file...';
  CreateEnvIfMissing(AppDir);

  // 3. Skip requirements if user unchecked the option
  if not IsTaskSelected('installreqs') then
  begin
    WizardForm.StatusLabel.Caption := 'Skipping requirements installation (unchecked).';
    Exit;
  end;

  // 4. Create virtual environment
  WizardForm.StatusLabel.Caption := 'Creating Python virtual environment...';
  Ok := RunCmd(
    ExpandConstant('{cmd}'),
    '/c python -m venv "' + AppDir + '\venv"',
    AppDir,
    'Creating Python virtual environment...'
  );
  if not Ok then begin
    MsgBox(
      'Failed to create the Python virtual environment.'          + #13#10 +
      'Ensure Python 3.10+ is installed and on your PATH.'        + #13#10#13#10 +
      'You can create it manually later by running:'              + #13#10 +
      '  python -m venv "' + AppDir + '\venv"'                  + #13#10 +
      '  "' + VenvPip + '" install -r requirements.txt',
      mbError, MB_OK
    );
    Exit;
  end;

  // 5. Upgrade pip
  WizardForm.StatusLabel.Caption := 'Upgrading pip...';
  RunCmd(VenvPip, 'install --upgrade pip --quiet', AppDir, 'Upgrading pip...');

  // 6. Install requirements
  WizardForm.StatusLabel.Caption := 'Installing Python requirements (this may take a few minutes)...';
  Ok := RunCmd(
    VenvPip,
    'install -r "' + AppDir + '\requirements.txt" --quiet',
    AppDir,
    'Installing Python requirements...'
  );
  if Ok then
    MsgBox(
      'Python requirements installed successfully!'               + #13#10#13#10 +
      'All dependencies from requirements.txt have been installed into the venv.',
      mbInformation, MB_OK
    )
  else
    MsgBox(
      'Dependency installation failed.'                          + #13#10 +
      'Check your internet connection, then run manually:'       + #13#10 +
      '  "' + VenvPip + '" install -r "' + AppDir + '\requirements.txt"',
      mbError, MB_OK
    );
end;
