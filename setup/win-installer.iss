[Setup]
AppName=Crystal Web Archiver
AppVersion=1.3.0b
AppCopyright=Copyright (C) 2011-2022 David Foster. All Rights Reserved
DefaultDirName={pf}\Crystal Web Archiver
DefaultGroupName=Crystal Web Archiver
UninstallDisplayIcon={app}\Crystal Web Archiver.exe
Compression=lzma2
SolidCompression=yes
OutputBaseFilename=crystal-win-1.3.0b
OutputDir=dist-win
DisableProgramGroupPage=yes

; NOTE: To regenerate file list: poetry run python make_win_installer.py
[Files]
Source: "dist\Crystal Web Archiver.exe"; DestDir: "{app}"
Source: "dist\MSVCP140.dll"; DestDir: "{app}"
Source: "dist\_asyncio.pyd"; DestDir: "{app}"
Source: "dist\_bz2.pyd"; DestDir: "{app}"
Source: "dist\_ctypes.pyd"; DestDir: "{app}"
Source: "dist\_decimal.pyd"; DestDir: "{app}"
Source: "dist\_elementtree.pyd"; DestDir: "{app}"
Source: "dist\_hashlib.pyd"; DestDir: "{app}"
Source: "dist\_lzma.pyd"; DestDir: "{app}"
Source: "dist\_multiprocessing.pyd"; DestDir: "{app}"
Source: "dist\_overlapped.pyd"; DestDir: "{app}"
Source: "dist\_queue.pyd"; DestDir: "{app}"
Source: "dist\_socket.pyd"; DestDir: "{app}"
Source: "dist\_sqlite3.pyd"; DestDir: "{app}"
Source: "dist\_ssl.pyd"; DestDir: "{app}"
Source: "dist\_testcapi.pyd"; DestDir: "{app}"
Source: "dist\_tkinter.pyd"; DestDir: "{app}"
Source: "dist\cacert.pem"; DestDir: "{app}"
Source: "dist\concrt140.dll"; DestDir: "{app}"
Source: "dist\libcrypto-1_1.dll"; DestDir: "{app}"
Source: "dist\libffi-7.dll"; DestDir: "{app}"
Source: "dist\libssl-1_1.dll"; DestDir: "{app}"
Source: "dist\msvcp140_1.dll"; DestDir: "{app}"
Source: "dist\msvcp140_2.dll"; DestDir: "{app}"
Source: "dist\msvcp140_atomic_wait.dll"; DestDir: "{app}"
Source: "dist\msvcp140_codecvt_ids.dll"; DestDir: "{app}"
Source: "dist\pyexpat.pyd"; DestDir: "{app}"
Source: "dist\python38.dll"; DestDir: "{app}"
Source: "dist\select.pyd"; DestDir: "{app}"
Source: "dist\sqlite3.dll"; DestDir: "{app}"
Source: "dist\tcl86t.dll"; DestDir: "{app}"
Source: "dist\tk86t.dll"; DestDir: "{app}"
Source: "dist\unicodedata.pyd"; DestDir: "{app}"
Source: "dist\vcamp140.dll"; DestDir: "{app}"
Source: "dist\vccorlib140.dll"; DestDir: "{app}"
Source: "dist\vcomp140.dll"; DestDir: "{app}"
Source: "dist\vcruntime140.dll"; DestDir: "{app}"
Source: "dist\wx._adv.pyd"; DestDir: "{app}"
Source: "dist\wx._core.pyd"; DestDir: "{app}"
Source: "dist\wx._html.pyd"; DestDir: "{app}"
Source: "dist\wx._msw.pyd"; DestDir: "{app}"
Source: "dist\wx.siplib.pyd"; DestDir: "{app}"
Source: "dist\wxbase315u_net_vc140.dll"; DestDir: "{app}"
Source: "dist\wxbase315u_vc140.dll"; DestDir: "{app}"
Source: "dist\wxmsw315u_core_vc140.dll"; DestDir: "{app}"
Source: "dist\wxmsw315u_html_vc140.dll"; DestDir: "{app}"

[Icons]
Name: "{group}\Crystal Web Archiver"; Filename: "{app}\Crystal Web Archiver.exe"
