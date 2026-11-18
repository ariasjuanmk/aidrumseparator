; Instalador de AI Drum Separation (Inno Setup 6). Solo ASCII a proposito.
; Compilar:  ISCC.exe installer\AIDrumSeparator.iss [/DAppVersion=0.1.0]
; Requiere que exista ..\dist\AI Drum Separation.vst3 (lo deja el workflow de build).

#define AppName "AI Drum Separation"
#ifndef AppVersion
  #define AppVersion "0.1.1"
#endif

[Setup]
AppId={{3F9A5D21-8C47-4E0B-A6D3-52B1E7C94F08}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=StemTools
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
OutputDir=Output
OutputBaseFilename=AIDrumSeparator-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName}
SetupLogging=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "engine"; Description: "Instalar ahora el motor de IA (Python + PyTorch + audio-separator). Descarga varios GB, recomendado"; GroupDescription: "Motor de IA:"
Name: "cpuonly"; Description: "Usar solo CPU (no instalar PyTorch con CUDA)"; GroupDescription: "Motor de IA:"; Flags: unchecked

[Files]
; el plugin va a la carpeta VST3 estandar que escanean todos los DAWs
Source: "..\dist\AI Drum Separation.vst3\*"; DestDir: "{commoncf64}\VST3\AI Drum Separation.vst3"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "install_engine.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\engine\drum_engine.py"; DestDir: "{app}"; Flags: ignoreversion
; instaladores incluidos (los baja el workflow de build): el usuario no depende de python.org para Python
Source: "redist\python-installer.exe"; DestDir: "{app}\redist"; Flags: ignoreversion skipifsourcedoesntexist
Source: "redist\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: ignoreversion deleteafterinstall skipifsourcedoesntexist

[Run]
; Visual C++ Runtime (lo necesitan PyTorch y el plugin). Si ya esta instalado, no hace nada.
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Instalando Visual C++ Runtime..."; Flags: waituntilterminated skipifdoesntexist
; Se ejecuta como el usuario que lanzo el instalador (no como administrador), para que
; el motor quede en SU %LOCALAPPDATA%, que es donde lo busca el plugin.
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install_engine.ps1"" -EngineScript ""{app}\drum_engine.py"" -PythonInstaller ""{app}\redist\python-installer.exe"""; StatusMsg: "Instalando el motor de IA (puede tardar varios minutos)..."; Flags: runasoriginaluser waituntilterminated; Tasks: engine and not cpuonly
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install_engine.ps1"" -EngineScript ""{app}\drum_engine.py"" -PythonInstaller ""{app}\redist\python-installer.exe"" -CpuOnly"; StatusMsg: "Instalando el motor de IA (CPU)..."; Flags: runasoriginaluser waituntilterminated; Tasks: engine and cpuonly

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if MsgBox('Borrar tambien el motor de IA, los modelos y la cache de stems?' + #13#10 +
              '(ocupan varios GB, en ' + ExpandConstant('{localappdata}\AIDrumSeparator') + ')',
              mbConfirmation, MB_YESNO) = IDYES then
      DelTree(ExpandConstant('{localappdata}\AIDrumSeparator'), True, True, True);
  end;
end;
