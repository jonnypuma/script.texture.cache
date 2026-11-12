# -*- coding: utf-8 -*-
"""
Kodi addon wrapper for Milhouse's texturecache utility.
https://github.com/xbmc/texturecache
"""

import base64
import json
import os
import re
import shlex
import ssl
import subprocess
import sys
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

_addon_root = os.path.normpath(xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo("path")))
if _addon_root not in sys.path:
    sys.path.insert(0, _addon_root)

from common import (
    LOCK_STALE_SECONDS,
    acquire_run_lock,
    addon,
    addon_path_native,
    addon_profile_native,
    append_run_history,
    clear_stop_request,
    format_elapsed as _format_elapsed,
    get_bool as _get_bool,
    get_int as _get_int,
    get_setting as _get_setting,
    library_is_scanning,
    localized as _localized,
    lock_heartbeat_age,
    lock_is_held,
    on_schedule_toggle,
    profile_path,
    read_live_status,
    read_run_history,
    reclaim_orphaned_run_lock,
    refresh_addon,
    refresh_next_scheduled_display,
    apply_repeat_to_next_run,
    release_run_lock,
    request_stop_run,
    set_bool as _set_bool,
    set_setting as _set_setting,
    stop_was_requested,
    userdata_path,
    wait_until_unlocked,
    write_live_status,
    write_scheduled_last_run,
)

OUTPUT_FILENAME = "texturecache_output.txt"
LAST_PATH_FILENAME = "last_output_path.txt"
STATUS_FILENAME = "last_run_status.txt"

DESTRUCTIVE_COMMANDS = frozenset({
    "P", "R", "Xd", "d", "purge", "purgetest", "remove", "C", "lC", "set", "testset",
    "aclean", "vclean", "fixurls", "watched",
    "power", "exec", "execw", "play", "playw",
})

# Passed only with the import-local preset. Commas stay inside each token;
# the command box splitter must not see them.
IMPORT_LOCAL_ARGS = [
    "@qa.useoldrefreshmethod=no",
    "@qa.art.movies=+banner,landscape,clearlogo,clearart,discart,keyart",
    "@qa.art.sets=+banner,landscape,clearlogo,clearart,discart,keyart",
    "@qa.art.tvshows.tvshow=+landscape,clearlogo,clearart,discart,keyart",
    "@qa.art.tvshows.season=+banner,landscape",
    "@qa.art.musicvideos=poster,fanart,thumb",
    # Do not request plot for seasons. Video.Fields.Season has no plot, and
    # that one illegal property makes Kodi reject GetSeasons for every show.
]

PRESETS = [
    ("Import local artwork (qax, c, R)", "importlocal{media}"),
    ("Cache all (c)", "c{media}"),
    ("Cache + remove orphans (c, R)", "c{media}, R"),
    ("Identify missing, no download (nc)", "nc{media}"),
    ("Prune preview, dry-run (p)", "p"),
    ("Prune delete (P)", "P"),
    ("Remove orphaned files (R)", "R"),
    ("QA check (qa)", "qa{media}"),
    ("Library stats (stats)", "stats"),
    ("Custom sequence (from settings)", None),
]

COMMAND_LABELS = {
    "c": "Cache all",
    "C": "Force re-cache",
    "nc": "Identify missing, no download",
    "lc": "Cache since last-run file",
    "lnc": "Identify missing since last-run",
    "lC": "Force re-cache since last-run",
    "p": "Prune preview, dry-run",
    "P": "Prune delete",
    "r": "Find orphaned files",
    "R": "Remove orphaned files",
    "qa": "QA check",
    "qax": "Refresh from local files",
    "stats": "Library stats",
    "vscan": "Scan video library",
    "vclean": "Clean video library",
    "ascan": "Scan audio library",
    "aclean": "Clean audio library",
    "fixurls": "Fix artwork URLs",
    "config": "Show config",
    "version": "Show version",
    "power": "Power",
    "exec": "Execute addon",
    "execw": "Execute addon (wait)",
    "play": "Play",
    "playw": "Play (wait)",
    "purge": "Purge",
    "purgetest": "Purge test",
    "remove": "Remove library item",
    "Xd": "Delete missing cache rows",
    "d": "Delete cache rows",
    "set": "Set library value",
    "testset": "Test set library value",
    "watched": "Watched list",
}

MEDIA_TYPES = [
    ("All media", ""),
    ("Movies", " movies"),
    ("TV shows", " tvshows"),
    ("Music videos", " musicvideos"),
    ("Artists", " artists"),
    ("Albums", " albums"),
    ("Songs", " songs"),
    ("Sets", " sets"),
]

PICKER_COMMANDS = [
    ("Import local artwork (qax, c, R)", "importlocal", True),
    ("Cache missing artwork (c)", "c", True),
    ("Identify missing, no download (nc)", "nc", True),
    ("Cache since last-run file (lc)", "lc", True),
    ("Force re-cache (C)", "C", True),
    ("Prune preview, dry-run (p)", "p", False),
    ("Prune delete (P)", "P", False),
    ("Find orphaned files (r)", "r", False),
    ("Remove orphaned files (R)", "R", False),
    ("QA check (qa)", "qa", True),
    ("Library stats (stats)", "stats", False),
    ("Scan video library (vscan)", "vscan", False),
    ("Clean video library (vclean)", "vclean", False),
    ("Scan audio library (ascan)", "ascan", False),
    ("Clean audio library (aclean)", "aclean", False),
    ("Fix artwork URLs (fixurls)", "fixurls", False),
    ("Show config (config)", "config", False),
    ("Show version (version)", "version", False),
]

# dbtype -> JSON-RPC details method, id key, result key, texturecache class, title field, properties
_DBTYPE_RPC = {
    "movie": ("VideoLibrary.GetMovieDetails", "movieid", "moviedetails", "movies", "title",
              ["title", "uniqueid", "year"]),
    "tvshow": ("VideoLibrary.GetTVShowDetails", "tvshowid", "tvshowdetails", "tvshows", "title",
               ["title", "uniqueid", "year"]),
    "episode": ("VideoLibrary.GetEpisodeDetails", "episodeid", "episodedetails", "tvshows", "showtitle",
                ["title", "showtitle", "uniqueid", "season", "episode"]),
    "season": ("VideoLibrary.GetSeasonDetails", "seasonid", "seasondetails", "tvshows", "showtitle",
               ["title", "showtitle", "season", "tvshowid"]),
    "artist": ("AudioLibrary.GetArtistDetails", "artistid", "artistdetails", "artists", "artist",
               ["artist", "title"]),
    "album": ("AudioLibrary.GetAlbumDetails", "albumid", "albumdetails", "albums", "title",
              ["title", "artist"]),
    "song": ("AudioLibrary.GetSongDetails", "songid", "songdetails", "songs", "title",
             ["title", "artist", "album"]),
    "musicvideo": ("VideoLibrary.GetMusicVideoDetails", "musicvideoid", "musicvideodetails", "musicvideos", "title",
                   ["title", "artist", "uniqueid", "year"]),
    "set": ("VideoLibrary.GetMovieSetDetails", "setid", "setdetails", "sets", "title",
            ["title"]),
}

_DBTYPE_MIN_PROPS = {
    "movie": ["title"],
    "tvshow": ["title"],
    "episode": ["title", "showtitle"],
    "season": ["title", "showtitle", "season"],
    "artist": ["artist"],
    "album": ["title"],
    "song": ["title"],
    "musicvideo": ["title"],
    "set": ["title"],
}

CONTEXT_MATCH_DBID = 0
CONTEXT_MATCH_TITLE = 1
CONTEXT_MATCH_BOTH = 2

SCHEME_AUTO = 0
SCHEME_HTTP = 1
SCHEME_HTTPS = 2

_resolved_http_scheme = None


