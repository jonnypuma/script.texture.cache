# Texture Cache Utility (Kodi Addon)

**Project page:** [jonnypuma.github.io/#/script.texture.cache](https://jonnypuma.github.io/#/script.texture.cache) · **All add-ons and apps by jonnypuma:** [jonnypuma.github.io](https://jonnypuma.github.io/)

A Kodi addon that provides a GUI wrapper for [Milhouse's texturecache](https://github.com/xbmc/texturecache) — the utility for managing and refreshing the Kodi texture cache (Textures13.db and Thumbnails folder).

**Current version: 2.0.6** — see [CHANGELOG.md](CHANGELOG.md).

## Features

- **Launch menu** — presets, custom sequence, background toggle, background status, last results, export, tools, settings
- **Command presets** with optional media-type scope (movies, TV, music, …). **Import local artwork** refreshes items from local NFO and artwork, then caches them
- **Safety** — confirm destructive commands, prune dry-run default, preflight webserver checks
- **Real progress** — live status and percent from texturecache during long runs
- **Cancel support** — Cancel on the foreground progress dialog; **Stop current run** on the main menu, Commands settings, and Background run status. A second start asks to stop the current run first (never two at once)
- **Continue on error** — optional; keep going through a sequence after a failure
- **Per-command status** — OK/FAIL/CANCELLED with durations in results
- **Library context menu** — cache artwork for the selected item by library ID, title, or both (episode/season caches the TV show)
- **Optional background progress** — keep using Kodi during a manual run, then **Background run status** (live progress, last 3 runs, Stop)
- **Scheduled maintenance** — optional background service when Kodi is idle and not scanning (always non-blocking)
- **Advanced settings** — download threads, lastrunfile, OMDb key, re-cache all, cast thumbs, QA period
- **All texturecache commands supported** — cache, prune, search, QA, library scans, and more

## Requirements

- **Kodi 19+** (Matrix or newer)
- **Web server** — Enable in Kodi: *Settings → Services → Web server*
- **Remote control** — Enable *Allow programs on this system to control Kodi* in *Settings → Services → Control*

## Installation

### From ZIP

1. Create a ZIP file containing the addon folder (the folder must be named `script.texture.cache`)
2. In Kodi: *Add-ons → Install from zip file* → select the ZIP

### Manual Install

1. Copy the `script.texture.cache` folder to your Kodi addons directory:
   - **Windows**: `%APPDATA%\Kodi\addons\`
   - **Linux**: `~/.kodi/addons/`
   - **macOS**: `~/Library/Application Support/Kodi/addons/`
2. Restart Kodi

## Usage

1. Go to **Add-ons → Program add-ons → Texture Cache Utility**
2. Choose a **preset** or **Run custom sequence**
3. Review results (status, summary, export, details)

### Configuring Commands

1. Right-click the addon (or Add-on info) → **Configure**
2. Enter commands in **Command sequence**, separated by commas

**Examples:**

| Sequence | What it does |
|----------|--------------|
| `c, R` | Cache missing artwork, then remove orphaned cache files |
| `c, R, p` | Same as above, plus prune (dry-run) to preview cleanup |
| `c movies, R` | Cache movies only, then remove orphans |
| `P` | Prune cache (blocked unless “Allow prune delete” is enabled) |
| `qa movies` | QA check on movies (missing plot, artwork, etc.) |

For labels or search terms with spaces, use quotes:
- `missing movies "My Movies"`
- `s "Dr. No"`

See [resources/commands_help.txt](resources/commands_help.txt) for the full command reference. Wrapper notes: [COMMANDS_VERIFICATION.md](COMMANDS_VERIFICATION.md).

## Configuration

### Addon Settings

- **Web server** — use this Kodi’s credentials, or set a remote host; HTTP/HTTPS/Auto; Test connection
- **Commands** — sequence, command picker, background progress, background status, context match, verbose logging
- **Safety** — confirm destructive ops (including power/exec/play), allow prune delete, preflight, continue on error
- **Advanced** — threads, lastrunfile, OMDb key, re-cache all, cast thumbs, QA period
- **Schedule** — enable service, last run time, next run time (a passed time is replaced with 2 hours from now), repeat (hours, days, weekly, or monthly), idle minutes, scheduled sequence

### Advanced: texturecache.cfg

The addon includes a `texturecache.cfg` file. When run as an addon, the userdata path is automatically set to Kodi's profile. UI settings override the common keys via `@key=value` arguments.

See `texturecache.cfg.defaults` for more options.

## Common Commands

| Command | Description |
|---------|-------------|
| `c` | Cache missing artwork for all media |
| `c movies` | Cache missing artwork for movies only |
| `C movies filter` | Force re-cache (remove + re-download) |
| `nc` | List what would be cached (no download) |
| `p` | Preview prune (what would be removed) |
| `P` | Prune cache (remove non-library artwork) |
| `r` | Find orphaned thumbnail files |
| `R` | Find and delete orphaned files |
| `qa` | QA check (missing plot, artwork, etc.) |
| `qax` | Refresh items from local NFO and artwork. See [qax](#qax-refresh-local-artwork-and-metadata) below |
| `vscan` | Scan video library |
| `vclean` | Clean video library |

## Import local artwork

**Import local artwork (qax, c, R)** is the first command preset, and the first item in **Pick commands…** (Commands settings and the scheduled sequence). After you pick it, choose the library. **All media** covers movies, TV shows, music, and the rest. The run then does three things:

1. **qax** refreshes items that are missing artwork or metadata and have a matching local file or NFO. The existing library item is updated. Poster, fanart, banner, landscape, clearlogo, clearart, discart, and keyart are included. A blank season plot refreshes the parent show, so Kodi re-reads `season.nfo`.
2. **c** copies the artwork paths now stored on those items into the texture cache.
3. **R** deletes thumbnail files that are not in the texture database. The new artwork stays. This step is why Kodi asks you to confirm before the run starts.

Use this after a tool such as TinyMediaManager has written new images and NFO files next to videos that are already in the library. A normal library scan does not update those existing items.

## qax: refresh local artwork and metadata

`qax` is the refresh step. It does not download artwork from the internet by itself. It finds library fields that are empty, checks the item folder for a matching file, and asks Kodi to refresh that item while keeping the local NFO.

Checked names are `type.jpg` / `type.png` in the item folder, and `Video Name-type.jpg` next to the file. Clearlogo also matches `logo.png`. Discart also matches `disc.png`. For a season, it also looks for `season01-poster.jpg` in the show folder and `poster.jpg` inside `Season 01` or `Season 1`.

A blank plot or MPAA rating on a movie, and a blank plot on a TV show or episode, also triggers a refresh. Kodi has no refresh call for a season. A blank season plot refreshes the parent show instead, which re-reads every `season.nfo` in that show folder.

Items with no matching local file are reported and left unchanged. Artwork Kodi already has a URL for is left as it is. `extrafanart` folders are not part of this check.

`c` is still required afterwards if you want those new paths in the texture cache before the views open them. `R` only removes thumbnail files that the texture database does not reference.

The same behavior from the command box, for movies:

```text
qax movies @qa.useoldrefreshmethod=no, c movies, R
```

That short form checks the built-in art list (poster and fanart for movies, plus banner for TV shows). The preset adds landscape, clearlogo, clearart, discart, and keyart, and it turns off the old method that removed the item and scanned the folder again. Do not put commas inside an `@qa.art...=` value in the command box. The box splits on commas.

## Troubleshooting

**"Command failed (exit code 2)"**
- Ensure Web server and remote control are enabled in Kodi
- Check the Kodi log for details: *Settings → System → Logging → Enable debug logging*

**"No commands found in settings"**
- Open addon settings and enter a command sequence (e.g. `c, R`)

**Long commands seem stuck**
- Foreground runs: the progress dialog shows live texturecache status — wait or use **Cancel**. Cancel closes the dialog and stops the run
- Background runs: open the addon → **Background run status** → **Stop current run** (the background bar itself has no Cancel button)
- Large libraries can take 30+ minutes for `c` (cache all)

**“A texture cache run is already in progress” after a Kodi restart**
- A leftover lock from the previous session is cleared when this addon’s service starts
- Dead locks (previous Kodi process gone) are also ignored the next time you run
- If a dialog still appears, open **Background run status** once, or delete `userdata/addon_data/script.texture.cache/run.lock`

**Last results shows thousands of “Undefined” items**
- That count is empty artwork *slots* (poster/fanart/thumb present on the item with no URL), not “unknown media type”
- The summary lists example titles and art types. Fill artwork in the library (or ignore empty slots); caching only downloads URLs that exist

**Download errors / HTTP 303 in Last results**
- 303 See Other is a redirect. The engine follows 301/302/303/307/308 (up to 5 hops)
- Failed downloads list HTTP status, reason, and the download URL under **Last results**
- Remaining 303s usually have no `Location` header. Enable Kodi debug logging and check `kodi.log` for `REDIRECT` / `ERROR ITEM` lines

**imdb command fails**
- Set **OMDb API key** in Advanced settings (or `omdb.apikey` in `texturecache.cfg`)

## Project Structure

```
script.texture.cache/
├── addon.xml
├── common.py            # Shared settings, lock, live status, stop file, run history
├── main.py              # Addon entry point / GUI
├── context.py           # Library context menu
├── service.py           # Optional scheduled runs
├── texturecache.py      # Milhouse's texturecache (modified for Kodi; Python 3 path on Matrix+)
├── texturecache.cfg
├── CHANGELOG.md
├── README.md
├── backup/              # Original icon.png / fanart.jpg before compression
├── resources/
│   ├── settings.xml
│   ├── commands_help.txt
│   └── language/
└── tools/               # Standalone utilities (mklocal, fixart, clean)
```

## Credits

- **texturecache** by Neil MacLeod (Milhouse) — [github.com/xbmc/texturecache](https://github.com/xbmc/texturecache)
- **Kodi** — [kodi.tv](https://kodi.tv)

## License

GPL-2.0-or-later (same as texturecache)
