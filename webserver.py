# -*- coding: utf-8 -*-
"""Kodi JSON-RPC and web server configuration / connectivity helpers."""

import base64
import json
import ssl
import threading

import xbmc
import xbmcgui

from common import (
    get_bool as _get_bool,
    get_int as _get_int,
    get_setting as _get_setting,
    localized as _localized,
)

SCHEME_AUTO = 0
SCHEME_HTTP = 1
SCHEME_HTTPS = 2

_resolved_http_scheme = None


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
