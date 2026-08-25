import sys


if sys.version_info < (3, 10):
    raise SystemExit(
        "O Timesheet CCEE requer Python 3.10 ou mais recente. "
        "Atualize o Python antes de abrir o aplicativo."
    )

from timesheet_ccee.ui import main


if __name__ == "__main__":
    main()
