# Installing Allowlist Guard on a PC with nothing installed

The target PC needs **no Python, no pip, no dependencies**. You build a
self-contained `.exe` once on a machine that has Python, then carry a single
installer file over.

- **Part 1** runs once, on *your* machine (needs Python).
- **Part 2** runs on *each* target PC (needs nothing but Windows 10/11 and an
  administrator account).

If someone has already handed you `AllowlistGuardSetup.exe`, skip straight to
Part 2.

---

## Part 1 — Build the installer (machine with Python)

### 1.1 Requirements

| Tool | Version | Notes |
|---|---|---|
| Windows | 10 or 11 | PyInstaller cannot cross-compile — you must build on Windows |
| Python | 3.9+ | `python --version`; must be on `PATH` |
| Inno Setup | 6.x | Optional, only for the installer — [download](https://jrsoftware.org/isdl.php) |

Build on the **oldest Windows version you need to support**, and on **64-bit**
unless a target is 32-bit — the output only runs on the architecture you build
for.

PyInstaller and Pillow are **not** prerequisites — `build.bat` installs them
into a repo-local `.venv` on first run. See `requirements-dev.txt`.

### 1.2 Build the executable

From the repository root:

```bat
build.bat
```

On first run this creates a **repo-local virtual environment in `.venv`** and
installs the build tools from `requirements-dev.txt` into it. Your system
Python is only used to bootstrap that venv — nothing is installed globally.
Later runs reuse the existing `.venv`.

The output is **`dist\AllowlistGuard.exe`** (~10 MB, one file), bundling the
CPython interpreter, tkinter, the mascot assets, and `default_allowlist.json` —
which is why the target PC needs nothing.

To set the venv up by hand instead:

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

The `--uac-admin` flag embeds a manifest, so the app always requests elevation
on launch.

> The mascot assets in `assets/` are committed to the repo, so a normal build
> needs nothing extra. Only if you change `pepe_cry.png` do you need to
> regenerate them — that step uses Pillow from the venv and is the only part of
> the project that isn't stdlib-only:
>
> ```bat
> .venv\Scripts\python.exe tools\make_assets.py
> ```

At this point `dist\AllowlistGuard.exe` is already usable — you can copy that
single file to the target PC and run it. The installer below just adds
shortcuts, the logon task, and clean removal.

### 1.3 Build the installer (recommended)

```bat
iscc installer.iss
```

Produces **`Output\AllowlistGuardSetup.exe`**. If `iscc` isn't on `PATH`, use
the full path, typically:

```bat
"C:\Program Files (x86)\Inno Setup 6\iscc.exe" installer.iss
```

**Copy that one file to the target PC** — USB, network share, whatever. Nothing
else needs to travel with it.

---

## Part 2 — Install on the target PC

### 2.1 What you need

- Windows 10 or later (the installer enforces `MinVersion=10.0`)
- An **administrator** account — enforcement writes to `HKLM` and terminates
  processes, neither of which works without it

### 2.2 Run the installer

Double-click **`AllowlistGuardSetup.exe`**.

**Expect a SmartScreen warning.** The executable is unsigned, so Windows shows
*"Windows protected your PC"*. Click **More info → Run anyway**. The only clean
fix is signing the binary with a real code-signing certificate.

**Expect possible antivirus complaints.** A PyInstaller one-file build that
terminates processes and writes browser policy to `HKLM` matches malware
heuristics almost exactly. You may need to add an exclusion for
`C:\Program Files\AllowlistGuard\`.

Click **Yes** at the UAC prompt, then walk the wizard. Two optional checkboxes,
both unticked by default:

| Checkbox | Effect |
|---|---|
| Create a desktop shortcut | Adds a desktop icon |
| Start enforcement at logon | Registers a scheduled task that runs the app elevated with `--enforce` at every logon |

Leave **"Start enforcement at logon" unticked for now.** Turn it on later, from
inside the app, once you've confirmed your lists are right — see 2.5.

### 2.3 What the installer puts where

| Path | Contents |
|---|---|
| `C:\Program Files\AllowlistGuard\AllowlistGuard.exe` | The application |
| `C:\ProgramData\AllowlistGuard\allowlist.json` | Your lists — seeded from the default **only if no config exists** |
| `C:\ProgramData\AllowlistGuard\guard.log` | Timestamped activity log |
| Scheduled task `AllowlistGuard` | Only if you ticked the logon option |

### 2.4 First run — build your lists

Launch **Allowlist Guard** and accept the UAC prompt. The bottom status bar
should read `administrator`; if it says `NOT elevated — enforcement disabled`,
close it and use **Run as administrator**.

On the **Lists** tab:

1. Add domains under *Allowed websites* — `example.com` form. Input is
   normalized, so `https://www.Example.com/path` becomes `example.com`, and a
   domain automatically covers its subdomains.
2. Add programs under *Allowed apps* — `slack.exe`, a full path, or just
   `slack` all normalize to `slack`.
3. Use the **Check** box to test any name before committing to it. A blocked
   lookup shows the crying frog and **NOT ON THE LIST**.

Changes save immediately — there is no Save button.

> **Add every program you actually need before going live**, including your
> browser. Windows system processes and anything under `C:\Windows` are always
> spared, but ordinary apps are not.

### 2.5 Turn on enforcement

On the **Enforcement** tab, in this order:

**Step 1 — Dry run the app watchdog.** Leave *"Dry run (log only, don't
terminate)"* **ticked** and click **Start app watchdog**. Every 5 seconds it
scans running processes and writes `[dry run] would terminate <name> (pid N)`
to the **Activity** tab for anything not on your list. Let it run a few minutes
while you use the PC normally.

