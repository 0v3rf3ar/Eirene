"""Frozen entry point."""

import multiprocessing
import sys

from eirene.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