class _Progress(object):
    """Foreground DialogProgress or background DialogProgressBG."""

    def __init__(self, background):
        self.background = background
        self._heading = _localized(30000, "Texture Cache Utility")
        self._d = xbmcgui.DialogProgressBG() if background else xbmcgui.DialogProgress()

    def create(self, heading, message):
        self._heading = heading
        self._d.create(heading, message)

    def update(self, percent, message):
        percent = max(0, min(100, int(percent)))
        try:
            if self.background:
                self._d.update(percent, self._heading, message)
            else:
                self._d.update(percent, message)
        except Exception:
            try:
                self._d.update(percent)
            except Exception:
                pass

    def iscanceled(self):
        if stop_was_requested():
            return True
        if self.background:
            return False
        try:
            return self._d.iscanceled()
        except Exception:
            return False

    def close(self):
        try:
            self._d.close()
        except Exception:
            pass


def _jsonrpc(method, params=None):
    query = {"jsonrpc": "2.0", "method": method, "id": 1}
    if params is not None:
        query["params"] = params
    try:
        return json.loads(xbmc.executeJSONRPC(json.dumps(query)))
    except Exception as e:
        xbmc.log("Texture Cache Addon: JSON-RPC error - %s" % e, xbmc.LOGERROR)
        return {}


def _setting_value(setting_id):
    result = _jsonrpc("Settings.GetSettingValue", {"setting": setting_id})
    return result.get("result", {}).get("value")


def get_webserver_config():
    """Host/port/user/password for texturecache. Default: this Kodi's settings."""
    use_kodi = _get_bool("webserver_use_kodi", True)
    if use_kodi:
        port_val = _setting_value("services.webserverport")
        port = _get_setting("webserver_port", "8080") if port_val in (None, "") else str(port_val)
        auth = _setting_value("services.webserverauthentication")
        if auth is False:
            user, password = "", ""
        else:
            user = _setting_value("services.webserverusername")
            password = _setting_value("services.webserverpassword")
            user = "" if user in (None,) else str(user)
            password = "" if password in (None,) else str(password)
        return "localhost", port, user, password
    return (
        _get_setting("webserver_host", "localhost"),
        _get_setting("webserver_port", "8080"),
        _get_setting("webserver_username", ""),
        _get_setting("webserver_password", ""),
    )


def _ping_url(url, user, password, timeout, insecure=False):
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    payload = json.dumps({"jsonrpc": "2.0", "method": "JSONRPC.Ping", "id": 1}).encode("utf-8")
    req = Request(url, data=payload, headers={"Content-Type": "application/json"})
    if user or password:
        token = base64.b64encode(("%s:%s" % (user, password)).encode("utf-8")).decode("ascii")
        req.add_header("Authorization", "Basic %s" % token)
    kwargs = {"timeout": timeout}
    if insecure:
        kwargs["context"] = ssl._create_unverified_context()
    resp = urlopen(req, **kwargs)
    try:
        body = resp.read().decode("utf-8", "replace")
    finally:
        resp.close()
    data = json.loads(body)
    if data.get("result") == "pong":
        return True, "Connected to %s" % url
    return True, "Connected to %s (JSON-RPC responded)." % url


def _ping_schemes():
    mode = _get_int("webserver_scheme", SCHEME_AUTO)
    if mode == SCHEME_HTTP:
        return ("http",)
    if mode == SCHEME_HTTPS:
        return ("https",)
    if _get_bool("webserver_use_kodi", True):
        if _setting_value("services.webserverssl") is True:
            return ("https", "http")
        return ("http", "https")
    return ("https", "http")


def web_scheme_for_run():
    mode = _get_int("webserver_scheme", SCHEME_AUTO)
    if mode == SCHEME_HTTP:
        return "http"
    if mode == SCHEME_HTTPS:
        return "https"
    if _resolved_http_scheme in ("http", "https"):
        return _resolved_http_scheme
    if _get_bool("webserver_use_kodi", True) and _setting_value("services.webserverssl") is True:
        return "https"
    return "http"


def ping_webserver(timeout=5.0):
    """JSON-RPC ping using Auto / HTTP / HTTPS setting."""
    global _resolved_http_scheme
    host, port, user, password = get_webserver_config()
    schemes = _ping_schemes()

    def _do():
        from urllib.error import HTTPError, URLError

        last_msg = "Web server check failed."
        for scheme in schemes:
            url = "%s://%s:%s/jsonrpc" % (scheme, host, port)
            try:
                ok, msg = _ping_url(url, user, password, timeout, insecure=(scheme == "https"))
                if ok:
                    return True, msg, scheme
            except HTTPError as e:
                if e.code == 401:
                    return False, (
                        "Web server at %s returned HTTP 401 (unauthorized). "
                        "Check username and password, or turn on "
                        "“Use this Kodi’s web server”."
                        % url
                    ), None
                last_msg = "Web server at %s returned HTTP %s." % (url, e.code)
            except URLError as e:
                reason = getattr(e, "reason", e)
                last_msg = (
                    "Cannot connect to web server at %s (%s). "
                    "Enable it in Kodi: Settings → Services → Control."
                    % (url, reason)
                )
            except Exception as e:
                last_msg = "Web server check failed (%s): %s" % (scheme, e)
        return False, last_msg, None

    box = {"result": None}

    def _run():
        box["result"] = _do()

    thread = threading.Thread(target=_run)
    thread.daemon = True
    thread.start()
    thread.join(timeout * max(len(schemes), 1) + 1.5)
    if box["result"] is None:
        return False, "Timed out connecting to web server at %s:%s." % (host, port)
    ok, msg, scheme = box["result"]
    if ok and scheme:
        _resolved_http_scheme = scheme
    return ok, msg


def show_webserver_test():
    ok, msg = ping_webserver()
    xbmcgui.Dialog().ok(_localized(30115, "Test web server"), msg)
    return ok


def pick_command_sequence(setting_id="cmd_sequence"):
    """Multi-select safe commands and write them into the sequence setting."""
    labels = [item[0] for item in PICKER_COMMANDS]
    current_raw = _get_setting(setting_id, "")
    current_cmds = [c.strip() for c in current_raw.split(",") if c.strip()]
    preselect = []
    for i, (_label, base, _takes_media) in enumerate(PICKER_COMMANDS):
        for cmd in current_cmds:
            try:
                parts = shlex.split(cmd)
            except ValueError:
                parts = cmd.split()
            if not parts:
                continue
            if parts[0] == base or (base == "importlocal" and parts[0] == "qax"):
                preselect.append(i)
                break

    selected = xbmcgui.Dialog().multiselect(
        _localized(30061, "Pick commands"),
        labels,
        preselect=preselect,
    )
    if selected is None:
        return
    if not selected:
        xbmcgui.Dialog().ok(
            _localized(30061, "Pick commands"),
            _localized(30066, "No commands selected."),
        )
        return

    chosen = [PICKER_COMMANDS[i] for i in selected]
    media = ""
    if any(item[2] for item in chosen):
        media = select_media_suffix()
        if media is None:
            return

    built = []
    seen = set()
    for _label, base, takes_media in chosen:
        if base == "importlocal":
            suffix = media if media else " all"
            pieces = ["qax%s" % suffix, "c%s" % suffix, "R"]
        else:
            pieces = [(base + media).strip() if takes_media else base]
        for cmd in pieces:
            key = " ".join(cmd.split())
            if not key or key in seen:
                continue
            seen.add(key)
            built.append(key)
    new_seq = ", ".join(built)

    if current_raw.strip():
        idx = xbmcgui.Dialog().select(
            _localized(30064, "Update command box"),
            [
                _localized(30062, "Replace command box"),
                _localized(30063, "Append to command box"),
            ],
        )
        if idx < 0:
            return
        if idx == 1:
            existing = []
            existing_keys = set()
            for part in current_raw.split(","):
                key = " ".join(part.split())
                if not key or key in existing_keys:
                    continue
                existing_keys.add(key)
                existing.append(key)
            added = [cmd for cmd in built if cmd not in existing_keys]
            if not added:
                xbmcgui.Dialog().ok(
                    _localized(30064, "Update command box"),
                    _localized(30086, "Those commands are already in the command box."),
                )
                return
            new_seq = ", ".join(existing + added)

    _set_setting(setting_id, new_seq)
    xbmcgui.Dialog().ok(
        _localized(30121, "Command sequence"),
        "%s\n\n%s" % (_localized(30065, "Command box now contains:"), new_seq),
    )


