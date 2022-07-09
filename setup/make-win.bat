set INNO_COMPILER="C:\Program Files (x86)\Inno Setup 5\Compil32.exe"

rmdir /s /q build dist dist-win

call poetry run python setup.py py2exe
IF %ERRORLEVEL% NEQ 0 (
    echo "py2exe failed."
    exit %ERRORLEVEL%
)

copy media\vcruntime140.dll dist\vcruntime140.dll

%INNO_COMPILER% /cc win-installer.iss
IF %ERRORLEVEL% NEQ 0 (
    echo "Inno Setup compiler failed."
    exit %ERRORLEVEL%
)
