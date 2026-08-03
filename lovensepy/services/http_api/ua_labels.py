"""User-Agent → short device / browser labels for the host UI."""

from __future__ import annotations


def device_label(user_agent: str | None) -> str:
    ua = (user_agent or "").lower()
    if not ua:
        return "Unknown device"
    if "iphone" in ua:
        return "iPhone"
    if "ipad" in ua:
        return "iPad"
    if "android" in ua:
        return "Android"
    if "macintosh" in ua or "mac os" in ua:
        return "Mac"
    if "windows" in ua:
        return "Windows"
    if "cros" in ua:
        return "Chromebook"
    if "linux" in ua:
        return "Linux"
    return "Unknown device"


def browser_label(user_agent: str | None) -> str:
    ua_l = (user_agent or "").lower()
    if not ua_l:
        return "Unknown browser"
    # Order matters: Edg/Chrome/Safari share substrings.
    if "edg/" in ua_l or "edgios/" in ua_l:
        return "Edge"
    if "crios/" in ua_l or ("chrome/" in ua_l and "chromium" not in ua_l):
        return "Chrome"
    if "firefox/" in ua_l or "fxios/" in ua_l:
        return "Firefox"
    if "safari/" in ua_l and "chrome" not in ua_l and "crios" not in ua_l:
        return "Safari"
    return "Browser"
