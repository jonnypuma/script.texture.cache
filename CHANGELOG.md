# Changelog

All notable changes to Texture Cache Utility (`script.texture.cache`) are documented here.

## 2.0.6 — 2026-09-24

- **Import local artwork (qax, c, R)** is in **Pick commands…** for the command box and the scheduled sequence, as well as **Run preset…**

## 2.0.5 — 2026-09-24

- Preset **Import local artwork (qax, c, R)** refreshes library items from local NFO and artwork files, caches the new URLs, then removes orphaned thumbnails. A blank season plot refreshes the parent show so `season.nfo` is read

## 2.0.4 — 2026-09-22

- Verbose logging is the first switch on the Schedule page. When it is on, scheduler startup and on/off write details to kodi.log

## 2.0.3 — 2026-09-22

- If the next scheduled run time has already passed, that time is cleared and replaced with 2 hours from now. Turning the scheduler off blanks it; turning it on sets a new time 2 hours ahead

## 2.0.2 — 2026-09-22

- Turning the scheduler off and on starts the next run from that moment. Changing Repeat, hours, or days updates the next-run time immediately

## 2.0.1 — 2026-09-22

- Reload the addon so Kodi drops the saved next-run time. A passed due time shows **Due now**; a scheduled run in progress shows **Running**

## 2.0.0 — 2026-09-21

### Runs and locking

- Optional **Run in background** from the main menu or Commands settings (non-blocking progress). Scheduled runs always use background progress
- **Background run status** with live command/percent, last 3 runs, and **Stop current run**
- Keep the run lock until the worker thread finishes (including after Cancel)
- If a run is already in progress, a second start asks to stop it first (never two in parallel). Scheduled ticks skip instead of interrupting
- Cancelling the “waiting to stop” dialog leaves the current run running
- Lock heartbeat resumes after sleep instead of being treated as dead immediately
- Leftover `run.lock` is cleared when Kodi/the addon service starts, and when the process that owned it is gone. Runs always release the lock when they finish
- Cancel closes the progress dialog. Library loading, downloads, prune, and orphan scans stop instead of leaving the dialog on “Canceling…”
- Heartbeat the lock from acquire until release so confirm/preflight dialogs cannot look “stale”
- First time the scheduler is enabled, wait a full interval before the first automatic run
- Skip scheduled runs while a video or music library scan is in progress
- Toast when a scheduled run completes or finishes with errors
- Last scheduled run time in Schedule settings is a single read-only label (no extra button)
- Schedule repeat can be hours, days, weekly, or monthly. Appending commands skips ones already in the box
- Schedule settings show the earliest time the next run can start. A passed due time is replaced with Due now on startup, and Running while that scheduled run is active

### Web server and safety

- **Connection** setting: Auto, HTTP, or HTTPS. Auto follows this Kodi’s SSL setting; the same protocol is passed to texturecache
- Follow HTTP 301/302/303/307/308 redirects when downloading artwork
- Last results explain Undefined (empty artwork URL, not unknown media), sample those items, and tally download HTTP status codes with the failed URL
- Username-only web server auth is sent (empty password allowed)
- Confirm dialog always mentions background mode when it is on, including how to stop
- Confirm also warns for `power`, `exec`/`execw`, `play`/`playw`, and `purgetest`
- Download threads (1–32) and QA period (1–3650) are clamped before being passed through
- Pick commands no longer closes settings (stays on Commands / Schedule)

### Context menu

- Match by library ID (DBID), title, or both (setting). Default is library ID
- JSON-RPC uses per-type properties, then a smaller fallback, then the list title
- Episode and season confirm that the **TV show** will be cached, not only that item

### Export and tools

- Copy path to clipboard on Windows and macOS; other devices show the path
- Tools menu states that mklocal/fixart/clean are CLI-only and can show the tools folder
- Main menu stays open after Last results, Export, Help, Tools, and Settings

### Packaging

- Shared `common.py` for settings/lock/schedule/live-status helpers
- Remove Python 2 shims and obsolete `start="startup"` from the wrapper (the bundled engine still has unused Python 2 import branches)
- Identify this package as the Kodi GUI wrapper `script.texture.cache`
- Compressed `icon.png` / `fanart.jpg` (originals in `backup/`)

