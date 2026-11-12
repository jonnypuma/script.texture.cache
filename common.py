# -*- coding: utf-8 -*-
"""Shared helpers for the Texture Cache addon (script + service)."""

import errno
import json
import os
import threading
import time

import xbmc
import xbmcaddon
import xbmcvfs

ADDON_ID = "script.texture.cache"
LOCK_FILENAME = "run.lock"
STOP_FILENAME = "run.stop"
SESSION_FILENAME = "kodi_session.json"
SCHEDULE_STAMP_FILENAME = "last_scheduled_run.txt"
NEXT_STAMP_FILENAME = "next_scheduled_run.txt"
LIVE_STATUS_FILENAME = "live_status.json"
RUN_HISTORY_FILENAME = "run_history.json"
LOCK_STALE_SECONDS = 180
LOCK_WAKE_WAIT_SECONDS = 15
HEARTBEAT_INTERVAL = 10
LIVE_HEARTBEAT_SECONDS = 30
HISTORY_LIMIT = 3
NEVER_DISPLAY = "Never"
DEFAULT_NEXT_DELAY_SECONDS = 2 * 3600

addon = xbmcaddon.Addon()
addon_path = addon.getAddonInfo("path")
addon_path_translated = xbmcvfs.translatePath(addon_path)
profile_path = xbmcvfs.translatePath("special://profile")
addon_path_native = os.path.normpath(addon_path_translated)
userdata_path = os.path.normpath(profile_path) if profile_path else None
addon_profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
addon_profile_native = os.path.normpath(addon_profile) if addon_profile else None

_lock_token = None
_session_id = None
_heartbeat_stop = threading.Event()
_heartbeat_thread = None
_heartbeat_lock = threading.Lock()


def refresh_addon():
    global addon
    addon = xbmcaddon.Addon()
    return addon


def localized(string_id, fallback):
    try:
        text = addon.getLocalizedString(string_id)
        if text and text != str(string_id):
            return text
    except Exception:
        pass
    return fallback


def get_bool(setting_id, default=False):
    refresh_addon()
    try:
        return bool(addon.getSettingBool(setting_id))
    except Exception:
        val = get_setting(setting_id, "")
        if val == "":
            return default
        return val.lower() in ("true", "1", "yes")


def schedule_verbose(message):
    """Info-level schedule trace. Kodi's log level here is info, so debug lines would be hidden."""
    try:
        if not get_bool("enable_verbose_logging", False):
            return
    except Exception:
        return
    xbmc.log("Texture Cache Addon: %s" % message, xbmc.LOGINFO)


def get_int(setting_id, default=0):
    try:
        return addon.getSettingInt(setting_id)
    except AttributeError:
        try:
            return int(addon.getSetting(setting_id) or default)
        except (TypeError, ValueError):
            return default
    except Exception:
        return default


def get_setting(setting_id, default=""):
    try:
        val = addon.getSetting(setting_id)
        return val if val not in (None, "") else default
    except Exception:
        return default


def set_setting(setting_id, value):
    refresh_addon()
    value = "" if value is None else str(value)
    try:
        addon.setSetting(setting_id, value)
    except Exception as e:
        schedule_verbose("setSetting %s failed: %s" % (setting_id, e))
    try:
        addon.setSettingString(setting_id, value)
    except Exception as e:
        schedule_verbose("setSettingString %s failed: %s" % (setting_id, e))
    readback = get_setting(setting_id, "")
    patched = False
    if readback != value:
        patched = _write_profile_setting(setting_id, value)
    if setting_id in ("next_scheduled_run_display", "enable_service"):
        schedule_verbose(
            "set %s = %r readback %r file_patch %s" % (setting_id, value, readback, patched)
        )