def find_writable_output_dir():
    temp_path = None
    try:
        temp_path = os.path.normpath(xbmcvfs.translatePath("special://temp"))
    except Exception:
        pass
    candidates = [
        addon_profile_native,
        os.path.join(profile_path, "addon_data", "script.texture.cache") if profile_path else None,
        os.path.join(os.path.expanduser("~"), ".kodi", "addon_data", "script.texture.cache"),
        addon_path_native,
        temp_path,
    ]
    for output_dir in candidates:
        if not output_dir:
            continue
        output_dir = os.path.normpath(output_dir)
        if not os.path.isdir(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
            except OSError:
                continue
        candidate = os.path.join(output_dir, OUTPUT_FILENAME)
        try:
            with open(candidate, "a", encoding="utf-8"):
                pass
            return output_dir, candidate
        except (IOError, OSError):
            continue
    return None, None


def remember_output_path(path):
    if not path or not addon_profile_native:
        return
    try:
        if not os.path.isdir(addon_profile_native):
            os.makedirs(addon_profile_native, exist_ok=True)
        marker = os.path.join(addon_profile_native, LAST_PATH_FILENAME)
        with open(marker, "w", encoding="utf-8") as f:
            f.write(path)
    except (IOError, OSError):
        pass


def get_last_output_path():
    if addon_profile_native:
        marker = os.path.join(addon_profile_native, LAST_PATH_FILENAME)
        try:
            with open(marker, "r", encoding="utf-8") as f:
                path = f.read().strip()
            if path and os.path.exists(path):
                return path
        except (IOError, OSError):
            pass
        fallback = os.path.join(addon_profile_native, OUTPUT_FILENAME)
        if os.path.exists(fallback):
            return fallback
    _, candidate = find_writable_output_dir()
    if candidate and os.path.exists(candidate):
        return candidate
    return None


def get_last_status_path():
    if addon_profile_native:
        return os.path.join(addon_profile_native, STATUS_FILENAME)
    return None


def show_commands_help():
    help_path = os.path.join(addon_path_native, "resources", "commands_help.txt")
    try:
        with open(help_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (IOError, OSError):
        content = (
            "Supported commands: c, nc, C, lc, lnc, lC, p, P, s, S, x, X, f, F, Xd, d, r, R, "
            "j, J, qa, qax, set, remove, imdb, purge, watched, duplicates, missing, ascan, "
            "vscan, aclean, vclean, directory, sources, status, stats, config, version. "
            "Format: comma-separated (e.g. c, R, p)."
        )
    xbmcgui.Dialog().textviewer(_localized(30010, "Supported Commands"), content)


def show_tools_help():
    tools_dir = os.path.join(addon_path_native, "tools")
    help_text = (
        "CLI tools (not runnable from this Kodi GUI)\n"
        "==========================================\n\n"
        "mklocal.py, fixart.py and clean.py are command-line scripts. They need a "
        "shell/SSH session and cannot be started from this menu.\n\n"
        "Folder:\n%s\n\n"
        "From this GUI you can run fixurls (a texturecache command that rewrites "
        "mangled artwork URLs in the library).\n\n"
        "CLI examples (outside Kodi):\n"
        "  texturecache.py jd movies | python mklocal.py --local /path\n"
        "See each script's --help and tools/CHANGELOG_mktool.md.\n"
        % tools_dir
    )
    choices = [
        _localized(30050, "Run fixurls"),
        _localized(30051, "View CLI tools help"),
        _localized(30067, "Show tools folder"),
        _localized(30052, "Back"),
    ]
    idx = xbmcgui.Dialog().select(_localized(30053, "Tools"), choices)
    if idx == 0:
        run_commands(["fixurls"])
    elif idx == 1:
        xbmcgui.Dialog().textviewer(_localized(30053, "Tools"), help_text)
    elif idx == 2:
        xbmcgui.Dialog().ok(_localized(30067, "Show tools folder"), tools_dir)


def preflight_checks(commands, interactive=True):
    """Warn if web server / remote control appear disabled, and ping JSON-RPC."""
    needs_web = False
    for cmd in commands:
        try:
            parts = shlex.split(cmd)
        except ValueError:
            parts = cmd.split()
        if not parts:
            continue
        op = parts[0]
        if op in ("c", "C", "nc", "lc", "lC", "lnc", "readfile"):
            needs_web = True
            break

    if not needs_web:
        return True

    warnings = []
    web = _setting_value("services.webserver")
    if web is False:
        warnings.append("Kodi web server appears disabled (Settings → Services → Control / Web server).")
    es = _setting_value("services.esenabled")
    if es is False:
        warnings.append("Allow remote control from applications on this system appears disabled.")

    ok, ping_msg = ping_webserver()
    if ok:
        return True
    warnings.insert(0, ping_msg)

    if not interactive:
        xbmc.log("Texture Cache Addon: Preflight failed: %s" % " | ".join(warnings), xbmc.LOGWARNING)
        xbmcgui.Dialog().notification(
            _localized(30020, "Preflight check"),
            ping_msg[:80],
            xbmcgui.NOTIFICATION_WARNING,
            5000,
        )
        return False

    msg = "Preflight warnings:\n\n" + "\n\n".join(warnings) + "\n\nContinue anyway?"
    return xbmcgui.Dialog().yesno(_localized(30020, "Preflight check"), msg)


def _command_base(cmd):
    try:
        parts = shlex.split(cmd)
    except ValueError:
        parts = cmd.split()
    return parts[0] if parts else ""


def apply_prune_safety(commands):
    """Rewrite P → p unless allow_prune_delete is enabled (dry-run default)."""
    if _get_bool("allow_prune_delete", False):
        return commands
    out = []
    rewritten = False
    for cmd in commands:
        base = _command_base(cmd)
        if base == "P":
            rest = cmd.strip()[1:].lstrip()
            out.append(("p " + rest).strip() if rest else "p")
            rewritten = True
        else:
            out.append(cmd)
    if rewritten:
        xbmcgui.Dialog().notification(
            _localized(30000, "Texture Cache"),
            _localized(30021, "Prune delete blocked — using dry-run (p). Enable in settings to allow P."),
            xbmcgui.NOTIFICATION_INFO,
            5000,
        )
    return out


def _describe_command(cmd):
    """Human label plus the raw token, e.g. Cache all (c) or Cache all (c movies)."""
    base = _command_base(cmd)
    label = COMMAND_LABELS.get(base)
    if label:
        return "%s (%s)" % (label, cmd)
    return cmd


def confirm_destructive(commands):
    if not commands:
        return True
    background = _get_bool("run_in_background", False)
    destructive = _get_bool("confirm_destructive", True) and any(
        _command_base(cmd) in DESTRUCTIVE_COMMANDS for cmd in commands
    )
    if not destructive and not background:
        return True
    bullets = "\n".join("• %s" % _describe_command(cmd) for cmd in commands)
    msg = bullets + "\n\nContinue?"
    if background:
        msg += "\n\n" + _localized(
            30083,
            "This will run in the background. Open Texture Cache → Background run status to stop.",
        )
    return xbmcgui.Dialog().yesno(
        _localized(30022, "Run with the following commands?"),
        msg,
    )


def select_media_suffix():
    labels = [m[0] for m in MEDIA_TYPES]
    idx = xbmcgui.Dialog().select(_localized(30023, "Media type"), labels)
    if idx < 0:
        return None
    return MEDIA_TYPES[idx][1]


def build_from_preset():
    """Return (commands, extra_args) or None when the user cancels."""
    labels = [p[0] for p in PRESETS]
    idx = xbmcgui.Dialog().select(_localized(30024, "Command preset"), labels)
    if idx < 0:
        return None
    _label, template = PRESETS[idx]
    if template is None:
        raw = _get_setting("cmd_sequence", "c, R")
        cmds = [c.strip() for c in raw.split(",") if c.strip()]
        return (cmds, None)

    media = ""
    if "{media}" in template:
        media = select_media_suffix()
        if media is None:
            return None
    if template.startswith("importlocal"):
        # Bare qax drops songs. "all" keeps every class, including songs.
        suffix = media if media else " all"
        return (["qax%s" % suffix, "c%s" % suffix, "R"], list(IMPORT_LOCAL_ARGS))
    cmd_str = template.format(media=media)
    return ([c.strip() for c in cmd_str.split(",") if c.strip()], None)


def build_addon_args(include_password=True):
    """Build @key=value overrides from addon settings."""
    config_path = os.path.join(addon_path_native, "texturecache.cfg")
    addon_args = []
    if userdata_path:
        addon_args.append("@userdata=%s" % userdata_path)
    if os.path.exists(config_path):
        addon_args.append("@config=%s" % config_path)

    host, port, username, password = get_webserver_config()
    addon_args.append("@xbmc.host=%s" % host)
    addon_args.append("@webserver.port=%s" % port)
    addon_args.append("@webserver.username=%s" % username)
    if include_password:
        addon_args.append("@webserver.password=%s" % password)

    threads = _clamped_setting_int("download_threads", 2, 1, 32)
    addon_args.append("@download.threads=%s" % threads)

    lastrun = _get_setting("lastrunfile", "")
    if lastrun:
        addon_args.append("@lastrunfile=%s" % lastrun)

    omdb = _get_setting("omdb_apikey", "")
    if omdb:
        addon_args.append("@omdb.apikey=%s" % omdb)

    if _get_bool("allow_recacheall", False):
        addon_args.append("@allow.recacheall=yes")

    if _get_bool("cache_castthumb", False):
        addon_args.append("@cache.castthumb=yes")

    qaperiod = _clamped_setting_int("qaperiod", 30, 1, 3650)
    addon_args.append("@qaperiod=%s" % qaperiod)

    if web_scheme_for_run() == "https":
        addon_args.append("@webserver.https=yes")
    else:
        addon_args.append("@webserver.https=no")

    return addon_args


def _clamped_setting_int(setting_id, default, min_v, max_v):
    raw = _get_setting(setting_id, str(default))
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    if value < min_v or value > max_v:
        return max(min_v, min(max_v, value))
    return value


def redact_secrets(text):
    """Remove password/API key values from text before logging or display."""
    if not text:
        return text
    text = re.sub(r"(@webserver\.password=)(\S+)", r"\1***", text)
    text = re.sub(r"(@omdb\.apikey=)(\S+)", r"\1***", text)
    text = re.sub(r"(webserver\.password\s*=\s*)(\S+)", r"\1***", text, flags=re.I)
    text = re.sub(r"(omdb\.apikey\s*=\s*)(\S+)", r"\1***", text, flags=re.I)
    text = re.sub(r"(password[\"']?\s*[:=]\s*[\"']?)([^\"'\s,]+)", r"\1***", text, flags=re.I)
    return text


def _clipboard_supported():
    try:
        if xbmc.getCondVisibility("System.Platform.Android"):
            return False
    except Exception:
        pass
    return sys.platform.startswith("win") or sys.platform == "darwin"


def _copy_to_clipboard(text):
    if not text:
        return False
    try:
        if sys.platform.startswith("win"):
            proc = subprocess.Popen(["clip"], stdin=subprocess.PIPE)
            proc.communicate(text.encode("utf-16le"))
            return proc.returncode == 0
        if sys.platform == "darwin":
            proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            proc.communicate(text.encode("utf-8"))
            return proc.returncode == 0
    except Exception:
        return False
    return False


def export_output(output_file):
    if not output_file or not os.path.exists(output_file):
        xbmcgui.Dialog().ok(_localized(30030, "Export"), "No output file found.")
        return
    choices = [
        _localized(30031, "Show file path"),
        _localized(30032, "Copy path to clipboard"),
        _localized(30033, "Open folder (FileManager)"),
    ]
    idx = xbmcgui.Dialog().select(_localized(30030, "Export"), choices)
    if idx == 0:
        xbmcgui.Dialog().ok(_localized(30030, "Export"), output_file)
    elif idx == 1:
        if _clipboard_supported() and _copy_to_clipboard(output_file):
            xbmcgui.Dialog().notification(
                _localized(30030, "Export"),
                _localized(30068, "Path copied to clipboard."),
                xbmcgui.NOTIFICATION_INFO,
                4000,
            )
        else:
            xbmcgui.Dialog().ok(
                _localized(30032, "Copy path to clipboard"),
                "Clipboard is not available on this device.\n\nPath:\n%s" % output_file,
            )
    elif idx == 2:
        folder = os.path.dirname(output_file)
        try:
            xbmc.executebuiltin("ActivateWindow(FileManager,%s,return)" % folder)
        except Exception:
            xbmcgui.Dialog().ok(_localized(30030, "Export"), "Folder:\n%s" % folder)


def _extract_summary(content):
    summary_marker = "Cache pre-load activity summary"
    lines = content.split("\n")
    summary_lines = []
    rest_before = []
    rest_after = []
    in_summary = False
    for i, line in enumerate(lines):
        if summary_marker in line:
            in_summary = True
            summary_lines.append(line)
            continue
        if in_summary:
            summary_lines.append(line)
            if "TOTAL RUNTIME:" in line:
                rest_after = lines[i + 1:]
                break
            continue
        rest_before.append(line)
    if not summary_lines:
        return None, content
    summary = "\n".join(summary_lines)
    rest = "\n".join(rest_before + rest_after)
    return summary, rest


def _format_summary_plain(summary_raw):
    lines = summary_raw.split("\n")
    header = None
    totals = []
    timing = []

    for line in lines:
        s = line.strip()
        if "Cache pre-load activity summary" in line:
            header = line.strip().rstrip(":")
            continue
        if s.startswith("|") or s.startswith("-") or s.startswith("=") or not s:
            continue
        if ":" in line and (
            "Loading:" in line or "Parsing:" in line or "Comparing:" in line or "TOTAL RUNTIME:" in line
        ):
            timing.append(line.strip())
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 2:
            cat = parts[0].strip()
            val = parts[-1].strip() if parts[-1] else "-"
            if not cat or not cat.replace("-", "").replace("=", "").strip():
                continue
            if cat.replace("-", "").replace(".", "").isdigit():
                continue
            totals.append((cat, val))

    if not header and not totals:
        return summary_raw

    result = []
    if header:
        result.append(header)
        result.append("=" * min(60, len(header)))
        result.append("")

    order = [
        "Not in Cache", "Stale Item", "Skipped", "Duplicate", "Ignored",
        "Cached", "Deleted", "Error", "Undefined", "Season-all", "TOTAL",
    ]
    seen = set()
    for cat in order:
        for c, v in totals:
            if c == cat:
                result.append("%-14s %s" % (c + ":", v))
                seen.add(c)
                break
    for c, v in totals:
        if c not in seen:
            result.append("%-14s %s" % (c + ":", v))

    if timing:
        result.append("")
        result.append("-" * 40)
        for t in timing:
            result.append(t)

    return "\n".join(result) if result else summary_raw


def _load_status_text():
    path = get_last_status_path()
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except (IOError, OSError):
        return None


def _show_results_modal(output_file, status_text=None):
    """Summary-first results, optional status, export, log path."""
    if not output_file or not os.path.exists(output_file):
        if status_text:
            xbmcgui.Dialog().textviewer(_localized(30040, "Run status"), status_text)
        return
    try:
        with open(output_file, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        max_chars = 1024 * 1024
        tail_chars = 256 * 1024
        truncated = len(content) > max_chars

        if truncated:
            tail_content = content[-tail_chars:] if len(content) > tail_chars else content
            summary, _ = _extract_summary(tail_content)
            rest = content[:max_chars] + "\n\n... [truncated - full file: %s]" % output_file
        else:
            summary, rest = _extract_summary(content)

        if status_text is None:
            status_text = _load_status_text()

        choices = []
        pages = []

        if status_text:
            choices.append(_localized(30040, "Run status"))
            pages.append(status_text)

        if summary:
            choices.append(_localized(30041, "Summary"))
            pages.append(_format_summary_plain(summary))

        choices.append(_localized(30042, "Full log path"))
        pages.append(output_file)

        choices.append(_localized(30030, "Export…"))
        pages.append(None)

        choices.append(_localized(30043, "Details…"))
        pages.append(("details", rest))

        while True:
            idx = xbmcgui.Dialog().select(_localized(30044, "Texture Cache - Results"), choices)
            if idx < 0:
                break
            page = pages[idx]
            if page is None:
                export_output(output_file)
                continue
            if isinstance(page, tuple) and page[0] == "details":
                _show_detail_pages(page[1])
                continue
            xbmcgui.Dialog().textviewer(choices[idx], page if page else "")
    except (IOError, OSError) as e:
        xbmc.log("Texture Cache Addon: Could not read output file - %s" % str(e), xbmc.LOGERROR)


def _show_detail_pages(rest):
    page_size = 80
    rest_lines = rest.split("\n")
    num_pages = max(1, (len(rest_lines) + page_size - 1) // page_size)
    labels = ["Page %d of %d" % (i + 1, num_pages) for i in range(num_pages)]
    idx = xbmcgui.Dialog().select(_localized(30043, "Details…"), labels)
    if idx >= 0:
        chunk = "\n".join(rest_lines[idx * page_size:(idx + 1) * page_size])
        xbmcgui.Dialog().textviewer(labels[idx], chunk)


def view_last_results():
    path = get_last_output_path()
    if not path:
        xbmcgui.Dialog().ok(
            _localized(30045, "Last results"),
            "No previous results found. Run a command sequence first.",
        )
        return
    _show_results_modal(path)


def _publish_live_status(state, commands, run_source, index=0, cmd="", percent=0, message="", elapsed=""):
    write_live_status({
        "state": state,
        "source": run_source,
        "commands": [_describe_command(c) for c in (commands or [])],
        "index": index,
        "total": len(commands or []),
        "command": _describe_command(cmd) if cmd else "",
        "percent": int(percent or 0),
        "message": message or "",
        "elapsed": elapsed or "",
    })


def _record_run_history(state, commands, run_source, message="", started=None):
    append_run_history({
        "state": state,
        "source": run_source,
        "commands": [_describe_command(c) for c in (commands or [])],
        "message": (message or "")[:160],
        "started": started or time.time(),
        "finished": time.time(),
    })


def _format_history_lines():
    history = read_run_history()
    if not history:
        return []
    lines = ["", _localized(30084, "Recent runs:")]
    for item in history:
        if not isinstance(item, dict):
            continue
        state = item.get("state") or "unknown"
        src = item.get("source") or ""
        finished = item.get("finished")
        when = ""
        if finished:
            try:
                when = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(finished)))
            except (TypeError, ValueError, OverflowError):
                when = ""
        cmds = item.get("commands") or []
        cmdtxt = ", ".join(cmds[:4])
        if len(cmds) > 4:
            cmdtxt += ", …"
        bit = "%s  %s" % (when, state) if when else state
        if src:
            bit += "  (%s)" % src
        lines.append("  • %s" % bit)
        if cmdtxt:
            lines.append("    %s" % cmdtxt)
        message = item.get("message") or ""
        if message:
            lines.append("    %s" % message)
    return lines


def show_background_status():
    reclaim_orphaned_run_lock("status")
    data = read_live_status()
    running = lock_is_held()
    history_lines = _format_history_lines()
    if not data and not running and not history_lines:
        xbmcgui.Dialog().ok(
            _localized(30072, "Background run status"),
            _localized(30073, "No background run is in progress."),
        )
        return

    if running:
        idx = xbmcgui.Dialog().select(
            _localized(30072, "Background run status"),
            [
                _localized(30094, "View details"),
                _localized(30079, "Stop current run"),
            ],
        )
        if idx < 0:
            return
        if idx == 1:
            stop_current_run(interactive=True)
            return

    lines = []
    data_state = (data or {}).get("state")
    age = lock_heartbeat_age() if running else None
    if running and data_state == "running":
        lines.append("State: running")
    elif running:
        lines.append("State: running (details not written yet)")
    elif data_state == "running":
        lines.append("State: interrupted (no longer running)")
        lines.append("")
        lines.append("Last recorded details:")
    elif data:
        lines.append("No run in progress.")
        lines.append("Last state: %s" % (data_state or "idle"))
        lines.append("")
        lines.append("Last recorded details:")
    elif running:
        lines.append("State: running (details not written yet)")

    if running and age is not None and age > LOCK_STALE_SECONDS:
        lines.append(_localized(
            30085,
            "Heartbeat is stale (the device may have been asleep).",
        ))

    if data:
        src = data.get("source") or ""
        if src:
            lines.append("Source: %s" % src)
        cmds = data.get("commands") or []
        if cmds:
            lines.append("Sequence:")
            for item in cmds:
                lines.append("  • %s" % item)
        total = data.get("total") or 0
        index = data.get("index") or 0
        current = data.get("command") or ""
        if current or total:
            lines.append("Current: [%s/%s] %s" % (index, total, current))
        percent = data.get("percent")
        if percent not in (None, ""):
            lines.append("Progress: %s%%" % percent)
        elapsed = data.get("elapsed") or ""
        if elapsed:
            lines.append("Elapsed: %s" % elapsed)
        message = data.get("message") or ""
        if message:
            lines.append("Detail: %s" % message)
        updated = data.get("updated")
        if updated:
            try:
                lines.append(
                    "Updated: %s"
                    % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(updated)))
                )
            except (TypeError, ValueError, OverflowError):
                pass
    lines.extend(history_lines)
    xbmcgui.Dialog().textviewer(_localized(30072, "Background run status"), "\n".join(lines) or " ")


