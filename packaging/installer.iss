; Inno Setup 6 script for the teacher journal (per-user, no admin rights).
; Build: packaging\build.ps1 (needs dist\TeacherJournal\ to exist first).
#define AppName "Електронний журнал"
#define AppExe "TeacherJournal.exe"
; The version comes from pyproject.toml via packaging\build.ps1 (ISCC /DAppVersion=x.y.z).
#ifndef AppVersion
  #error AppVersion is not defined. Build with packaging\build.ps1.
#endif

[Setup]
AppId={{7B1E6F52-4C0D-4E8A-9E53-0F6D2A1B7C34}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher=Teacher Journal
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\TeacherJournal
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=TeacherJournal-Setup
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=icon.ico
; One running copy: the app creates this named mutex (single_instance.MUTEX_NAME).
AppMutex=TeacherJournal-Running
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "ukrainian"; MessagesFile: "compiler:Languages\Ukrainian.isl"

[Messages]
ukrainian.ConfirmUninstall=Видалити %1 з цього комп'ютера?%n%nДані журналу (оцінки, учні) НЕ видаляються: вони лишаються на цьому комп'ютері в папці даних програми.

[Tasks]
Name: "desktopicon"; Description: "Створити ярлик на робочому столі"; Flags: unchecked

[Files]
Source: "..\dist\TeacherJournal\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Запустити {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop the embedded database server of this install before its files are removed (the app is closed by now).
Filename: "{app}\{#AppExe}"; Parameters: "--stop-server"; Flags: runhidden waituntilterminated; RunOnceId: "StopEmbeddedServer"

[Code]
// On upgrade (same AppId, same folder) stop the embedded server before files are replaced.
// The data folder is never touched. First start after the upgrade runs the backup + migration.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  Helper: String;
begin
  Helper := ExpandConstant('{app}\{#AppExe}');
  if FileExists(Helper) then
    Exec(Helper, '--stop-server', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

// Uninstall removes only files installed into {app}; the data folder is never touched.
