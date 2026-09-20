# Installing Block Guard on a PC with nothing installed

Block Guard keeps a **blocklist**: you list the websites and apps you want
stopped, and everything you do not list is left alone.

The target PC needs **no Python, no pip, no dependencies**. You build a
self-contained `.exe` once on a machine that has Python, then carry a single
installer file over.

- **Part 1** runs once, on *your* machine (needs Python).
- **Part 2** runs on *each* target PC (needs nothing but Windows 10/11 and an
  administrator account).

If someone has already handed you `BlockGuardSetup.exe`, skip to Part 2.

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

PyInstaller, Pillow and pytest are **not** prerequisites — `build.bat` installs
them into a repo-local `.venv` on first run. See `requirements-dev.txt`.

### 1.2 Build the executable

From the repository root:

```bat
build.bat
```

On first run this creates a **repo-local virtual environment in `.venv`** and
installs the build tools into it. Your system Python is only used to bootstrap
that venv — nothing is installed globally. Later runs reuse the existing
`.venv`.

The output is **`dist\BlockGuard.exe`** (~10 MB, one file), bundling the
CPython interpreter, tkinter, the mascot assets, and `default_blocklist.json` —
which is why the target PC needs nothing.

To set the venv up by hand instead:

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

> The mascot assets in `assets/` are committed to the repo, so a normal build
> needs nothing extra. Only if you change `pepe_cry.png` do you need to
> regenerate them:
>
> ```bat
> .venv\Scripts\python.exe tools\make_assets.py
> ```

### 1.3 Run the tests (optional)

```bat
.venv\Scripts\python.exe -m pytest --cov=blockguard
```

### 1.4 Build the installer (recommended)

```bat
iscc installer.iss
```

Produces **`Output\BlockGuardSetup.exe`** (~12 MB). `iscc` is not added to
`PATH` by the installer, so use the full path. A winget install puts it under
your user profile rather than Program Files:

```bat
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer.iss
```

Inno Setup itself can be installed with:

```bat
winget install --id JRSoftware.InnoSetup
```

**Copy that one file to the target PC.** Nothing else needs to travel with it.
The bare `dist\BlockGuard.exe` also works on its own if you skip the installer.

---

## Part 2 — Install on the target PC

### 2.1 What you need

- Windows 10 or later (the installer enforces `MinVersion=10.0`)
- An **administrator** account — enforcement writes to `HKLM` and terminates
  processes, neither of which works without it

### 2.2 Run the installer

Double-click **`BlockGuardSetup.exe`**.

**Expect a SmartScreen warning.** The executable is unsigned, so Windows shows
*"Windows protected your PC"*. Click **More info → Run anyway**. Signing the
binary with a real certificate is the only clean fix.

**Expect possible antivirus complaints.** A PyInstaller one-file build that
terminates processes and writes browser policy to `HKLM` matches malware
heuristics closely. You may need an exclusion for
`C:\Program Files\BlockGuard\`.

Click **Yes** at the UAC prompt, then walk the wizard. Two optional checkboxes,
both unticked by default:

| Checkbox | Effect |
|---|---|
| Create a desktop shortcut | Adds a desktop icon |
| Start Block Guard at logon | Registers a scheduled task that runs the app elevated and **hidden** (`--background`) at every logon |

Leave **"Start Block Guard at logon" unticked for now** — turn it on from
inside the app once your lists are right (see 2.6).

### 2.3 What the installer puts where

| Path | Contents |
|---|---|
| `C:\Program Files\BlockGuard\BlockGuard.exe` | The application |
| `C:\ProgramData\BlockGuard\blocklist.json` | Your lists — seeded from the default **only if no config exists** |
| `C:\ProgramData\BlockGuard\security.json` | Salted PBKDF2 digest of the PIN — never the PIN itself |
| `C:\ProgramData\BlockGuard\guard.log` | Timestamped activity log |
| Scheduled task `BlockGuard` | Only if you ticked the logon option |

### 2.4 First run — create the PIN

Launch **Block Guard** and accept the UAC prompt. The first time it opens it
asks you to **create a 6-digit PIN**, entered twice. Nothing else is reachable
until you do.

From then on, every launch opens on a lock screen and the blocklist stays
hidden until the PIN is entered — so a student cannot see or change what is
blocked. Use **Lock** (bottom right) to re-lock without closing the app, and
**Change PIN** on the Enforcement tab to replace it (the current PIN is
required).

**Enforcement does not wait for the PIN.** When the logon task starts the app
with `--background`, the watchdog and website blocks come up immediately with
no window at all. There is nothing for a student to dismiss, and dismissing the
lock screen when it is shown does not unblock anything either.

The PIN itself is never stored — only a salted PBKDF2-SHA256 digest in
`C:\ProgramData\BlockGuard\security.json`. After 3 wrong entries a lockout
starts and grows with each further attempt, up to 15 minutes; it is written to
disk, so closing and reopening the app does not clear it.

On enrollment the app also restricts `C:\ProgramData\BlockGuard\` to
administrators, so a standard user cannot simply delete the PIN and blocklist
files to undo everything.

> **Be clear about what this does and does not stop.** The PIN keeps ordinary
> students out of the settings. It is not a defence against someone with
> administrator rights on the machine: an admin can uninstall the app, delete
> the config, edit the registry directly, or end the process from Task Manager.
> If students have admin on these PCs, no application-level control will hold —
> take admin away from their accounts first, and run Block Guard elevated from
> a separate account.

### 2.5 Build your blocklist

The bottom status bar should read `administrator`; if it says `NOT elevated —
enforcement disabled`, close it and use **Run as administrator**.

**The easy way — the "Installed apps" tab.** It scans this PC (uninstall
registry plus running processes) and lists what it finds, with apps that are
running right now sorted to the top. Search by name, select one or more rows,
and click **Block selected** — they are added to the blocked apps list with the
correct executable name already worked out. Double-clicking a row does the
same.

**The manual way — the "Blocklists" tab.** Type entries directly:

- *Blocked websites* — `facebook.com` form. Input is normalized, so
  `https://www.Facebook.com/feed` becomes `facebook.com`, and a domain
  automatically covers its subdomains.
