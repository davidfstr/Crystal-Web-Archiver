[Setup]
AppName=Crystal Web Archiver
AppVersion=1.0
DefaultDirName={pf}\Crystal Web Archiver
DefaultGroupName=Crystal Web Archiver
UninstallDisplayIcon={app}\Crystal Web Archiver.exe
Compression=lzma2
SolidCompression=yes
OutputBaseFilename=crystal-win-1.0
OutputDir=dist-win
DisableProgramGroupPage=yes

[Files]
Source: "dist\_hashlib.pyd"; DestDir: "{app}"
Source: "dist\_socket.pyd"; DestDir: "{app}"
Source: "dist\_sqlite3.pyd"; DestDir: "{app}"
Source: "dist\_ssl.pyd"; DestDir: "{app}"
Source: "dist\bz2.pyd"; DestDir: "{app}"
Source: "dist\Crystal Web Archiver.exe"; DestDir: "{app}"
Source: "dist\pyexpat.pyd"; DestDir: "{app}"
Source: "dist\python27.dll"; DestDir: "{app}"
Source: "dist\select.pyd"; DestDir: "{app}"
Source: "dist\sqlite3.dll"; DestDir: "{app}"
Source: "dist\unicodedata.pyd"; DestDir: "{app}"
Source: "dist\w9xpopen.exe"; DestDir: "{app}"
Source: "dist\wx._controls_.pyd"; DestDir: "{app}"
Source: "dist\wx._core_.pyd"; DestDir: "{app}"
Source: "dist\wx._gdi_.pyd"; DestDir: "{app}"
Source: "dist\wx._misc_.pyd"; DestDir: "{app}"
Source: "dist\wx._windows_.pyd"; DestDir: "{app}"
Source: "dist\wxbase28uh_net_vc.dll"; DestDir: "{app}"
Source: "dist\wxbase28uh_vc.dll"; DestDir: "{app}"
Source: "dist\wxmsw28uh_adv_vc.dll"; DestDir: "{app}"
Source: "dist\wxmsw28uh_core_vc.dll"; DestDir: "{app}"
Source: "dist\wxmsw28uh_html_vc.dll"; DestDir: "{app}"

[Icons]
Name: "{group}\Crystal Web Archiver"; Filename: "{app}\Crystal Web Archiver.exe"