def stop_current_run(interactive=True, already_confirmed=False):
    reclaim_orphaned_run_lock("stop")
    if not lock_is_held():
        if interactive:
            xbmcgui.Dialog().ok(
                _localized(30079, "Stop current run"),
                _localized(30082, "No run is in progress to stop."),
            )
        return False
    if interactive and not already_confirmed:
        if not xbmcgui.Dialog().yesno(
            _localized(30079, "Stop current run"),
            _localized(30080, "Stop this run?"),
            nolabel=_localized(30078, "Keep current run"),
            yeslabel=_localized(30079, "Stop current run"),
        ):
            return False
    request_stop_run()
    xbmcgui.Dialog().notification(
        _localized(30000, "Texture Cache"),
        _localized(30081, "Stopping the current run..."),
        xbmcgui.NOTIFICATION_INFO,
        4000,
    )
    return True


def toggle_run_in_background():
    current = _get_bool("run_in_background", False)
    _set_bool("run_in_background", not current)
    on = not current
    xbmcgui.Dialog().notification(
        _localized(30000, "Texture Cache"),
        _localized(30127, "Run in background") + (": On" if on else ": Off"),
        xbmcgui.NOTIFICATION_INFO,
        3000,
    )


def _signal_worker_stop():
    try:
        import texturecache
        if getattr(texturecache, "stopped", None) is not None:
            texturecache.stopped.set()
    except Exception:
        pass


