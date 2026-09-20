#!/usr/bin/env python3
"""Block Guard entry point.

    python block_guard.py            open the window
    python block_guard.py --enforce  open and start the watchdog (needs admin)
"""

from blockguard.ui_app import main

if __name__ == "__main__":
    main()
