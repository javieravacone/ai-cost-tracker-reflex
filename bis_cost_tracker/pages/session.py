"""Session detail (`/sesiones/[id]`), port of src/app/sesiones/[id]/page.tsx and its actions."""

from __future__ import annotations

import time
from typing import Any

import reflex as rx

from bis_cost_tracker.components.layout import shell
from bis_cost_tracker.components.rich import D, L, box, chevron, rich_cell, seg, segs
from bis_cost_tracker.components.transcript import scroll_into_view_script, transcript_section
from bis_cost_tracker.components.ui import card, confidence_help, kpi, loading, not_found, notice, page_header, th
from bis_cost_tracker.state import AppState
from bis_cost_tracker.views import session


@AppState.register
class SessionState(AppState):
    data: dict[str, Any] = session.empty()
    loaded: bool = False

    def _build(self) -> None:
        data = session.build(self._segment(1), self._query())
        # New key on every load: React remounts the transcript and the turns table, so <details>
        # opened before a client-side navigation (e.g. after saving) start closed like a fresh page.
        data["nonce"] = str(time.time_ns())
        self.data = data
        self.loaded = True

    @rx.event
    def load(self):
        self._shell("SessionState")
        self._build()
        target = self.data.get("scroll_to") or ""
        if target:
            return rx.call_script(scroll_into_view_script(target))
        return None

    @rx.event
    def save_assignment(self, form: dict[str, Any]):
        return rx.redirect(session.save_assignment(form))

    @rx.event
    def remove_assignment(self, form: dict[str, Any]):
        return rx.redirect(session.remove_assignment(form))


INPUT = (
    "mt-1.5 w-full rounded-[10px] bg-surface px-3 py-2 text-[13.5px] text-label shadow-[inset_0_0_0_1px_var(--separator-strong)] "
    "outline-none placeholder:text-label-3 focus:shadow-[inset_0_0_0_2px_var(--accent)]"
)
FIELD = "block text-[12px] font-medium text-label-3"
COLS = [("Time (UTC)", False, ""), ("Repo and branch", False, ""), ("Model", False, ""), ("AI credits", True, ""), ("Attribution", False, ""), ("sr:Assign", True, "")]


def _hidden(r: Any) -> rx.Component:
    return rx.fragment(
        rx.el.input(type="hidden", name="turnId", value=r["id"].to(str)),
        rx.el.input(type="hidden", name="days", value=r["days"].to(str)),
    )


def _assign_form(r: Any) -> rx.Component:
    f = D(r["form"])
    return rx.el.td(
        rx.el.form(
            _hidden(r),
            rx.el.label(
                "Repo",
                rx.el.input(name="repo", required=True, default_value=f["repo"].to(str), placeholder="owner/name", class_name=f"{INPUT} font-mono text-[12px]"),
                class_name=f"{FIELD} w-60",
            ),
            rx.el.label(
                "Issue #",
                rx.el.input(name="issue", input_mode="numeric", default_value=f["issue"].to(str), placeholder="123", class_name=INPUT),
                class_name=f"{FIELD} w-24",
            ),
            rx.el.label(
                "PR #",
                rx.el.input(name="pr", input_mode="numeric", default_value=f["pr"].to(str), placeholder="45", class_name=INPUT),
                class_name=f"{FIELD} w-24",
            ),
            rx.el.label(
                "Note",
                rx.el.input(name="note", max_length=500, default_value=f["note"].to(str), placeholder="Optional", class_name=INPUT),
                class_name=f"{FIELD} min-w-[12rem] flex-1",
            ),
            rx.el.button(
                "Save assignment",
                type="submit",
                class_name="press rounded-[10px] bg-accent px-5 py-2 text-[13.5px] font-medium text-white shadow-control hover:bg-accent-hover",
            ),
            key=r["form_key"].to(str),
            on_submit=SessionState.save_assignment,
            reset_on_submit=False,
            class_name="flex flex-wrap items-end gap-4 rounded-[16px] bg-surface p-5 shadow-card",
        ),
        rx.cond(
            r["manual"],
            rx.el.form(
                _hidden(r),
                rx.el.button(
                    "Remove manual assignment",
                    type="submit",
                    class_name="press rounded-full px-3 py-1.5 text-[13px] font-medium text-bad-text hover:bg-bad/10",
                ),
                on_submit=SessionState.remove_assignment,
                reset_on_submit=False,
                class_name="mt-3",
            ),
        ),
        col_span=6,
        class_name="bg-accent/6 px-6! pt-1 pb-6",
    )


