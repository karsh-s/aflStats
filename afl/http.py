"""A small cached, rate-limited HTTP layer shared by every data source.

Caching matters here for three reasons: the public APIs ask to be treated
gently, the free Odds-API tier has a hard monthly quota, and re-running the
pipeline during development shouldn't re-download the entire history each time.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

import requests

from . import config

# Some sources (afltables.com) publish an AAAA record, but CI runners such as
# GitHub Actions have no working IPv6 route — Python then picks the IPv6
# address and every request dies with "Network is unreachable". Forcing the
# resolver to IPv4 avoids that. Opt-in so local/dual-stack setups are
# untouched: CI=true is set by GitHub Actions.
if os.environ.get("AFL_FORCE_IPV4") == "1" or os.environ.get("CI") == "true":
    import socket
    import urllib3.util.connection as _u3conn
    _u3conn.allowed_gai_family = lambda: socket.AF_INET

_session = requests.Session()
_session.headers.update({"User-Agent": config.USER_AGENT})

# Minimum spacing between live (non-cached) requests to the same host.
_MIN_INTERVAL = 0.6
_last_request_ts: dict[str, float] = {}


def _cache_path(key: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return config.CACHE_DIR / f"{digest}.json"


def _throttle(host: str) -> None:
    now = time.time()
    last = _last_request_ts.get(host, 0.0)
    wait = _MIN_INTERVAL - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_request_ts[host] = time.time()


def get_json(
    url: str,
    params: Optional[dict] = None,
    *,
    ttl: Optional[int] = None,
    force: bool = False,
) -> Any:
    """GET ``url`` and parse JSON, transparently caching to disk."""
    ttl = config.CACHE_TTL_SECONDS if ttl is None else ttl
    key = url + "?" + json.dumps(params or {}, sort_keys=True)
    path = _cache_path(key)

    if not force and path.exists() and (time.time() - path.stat().st_mtime) < ttl:
        return json.loads(path.read_text())

    host = requests.utils.urlparse(url).netloc
    _throttle(host)
    resp = _session.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    path.write_text(json.dumps(data))
    return data


def get_text(
    url: str,
    params: Optional[dict] = None,
    *,
    ttl: Optional[int] = None,
    force: bool = False,
) -> str:
    """GET ``url`` and return the raw text body (used for HTML scraping)."""
    ttl = config.CACHE_TTL_SECONDS if ttl is None else ttl
    key = "TEXT:" + url + "?" + json.dumps(params or {}, sort_keys=True)
    path = _cache_path(key)

    if not force and path.exists() and (time.time() - path.stat().st_mtime) < ttl:
        return path.read_text()

    host = requests.utils.urlparse(url).netloc
    _throttle(host)
    resp = _session.get(url, params=params, timeout=30)
    resp.raise_for_status()
    path.write_text(resp.text)
    return resp.text
