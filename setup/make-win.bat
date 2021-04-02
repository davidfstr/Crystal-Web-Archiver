set INNO_COMPILER="C:\Program Files (x86)\Inno Setup 5\Compil32.exe"

rmdir /s /q build dist dist-win
call poetry run python setup.py py2exe
%INNO_COMPILER% /cc win-installer.iss