def _join_worker_and_release(thread):
    try:
        if thread is not None and thread.is_alive():
            thread.join()
    finally:
        release_run_lock()


def _wait_for_worker(thread, progress=None, timeout=None, message=None):
    if thread is None:
        return True
    deadline = None if timeout is None else time.time() + max(0.5, float(timeout))
    monitor = xbmc.Monitor()
    while thread.is_alive():
        if progress is not None and message:
            progress.update(0, message)
        if deadline is not None and time.time() >= deadline:
            xbmc.log(
                "Texture Cache Addon: worker still running after cancel timeout",
                xbmc.LOGWARNING,
            )
            return False
        if monitor.abortRequested() and deadline is None:
            deadline = time.time() + 8.0
        thread.join(timeout=0.4)
    return True


def _busy_run_message():
    lines = [_localized(30060, "A texture cache run is already in progress.")]
    data = read_live_status() or {}
    cmd = data.get("command") or ""
    percent = data.get("percent")
    src = data.get("source") or ""
    if cmd or percent not in (None, "") or src:
        lines.append("")
        if src:
            lines.append("Source: %s" % src)
        if cmd:
            lines.append("Current: %s" % cmd)
        if percent not in (None, ""):
            lines.append("Progress: %s%%" % percent)
    lines.append("")
    lines.append(_localized(30074, "Stop the current run and start this one?"))
    return "\n".join(lines)