def _turn_rows(r: rx.Var) -> rx.Component:
    r = D(r)
    return rx.fragment(
        rx.el.tr(
            rx.foreach(L(r["cells"]), lambda c: rich_cell(b=c)),
            rx.el.td(
                rx.el.details(
                    rx.el.summary(
                        chevron("size-2.5"),
                        rx.cond(r["manual"], "Edit", "Assign"),
                        aria_controls=r["form_id"].to(str),
                        class_name="press inline-flex cursor-pointer select-none items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] font-medium text-link hover:bg-accent/10",
                    ),
                    open=r["open"].to(bool),
                ),
                rx.cond(r["manual"], rx.el.div("assigned by hand", class_name="mt-1 px-3 text-[12px] text-label-3")),
                class_name="px-3 py-3.5 align-top whitespace-nowrap text-right tabular-nums",
            ),
            id=r["rid"].to(str),
            class_name=r["c"].to(str),
        ),
        # Shown (CSS :has) while the row's <details> is open.
        rx.el.tr(_assign_form(r), id=r["form_id"].to(str), class_name="row-detail"),
    )


def _turns_table(d: Any) -> rx.Component:
    return card(
        rx.el.div(
            rx.el.table(
                rx.el.thead(rx.el.tr(*[th(label, right, c) for label, right, c in COLS])),
                rx.el.tbody(rx.foreach(L(d["rows"]), _turn_rows), key=d["nonce"].to(str)),
                class_name="dtable",
            ),
            class_name="scroll-area overflow-auto max-h-[min(76vh,56rem)]",
        ),
        rx.el.p(
            "If you only enter a PR, the issue is taken from its single linked issue (if synced). With no issue or PR, the turn "
            "is assigned only to the repo’s project.",
            class_name="px-6 py-5 text-[12.5px] text-label-3",
        ),
        title="Turns",
        subtitle="Manual assignment takes precedence over the automatic cascade.",
        flush=True,
    )


def _hero(d: Any) -> rx.Component:
    return card(
        rx.el.div(
            rx.foreach(L(d["kpis"]), lambda k: kpi(k["label"], segs(k["value"]), k["hint"])),
            class_name="stagger grid grid-cols-2 gap-x-10 gap-y-8 lg:grid-cols-4",
        ),
        rx.el.div(
            rx.el.span("Confidence", class_name="font-medium text-label-2"),
            seg(d["mix"]),
            rx.el.span(d["with_counts"], class_name="tabular-nums"),
            class_name="mt-8 flex flex-wrap items-center gap-x-6 gap-y-3 text-[13px] text-label-2",
        ),
        hero=True,
    )


def _content(d: Any) -> rx.Component:
    return rx.cond(
        d["found"],
        rx.fragment(
            page_header(d["title"], box(d["subtitle"]), crumbs=d["crumbs"]),
            rx.cond(d["ok"] != "", notice("ok", d["ok"], d["ok_body"])),
            rx.cond(d["error"] != "", notice("error", "Couldn’t save", d["error"])),
            _hero(d),
            rx.cond(d["show_transcript"], rx.fragment(transcript_section(d["tx"], d["tx_title"], d["tx_note"]), key=d["nonce"].to(str))),
            _turns_table(d),
            confidence_help(),
        ),
        not_found(),
    )


def page() -> rx.Component:
    return shell("/sesiones", rx.cond(SessionState.loaded, _content(SessionState.data), loading()))
