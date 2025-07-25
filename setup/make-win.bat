@set INNO_COMPILER="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

@echo Clearing dist...
rmdir /s /q build dist dist-win 2>nul

@echo Building executable...
call poetry run python setup.py py2exe -q
@IF %ERRORLEVEL% NEQ 0 (
    @echo "py2exe failed."
    @exit %ERRORLEVEL%
)

@echo Copying in C runtime DLL...
copy media\vcruntime140\*.dll dist\ >nul

@echo Copying in tzdata...
call poetry run python -c "import os, shutil, tzdata; shutil.copytree(tzdata.__path__[0], os.path.join('dist', 'lib', 'tzdata'))"

@echo Built files:
dir dist

@echo Regenerating list of built files in installer script...
call poetry run python make_win_installer.py

@echo Building installer...
%INNO_COMPILER% /Q win-installer.iss
@IF %ERRORLEVEL% NEQ 0 (
    @echo "Inno Setup compiler failed."
    @exit %ERRORLEVEL%
)