- *Blocked apps* — `steam.exe`, a full path, or just `steam` all normalize to
  `steam`.

Use the **Check** box to test any entry. A blocked lookup shows the crying frog
and **BLOCKED**; anything else reports **not blocked**.

Changes save immediately — there is no Save button.

> **Critical Windows processes are refused even if you list them.** Adding
> `explorer` to the list will not terminate your desktop; the Check box will
> report it as *not blocked*. The same protection covers Block Guard itself.

### 2.6 Turn on enforcement

On the **Enforcement** tab:

**Step 1 — Dry run the app watchdog.** Leave *"Dry run (log only, don't
terminate)"* **ticked** and click **Start app watchdog**. Every 5 seconds it
scans running processes and writes `[dry run] would terminate <name> (pid N)`
to the **Activity** tab for anything on your blocklist. Confirm it names only
what you intend.

**Step 2 — Go live.** Click **Stop app watchdog**, untick *Dry run*, then click
**Start app watchdog** and confirm the warning, which lists exactly what will
be terminated.

> Stopping first is deliberate. The dry-run checkbox is read live on every
> scan, so unticking it while the watchdog runs goes straight to terminating
> processes **without** showing the confirmation dialog.

The blocklist itself is re-read on every scan, so adding an app takes effect
within about 5 seconds with no restart.

**Step 3 — Website blocks.** Click **Apply website blocks**. This writes the
listed domains to Chrome and Edge `URLBlocklist` policy. The status label flips
to **active**.

- **Restart the browser** — policy only takes effect on a fresh launch.
- **Verify** at `chrome://policy` (or `edge://policy`) → *Reload policies*.
- **Firefox and other browsers are not covered.** Block them as apps instead.

**Step 4 — Survive reboots.** Click **Start at logon (background)** to register
the scheduled task. Without it the watchdog stops when you close the app; the
website policy persists either way, since it lives in the registry.

---

## Background mode

With the logon task registered, Block Guard starts **hidden** every time the
student signs in. There is no window, no taskbar button and no tray icon — the
blocks are simply already in force. A blocked app closes with the frog notice,
which is the only thing the student ever sees.

**To get back in**, launch Block Guard normally — Start menu, desktop shortcut
or the executable. That does not start a second copy: it signals the one
already running, which brings up its lock screen. Enter the PIN and the tabs
appear as usual.

**Closing the window does not stop enforcement** while in background mode. It
re-locks and hides again, and the watchdog keeps running. To genuinely stop it,
untick **Start at logon**, stop the watchdog, and remove the website blocks.

> **Put the executable somewhere permanent before enabling this.** The
> scheduled task stores an absolute path, so if you run Block Guard from a USB
> stick, Downloads or the Desktop and later move or delete it, the task
> silently fails at every logon with no error. Installing via
> `BlockGuardSetup.exe` handles this for you by placing it in Program Files.

---

---

## What the student sees

**A blocked app.** It opens normally, then closes within about 5 seconds — the
watchdog's scan interval. A notice appears in the bottom-right corner with the
mascot:

