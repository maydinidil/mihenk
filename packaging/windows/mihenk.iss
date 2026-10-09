#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{83DA634F-AEEA-484A-BAFD-E5ADED97378D}
AppName=mihenk
AppVersion={#AppVersion}
AppPublisher=maydinidil
DefaultDirName={localappdata}\Programs\mihenk
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=mihenk-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes

[Files]
Source: "..\..\dist\mihenk\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: not WebView2Installed

[Icons]
Name: "{autoprograms}\mihenk"; Filename: "{app}\mihenk.exe"

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Installing Microsoft WebView2..."; Flags: waituntilterminated; Check: not WebView2Installed
Filename: "{app}\mihenk.exe"; Description: "Start mihenk"; Flags: nowait postinstall skipifsilent

[Code]
function HasVersion(Root: Integer; Key: String): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(Root, Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0');
end;

function WebView2Installed(): Boolean;
var
  Key: String;
begin
  Key := '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result := HasVersion(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + Key)
         or HasVersion(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\' + Key);
end;
