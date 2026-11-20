# -*- coding: utf-8 -*-
"""Unit tests for script.texture.cache with mocked Kodi modules."""

import os
import sys
import types
import xml.etree.ElementTree as ET
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _install_kodi_stubs(tmp_path):
    profile_dir = str(tmp_path / "profile")
    os.makedirs(profile_dir, exist_ok=True)
    settings_store = {}

    xbmc = types.ModuleType("xbmc")
    xbmc.LOGINFO = 1
    xbmc.LOGWARNING = 2
    xbmc.LOGERROR = 3
    xbmc.log = lambda *a, **kw: None
    xbmc.executeJSONRPC = lambda *a, **kw: "{}"
    xbmc.executebuiltin = lambda *a, **kw: None
    xbmc.getCondVisibility = lambda *a, **kw: False
    xbmc.getGlobalIdleTime = lambda: 0

    class _Monitor:
        def __init__(self):
            self._abort = False

        def abortRequested(self):
            return self._abort

        def waitForAbort(self, timeout=0):
            return self._abort

    class _Player:
        def isPlaying(self):
            return False

    xbmc.Monitor = _Monitor
    xbmc.Player = _Player

    xbmcaddon = types.ModuleType("xbmcaddon")

    class _Addon:
        def getAddonInfo(self, key):
            if key == "path":
                return REPO_ROOT
            if key == "profile":
                return profile_dir
            if key == "version":
                return "2.0.6"
            return ""

        def getLocalizedString(self, sid):
            return ""

        def getSetting(self, key):
            return str(settings_store.get(key, ""))

        def getSettingBool(self, key):
            val = settings_store.get(key, False)
            if isinstance(val, bool):
                return val
            return str(val).lower() in ("true", "1", "yes")

        def getSettingInt(self, key):
            return int(settings_store.get(key, 0))

        def setSetting(self, key, val):
            settings_store[key] = str(val)

        def setSettingString(self, key, val):
            settings_store[key] = str(val)

        def setSettingBool(self, key, val):
            settings_store[key] = bool(val)

    xbmcaddon.Addon = _Addon

    xbmcgui = types.ModuleType("xbmcgui")
    xbmcgui.NOTIFICATION_INFO = 0

    class _Dialog:
        def ok(self, *a, **kw):
            return True

        def yesno(self, *a, **kw):
            return False

        def notification(self, *a, **kw):
            return None

    class _DialogProgress:
        def create(self, *a, **kw):
            pass

        def update(self, *a, **kw):
            pass

        def iscanceled(self):
            return False

        def close(self):
            pass

    xbmcgui.Dialog = _Dialog
    xbmcgui.DialogProgress = _DialogProgress
    xbmcgui.DialogProgressBG = _DialogProgress

    xbmcvfs = types.ModuleType("xbmcvfs")
    xbmcvfs.translatePath = lambda p: p

    sys.modules["xbmc"] = xbmc
    sys.modules["xbmcaddon"] = xbmcaddon
    sys.modules["xbmcgui"] = xbmcgui
    sys.modules["xbmcvfs"] = xbmcvfs

    return profile_dir, settings_store


def test_write_profile_setting_xml_safe(tmp_path):
    profile_dir, _ = _install_kodi_stubs(tmp_path)
    import importlib
    import common
    importlib.reload(common)

    settings_xml = os.path.join(profile_dir, "settings.xml")
    with open(settings_xml, "w", encoding="utf-8") as f:
        f.write(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<settings version="2">\n'
            '  <setting id="next_scheduled_run_display">Never</setting>\n'
            '  <setting id="legacy_attr" value="old" />\n'
            '</settings>\n'
        )

    assert common._write_profile_setting("next_scheduled_run_display", "2026-11-20 & <test>")
    assert common._write_profile_setting("legacy_attr", 'new"val')
    assert not common._write_profile_setting("missing_key", "123")

    tree = ET.parse(settings_xml)
    root = tree.getroot()
    elems = {e.get("id"): e for e in root.iter("setting")}
    assert elems["next_scheduled_run_display"].text == "2026-11-20 & <test>"
    assert elems["legacy_attr"].get("value") == 'new"val'


def test_redact_secrets_and_prune_safety(tmp_path):
    _, settings_store = _install_kodi_stubs(tmp_path)
    import importlib
    import common
    import webserver
    import main
    importlib.reload(common)
    importlib.reload(webserver)
    importlib.reload(main)

    masked = main.redact_secrets("@webserver.password=secret123 @omdb.apikey=key999 c")
    assert "secret123" not in masked
    assert "key999" not in masked
    assert "@webserver.password=***" in masked
    assert "@omdb.apikey=***" in masked

    settings_store["allow_prune_delete"] = False
    assert main.apply_prune_safety(["c", "P"]) == ["c", "p"]

    settings_store["allow_prune_delete"] = True
    assert main.apply_prune_safety(["c", "P"]) == ["c", "P"]


def test_run_should_stop_on_kodi_abort(tmp_path):
    _install_kodi_stubs(tmp_path)
    import importlib
    import main
    importlib.reload(main)

    class _DummyProgress:
        def iscanceled(self):
            return False

    class _DummyMonitor:
        def __init__(self, aborted):
            self._aborted = aborted

        def abortRequested(self):
            return self._aborted

    assert main._run_should_stop(_DummyProgress(), _DummyMonitor(False)) is False
    assert main._run_should_stop(_DummyProgress(), _DummyMonitor(True)) is True


def test_service_on_settings_changed(tmp_path):
    _, settings_store = _install_kodi_stubs(tmp_path)
    import importlib
    import common
    import service
    importlib.reload(common)
    importlib.reload(service)

    monitor = service.TextureCacheMonitor()
    settings_store["enable_service"] = False
    monitor.onSettingsChanged()
    assert monitor._schedule_was_on is False

    settings_store["enable_service"] = True
    monitor.onSettingsChanged()
    assert monitor._schedule_was_on is True


def test_package_build_zip(tmp_path):
    from tools.package import build_zip

    out_zip = tmp_path / "out.zip"
    path, count = build_zip(REPO_ROOT, str(out_zip))
    assert os.path.isfile(path)
    assert count > 0

    with zipfile.ZipFile(path, "r") as zf:
        names = set(zf.namelist())
        assert "script.texture.cache/addon.xml" in names
        assert "script.texture.cache/resources/settings.xml" in names
        assert "script.texture.cache/webserver.py" in names
        assert not any(n.startswith("script.texture.cache/tests/") for n in names)
        assert not any("__pycache__" in n for n in names)