> **Steam is blocked**
> Ask your Tito or Mommy Joy to unblock it.

A short "failure trumpet" plays at the same moment. It dismisses itself after
7 seconds, or on click. If an app spawns many
processes — a browser is typically a dozen — they are all closed, but only one
notice is shown, and the same app will not raise another for 30 seconds.

Where possible the notice uses the app's proper name from the Installed apps
scan ("Google Chrome" rather than "chrome").

Neither the notice nor the sound appears during a dry run, since nothing is
actually being closed.

The sound is played through Windows MCI. A PC with no audio device, or a
remote session, simply gets the notice without it.

> Termination is a forced kill of the process tree, so anything unsaved in a
> blocked app is lost without a prompt. Keep the blocklist to things like games
> and chat apps rather than anything document-shaped.

**At logon.** Nothing. Block Guard starts hidden; the student sees no window
and no prompt, only that blocked things do not work.

**A blocked website.** Chrome and Edge show their own built-in block page
(`ERR_BLOCKED_BY_ADMINISTRATOR`), saying the page was blocked by the
administrator. That wording comes from the browser, not from Block Guard.

The frog notice and the trumpet also appear, a second or two later. Block Guard
cannot see browser navigation, so it works this out from the browser's window
title: a blocked tab is titled with the host it refused to load. Matching is
strict on purpose — searching Google for "reddit.com" is titled
`reddit.com - Google Search` and deliberately does **not** trigger a notice.

Because it is a title heuristic rather than a hook into the browser, it is
worth confirming once on a new machine: block a site, open it, and check the
**Activity** tab for `blocked site on screen: <host>`. If the notice does not
appear, the browser is titling the blocked page differently — the list of
recognised browser suffixes is `BROWSER_SUFFIXES` in
`blockguard/browser_watch.py`.

Other browsers are not policy-managed, so the site loads normally and no notice
appears — block them as apps instead.

---

## Uninstalling

**Settings → Apps → Block Guard → Uninstall**, or the Start-menu entry.

The uninstaller deliberately unlocks the machine: it deletes the scheduled task
and the policy registry keys, so you are not left with blocked sites after the
app is gone.

It does **not** delete `C:\ProgramData\BlockGuard\` — your lists and log survive
a reinstall. Remove that folder by hand for a clean slate.

To undo enforcement without uninstalling: **Remove website blocks**, **Stop app
watchdog**, **Stop running at logon**.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `NOT elevated — enforcement disabled` | Not running as admin. Relaunch via **Run as administrator**, or accept the app's offer to restart elevated. |
| Blocked sites still load | The browser wasn't restarted. Check `chrome://policy` → *Reload policies*. |
| Firefox ignores the block | Expected — only Chrome and Edge policy is written. Block `firefox` as an app instead. |
| A blocked app keeps running | Confirm the watchdog is started, *Dry run* is unticked, and the name matches. The Check box tells you what the app will actually match on. |
| Listing `explorer` does nothing | By design — critical Windows processes are protected and can never be terminated. |
| An app isn't in the "Installed apps" list | Not every installer records a usable executable. Launch the app, tick **Running now only**, and it will appear — or type its name manually. |
| Nothing happens at logon | The task only exists if you ticked the installer option or clicked **Start at logon**. Verify with `schtasks /Query /TN BlockGuard`. |
| Blocks stopped working after moving the exe | The logon task stores an absolute path. Re-register it with **Start at logon** from the new location, or reinstall. |
| Double-clicking Block Guard seems to do nothing | It is already running in the background; the launch signals that copy, and its lock screen should appear within a second. If it does not, check Task Manager for `BlockGuard.exe`. |
| Want the blocks gone immediately | Delete the keys under `HKLM\SOFTWARE\Policies\Google\Chrome` and `...\Microsoft\Edge`, then `schtasks /Delete /F /TN BlockGuard`. |
| SmartScreen blocks the installer | Unsigned binary — **More info → Run anyway**, or sign it. |
| Forgot the PIN | As an administrator, delete `C:\ProgramData\BlockGuard\security.json`. The app will ask you to enroll a new PIN on the next launch; the blocklist is untouched. |
| "Too many wrong attempts" | The lockout is deliberate and persists across restarts. Wait for the countdown, or clear it by deleting `security.json` as an administrator. |
| A student edited the blocklist anyway | They have administrator rights. Remove those first — no application-level lock survives an admin account. |

Activity is logged to `C:\ProgramData\BlockGuard\guard.log`; the path is shown
at the bottom of the **Activity** tab.
