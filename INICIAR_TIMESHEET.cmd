@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Preparando o ambiente do Timesheet CCEE...
  where py.exe >nul 2>&1
  if not errorlevel 1 (
    py -3 -m venv .venv
  ) else (
    where python.exe >nul 2>&1
    if errorlevel 1 (
      echo Python 3 nao foi encontrado.
      echo Instale-o em https://www.python.org/downloads/
      if not defined TIMESHEET_SILENT pause
      exit /b 1
    )
    python -m venv .venv
  )
  if errorlevel 1 (
    echo Nao foi possivel criar o ambiente Python.
    if not defined TIMESHEET_SILENT pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1
if errorlevel 1 (
  echo O Timesheet CCEE requer Python 3.9 ou mais recente.
  echo Se necessario, remova a pasta .venv e instale uma versao atual em https://www.python.org/downloads/
  if not defined TIMESHEET_SILENT pause
  exit /b 1
)

".venv\Scripts\python.exe" -c "import hashlib,pathlib; r=pathlib.Path('requirements.txt').read_bytes(); m=pathlib.Path('.venv/.timesheet-requirements'); raise SystemExit(0 if m.is_file() and m.read_text() == hashlib.sha256(r).hexdigest() else 1)" >nul 2>&1
if errorlevel 1 (
  echo Instalando as dependencias do aplicativo...
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 (
    echo Nao foi possivel instalar as dependencias. Verifique sua internet.
    if not defined TIMESHEET_SILENT pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -c "import hashlib,pathlib; r=pathlib.Path('requirements.txt').read_bytes(); pathlib.Path('.venv/.timesheet-requirements').write_text(hashlib.sha256(r).hexdigest())"
)

start "" ".venv\Scripts\pythonw.exe" run_timesheet.py
if errorlevel 1 exit /b 1
endlocal
exit /b 0
