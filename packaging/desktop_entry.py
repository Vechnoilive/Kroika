"""PyInstaller entry: dispatch workers before importing the application or GUI."""

import multiprocessing
import os
import sys


if __name__ == "__main__":
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    multiprocessing.freeze_support()
    from kroika_backend.desktop import main
    raise SystemExit(main())
