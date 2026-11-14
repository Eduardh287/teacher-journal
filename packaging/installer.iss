; Inno Setup 6 script for the teacher journal (per-user, no admin rights).
; Build: packaging\build.ps1 (needs dist\TeacherJournal\ to exist first).
#define AppName "Електронний журнал"
#define AppExe "TeacherJournal.exe"

[Setup]
AppId={{7B1E6F52-4C0D-4E8A-9E53-0F6D2A1B7C34}
AppName={#AppName}
AppVersion=0.1.0
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

[Languages]
Name: "ukrainian"; MessagesFile: "compiler:Languages\Ukrainian.isl"

[Messages]
ukrainian.ConfirmUninstall=Видалити %1 з цього комп'ютера?%n%nДані журналу (оцінки, учні) НЕ видаляються: вони лишаються у папці %%LOCALAPPDATA%%\teacher-journal.

[Tasks]
Name: "desktopicon"; Description: "Створити ярлик на робочому столі"; Flags: unchecked

[Files]
Source: "..\dist\TeacherJournal\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Запустити {#AppName}"; Flags: nowait postinstall skipifsilent

; Uninstall removes only files installed into {app}; the data folder is never touched.
