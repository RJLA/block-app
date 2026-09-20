"""
Block Guard  (Windows 10 / 11)
------------------------------
Maintains a BLOCKLIST of websites and apps, and optionally enforces it:

  Websites : writes Chrome + Edge enterprise policy under
             HKLM\\SOFTWARE\\Policies\\...\\URLBlocklist = <your domains>
             Everything not listed stays reachable.
  Apps     : a watchdog that terminates user-session processes whose
             executable IS on the blocklist. Critical Windows processes
             are refused even if listed.

Stdlib only. Enforcement requires administrator rights.
"""

APP_NAME = "Block Guard"
TASK_NAME = "BlockGuard"
FOLDER_NAME = "BlockGuard"
CONFIG_NAME = "blocklist.json"
LOG_NAME = "guard.log"
VERSION = "2.0.0"

# How often the watchdog rescans running processes.
POLL_SECONDS = 5