def _offer_to_stop_busy_run(interactive, run_source):
    msg = _localized(30060, "A texture cache run is already in progress.")
    xbmc.log("Texture Cache Addon: %s (new source=%s)" % (msg, run_source), xbmc.LOGINFO)
    if not interactive:
        xbmcgui.Dialog().notification(
            _localized(30000, "Texture Cache"),
            msg,
            xbmcgui.NOTIFICATION_INFO,
            4000,
        )
        return False

    if not xbmcgui.Dialog().yesno(
        _localized(30000, "Texture Cache"),
        _busy_run_message(),
        nolabel=_localized(30078, "Keep current run"),
        yeslabel=_localized(30077, "Stop and start"),
    ):
        return False

    request_stop_run()
    waiting = xbmcgui.DialogProgress()
    wait_msg = _localized(30075, "Waiting for the current run to stop...")
    waiting.create(_localized(30000, "Texture Cache"), wait_msg)
    stopped = wait_until_unlocked(timeout=90.0, progress=waiting, message=wait_msg)
    cancelled_wait = waiting.iscanceled()
    waiting.close()
    if cancelled_wait:
        clear_stop_request()
        return False
    if not stopped or lock_is_held():
        xbmcgui.Dialog().ok(
            _localized(30000, "Texture Cache"),
            _localized(30076, "Could not stop the current run. It is still in progress."),
        )
        return False
    return True


def _run_should_stop(progress):
    return bool(progress.iscanceled() or stop_was_requested())


def run_commands(commands=None, interactive=True, run_source="gui", extra_args=None):
    if commands is None:
        raw_input = _get_setting("cmd_sequence", "")
        if not raw_input:
            xbmcgui.Dialog().ok(
                _localized(30046, "Error"),
                "No commands found in settings.\n\nAdd commands in Add-on settings (e.g. c, R, p)",
            )
            return
        commands = [c.strip() for c in raw_input.split(",") if c.strip()]

    if not commands:
        xbmcgui.Dialog().ok(_localized(30046, "Error"), "No valid commands.")
        return

    locked = acquire_run_lock(run_source)
    handed_off = False
    if not locked:
        if not _offer_to_stop_busy_run(interactive, run_source):
            return
        locked = acquire_run_lock(run_source)
        if not locked:
            msg = _localized(30060, "A texture cache run is already in progress.")
            xbmc.log("Texture Cache Addon: %s" % msg, xbmc.LOGINFO)
            if interactive:
                xbmcgui.Dialog().ok(
                    _localized(30000, "Texture Cache"),
                    _localized(30076, "Could not stop the current run. It is still in progress."),
                )
            else:
                xbmcgui.Dialog().notification(
                    _localized(30000, "Texture Cache"),
                    msg,
                    xbmcgui.NOTIFICATION_INFO,
                    4000,
                )
            return

    try:
        handed_off = _run_commands_locked(
            commands,
            interactive=interactive,
            run_source=run_source,
            extra_args=extra_args,
        ) is True
    finally:
        if locked and not handed_off:
            release_run_lock()


