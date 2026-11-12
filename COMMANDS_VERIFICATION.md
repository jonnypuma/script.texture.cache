# Texture Cache Addon — command notes

The in-Kodi command list is `resources/commands_help.txt` (Program add-ons → Texture Cache → Supported commands). This file is only extra notes for the wrapper, not a second command table.

## Sequence format

Comma-separated tokens in addon settings, parsed with `shlex` so quotes work:

- `c, R, p`
- `c movies, R`
- `missing movies "My Movies"`

## Output

- All command output is streamed to a file (no RAM buffer).
- **Foreground** runs open the results window when the sequence finishes.
- **Background** and **scheduled** runs skip that window. Use **Last results** or **Background run status**.

## Limits in the addon

| Command | Limitation |
|---------|------------|
| `set` (stdin) | Batch mode reads stdin; the GUI does not provide stdin |
| `update`, `fupdate` | Disabled in addon mode (would kill Kodi) |
| `monitor` | Blocks until events; progress shows elapsed time |
| Context on episode/season | texturecache cannot filter those types; the wrapper caches the **TV show** and says so in the confirm dialog |

## Engine vs wrapper

`texturecache.py` still contains Python 2 import branches for CLI use. Kodi Matrix+ always takes the Python 3 path. Do not run `update`/`fupdate` from the addon.