**This dry-run list is your real safety check.** Anything in it that you need,
add to the app allowlist now — the watchdog re-reads the list on every scan, so
additions take effect within about 5 seconds, with no restart.

**Step 2 — Go live.** Click **Stop app watchdog**, untick *Dry run*, then click
**Start app watchdog** and confirm the warning. Unlisted programs are now
terminated as they appear.

> Stopping first is deliberate. The dry-run checkbox is read live on every
> scan, so unticking it while the watchdog runs goes straight to killing
> processes **without** showing the confirmation dialog.

**Step 3 — Website policy.** Click **Apply website policy**. This writes
Chrome and Edge enterprise policy: block everything (`URLBlocklist = *`), then
allow your listed domains. The status label flips to **active**.

- **Restart the browser** — policy only takes effect on a fresh launch.
- **Verify** at `chrome://policy` (or `edge://policy`) → *Reload policies*. You
  should see `URLBlocklist` and `URLAllowlist` populated.
- **Firefox and other browsers are not covered.** Block them through the app
  watchdog if you need full coverage.

**Step 4 — Survive reboots.** Click **Run at logon** to register the scheduled
task (same thing the installer checkbox does). Without this, the watchdog stops
when you close the app; the website policy persists either way, since it lives
in the registry.

---

## Uninstalling

**Settings → Apps → Allowlist Guard → Uninstall**, or the Start-menu entry.

The uninstaller deliberately unlocks the machine: it deletes the scheduled task
and all four policy registry keys, so you are not left with a browser that
blocks everything after the app is gone.

It does **not** delete `C:\ProgramData\AllowlistGuard\` — your lists and log
survive a reinstall. Remove that folder by hand if you want a clean slate.

To undo enforcement without uninstalling: **Remove website policy**, **Stop app
watchdog**, **Stop running at logon**.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `NOT elevated — enforcement disabled` | Not running as admin. Relaunch via **Run as administrator**, or accept the app's offer to restart elevated. |
| Websites still load after applying policy | The browser wasn't restarted. Check `chrome://policy` → *Reload policies*. |
| Firefox ignores the block entirely | Expected — only Chrome and Edge policy is written. Block `firefox` via the app watchdog. |
| The watchdog kills something you need | Add it to the app allowlist — it applies on the next 5-second scan. Use dry run first to avoid this. |
| Watchdog does nothing in live mode | Confirm *Dry run* is unticked, the watchdog is started, and the button reads **Stop app watchdog**. |
| Nothing happens at logon | The task only exists if you ticked the installer option or clicked **Run at logon**. Verify with `schtasks /Query /TN AllowlistGuard`. |
| Locked out and can't open the app | Boot into Safe Mode, then delete the policy keys under `HKLM\SOFTWARE\Policies\Google\Chrome` and `...\Microsoft\Edge`, and run `schtasks /Delete /F /TN AllowlistGuard`. |
| SmartScreen blocks the installer | Unsigned binary — **More info → Run anyway**, or sign it. |

Activity is logged to `C:\ProgramData\AllowlistGuard\guard.log`; the path is
shown at the bottom of the **Activity** tab.
