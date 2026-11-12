# -*- coding: utf-8 -*-
"""
Background service for scheduled texturecache maintenance runs.
"""

import sys
import time

import xbmc
import xbmcaddon
import xbmcvfs

addon = xbmcaddon.Addon()
ADDON_ID = "script.texture.cache"


def _load_common():
    import os
    root = os.path.normpath(xbmcvfs.translatePath(addon.getAddonInfo("path")))
    if root not in sys.path:
        sys.path.insert(0, root)
    import common
    return common


class TextureCacheMonitor(xbmc.Monitor):
    def __init__(self):
        xbmc.Monitor.__init__(self)
        self.last_launch_attempt = 0.0
        self._schedule_was_on = None

    def _maybe_run(self):
        global addon
        addon = xbmcaddon.Addon()

        try:
            common = _load_common()
        except Exception as e:
            xbmc.log("Texture Cache Service: could not load common.py - %s" % e, xbmc.LOGERROR)
            return

        common.refresh_addon()
        enabled = common.get_bool("enable_service", False)
        if self._schedule_was_on is None:
            common.schedule_verbose("service first tick enabled=%s" % enabled)
        if self._schedule_was_on is False and enabled:
            future = common.next_run_is_future()
            common.schedule_verbose("service saw scheduler turn on; next already future=%s" % future)
            if not future:
                common.restart_schedule_from_now()
        elif self._schedule_was_on and not enabled:
            common.schedule_verbose("service saw scheduler turn off")
            common.clear_next_scheduled_run()
        self._schedule_was_on = enabled
        if not enabled:
            return

        common.ensure_schedule_origin()
        common.refresh_next_scheduled_display()

        idle_minutes = max(0, common.get_int("service_idle_minutes", 10))
        now = time.time()

        if common.lock_is_held():
            return

        if common.library_is_scanning():
            xbmc.log("Texture Cache Service: skipping, library scan in progress", xbmc.LOGINFO)
            return

        if not common.schedule_interval_elapsed(now):
            return

        if xbmc.Player().isPlaying():
            return

        idle_sec = idle_minutes * 60
        if idle_sec > 0:
            try:
                idle = int(xbmc.getGlobalIdleTime())
            except Exception:
                idle = 0
            if idle < idle_sec:
                return

        if self.last_launch_attempt and (now - self.last_launch_attempt) < 90:
            return

        self.last_launch_attempt = now
        xbmc.log("Texture Cache Service: triggering scheduled run", xbmc.LOGINFO)
        xbmc.executebuiltin("RunScript(%s,service)" % ADDON_ID)


if __name__ == "__main__":
    xbmc.log("Texture Cache Service: started (addon 2.0.6)", xbmc.LOGINFO)
    try:
        common = _load_common()
        common.begin_kodi_session()
        common.refresh_addon()
        enabled = common.get_bool("enable_service", False)
        common.schedule_verbose(
            "service start enabled=%s profile=%s display=%r last=%s next=%s"
            % (
                enabled,
                common.addon_profile_native,
                common.get_setting("next_scheduled_run_display", ""),
                common.read_scheduled_last_run(),
                common._read_next_run(),
            )
        )
        if enabled:
            common.ensure_future_next_run()
        common.refresh_next_scheduled_display()
        common.schedule_verbose(
            "service start done display=%r next=%s"
            % (common.get_setting("next_scheduled_run_display", ""), common._read_next_run())
        )
    except Exception as e:
        xbmc.log("Texture Cache Service: session start failed - %s" % e, xbmc.LOGERROR)
    monitor = TextureCacheMonitor()
    while not monitor.abortRequested():
        try:
            monitor._maybe_run()
        except Exception as e:
            xbmc.log("Texture Cache Service: error - %s" % e, xbmc.LOGERROR)
        if monitor.waitForAbort(60):
            break
    xbmc.log("Texture Cache Service: stopped", xbmc.LOGINFO)
