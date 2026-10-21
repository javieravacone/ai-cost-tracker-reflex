"""Session detail (`/sesiones/[id]`), port of src/app/sesiones/[id]/page.tsx, its server actions
(actions.ts) and the transcript components (src/components/transcript.tsx, markdown.tsx).

Everything here is plain data; captured text is passed through as strings and rendered by
React as text nodes (never as HTML), like the Next app.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from bis_core._js import encode_uri_component, js_round, parse_iso_ms, to_fixed
from bis_core.app_data import href_with, langsmith_ref, param, person_href, safe_decode, team_href
from bis_core.attribution import normalize_repo
from bis_core.content_types import args_file_ref, has_captured_content, summarize_args
from bis_core.cost import NANO_PER_CREDIT
from bis_core.db import delete_manual_assignment, get_db, get_turn, list_turns_by_conversation, set_manual_assignment
from bis_core.db.content import get_turn_contents, get_turn_events
from bis_core.links import branch_url, commit_url, file_url, github_repo_url, issue_key_url, langsmith_trace_url, pr_key_url
from bis_core.markdown import parse_markdown
from bis_core.report import DEFAULT_DAYS, conversation_key_of, load_conversation, parse_days, parse_issue_key, parse_pr_key, summarize
from bis_core.report.format import (
    format_credits,
    format_date,
    format_date_time,
    format_int,
    format_number,
    format_pct,
    format_time,
    format_tokens,
    format_usd,
    plural,
)
from bis_core.types import ManualAssignment

from bis_cost_tracker.views import kit
from bis_cost_tracker.views.kit import LINK, MONO, box, chip, ext, group, link, muted, real_chip, td, txt

ERRORS = {
    "turn": "The turn doesn’t exist.",
    "repo": "Invalid repo: use “owner/name” or a GitHub URL.",
    "issue": "Invalid issue number (positive integer).",
    "pr": "Invalid PR number (positive integer).",
    "note": "The note is too long (max. 500 characters).",
}
MAX_NOTE = 500
TRUNCATED_TITLE = "Shortened for local storage; the full text is in LangSmith"


# --- small helpers of transcript.tsx ------------------------------------------------------------


def format_duration(ms: float | None) -> str | None:
    if ms is None:
        return None
    if ms < 1000:
        return f"{max(0, js_round(ms))} ms"
    s = ms / 1000
    if s < 60:
        return f"{to_fixed(s, 1)} s" if s < 10 else f"{js_round(s)} s"
    return f"{int(s // 60)} min {js_round(s % 60)} s"


def prompt_preview(prompt: str | None, n: int = 100) -> str | None:
    s = re.sub(r"\s+", " ", prompt or "").strip()
    if not s:
        return None
    return f"{s[: n - 1].rstrip()}…" if len(s) > n else s


def count_by(names: Sequence[str]) -> str:
    counts: dict[str, int] = {}
    for n in names:
        counts[n] = counts.get(n, 0) + 1
    return ", ".join(f"{n} ×{c}" if c > 1 else n for n, c in counts.items())


def steps_hint(events: Sequence[Any]) -> str:
    tools = sum(1 for e in events if e.kind == "tool")
    llm = len(events) - tools
    first = next((e.started_at for e in events if e.started_at), None)
    last_end: float | None = None
    for e in events:
        if not e.started_at or e.duration_ms is None:
            continue
        start = parse_iso_ms(e.started_at)
        if start is None:
            continue
        end = start + e.duration_ms
        if last_end is None or end > last_end:
            last_end = end
    first_ms = parse_iso_ms(first) if first else None
    span = format_duration(last_end - first_ms) if first_ms is not None and last_end is not None else None
    return " · ".join(x for x in [plural(tools, "tool call", "tool calls"), plural(llm, "model call", "model calls"), span] if x)


def transcript_summary(turns: Sequence[dict[str, Any]]) -> str:
    steps = sum(len(t["events"]) for t in turns)
    known = [t for t in turns if t["row"].cost.ai_credits is not None]
    credits = sum(t["row"].cost.ai_credits or 0 for t in known)
    parts = [plural(len(turns), "turn", "turns"), plural(steps, "agent step", "agent steps")]
    if known:
        parts.append(f"{'≥ ' if len(known) < len(turns) else ''}{format_credits(credits)} credits")
    return " · ".join(parts)


# --- markdown -> flat inline leaves ------------------------------------------------------------

CODE_INLINE = "rounded-[5px] bg-fill px-1 py-px font-mono text-[0.86em] text-label"
MD_LINK = "text-link underline-offset-2 hover:underline"
MD_DEAD_LINK = "font-medium text-label underline decoration-separator-strong decoration-dotted underline-offset-2"


def md_leaves(nodes: Sequence[Mapping[str, Any]], cls: str = "", href: str | None = None, title: str = "") -> list[dict[str, Any]]:
    """Inline AST -> flat list of styled text leaves ({"k": "text"|"link", "v", "c", "h", "ti"}).
    Nesting (bold inside a link...) only changes classes, so flattening keeps the look."""
    out: list[dict[str, Any]] = []
    for n in nodes:
        t = n["t"]
        if t in ("text", "code"):
            c = f"{cls} {CODE_INLINE}".strip() if t == "code" else cls
            leaf = {"k": "link" if href else "text", "v": n["v"], "c": c, "h": href or "", "ti": title}
            out.append(leaf)
        elif t == "strong":
            out += md_leaves(n["c"], f"{cls} font-semibold text-label".strip(), href, title)
        elif t == "em":
            out += md_leaves(n["c"], f"{cls} italic".strip(), href, title)
        elif t == "link":
            if n.get("href"):
                out += md_leaves(n["c"], f"{MD_LINK} {cls}".strip(), n["href"], title)
            else:
                out += md_leaves(n["c"], f"{MD_DEAD_LINK} {cls}".strip(), None, n.get("target", ""))
    return out


def md_blocks(source: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for b in parse_markdown(source):
        t = b["t"]
        if t in ("p", "quote"):
            out.append({"t": t, "c": md_leaves(b["c"])})
        elif t == "h":
            out.append({"t": "h", "c": md_leaves(b["c"]), "cls": "font-semibold text-label " + ("text-[15px]" if b["level"] <= 2 else "text-[14px]")})
        elif t == "code":
            out.append({"t": "code", "v": b["v"]})
        elif t in ("ul", "ol"):
            out.append({"t": t, "start": b.get("start", 1), "items": [{"c": md_leaves(it)} for it in b["items"]]})
        elif t == "hr":
            out.append({"t": "hr"})
        elif t == "table":
            out.append(
                {
                    "t": "table",
                    "head": [{"c": md_leaves(c)} for c in b["head"]],
                    "rows": [{"cells": [{"c": md_leaves(c)} for c in r]} for r in b["rows"]],
                }
            )
    return out


# --- transcript ------------------------------------------------------------------------------


def _step(e: Any, answer: str | None, repo: str | None, sha: str | None) -> dict[str, Any]:
    dur = format_duration(e.duration_ms) or ""
    if e.kind == "llm":
        stats = (
            f"{format_tokens(e.tokens_in)} → {format_tokens(e.tokens_out or 0)} tokens" if e.tokens_in is not None else "no token data"
        )
        if e.nano_aiu is not None:
            stats += f" · {format_credits(e.nano_aiu / NANO_PER_CREDIT)} credits"
        if dur:
            stats += f" · {dur}"
        mode = "final" if e.text and answer and e.text.strip() == answer.strip() else ("text" if e.text else "")
        return {
            "kind": "llm",
            "model": re.sub(r"^chat\s+", "", e.name),
            "stats": stats,
            "mode": mode,
            "text": e.text or "",
            "calls": count_by(e.tool_calls),
            "error": e.error or "",
        }
    summary = summarize_args(e.args) or ""
    f = args_file_ref(e.args)
    href = file_url(repo, sha, f.path, f) if f else None
    return {
        "kind": "tool",
        "name": e.name,
        "summary": summary,
        "file": [ext(None, href, f"Open the file on GitHub at {(sha or '')[:7]}", "text-[12px]")] if href else [],
        "dur": dur,
        "error": e.error or "",
        "has_args": bool(e.args),
        "args": e.args or "",
        "args_trunc": bool(e.args_truncated),
        "result": e.result or "",
        "result_trunc": bool(e.result_truncated),
    }


def load_transcript(db: Any, rows: Sequence[Any]) -> list[dict[str, Any]]:
    ids = [r.turn.id for r in rows]
    contents = get_turn_contents(db, ids)
    events = get_turn_events(db, ids)
    ls = langsmith_ref(db)
    return [
        {
            "row": r,
            "content": contents.get(r.turn.id),
            "events": events.get(r.turn.id, []),
            "trace_url": langsmith_trace_url(ls, r.turn.id, r.turn.trace_id) if r.turn.source == "langsmith" else None,
        }
        for r in rows
    ]


def transcript_view(turns: list[dict[str, Any]], focus_turn: str | None) -> dict[str, Any]:
    focus = focus_turn if focus_turn and any(t["row"].turn.id == focus_turn for t in turns) else None
    out = []
    for i, t in enumerate(turns):
        r, c, events = t["row"], t["content"], t["events"]
        prompt = c.user_prompt if c else None
        answer = c.final_answer if c else None
        captured = has_captured_content(c)
        preview = prompt_preview(prompt)
        out.append(
            {
                "id": r.turn.id,
                "open": len(turns) == 1 or r.turn.id == focus,
                "focused": r.turn.id == focus,
                "label": f"Turn {format_int(i + 1)}",
                "time": f"{format_time(r.turn.started_at)} UTC",
                "model": r.turn.model or "",
                "credits": [kit.credits_inline(kit.turn_credit_figures(r.cost, r.turn.copilot_usage_coverage))],
                "captured": captured,
                "preview": f"“{preview}”" if preview else "",
                "preview_title": preview or "",
                "skills": [
                    {"name": s.name, "version": f"· v{s.version}" if s.version else "", "href": f"/skills?skill={encode_uri_component(s.name)}"}
                    for s in (c.skills if c else [])
                ],
                "trace": [ext("Open in LangSmith", t["trace_url"], "Open this turn’s trace in LangSmith", "font-medium")],
                "error": (c.error if c else None) or "",
                "prompt": prompt or "",
                "prompt_trunc": bool(c and c.user_prompt_truncated),
                "has_answer": bool(answer),
                "answer": md_blocks(answer) if answer else [],
                "answer_trunc": bool(c and c.final_answer_truncated),
                "has_steps": bool(events),
                "steps_hint": steps_hint(events),
                "steps": [_step(e, answer, r.attribution.repo, r.turn.commit_sha) for e in events],
            }
        )
    return {"turns": out, "summary": transcript_summary(turns), "open": len(turns) <= 1 or focus is not None, "multi": len(turns) > 1, "focus": focus or ""}


# --- page ----------------------------------------------------------------------------------------


def empty() -> dict[str, Any]:
    return {
        "found": False,
        "crumbs": [],
        "title": "",
        "subtitle": {"s": [], "b": []},
        "ok": "",
        "ok_body": "",
        "error": "",
        "kpis": [],
        "mix": kit.confidence_mix({}),
        "with_counts": "",
        "show_transcript": False,
        "tx_title": "",
        "tx_note": "",
        "tx": {"turns": [], "summary": "", "open": False, "multi": False, "focus": ""},
        "rows": [],
        "scroll_to": "",
        "nonce": "",
    }


def _uniq(xs: Sequence[str | None]) -> list[str]:
    return list(dict.fromkeys(x for x in xs if x))


def _subtitle(rows: Sequence[Any], key: str, is_real: bool) -> dict[str, Any]:
    first = rows[0]
    segs = [
        real_chip() if is_real else chip("Sample", ti="Turns generated by the seed (fictional names)"),
        txt(first.team_name) if first.team_name else None,
        txt("·", "text-label-3"),
        txt(f"{format_date_time(rows[0].turn.started_at)} – {format_date_time(rows[-1].turn.started_at)} UTC"),
    ]
    repos = _uniq([r.attribution.repo for r in rows])
    boxes = []
    if repos:
        line = []
        for repo in repos:
            branches = _uniq([r.turn.branch for r in rows if r.attribution.repo == repo])
            line.append(
                group(
                    [ext(repo, github_repo_url(repo), "Repository on GitHub", MONO)]
                    + [ext(b, branch_url(repo, b), "Branch on GitHub", f"{MONO} text-label-2") for b in branches],
                    "inline-flex flex-wrap items-center gap-x-2 gap-y-1",
                )
            )
        for k in _uniq([r.attribution.issue_key for r in rows]):
            line.append(ext(f"#{(parse_issue_key(k) or {}).get('number', k)}", issue_key_url(k), f"Issue {k} on GitHub", MONO))
        for k in _uniq([r.attribution.pr_key for r in rows]):
            line.append(ext(f"!{(parse_pr_key(k) or {}).get('number', k)}", pr_key_url(k), f"Pull request {k} on GitHub", MONO))
        boxes.append(box("flex w-full flex-wrap items-center gap-x-3 gap-y-1 text-[13.5px]", line))
    boxes.append(box(f"w-full truncate text-label-3 {MONO}", [txt(key)], ti=key))
    return box("flex flex-wrap items-center gap-x-2 gap-y-1", segs, boxes)


def _turn_row(r: Any, manual: ManualAssignment | None, days: int, unpriced: bool, trace: str | None, focus: str | None, error: str | None) -> dict[str, Any]:
    a, t = r.attribution, r.turn
    when = td([txt(format_date(t.started_at))], top=True, c="whitespace-nowrap tabular-nums", b=[box("text-[12.5px] text-label-3", [txt(format_time(t.started_at))])])
    if t.source == "langsmith":
        when["b"].append(box("mt-1", [real_chip()]))
    if trace:
        when["b"].append(box("mt-1 text-[12.5px]", [ext("LangSmith", trace, "Open this turn’s trace in LangSmith")]))

    where = [
        box(f"truncate {MONO}", [ext(a.repo, github_repo_url(a.repo), "Repository on GitHub") if a.repo else muted("no repo")], ti=t.repo_url or ""),
        box(
            f"mt-0.5 truncate text-label-3 {MONO}",
            [ext(t.branch, branch_url(a.repo, t.branch), "Branch on GitHub") if t.branch else txt("—")],
            ti=t.branch or "",
        ),
    ]
    if t.commit_sha:
        where.append(box(f"mt-0.5 truncate text-label-3 {MONO}", [txt("@ "), ext(t.commit_sha[:7], commit_url(a.repo, t.commit_sha), "Commit on GitHub")], ti=t.commit_sha))
    if r.project_name:
        where.append(box("mt-0.5 text-[12.5px] text-label-2", [txt(r.project_name)]))

    tok_title = f"{format_int(t.input_tokens)} input (incl. cache) · {format_int(t.output_tokens)} output" + (
        f" · cache {format_int(t.cache_read_tokens)}" if t.cache_read_tokens > 0 else ""
    )
    model = td(
        None,
        top=True,
        b=[
            box(f"whitespace-nowrap {MONO}", [txt(t.model) if t.model else muted("—")]),
            box("mt-0.5 whitespace-nowrap text-[12.5px] tabular-nums text-label-3", [txt(f"{format_tokens(t.input_tokens)} → {format_tokens(t.output_tokens)}")], ti=tok_title),
        ],
    )

    cov = t.copilot_usage_coverage
    cost_title = f"Subscription charged {format_usd(r.cost.subscription_usd)} · {format_number(r.cost.premium_requests)} premium requests (legacy)" + (
        f" · credits reported for {format_pct(cov)} of calls" if t.copilot_nano_aiu is not None and cov is not None and cov < 1 else ""
    )
    cost = td(
        [kit.credits_compact(kit.turn_credit_figures(r.cost, cov))],
        top=True,
        right=True,
        b=[
            box(
                "mt-1 text-[12.5px] text-label-3",
                [txt("API "), kit.api_cost(r.cost.api_equivalent_usd, 1, 1 if unpriced else 0), txt(f" · sub. {format_usd(r.cost.subscription_usd)}")],
                ti=cost_title,
            )
        ],
    )

    issue = parse_issue_key(a.issue_key) if a.issue_key else None
    pr = parse_pr_key(a.pr_key) if a.pr_key else None
    chips = [kit.confidence_badge(a.confidence)]
    if issue:
        chips.append(
            group(
                [
                    link(f"#{issue['number']}", href_with("/sesiones", {"days": days, "issue": a.issue_key}), f"{LINK} {MONO}"),
                    ext(None, issue_key_url(a.issue_key), f"Issue #{issue['number']} on GitHub", "text-[12px]"),
                ],
                "inline-flex items-baseline",
            )
        )
    if pr:
        chips.append(
            group(
                [
                    link(f"!{pr['number']}", href_with("/sesiones", {"days": days, "pr": a.pr_key}), f"{LINK} {MONO}"),
                    ext(None, pr_key_url(a.pr_key), f"Pull request #{pr['number']} on GitHub", "text-[12px]"),
                ],
                "inline-flex items-baseline",
            )
        )
    attribution = td(
        None,
        top=True,
        c="min-w-[13rem]",
        b=[box("flex flex-wrap items-center gap-x-2 gap-y-1", chips), box("mt-1.5 text-[12.5px] leading-snug text-label-3", [txt(a.reason)])],
    )

    form = {
        "repo": (manual.repo if manual else a.repo) or "",
        "issue": "" if not manual or manual.issue_number is None else str(manual.issue_number),
        "pr": "" if not manual or manual.pr_number is None else str(manual.pr_number),
        "note": (manual.note if manual else None) or "",
    }
    return {
        "id": t.id,
        "rid": f"turn-{t.id}",
        "form_id": f"assign-{t.id}",
        "c": "trow trow-turn bg-accent/8" if focus == t.id else "trow trow-turn",
        "cells": [when, td(None, top=True, c="max-w-[14rem]", b=where), model, cost, attribution],
        "manual": manual is not None,
        "open": focus == t.id and bool(error),
        "days": "" if days == DEFAULT_DAYS else str(days),
        "form": form,
        "form_key": "|".join([t.id, *form.values()]),
    }


def build(key_raw: str, sp_: Mapping[str, Any]) -> dict[str, Any]:
    key = safe_decode(key_raw)
    db = get_db()
    turns = list_turns_by_conversation(db, key)
    if not turns:
        single = get_turn(db, key)
        if single is not None and single.conversation_id is None:
            turns = [single]
    report = load_conversation(db, key, turns)
    out = empty()
    if report is None or not report.rows:
        return out
    out["found"] = True

    days = parse_days(param(sp_, "days"))
    rows = report.rows
    m = summarize(rows)
    first = rows[0]
    manual_by_turn = {x.turn_id: x for x in report.refs.manual_assignments}
    unpriced = {u.model for u in report.unpriced_models}
    unpriced_turns = sum(1 for r in rows if r.turn.model in unpriced)
    is_real = any(r.turn.source == "langsmith" for r in rows)
    ok, error, focus = param(sp_, "ok"), param(sp_, "error"), param(sp_, "turn")
    who = first.user_display_name or first.attribution.user_name or "Unknown person"
    transcript = load_transcript(db, rows)
    trace_by_turn = {t["row"].turn.id: t["trace_url"] for t in transcript}
    captured = sum(1 for t in transcript if has_captured_content(t["content"]))
    show = any(t["events"] or has_captured_content(t["content"]) for t in transcript)

    user_name = first.attribution.user_name
    member = next((x for x in report.refs.members if x.user_name.lower() == user_name.lower()), None) if user_name else None
    team_id = member.team_id if member else first.attribution.team_id
    team_name = (next((t.name for t in report.refs.teams if t.id == team_id), None) or first.team_name or team_id) if team_id else None
    if user_name:
        crumbs = [{"label": "Teams", "href": href_with("/equipos", {"days": days})}]
        if team_id:
            crumbs.append({"label": team_name or team_id, "href": team_href(team_id, days)})
        crumbs += [
            {"label": member.display_name if member else who, "href": person_href(member.user_name if member else user_name, days)},
            {"label": "Session", "href": ""},
        ]
    else:
        crumbs = [{"label": "Sessions", "href": href_with("/sesiones", {"days": days})}, {"label": "Session", "href": ""}]

    out["crumbs"] = crumbs
    out["title"] = f"Session by {who}"
    out["subtitle"] = _subtitle(rows, key, is_real)
    if ok:
        out["ok"] = "Manual assignment removed" if ok == "removed" else "Manual assignment saved"
        out["ok_body"] = f"Attribution was recalculated{' with “manual” confidence' if ok == 'saved' else ''}."
    if error:
        out["error"] = ERRORS.get(error, "Unknown error.")

    lower = m.credit_turns < m.turns or m.credit_partial_turns > 0
    out["kpis"] = [
        {
            "label": "Actual Copilot usage",
            "value": [kit.no_data_chip()] if m.credit_turns == 0 else [txt(f"{format_credits(m.ai_credits)} credits")],
            "hint": "no AI credit data" if m.credit_turns == 0 else f"{format_usd(m.ai_credits_usd)} gross{' · lower bound, some data missing' if lower else ''}",
        },
        {
            "label": "API equivalent",
            "value": [kit.api_cost(m.api_equivalent_usd, m.turns, unpriced_turns)],
            "hint": f"{plural(unpriced_turns, 'turn', 'turns')} with no price"
            if 0 < unpriced_turns < m.turns
            else f"{format_tokens(m.input_tokens)} input · {format_tokens(m.output_tokens)} output",
        },
        {"label": "Subscription charged", "value": [txt(format_usd(m.subscription_usd))], "hint": f"{format_number(m.premium_requests)} premium (legacy)"},
        {"label": "Turns", "value": [txt(format_int(m.turns))], "hint": f"{format_tokens(m.tokens)} tokens"},
    ]
    out["mix"] = kit.confidence_mix(m.confidence, "w-full max-w-md flex-1")
    out["with_counts"] = f"{format_int(m.with_issue)} with issue · {format_int(m.with_pr)} with PR"

    out["show_transcript"] = show
    out["tx_title"] = "Transcript" if captured > 0 else "Agent steps"
    out["tx_note"] = (
        f"{plural(captured, 'turn', 'turns')} with captured content · may include code and secrets, stored locally"
        if captured > 0
        else "Content capture was off for these turns: tool and model calls only"
    )
    out["tx"] = transcript_view(transcript, focus)
    # After saving a manual assignment `?turn=` points at the turns table, not the transcript.
    out["scroll_to"] = f"transcript-{out['tx']['focus']}" if out["tx"]["focus"] and not ok and not error else ""

    out["rows"] = [
        _turn_row(r, manual_by_turn.get(r.turn.id), days, r.turn.model in unpriced, trace_by_turn.get(r.turn.id), focus, error) for r in rows
    ]
    return out


# --- manual assignment (port of actions.ts) -------------------------------------------------------


def _str(form: Mapping[str, Any], name: str) -> str:
    v = form.get(name)
    return v.strip() if isinstance(v, str) else ""


def optional_number(raw: str) -> int | None | bool:
    """"" -> None; positive integer (optionally prefixed by # or !) -> int; anything else -> False (invalid)."""
    if raw == "":
        return None
    mt = re.fullmatch(r"[#!]?([0-9]{1,9})", raw)
    if not mt:
        return False
    n = int(mt.group(1))
    return n if n > 0 else False


def back_url(conversation_key: str, days: str, extra: Mapping[str, str]) -> str:
    qs = dict(extra)
    d = parse_days(days)
    if d != DEFAULT_DAYS:
        qs["days"] = str(d)
    return f"/sesiones/{encode_uri_component(conversation_key)}?{urlencode(qs)}"


def save_assignment(form: Mapping[str, Any], db: Any = None) -> str:
    """Validates and stores a manual assignment; returns the URL to go back to."""
    db = db if db is not None else get_db()
    turn_id, days = _str(form, "turnId"), _str(form, "days")
    turn = get_turn(db, turn_id) if turn_id else None
    if turn is None:
        return "/sesiones?error=turn"
    key = conversation_key_of(turn)

    def fail(code: str) -> str:
        return back_url(key, days, {"error": code, "turn": turn.id})

    repo = normalize_repo(_str(form, "repo"))
    if not repo:
        return fail("repo")
    issue = optional_number(_str(form, "issue"))
    if issue is False:
        return fail("issue")
    pr = optional_number(_str(form, "pr"))
    if pr is False:
        return fail("pr")
    note = _str(form, "note")
    if len(note) > MAX_NOTE:
        return fail("note")
    set_manual_assignment(db, ManualAssignment(turn_id=turn.id, repo=repo, issue_number=issue, pr_number=pr, note=note or None))  # type: ignore[arg-type]
    return back_url(key, days, {"ok": "saved", "turn": turn.id})


def remove_assignment(form: Mapping[str, Any], db: Any = None) -> str:
    db = db if db is not None else get_db()
    turn_id, days = _str(form, "turnId"), _str(form, "days")
    turn = get_turn(db, turn_id) if turn_id else None
    if turn is None:
        return "/sesiones?error=turn"
    delete_manual_assignment(db, turn.id)
    return back_url(conversation_key_of(turn), days, {"ok": "removed", "turn": turn.id})
