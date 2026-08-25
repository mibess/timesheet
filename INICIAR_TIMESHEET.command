#!/bin/zsh

set -u
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 não foi encontrado. Instale-o em https://www.python.org/downloads/"
  read -r "?Pressione Enter para fechar."
  exit 1
fi

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
  echo "O Timesheet CCEE requer Python 3.9 ou mais recente."
  echo "Atualize o Python em https://www.python.org/downloads/"
  read -r "?Pressione Enter para fechar."
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Preparando o ambiente do Timesheet CCEE…"
  python3 -m venv .venv || exit 1
fi

if ! .venv/bin/python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
  echo "O ambiente .venv usa uma versão antiga do Python."
  echo "Remova a pasta .venv e abra novamente após instalar o Python 3.9 ou mais recente."
  read -r "?Pressione Enter para fechar."
  exit 1
fi

if ! .venv/bin/python -c 'import hashlib,pathlib; r=pathlib.Path("requirements.txt").read_bytes(); m=pathlib.Path(".venv/.timesheet-requirements"); raise SystemExit(0 if m.is_file() and m.read_text() == hashlib.sha256(r).hexdigest() else 1)' >/dev/null 2>&1; then
  echo "Instalando as dependências do aplicativo…"
  .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt || {
    echo "Não foi possível instalar as dependências. Verifique sua internet."
    read -r "?Pressione Enter para fechar."
    exit 1
  }
  .venv/bin/python -c 'import hashlib,pathlib; r=pathlib.Path("requirements.txt").read_bytes(); pathlib.Path(".venv/.timesheet-requirements").write_text(hashlib.sha256(r).hexdigest())'
fi

exec .venv/bin/python run_timesheet.py
