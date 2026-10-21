"""Pure URL builders for external pages (GitHub, LangSmith). Port of src/lib/links.ts.

Every GitHub builder returns None for repos that are not real (the fictional seed org) or not
parseable, so the UI can render plain text instead of a link to a page that doesn't exist.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote_to_bytes, urlsplit

from bis_core._js import encode_uri_component
from bis_core.attribution.repo import normalize_repo

# Owners of the fictional seed data; their repos don't exist on GitHub.
FICTIONAL_OWNERS: frozenset[str] = frozenset({"acme-labs"})

GITHUB = "https://github.com"
DEFAULT_LANGSMITH_ENDPOINT = "https://api.smith.langchain.com"


def linkable_repo(repo_or_url: str | None) -> str | None:
    """"owner/name" when the repo is a real GitHub repo; None for fictional or unparseable input."""
    repo = normalize_repo(repo_or_url)
    if not repo:
        return None
    owner = repo[: repo.index("/")]
    return None if owner in FICTIONAL_OWNERS else repo


def _encode_path(p: str) -> str:
    """Encodes each path segment, keeping the slashes (branch names like "feat/20-x", paths)."""
    return "/".join(encode_uri_component(s) for s in p.split("/"))


def github_repo_url(repo: str | None) -> str | None:
    r = linkable_repo(repo)
    return f"{GITHUB}/{r}" if r else None


def issue_url(repo: str | None, n: int | None) -> str | None:
    base = github_repo_url(repo)
    return f"{base}/issues/{n}" if base and n and n > 0 else None


def pr_url(repo: str | None, n: int | None) -> str | None:
    base = github_repo_url(repo)
    return f"{base}/pull/{n}" if base and n and n > 0 else None


def branch_url(repo: str | None, branch: str | None) -> str | None:
    base = github_repo_url(repo)
    return f"{base}/tree/{_encode_path(branch)}" if base and branch else None


_SHA_RE = re.compile(r"[0-9a-f]{7,40}", re.IGNORECASE)


def commit_url(repo: str | None, sha: str | None) -> str | None:
    base = github_repo_url(repo)
    return f"{base}/commit/{sha.lower()}" if base and sha and _SHA_RE.fullmatch(sha) else None


def compare_url(repo: str | None, base: str, head: str) -> str | None:
    root = github_repo_url(repo)
    return f"{root}/compare/{_encode_path(base)}...{_encode_path(head)}" if root and base and head else None


def _line(lines: Any, name: str) -> Any:
    if lines is None:
        return None
    if isinstance(lines, Mapping):
        return lines.get(name)
    return getattr(lines, name, None)


def blob_url(repo: str | None, ref: str | None, path: str | None, lines: Mapping[str, Any] | Any = None) -> str | None:
    """File at a ref ("HEAD" = default branch). `path` is relative to the repo root.
    `lines` is an optional {"start": n, "end": m} mapping (or object with start/end)."""
    root = github_repo_url(repo)
    if not root or not ref or not path:
        return None
    clean = re.sub(r"^/+", "", path)
    if not clean or any(s in ("..", ".") for s in clean.split("/")):
        return None
    ls, le = _line(lines, "start"), _line(lines, "end")
    start = ls if ls and ls > 0 else None
    end = le if le and start and le > start else None
    anchor = f"#L{start}" + (f"-L{end}" if end else "") if start else ""
    return f"{root}/blob/{_encode_path(ref)}/{_encode_path(clean)}{anchor}"


def _decode_uri_component(s: str) -> str | None:
    """Strict `decodeURIComponent`: None where JS would throw."""
    if re.search(r"%(?![0-9a-fA-F]{2})", s):
        return None
    try:
        return unquote_to_bytes(s).decode("utf-8")
    except UnicodeDecodeError:
        return None


def _remove_dot_segments(path: str) -> str:
    out: list[str] = []
    segs = path.split("/")
    for i, seg in enumerate(segs):
        last = i == len(segs) - 1
        if seg == ".":
            if last:
                out.append("")
            continue
        if seg == "..":
            if len(out) > 1:
                out.pop()
            if last:
                out.append("")
            continue
        out.append(seg)
    return "/".join(out)


def repo_relative_path(repo: str | None, local_path: str | None) -> str | None:
    """Path relative to the repo root for a local path seen by the agent: everything after the
    first folder named like the repo ("/home/me/code/ai-cost-tracker/src/x.ts" -> "src/x.ts").
    Accepts Windows separators and file:// URIs. Already-relative paths are kept. Returns None
    when the path is outside the repo folder."""
    r = normalize_repo(repo)
    if not r or not local_path:
        return None
    p = local_path.strip().replace("\\", "/")
    if re.match(r"file://", p, re.IGNORECASE):
        try:
            pathname = _remove_dot_segments(urlsplit(p).path or "/")
        except ValueError:
            return None
        decoded = _decode_uri_component(pathname)
        if decoded is None:
            return None
        p = decoded
    absolute = p.startswith("/") or bool(re.match(r"[a-z]:/", p, re.IGNORECASE)) or p.startswith("~")
    segs = [s for s in p.split("/") if s]
    if absolute:
        name = r[r.index("/") + 1 :]
        at = next((i for i, s in enumerate(segs) if s.lower() == name), -1)
        if at < 0:
            return None
        rest = segs[at + 1 :]
    else:
        rest = segs[1:] if segs and segs[0] == "." else segs
    if not rest or any(s == ".." for s in rest):
        return None
    return "/".join(rest)


def file_url(repo: str | None, ref: str | None, local_path: str | None, lines: Mapping[str, Any] | Any = None) -> str | None:
    """GitHub blob link for a local file path at a commit, or None when it can't be resolved."""
    return blob_url(repo, ref, repo_relative_path(repo, local_path), lines)


