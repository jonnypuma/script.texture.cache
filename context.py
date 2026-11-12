# -*- coding: utf-8 -*-
"""
Library context menu entry: cache missing artwork for the selected item.
"""

import os
import sys

import xbmcaddon
import xbmcvfs

addon = xbmcaddon.Addon()
root = os.path.normpath(xbmcvfs.translatePath(addon.getAddonInfo("path")))
if root not in sys.path:
    sys.path.insert(0, root)

import main  # noqa: E402

if __name__ == "__main__":
    main.run_context_item()