## 1.2.1 — 2026-08-15

### Settings

- Use this Kodi’s web server settings by default, with a connection test
- Command picker fills the sequence box
- Persist scheduled last-run across Kodi restarts
- File lock so GUI, context, and schedule cannot overlap

## 1.2.0 — 2026-07-25

### Packaging

- Rename addon id / folder from `script.texture.wrapper` to `script.texture.cache`

## 1.1.9 — 2026-07-25

### Security & polish

- Redact webserver passwords and OMDb API keys from verbose logs and argv logging
- Longer cancel join timeout (30s) with clearer status when a command is still finishing
- Results flow prefers **Run status → Summary → Full log path → Export → Details** (less pagination noise)

## 1.1.8 — 2026-07-25

### Packaging

- Richer `addon.xml` metadata: license, source, website, `news`, `summary`/`description` with `lang`
- Require `xbmc.python` 3.0.1 (Matrix+)

## 1.1.7 — 2026-07-25

### Packaging

- Convert `resources/settings.xml` to modern Matrix+ format (`version="1"` with section/category/group)

## 1.1.6 — 2026-07-25

### Localization

- Add `resources/language/resource.language.en_gb` and `en_us` (`strings.po`)
- Wire UI labels through localized string IDs with English fallbacks

## 1.1.5 — 2026-07-25

### Tools

- Expose bundled `tools/` via a Tools menu (run `fixurls`, view help for mklocal/fixart/clean)

## 1.1.4 — 2026-07-25

### Schedule

- Background `service.py` for optional scheduled maintenance
- Settings: enable service, interval (hours), idle requirement, dedicated command sequence

## 1.1.3 — 2026-07-25

### Library integration

- Context menu item **Cache artwork for this item** for movies, TV, music, and sets
- New `context.py` entry point

## 1.1.2 — 2026-07-25

### Export

- Export last output: show path, copy/display path, open folder in FileManager
- Available from main menu and results dialog

## 1.1.1 — 2026-07-25

### Settings

- Expose advanced texturecache options in the UI: download threads, lastrunfile, OMDb API key, allow re-cache all, cache cast thumbs, QA period
- Pass through as `@key=value` overrides (same as webserver settings)

## 1.1.0 — 2026-07-25

### Progress

- Live progress text and percent from texturecache (`progress_message` / `progress_percent`)
- Dialog shows caching remaining counts / loading messages instead of elapsed time only

## 1.0.9 — 2026-07-25

### Results

- Per-command run status (OK / FAIL / CANCELLED + duration) written to status file and shown first in results

## 1.0.8 — 2026-07-25

### Reliability

- **Continue sequence on error** setting — remaining commands can proceed after a failure

## 1.0.7 — 2026-07-25

### Safety

- Preflight checks for Kodi web server and remote-control settings before cache commands
- Optional; can continue after warning

## 1.0.6 — 2026-07-25

### Results

- **Last results** menu/settings action to reopen the previous output without re-running
- Remember output path via addon profile marker file

## 1.0.5 — 2026-07-25

### Safety

- Dry-run default for prune: `P` is rewritten to `p` unless **Allow prune delete (P)** is enabled

## 1.0.4 — 2026-07-25

### Safety

- Confirmation dialog before destructive commands (`P`, `R`, `Xd`, `purge`, `remove`, `C`, cleans, etc.)
- Toggle: **Confirm destructive commands** (default on)

## 1.0.3 — 2026-07-25

### UX

- Media-type scope picker (All / Movies / TV / Music / …) when using presets that support `{media}`

## 1.0.2 — 2026-07-25

### UX

- Command presets: cache missing, cache+orphans, identify, prune preview/delete, QA, stats, custom

## 1.0.1 — 2026-07-25

### UX

- Launch menu instead of immediately running the sequence
- Entries: Run preset, Run custom, Last results, Export, Supported commands, Tools, Settings

## 1.0.0 — 2026-07-25

### Baseline

- GUI wrapper for Milhouse's texturecache (cache, prune, orphans, QA, library tools)
- Configurable comma-separated command sequences
- Progress dialog with elapsed time and cancel support
- Streamed command output to file (low RAM) with results modal
- Web server host/port/credentials in addon settings
- Verbose logging toggle and supported-commands help viewer