_ISSUE_KEY_RE = re.compile(r"(.+)#([0-9]+)")
_PR_KEY_RE = re.compile(r"(.+)!([0-9]+)")


def issue_key_url(key: str | None) -> str | None:
    """"owner/name#12" -> GitHub issue."""
    m = _ISSUE_KEY_RE.fullmatch(key) if key else None
    return issue_url(m.group(1), int(m.group(2))) if m else None


def pr_key_url(key: str | None) -> str | None:
    """"owner/name!45" -> GitHub PR."""
    m = _PR_KEY_RE.fullmatch(key) if key else None
    return pr_url(m.group(1), int(m.group(2))) if m else None


_GH_USER_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,38})", re.IGNORECASE)


def github_profile_url(user_name: str | None) -> str | None:
    u = user_name.strip() if user_name else user_name
    return f"{GITHUB}/{u}" if u and _GH_USER_RE.fullmatch(u) else None


# --- LangSmith -------------------------------------------------------------------------------

_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443, "ftp": 21}
_LS_API_HOST = re.compile(r"(^|\.)api\.smith\.langchain\.com\Z")


def langsmith_host(endpoint: str | None) -> str | None:
    """LangSmith UI origin for an API endpoint: api.smith... -> smith..., eu.api.smith... -> eu.smith..."""
    raw = (endpoint.strip() if endpoint else "") or DEFAULT_LANGSMITH_ENDPOINT
    try:
        u = urlsplit(raw)
        scheme = u.scheme.lower()
        host = u.hostname
        port = u.port
    except ValueError:
        return None
    if not scheme or not re.fullmatch(r"[a-z][a-z0-9+.-]*", scheme):
        return None
    if scheme in _DEFAULT_PORTS and not host:
        return None
    host = host or ""
    if _LS_API_HOST.search(host):
        return f"{scheme}://{re.sub(r'(^|\.)api\.', r'\1', host, count=1)}"
    # Self-hosted: the API is served under /api on the UI host.
    if scheme not in _DEFAULT_PORTS:
        return "null"
    port_part = f":{port}" if port is not None and port != _DEFAULT_PORTS[scheme] else ""
    return f"{scheme}://{host}{port_part}"


@dataclass
class LangsmithRef:
    tenant_id: str | None
    project_id: str | None
    # API endpoint (LANGSMITH_ENDPOINT); the UI host is derived from it.
    endpoint: str | None = None


def langsmith_project_url(ref: LangsmithRef) -> str | None:
    origin = langsmith_host(ref.endpoint)
    if not origin or not ref.tenant_id or not ref.project_id:
        return None
    return f"{origin}/o/{encode_uri_component(ref.tenant_id)}/projects/p/{encode_uri_component(ref.project_id)}"


def langsmith_trace_url(ref: LangsmithRef, run_id: str, trace_id: str | None) -> str | None:
    """Deep link to a run inside its trace in the LangSmith UI; None when ids are unknown."""
    project = langsmith_project_url(ref)
    if not project or not run_id:
        return None
    e = encode_uri_component
    return f"{project}/r/{e(run_id)}?trace_id={e(trace_id or run_id)}"