def _run_commands_locked(commands, interactive=True, run_source="gui", extra_args=None):
    extra_args = list(extra_args or [])
    commands = apply_prune_safety(commands)

    if interactive and not confirm_destructive(commands):
        return

    if _get_bool("enable_preflight", True):
        if not preflight_checks(commands, interactive=interactive):
            return

    if run_source == "service":
        write_scheduled_last_run(update_display=True)

    background = (run_source == "service") or _get_bool("run_in_background", False)
    show_results = interactive and not background

    _, output_file = find_writable_output_dir()
    if output_file:
        remember_output_path(output_file)

    progress = _Progress(background)
    progress.create(_localized(30000, "Texture Cache Utility"), "Initializing...")
    run_started = time.time()
    _publish_live_status("running", commands, run_source, index=0, message="Initializing...")
    if background:
        xbmcgui.Dialog().notification(
            _localized(30000, "Texture Cache"),
            _localized(
                30083,
                "This will run in the background. Open Texture Cache → Background run status to stop.",
            ),
            xbmcgui.NOTIFICATION_INFO,
            6000,
        )

    try:
        import texturecache
    except ImportError as e:
        xbmc.log("Texture Cache Addon: Failed to import texturecache - %s" % str(e), xbmc.LOGERROR)
        progress.close()
        _publish_live_status("failed", commands, run_source, message=str(e))
        _record_run_history("failed", commands, run_source, message=str(e), started=run_started)
        xbmcgui.Dialog().ok(_localized(30046, "Error"), "Failed to load texturecache module.\n\n%s" % str(e))
        return

    texturecache.close_output_file()
    texturecache.verbose_logging = _get_bool("enable_verbose_logging", False)
    if not hasattr(texturecache, "progress_message"):
        texturecache.progress_message = ""
        texturecache.progress_percent = -1

    if output_file:
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write("=== Texture Cache - Command Results ===\n\n")
        except (IOError, OSError):
            output_file = None
        texturecache.output_file_path = output_file
    else:
        xbmc.log("Texture Cache Addon: Could not create output file", xbmc.LOGWARNING)
        texturecache.output_file_path = None

    continue_on_error = _get_bool("continue_on_error", False)
    status_lines = ["Command sequence status", "=" * 40, ""]
    sequence_failed = False
    cancelled = False
    cancelled_by_request = False
    worker = None

    for i, cmd in enumerate(commands):
        if _run_should_stop(progress):
            cancelled = True
            cancelled_by_request = stop_was_requested()
            _signal_worker_stop()
            progress.update(0, _localized(30081, "Stopping the current run..."))
            break

        if output_file:
            try:
                with open(output_file, "a", encoding="utf-8") as f:
                    f.write("--- Command: %s ---\n\n" % cmd)
            except (IOError, OSError):
                pass

        try:
            argv_cmd = shlex.split(cmd)
        except ValueError:
            argv_cmd = cmd.split()

        addon_args = build_addon_args(include_password=True)
        cmd_extra = list(extra_args)
        if _command_base(cmd) == "qax":
            for arg in IMPORT_LOCAL_ARGS:
                if arg not in cmd_extra:
                    cmd_extra.append(arg)
        argv = addon_args + cmd_extra + argv_cmd

        xbmc.log(
            "Texture Cache Addon: Running %s" % redact_secrets(" ".join(argv)),
            xbmc.LOGINFO,
        )

        result = {"exit_code": None, "exception": None}
        texturecache.progress_message = ""
        texturecache.progress_percent = -1
        texturecache.stopped = threading.Event()

        def run_in_thread():
            try:
                texturecache.addon_entry(argv)
                result["exit_code"] = 0
            except SystemExit as e:
                code = getattr(e, "code", 1)
                if code is None:
                    code = 0
                result["exit_code"] = code
                result["exception"] = e
            except Exception as e:
                result["exception"] = e

        thread = threading.Thread(target=run_in_thread)
        thread.daemon = True
        thread.start()
        worker = thread

        start_time = time.time()
        poll_interval = 0.4
        cmd_cancelled = False

        while thread.is_alive():
            elapsed = int(time.time() - start_time)
            base_pct = int((i / float(len(commands))) * 100) if commands else 0
            tc_pct = getattr(texturecache, "progress_percent", -1)
            if isinstance(tc_pct, (int, float)) and tc_pct >= 0:
                span = int(100.0 / max(len(commands), 1))
                percent = min(99, base_pct + int((tc_pct / 100.0) * span))
            else:
                percent = base_pct

            tc_msg = (getattr(texturecache, "progress_message", "") or "").strip()
            if tc_msg:
                tc_msg = tc_msg[:80]
                msg = "[%d/%d] %s (%s)" % (i + 1, len(commands), tc_msg, _format_elapsed(elapsed))
            else:
                msg = "[%d/%d] %s... (%s)" % (i + 1, len(commands), cmd, _format_elapsed(elapsed))

            progress.update(max(0, min(100, percent)), msg)
            _publish_live_status(
                "running",
                commands,
                run_source,
                index=i + 1,
                cmd=cmd,
                percent=percent,
                message=msg,
                elapsed=_format_elapsed(elapsed),
            )

            if _run_should_stop(progress):
                cmd_cancelled = True
                cancelled = True
                cancelled_by_request = stop_was_requested()
                _signal_worker_stop()
                progress.update(
                    max(0, min(100, percent)),
                    _localized(30081, "Stopping the current run..."),
                )
                break

            time.sleep(poll_interval)

        if cmd_cancelled:
            elapsed_total = int(time.time() - start_time)
            status_lines.append(
                "CANCELLED  %s  after %s (waiting for worker to finish)"
                % (cmd, _format_elapsed(elapsed_total))
            )
            break

        elapsed_total = int(time.time() - start_time)
        exc = result["exception"]
        code = result["exit_code"]
        failed = False
        err_msg = ""

        if exc is not None and not isinstance(exc, SystemExit):
            failed = True
            err_msg = str(exc)
            xbmc.log("Texture Cache Addon Error: %s" % err_msg, xbmc.LOGERROR)
        elif code is not None and code != 0:
            failed = True
            err_msg = "exit code %s" % code
            xbmc.log("Texture Cache Addon: Command '%s' %s" % (cmd, err_msg), xbmc.LOGERROR)

        if failed:
            sequence_failed = True
            status_lines.append("FAIL       %s  (%s)  %s" % (cmd, err_msg, _format_elapsed(elapsed_total)))
            if not continue_on_error:
                _wait_for_worker(worker, timeout=15.0)
                progress.close()
                texturecache.close_output_file()
                texturecache.output_file_path = None
                _write_status(status_lines)
                _publish_live_status(
                    "failed",
                    commands,
                    run_source,
                    index=i + 1,
                    cmd=cmd,
                    percent=100,
                    message=err_msg,
                    elapsed=_format_elapsed(elapsed_total),
                )
                _record_run_history("failed", commands, run_source, message=err_msg, started=run_started)
                _notify_run_finished(run_source, interactive, sequence_failed=True, cancelled=False)
                if show_results:
                    _show_results_modal(output_file, "\n".join(status_lines))
                    xbmcgui.Dialog().ok(
                        _localized(30047, "Texture Cache Error"),
                        "Command '%s' failed:\n\n%s" % (cmd, err_msg),
                    )
                return
            status_lines.append("           (continuing — continue_on_error is enabled)")
        else:
            status_lines.append("OK         %s  %s" % (cmd, _format_elapsed(elapsed_total)))

    if cancelled:
        progress.close()
        worker_done = _wait_for_worker(worker, timeout=20.0)
    else:
        worker_done = _wait_for_worker(worker)
        progress.close()
    texturecache.close_output_file()
    texturecache.output_file_path = None

    if cancelled:
        status_lines.append("")
        if cancelled_by_request:
            status_lines.append("Sequence cancelled because a new run was requested.")
        else:
            status_lines.append("Sequence cancelled by user.")
        _write_status(status_lines)
        _publish_live_status(
            "cancelled",
            commands,
            run_source,
            percent=0,
            message="Cancelled",
        )
        _record_run_history("cancelled", commands, run_source, message="Cancelled", started=run_started)
        _notify_run_finished(run_source, interactive, sequence_failed=False, cancelled=True)
        if not worker_done:
            threading.Thread(
                target=_join_worker_and_release,
                args=(worker,),
                name="texturecache-cancel-release",
            ).start()
            return True
        return

    status_lines.append("")
    status_lines.append("Sequence complete%s." % (" with errors" if sequence_failed else ""))
    _write_status(status_lines)
    _publish_live_status(
        "failed" if sequence_failed else "complete",
        commands,
        run_source,
        index=len(commands),
        percent=100,
        message="Sequence complete%s." % (" with errors" if sequence_failed else ""),
    )
    _record_run_history(
        "failed" if sequence_failed else "complete",
        commands,
        run_source,
        message="Sequence complete%s." % (" with errors" if sequence_failed else ""),
        started=run_started,
    )
    if show_results:
        _show_results_modal(output_file, "\n".join(status_lines))
    _notify_run_finished(run_source, interactive, sequence_failed=sequence_failed, cancelled=False)


def _notify_run_finished(run_source, interactive, sequence_failed, cancelled):
    icon = addon.getAddonInfo("icon")
    title = _localized(30000, "Texture Cache")
    if cancelled:
        msg = _localized(30048, "Cancelled")
    elif run_source == "service":
        if sequence_failed:
            msg = _localized(30070, "Scheduled run finished with errors")
        else:
            msg = _localized(30069, "Scheduled run complete")
    elif sequence_failed:
        msg = "Completed with errors"
    else:
        msg = _localized(30049, "Command sequence complete")
    xbmcgui.Dialog().notification(title, msg, icon, 8000 if run_source == "service" else 5000)


def _write_status(status_lines):
    path = get_last_status_path()
    if not path:
        return
    try:
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(status_lines) + "\n")
    except (IOError, OSError):
        pass


def show_main_menu():
    refresh_next_scheduled_display()
    while True:
        bg = _get_bool("run_in_background", False)
        running = lock_is_held()
        items = [
            ("preset", _localized(30001, "Run preset…")),
            ("custom", _localized(30002, "Run custom sequence")),
            ("bg", "%s: %s" % (_localized(30127, "Run in background"), "On" if bg else "Off")),
            ("status", _localized(30072, "Background run status")),
        ]
        if running:
            items.append(("stop", _localized(30079, "Stop current run")))
        items.extend([
            ("results", _localized(30003, "Last results")),
            ("export", _localized(30004, "Export last output…")),
            ("commands", _localized(30005, "Supported commands")),
            ("tools", _localized(30006, "Tools…")),
            ("settings", _localized(30007, "Settings")),
        ])
        idx = xbmcgui.Dialog().select(
            _localized(30000, "Texture Cache Utility"),
            [label for _key, label in items],
        )
        if idx < 0:
            return
        action = items[idx][0]
        if action == "preset":
            built = build_from_preset()
            if built:
                cmds, extra = built
                run_commands(cmds, extra_args=extra)
            continue
        if action == "custom":
            run_commands()
            continue
        if action == "bg":
            toggle_run_in_background()
            continue
        if action == "status":
            show_background_status()
            continue
        if action == "stop":
            stop_current_run(interactive=True)
            continue
        if action == "results":
            view_last_results()
            continue
        if action == "export":
            export_output(get_last_output_path())
            continue
        if action == "commands":
            show_commands_help()
            continue
        if action == "tools":
            show_tools_help()
            continue
        if action == "settings":
            refresh_next_scheduled_display()
            addon.openSettings()
            continue


def _uniqueid_value(details):
    uid = details.get("uniqueid") or {}
    if isinstance(uid, dict):
        for key in ("imdb", "tmdb", "tvdb", "musicbrainz"):
            if uid.get(key):
                return str(uid[key])
        for value in uid.values():
            if value:
                return str(value)
    return ""


def _jsonrpc_details(method, id_key, dbid_int, result_key, properties):
    data = _jsonrpc(method, {id_key: dbid_int, "properties": properties})
    if data.get("error"):
        xbmc.log(
            "Texture Cache Addon: %s failed for id %s: %s"
            % (method, dbid_int, data.get("error")),
            xbmc.LOGWARNING,
        )
        return {}
    return (data.get("result") or {}).get(result_key) or {}


