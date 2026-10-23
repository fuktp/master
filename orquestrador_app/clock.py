from __future__ import annotations

import datetime as dt

import tzlocal


def local_now() -> dt.datetime:
    # Reload the Windows registry/system zone to observe changes while the monitor is running.
    return dt.datetime.now(tzlocal.reload_localzone())
