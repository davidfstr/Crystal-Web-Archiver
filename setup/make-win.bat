set INNO_COMPILER="C:\Program Files\Inno Setup 5\Compil32.exe"

rmdir /s /q build dist dist-win
python setup.py py2exe
%INNO_COMPILER% /cc win-installer.iss