def _write_profile_setting(setting_id, value):
    """Patch userdata settings.xml when the settings API keeps the previous value."""
    if not addon_profile_native:
        return False
    path = os.path.join(addon_profile_native, "settings.xml")
    if not os.path.isfile(path):
        schedule_verbose("settings file missing: %s" % path)
        return False
    try:
        import re
        with open(path, "r", encoding="utf-8") as handle:
            data = handle.read()
        body = re.compile(
            r'(<setting id="%s"[^>]*>)(.*?)(</setting>)' % re.escape(setting_id),
            re.DOTALL,
        )
        updated, count = body.subn(r"\g<1>%s\g<3>" % value, data, count=1)
        if count == 0:
            attr = re.compile(
                r'(<setting id="%s"[^>]*\bvalue=")[^"]*(")' % re.escape(setting_id)
            )
            updated, count = attr.subn(r"\g<1>%s\g<2>" % value, data, count=1)
        if count == 0:
            schedule_verbose("settings file has no %s entry in %s" % (setting_id, path))
            return False
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(updated)
        return True
    except Exception as e:
        xbmc.log(
            "Texture Cache Addon: could not store setting %s - %s" % (setting_id, e),
            xbmc.LOGWARNING,
        )
        return False


def set_bool(setting_id, value):
    refresh_addon()
    try:
        addon.setSettingBool(setting_id, bool(value))
    except AttributeError:
        set_setting(setting_id, "true" if value else "false")


