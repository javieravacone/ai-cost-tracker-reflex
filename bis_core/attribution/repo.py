"""Repository URL normalization: any GitHub-ish remote -> "owner/name" (lowercase).

Port of src/lib/attribution/repo.ts.
"""

from __future__ import annotations

import re

_OWNER_RE = re.compile(r"[a-z0-9](?:[a-z0-9_-]*[a-z0-9_])?")
_NAME_RE = re.compile(r"[a-z0-9._-]+")
_URL_RE = re.compile(r"^[a-z][a-z0-9+.-]*://(?:[^@/]+@)?[^/]+/(.*)\Z", re.IGNORECASE | re.DOTALL)
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_SCP_RE = re.compile(r"^[^@/\s:]+@[^/\s:]+:(.*)\Z", re.DOTALL)
_WS_RE = re.compile(r"\s")


def _extract_path(value: str) -> str | None:
    """Strips "scheme://[user@]host[:port]" or "user@host:" (scp-like) and returns the path."""
    url = _URL_RE.match(value)
    if url:
        return url.group(1)
    if _SCHEME_RE.match(value):
        return None  # scheme with no path
    scp = _SCP_RE.match(value)
    if scp:
        return scp.group(1)
    segs = [s for s in value.split("/") if s]
    if len(segs) >= 3 and "." in segs[0]:
        return "/".join(segs[1:])
    return value


def normalize_repo(url: str | None) -> str | None:
    """Normalizes a repository reference to "owner/name" in lowercase.

    Accepts https/http/ssh/git URLs (with optional user@ and :port), scp-like
    `git@host:owner/name.git`, GitHub Enterprise hosts (host is dropped), host-without-scheme
    and already-normalized "owner/name". Extra path segments after owner/name are ignored.
    Returns None for anything that does not yield a plausible owner and name.
    """
    if url is None:
        return None
    value = url.strip()
    if not value or _WS_RE.search(value):
        return None
    path = _extract_path(value)
    if path is None:
        return None
    segs = [s for s in re.sub(r"[?#].*\Z", "", path, count=1, flags=re.DOTALL).split("/") if s]
    if len(segs) < 2:
        return None
    owner = segs[0].lower()
    name = re.sub(r"\.git\Z", "", segs[1].lower(), count=1)
    if not _OWNER_RE.fullmatch(owner):
        return None
    if not _NAME_RE.fullmatch(name) or name in (".", ".."):
        return None
    return f"{owner}/{name}"