def _library_item_from_dbid(dbtype, dbid):
    spec = _DBTYPE_RPC.get(dbtype)
    if not spec:
        return None
    method, id_key, result_key, mediaclass, title_field, props = spec
    try:
        dbid_int = int(dbid)
    except (TypeError, ValueError):
        return None
    details = _jsonrpc_details(method, id_key, dbid_int, result_key, props)
    if not details:
        details = _jsonrpc_details(
            method, id_key, dbid_int, result_key, _DBTYPE_MIN_PROPS.get(dbtype, ["title"])
        )
    if not details:
        return None
    title = (details.get(title_field) or details.get("title") or details.get("label") or "").strip()
    if dbtype in ("episode", "season") and not title:
        title = (details.get("showtitle") or "").strip()
    return {
        "mediaclass": mediaclass,
        "title": title,
        "uniqueid": _uniqueid_value(details),
        "year": details.get("year"),
    }


def run_context_item():
    """Cache artwork for the focused library item (DBID, title, or both)."""
    content = (xbmc.getInfoLabel("Container.Content") or "").lower()
    list_title = xbmc.getInfoLabel("ListItem.Title") or xbmc.getInfoLabel("ListItem.Label") or ""
    dbtype = (xbmc.getInfoLabel("ListItem.DBTYPE") or "").lower()
    showtitle = xbmc.getInfoLabel("ListItem.TVShowTitle") or ""
    dbid = (xbmc.getInfoLabel("ListItem.DBID") or "").strip()
    match_mode = _get_int("context_match", CONTEXT_MATCH_DBID)

    media_map = {
        "movies": "movies", "movie": "movies",
        "tvshows": "tvshows", "tvshow": "tvshows",
        "episodes": "tvshows", "episode": "tvshows",
        "seasons": "tvshows", "season": "tvshows",
        "artists": "artists", "artist": "artists",
        "albums": "albums", "album": "albums",
        "songs": "songs", "song": "songs",
        "musicvideos": "musicvideos", "musicvideo": "musicvideos",
        "sets": "sets", "set": "sets",
    }

    mediaclass = media_map.get(dbtype) or media_map.get(content)
    if not mediaclass:
        xbmcgui.Dialog().ok(
            _localized(30000, "Texture Cache"),
            _localized(30095, "Context cache is available for movies, TV, music, and sets."),
        )
        return

    is_episode_or_season = dbtype in ("episode", "episodes", "season", "seasons")
    title_filter = list_title
    if is_episode_or_season and showtitle:
        title_filter = showtitle

    extra_args = []
    display_name = title_filter
    resolved = None
    cmd = ""
    used_title_fallback = False

    if match_mode in (CONTEXT_MATCH_DBID, CONTEXT_MATCH_BOTH):
        resolved = _library_item_from_dbid(dbtype, dbid) if dbid else None
        if not resolved:
            used_title_fallback = True
            if not title_filter:
                xbmcgui.Dialog().ok(
                    _localized(30000, "Texture Cache"),
                    _localized(30089, "Could not resolve library ID %s; using the list title instead.")
                    % (dbid or "(empty)"),
                )
                return
            xbmcgui.Dialog().notification(
                _localized(30000, "Texture Cache"),
                _localized(30089, "Could not resolve library ID %s; using the list title instead.")
                % (dbid or "(empty)"),
                xbmcgui.NOTIFICATION_INFO,
                5000,
            )
            extra_args = []
            cmd = 'c %s "%s"' % (mediaclass, title_filter.replace('"', ""))
            display_name = title_filter
        else:
            mediaclass = resolved["mediaclass"]
            display_name = resolved["title"] or title_filter
            if match_mode == CONTEXT_MATCH_BOTH:
                check = (title_filter or list_title or "").strip().lower()
                got = (resolved["title"] or "").strip().lower()
                if check and got and check not in got and got not in check:
                    xbmcgui.Dialog().ok(
                        _localized(30000, "Texture Cache"),
                        "DBID and title do not match:\n\nID title: %s\nList title: %s"
                        % (resolved["title"], title_filter or list_title),
                    )
                    return
            if resolved["uniqueid"] and dbtype == "movie":
                extra_args = ["@filter.operator=is", "@filter=uniqueid"]
                cmd = 'c movies "%s"' % resolved["uniqueid"].replace('"', "")
            elif resolved["uniqueid"] and dbtype == "tvshow":
                extra_args = ["@filter.operator=is", "@filter=uniqueid"]
                cmd = 'c tvshows "%s"' % resolved["uniqueid"].replace('"', "")
            else:
                extra_args = ["@filter.operator=is"]
                cmd = 'c %s "%s"' % (mediaclass, (resolved["title"] or title_filter).replace('"', ""))

    if match_mode == CONTEXT_MATCH_TITLE or (match_mode == CONTEXT_MATCH_BOTH and not resolved and not cmd):
        if not title_filter:
            xbmcgui.Dialog().ok(
                _localized(30000, "Texture Cache"),
                _localized(30096, "Could not determine item title."),
            )
            return
        extra_args = []
        cmd = 'c %s "%s"' % (mediaclass, title_filter.replace('"', ""))
        display_name = title_filter

    if not cmd or not cmd.split()[-1].strip('"'):
        xbmcgui.Dialog().ok(
            _localized(30000, "Texture Cache"),
            _localized(30097, "Could not determine item to cache."),
        )
        return

    match_label = ("library ID", "title", "library ID + title")[max(0, min(2, match_mode))]
    if used_title_fallback:
        match_label = "title (library ID fallback)"
    msg = "Cache missing artwork for:\n\n%s (%s)\nMatch: %s\n\nCommand: %s" % (
        display_name, mediaclass, match_label, cmd,
    )
    if is_episode_or_season:
        msg += "\n\n" + _localized(
            30088,
            "This will cache artwork for the TV show, not only this episode or season.",
        )
    if not xbmcgui.Dialog().yesno(_localized(30000, "Texture Cache"), msg):
        return
    run_commands([cmd], run_source="context", extra_args=extra_args)


def run_service_tick():
    """Called from service.py when schedule conditions are met."""
    if library_is_scanning():
        xbmc.log("Texture Cache Addon: Scheduled run skipped, library scan in progress", xbmc.LOGINFO)
        return
    raw = _get_setting("service_cmd_sequence", "") or _get_setting("cmd_sequence", "c, R")
    commands = [c.strip() for c in raw.split(",") if c.strip()]
    if not commands:
        return
    xbmc.log("Texture Cache Addon: Scheduled run starting: %s" % raw, xbmc.LOGINFO)
    run_commands(commands, interactive=False, run_source="service")


if __name__ == "__main__":
    arg = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    if arg == "showcommands":
        show_commands_help()
    elif arg == "lastresults":
        view_last_results()
    elif arg == "export":
        export_output(get_last_output_path())
    elif arg == "context":
        run_context_item()
    elif arg == "service":
        run_service_tick()
    elif arg == "tools":
        show_tools_help()
    elif arg == "run":
        run_commands()
    elif arg == "settings":
        refresh_next_scheduled_display()
        addon.openSettings()
    elif arg == "testwebserver":
        show_webserver_test()
    elif arg == "pickcommands":
        pick_command_sequence("cmd_sequence")
    elif arg == "pickservicecommands":
        pick_command_sequence("service_cmd_sequence")
    elif arg == "bgstatus":
        show_background_status()
    elif arg == "togglebackground":
        toggle_run_in_background()
    elif arg == "stoprun":
        stop_current_run(interactive=True)
    elif arg == "toggleschedule":
        xbmc.log("Texture Cache Addon: schedule toggle script started", xbmc.LOGINFO)
        on_schedule_toggle()
    elif arg == "refreshschedule":
        refresh_addon()
        apply_repeat_to_next_run()
    else:
        show_main_menu()