def format_elapsed(seconds):
    if seconds < 60:
        return "%ds" % seconds
    elif seconds < 3600:
        return "%dm %02ds" % (seconds // 60, seconds % 60)
    else:
        return "%dh %02dm %02ds" % (seconds // 3600, (seconds % 3600) // 60, seconds % 60)


def format_local_time(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))
    except (TypeError, ValueError, OverflowError):
        return NEVER_DISPLAY


def ensure_addon_profile():
    if addon_profile_native and not os.path.isdir(addon_profile_native):
        try:
            os.makedirs(addon_profile_native, exist_ok=True)
        except OSError:
            return False
    return bool(addon_profile_native)


def lock_path():
    if not addon_profile_native:
        return None
    return os.path.join(addon_profile_native, LOCK_FILENAME)


def schedule_stamp_path():
    if not addon_profile_native:
        return None
    return os.path.join(addon_profile_native, SCHEDULE_STAMP_FILENAME)


def next_schedule_stamp_path():
    if not addon_profile_native:
        return None
    return os.path.join(addon_profile_native, NEXT_STAMP_FILENAME)


def live_status_path():
    if not addon_profile_native:
        return None
    return os.path.join(addon_profile_native, LIVE_STATUS_FILENAME)


def stop_request_path():
    if not addon_profile_native:
        return None
    return os.path.join(addon_profile_native, STOP_FILENAME)


def session_path():
    if not addon_profile_native:
        return None
    return os.path.join(addon_profile_native, SESSION_FILENAME)


def request_stop_run():
    path = stop_request_path()
    if not path or not ensure_addon_profile():
        return False
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("%s\n" % time.time())
        return True
    except (IOError, OSError):
        return False


def clear_stop_request():
    path = stop_request_path()
    if not path or not os.path.exists(path):
        return
    try:
        os.remove(path)
    except (IOError, OSError):
        pass


def stop_was_requested():
    path = stop_request_path()
    return bool(path and os.path.exists(path))


def wait_until_unlocked(timeout=90.0, progress=None, message=""):
    reclaim_orphaned_run_lock("wait")
    monitor = xbmc.Monitor()
    deadline = time.time() + max(1.0, float(timeout))
    while lock_is_held():
        if time.time() >= deadline or monitor.abortRequested():
            return False
        if progress is not None and progress.iscanceled():
            return False
        remaining = max(0, int(deadline - time.time()))
        if progress is not None:
            spent = max(0, int(timeout - remaining))
            pct = min(99, int((spent / float(timeout)) * 100))
            msg = message or "Waiting..."
            progress.update(pct, "%s (%ds)" % (msg, remaining))
        if monitor.waitForAbort(0.4):
            return False
        reclaim_orphaned_run_lock("wait")
    return True


def write_live_status(payload):
    path = live_status_path()
    if not path or not ensure_addon_profile():
        return
    data = dict(payload or {})
    data["updated"] = time.time()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except (IOError, OSError, TypeError, ValueError):
        pass


def read_live_status():
    path = live_status_path()
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (IOError, OSError, ValueError):
        return None


def read_scheduled_last_run():
    path = schedule_stamp_path()
    if not path or not os.path.exists(path):
        return 0.0
    try:
        with open(path, "r", encoding="utf-8") as f:
            return float(f.read().strip() or 0)
    except (IOError, OSError, ValueError):
        return 0.0


def write_scheduled_last_run(ts=None, update_display=True):
    path = schedule_stamp_path()
    if not path or not ensure_addon_profile():
        return
    if ts is None:
        ts = time.time()
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("%s\n" % ts)
    except (IOError, OSError):
        return
    if update_display:
        try:
            set_setting("last_scheduled_run_display", format_local_time(ts))
        except Exception:
            pass
        # A real scheduled run just started. The one after it follows Repeat.
        following = scheduled_next_time(ts)
        _write_next_run(following)
        set_setting("next_scheduled_run_display", format_local_time(following))
    else:
        refresh_next_scheduled_display()


def _add_calendar_months(ts, months):
    import calendar
    when = time.localtime(ts)
    month_index = when.tm_year * 12 + (when.tm_mon - 1) + int(months)
    year, month0 = divmod(month_index, 12)
    month = month0 + 1
    day = min(when.tm_mday, calendar.monthrange(year, month)[1])
    try:
        return time.mktime((year, month, day, when.tm_hour, when.tm_min, when.tm_sec, 0, 0, -1))
    except (OverflowError, ValueError, OSError):
        return ts + 30 * 86400


def scheduled_next_time(last_run):
    """When the next scheduled run is allowed, based on Repeat."""
    unit = get_int("service_interval_unit", 0)
    if unit == 1:
        days = get_int("service_interval_days", 1)
        if days < 1:
            days = 1
        elif days > 31:
            days = 31
        return last_run + days * 86400
    if unit == 2:
        return last_run + 7 * 86400
    if unit == 3:
        return _add_calendar_months(last_run, 1)
    hours = get_int("service_interval_hours", 24)
    if hours < 1:
        hours = 1
    elif hours > 168:
        hours = 168
    return last_run + hours * 3600


def _read_next_run():
    path = next_schedule_stamp_path()
    if not path or not os.path.exists(path):
        return 0.0
    try:
        with open(path, "r", encoding="utf-8") as f:
            return float(f.read().strip() or 0)
    except (IOError, OSError, ValueError):
        return 0.0


def _write_next_run(ts):
    path = next_schedule_stamp_path()
    if not path or not ensure_addon_profile():
        return False
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("%s\n" % float(ts))
        return True
    except (IOError, OSError, TypeError, ValueError):
        return False


def clear_next_scheduled_run():
    """Blank the next-run time. Used when the scheduler is turned off."""
    path = next_schedule_stamp_path()
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except (IOError, OSError):
            pass
    set_setting("next_scheduled_run_display", "")


def next_run_is_future(now=None):
    if now is None:
        now = time.time()
    return _read_next_run() > now


def schedule_interval_elapsed(now=None):
    """True when the saved next-run time has been reached."""
    if now is None:
        now = time.time()
    nxt = _read_next_run()
    if not nxt:
        return False
    return now >= nxt


def restart_schedule_from_now():
    """Blank a passed or missing next-run time and set it to now plus 2 hours."""
    now = time.time()
    schedule_verbose("replace next run with now+2h; profile %s" % addon_profile_native)
    set_setting("next_scheduled_run_display", "")
    nxt = now + DEFAULT_NEXT_DELAY_SECONDS
    wrote = _write_next_run(nxt)
    text = format_local_time(nxt)
    set_setting("next_scheduled_run_display", text)
    schedule_verbose("next file write %s value %s" % (wrote, text))
    xbmc.log("Texture Cache Addon: next scheduled run set to %s" % text, xbmc.LOGINFO)
    return nxt


def ensure_future_next_run(now=None):
    """Keep a future next-run time. If it is missing or already past, set now plus 2 hours."""
    if now is None:
        now = time.time()
    nxt = _read_next_run()
    shown = get_setting("next_scheduled_run_display", "")
    last = read_scheduled_last_run()
    schedule_verbose(
        "ensure now=%s next_file=%s shown=%r last_stamp=%s" % (now, nxt, shown, last)
    )
    if nxt > now:
        schedule_verbose("ensure kept future stamp %s" % format_local_time(nxt))
        return nxt
    computed = scheduled_next_time(last) if last else 0
    shown_past = _clock_time_is_past(shown, now)
    if computed > now and not shown_past:
        _write_next_run(computed)
        schedule_verbose("ensure kept repeat time %s" % format_local_time(computed))
        return computed
    schedule_verbose(
        "ensure replacing passed or missing time (shown_past=%s computed=%s)"
        % (shown_past, computed)
    )
    return restart_schedule_from_now()


def apply_repeat_to_next_run():
    """Repeat changed. Move the next run to one interval after the last stamp, or 2 hours if that is already past."""
    refresh_addon()
    if not get_bool("enable_service", False):
        return ""
    now = time.time()
    last = read_scheduled_last_run()
    nxt = scheduled_next_time(last) if last else 0
    if not nxt or nxt <= now:
        nxt = restart_schedule_from_now()
    else:
        _write_next_run(nxt)
        set_setting("next_scheduled_run_display", format_local_time(nxt))
    return format_local_time(nxt)


def on_schedule_toggle():
    refresh_addon()
    enabled = get_bool("enable_service", False)
    schedule_verbose(
        "toggle begin enabled=%s display=%r next_file=%s profile=%s"
        % (enabled, get_setting("next_scheduled_run_display", ""), _read_next_run(), addon_profile_native)
    )
    if enabled:
        restart_schedule_from_now()
    else:
        clear_next_scheduled_run()
        schedule_verbose("toggle cleared next run")
    schedule_verbose(
        "toggle end display=%r next_file=%s" % (get_setting("next_scheduled_run_display", ""), _read_next_run())
    )


def ensure_schedule_origin():
    """If the scheduler has never stamped, start the interval now (no 'last run' display)."""
    if read_scheduled_last_run():
        return
    write_scheduled_last_run(update_display=False)


def last_scheduled_display():
    ts = read_scheduled_last_run()
    text = NEVER_DISPLAY if not ts else format_local_time(ts)
    stored = get_setting("last_scheduled_run_display", "")
    if stored != text:
        try:
            set_setting("last_scheduled_run_display", text)
        except Exception:
            pass
    return text


def scheduled_run_is_active():
    """True while the scheduler's own run holds the lock."""
    if not lock_is_held():
        return False
    info = _read_lock_info(lock_path()) or {}
    if info.get("tag") == "service":
        return True
    data = read_live_status() or {}
    return data.get("source") == "service" and data.get("state") == "running"


def _clock_time_is_past(text, now=None):
    try:
        parsed = time.strptime((text or "").strip(), "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return False
    if now is None:
        now = time.time()
    try:
        return time.mktime(parsed) <= now
    except (OverflowError, ValueError, OSError):
        return False


def refresh_next_scheduled_display():
    """Show the saved next run. A missing time is filled with now plus 2 hours when the old one has passed."""
    if not get_bool("enable_service", False):
        return ""
    if scheduled_run_is_active():
        text = localized(30195, "Running")
    else:
        nxt = _read_next_run()
        if nxt <= 0:
            nxt = ensure_future_next_run()
        text = format_local_time(nxt) if nxt else ""
    try:
        set_setting("next_scheduled_run_display", text)
    except Exception as e:
        xbmc.log("Texture Cache Addon: next run display failed - %s" % e, xbmc.LOGWARNING)
    xbmc.log("Texture Cache Addon: next scheduled run is %s" % text, xbmc.LOGINFO)
    schedule_verbose("display refresh wrote %r active=%s" % (text, scheduled_run_is_active()))
    return text


def run_history_path():
    if not addon_profile_native:
        return None
    return os.path.join(addon_profile_native, RUN_HISTORY_FILENAME)


def read_run_history():
    path = run_history_path()
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (IOError, OSError, ValueError):
        return []


def append_run_history(entry):
    path = run_history_path()
    if not path or not ensure_addon_profile():
        return
    items = read_run_history()
    row = dict(entry or {})
    row["finished"] = row.get("finished") or time.time()
    items.insert(0, row)
    items = items[:HISTORY_LIMIT]
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(items, f)
    except (IOError, OSError, TypeError, ValueError):
        pass


def library_is_scanning():
    for method in ("VideoLibrary.IsScanningVideo", "AudioLibrary.IsScanningMusic"):
        query = {"jsonrpc": "2.0", "method": method, "id": 1}
        try:
            data = json.loads(xbmc.executeJSONRPC(json.dumps(query)))
        except Exception:
            continue
        result = data.get("result")
        if result is True:
            return True
        if isinstance(result, dict) and result.get("scanning") is True:
            return True
    return False


def _pid_is_alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _parse_lock_pid(token):
    if not token:
        return None
    part = str(token).split("-", 1)[0]
    try:
        return int(part)
    except (TypeError, ValueError):
        return None


def _read_lock_info(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except (IOError, OSError):
        return None
    if not lines:
        return None
    token = (lines[0] if lines else "").strip()
    timestamp = None
    if len(lines) >= 2:
        try:
            timestamp = float(lines[1])
        except (TypeError, ValueError):
            timestamp = None
    tag = (lines[2] if len(lines) >= 3 else "").strip()
    session_id = (lines[3] if len(lines) >= 4 else "").strip()
    return {
        "token": token,
        "timestamp": timestamp,
        "tag": tag,
        "session_id": session_id,
        "pid": _parse_lock_pid(token),
    }


def _write_lock_contents(path, token, timestamp, tag, session_id=""):
    with open(path, "w", encoding="utf-8") as f:
        f.write("%s\n%s\n%s\n%s\n" % (token, timestamp, tag, session_id or ""))


def _remove_lock_file(reason=""):
    path = lock_path()
    if not path or not os.path.exists(path):
        return True
    try:
        os.remove(path)
        if reason:
            xbmc.log("Texture Cache Addon: removed run.lock (%s)" % reason, xbmc.LOGINFO)
        return True
    except (IOError, OSError) as e:
        xbmc.log("Texture Cache Addon: could not remove run.lock - %s" % e, xbmc.LOGWARNING)
        return False


def _read_session():
    global _session_id
    if _session_id:
        return {"id": _session_id, "pid": os.getpid()}
    path = session_path()
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("id"):
        return None
    try:
        file_pid = int(data.get("pid") or 0)
    except (TypeError, ValueError):
        file_pid = 0
    if file_pid and file_pid != os.getpid():
        return None
    _session_id = data.get("id")
    return data


def current_session_id():
    data = _read_session()
    return (data or {}).get("id") or ""


def _mark_live_status_interrupted():
    data = read_live_status()
    if not data or data.get("state") != "running":
        return
    data["state"] = "interrupted"
    data["message"] = "Kodi or the addon restarted; the previous run did not finish."
    write_live_status(data)


def lock_is_orphaned():
    path = lock_path()
    if not path or not os.path.exists(path):
        return False
    info = _read_lock_info(path)
    if not info or not info.get("token"):
        return True
    pid = info.get("pid")
    if pid and pid != os.getpid() and not _pid_is_alive(pid):
        return True
    age = None
    if info.get("timestamp") is not None:
        age = time.time() - info["timestamp"]
    if pid == os.getpid() and age is not None and age <= LIVE_HEARTBEAT_SECONDS:
        return False
    session = _read_session()
    lock_session = info.get("session_id") or ""
    if session and lock_session and lock_session != session.get("id"):
        return True
    return False


def reclaim_orphaned_run_lock(reason="orphaned", force=False):
    path = lock_path()
    if not path or not os.path.exists(path):
        clear_stop_request()
        return True
    if not force and not lock_is_orphaned():
        return False
    _remove_lock_file(reason)
    clear_stop_request()
    _mark_live_status_interrupted()
    return True


def begin_kodi_session():
    """Called when the addon service starts with Kodi. Leftover locks cannot be live."""
    global _session_id
    if not ensure_addon_profile():
        return
    _session_id = "%s-%s" % (os.getpid(), time.time())
    path = session_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "id": _session_id,
                "pid": os.getpid(),
                "started": time.time(),
            }, f)
    except (IOError, OSError, TypeError, ValueError) as e:
        xbmc.log("Texture Cache Addon: could not write session file - %s" % e, xbmc.LOGWARNING)
    xbmc.log("Texture Cache Addon: Kodi session %s" % _session_id, xbmc.LOGINFO)
    path = lock_path()
    if path and os.path.exists(path):
        info = _read_lock_info(path)
        age = _lock_heartbeat_age(path)
        if (
            info
            and info.get("pid") == os.getpid()
            and age is not None
            and age <= LIVE_HEARTBEAT_SECONDS
        ):
            xbmc.log(
                "Texture Cache Addon: keeping live run.lock from this Kodi process",
                xbmc.LOGINFO,
            )
            return
    reclaim_orphaned_run_lock("kodi-session-start", force=True)


def _lock_timestamp(path):
    info = _read_lock_info(path)
    if not info:
        return None
    return info.get("timestamp")


def _lock_heartbeat_age(path):
    ts = _lock_timestamp(path)
    if ts is None:
        return None
    return time.time() - ts


def lock_heartbeat_age():
    path = lock_path()
    if not path or not os.path.exists(path):
        return None
    return _lock_heartbeat_age(path)


def lock_is_held():
    path = lock_path()
    if not path or not os.path.exists(path):
        return False
    if lock_is_orphaned():
        return False
    return True


def _heartbeat_still_alive(path, timeout=LOCK_WAKE_WAIT_SECONDS):
    start_ts = _lock_timestamp(path)
    if start_ts is None:
        return False
    monitor = xbmc.Monitor()
    deadline = time.time() + max(1.0, float(timeout))
    while time.time() < deadline:
        if monitor.waitForAbort(0.5):
            return True
        if lock_is_orphaned():
            return False
        new_ts = _lock_timestamp(path)
        if new_ts is None:
            return False
        if new_ts > start_ts + 0.05:
            return True
    return False


def touch_run_lock():
    path = lock_path()
    if not path or not _lock_token:
        return
    try:
        info = _read_lock_info(path) or {}
        tag = info.get("tag") or "running"
        _write_lock_contents(
            path,
            _lock_token,
            time.time(),
            tag,
            current_session_id(),
        )
    except (IOError, OSError):
        pass


def _heartbeat_loop():
    while not _heartbeat_stop.wait(HEARTBEAT_INTERVAL):
        with _heartbeat_lock:
            if _lock_token:
                touch_run_lock()


def acquire_run_lock(source="gui"):
    global _lock_token, _heartbeat_thread
    path = lock_path()
    if not path:
        return True
    if not ensure_addon_profile():
        return True
    if os.path.exists(path):
        if not reclaim_orphaned_run_lock("acquire"):
            age = _lock_heartbeat_age(path)
            if age is not None and age <= LIVE_HEARTBEAT_SECONDS:
                return False
            if _heartbeat_still_alive(path):
                return False
            if not _remove_lock_file("stale-heartbeat"):
                return False
            _mark_live_status_interrupted()
            clear_stop_request()
    token = "%s-%s-%s" % (os.getpid(), time.time(), source)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        fd = os.open(path, flags)
    except OSError as e:
        if e.errno == errno.EEXIST:
            return False
        xbmc.log("Texture Cache Addon: lock open failed - %s" % e, xbmc.LOGWARNING)
        return True
    try:
        payload = "%s\n%s\n%s\n%s\n" % (token, time.time(), source, current_session_id())
        os.write(fd, payload.encode("utf-8"))
    except (IOError, OSError) as e:
        xbmc.log("Texture Cache Addon: lock write failed - %s" % e, xbmc.LOGWARNING)
        try:
            os.close(fd)
        except (IOError, OSError):
            pass
        try:
            os.remove(path)
        except (IOError, OSError):
            pass
        return True
    else:
        os.close(fd)
    with _heartbeat_lock:
        _lock_token = token
    _heartbeat_stop.clear()
    _heartbeat_thread = threading.Thread(target=_heartbeat_loop)
    _heartbeat_thread.daemon = True
    _heartbeat_thread.start()
    clear_stop_request()
    return True


def release_run_lock():
    global _lock_token, _heartbeat_thread
    _heartbeat_stop.set()
    thread = _heartbeat_thread
    _heartbeat_thread = None
    if thread is not None:
        thread.join(timeout=2.0)
    path = lock_path()
    with _heartbeat_lock:
        token = _lock_token
        _lock_token = None
    if not path:
        clear_stop_request()
        return
    if not token:
        clear_stop_request()
        return
    try:
        info = _read_lock_info(path) if os.path.exists(path) else None
        if info is None or info.get("token") == token:
            _remove_lock_file("run-finished")
        else:
            xbmc.log(
                "Texture Cache Addon: leaving run.lock (owner changed during release)",
                xbmc.LOGINFO,
            )
    except (IOError, OSError):
        _remove_lock_file("run-finished")
    clear_stop_request()
