"""Session transcript (port of src/components/transcript.tsx, transcript-controls.tsx, markdown.tsx).

Data comes from views.session.transcript_view(); every captured string is rendered as a React
text node, so content can never inject HTML. Only "Expand all / Collapse all" and the scroll to
`?turn=` use client JS (rx.call_script, run in the browser).
"""

from __future__ import annotations

from typing import Any

import reflex as rx

from bis_cost_tracker.components.rich import D, Dict, L, chevron, segs, svg_attrs
from bis_cost_tracker.components.ui import MONO, notice, rlink
from bis_cost_tracker.views.kit import CHIP, CHIP_BASE
from bis_cost_tracker.views.session import TRUNCATED_TITLE


def chip(text: Any, tone: str = "neutral", title: str = "") -> rx.Component:
    return rx.el.span(text, class_name=f"{CHIP_BASE} {CHIP[tone]}", title=title)


def truncated_chip() -> rx.Component:
    return chip("truncated", "warn", TRUNCATED_TITLE)


# --- markdown ----------------------------------------------------------------------------------


def _leaf(x: rx.Var) -> rx.Component:
    x = D(x)
    return rx.cond(
        x["k"] == "link",
        rx.el.a(x["v"], href=x["h"].to(str), target="_blank", rel="noreferrer noopener", class_name=x["c"].to(str)),
        rx.el.span(x["v"], class_name=x["c"].to(str), title=x["ti"].to(str)),
    )


def _inl(v: Any) -> rx.Component:
    return rx.foreach(L(v), _leaf)


def _block(b: rx.Var) -> rx.Component:
    b = D(b)
    return rx.match(
        b["t"],
        ("p", rx.el.p(_inl(b["c"]))),
        ("h", rx.el.p(_inl(b["c"]), class_name=b["cls"].to(str))),
        (
            "code",
            rx.el.pre(
                rx.el.code(b["v"]),
                class_name="scroll-area max-h-80 overflow-auto rounded-[12px] bg-fill/70 px-4 py-3 font-mono text-[12px] leading-relaxed text-label",
            ),
        ),
        ("ul", rx.el.ul(rx.foreach(L(b["items"]), lambda it: rx.el.li(_inl(it["c"]))), class_name="list-disc space-y-1 pl-5 marker:text-label-3")),
        (
            "ol",
            rx.el.ol(
                rx.foreach(L(b["items"]), lambda it: rx.el.li(_inl(it["c"]))),
                start=b["start"].to(int),
                class_name="list-decimal space-y-1 pl-5 marker:text-label-3",
            ),
        ),
        ("quote", rx.el.blockquote(_inl(b["c"]), class_name="border-l-2 border-separator-strong pl-3 text-label-2")),
        ("hr", rx.el.hr(class_name="border-separator")),
        (
            "table",
            rx.el.div(
                rx.el.table(
                    rx.el.thead(
                        rx.el.tr(
                            rx.foreach(
                                L(b["head"]),
                                lambda c: rx.el.th(_inl(c["c"]), class_name="border-b border-separator px-2 py-1 text-left font-medium text-label-2"),
                            )
                        )
                    ),
                    rx.el.tbody(
                        rx.foreach(
                            L(b["rows"]),
                            lambda r: rx.el.tr(
                                rx.foreach(L(r["cells"]), lambda c: rx.el.td(_inl(c["c"]), class_name="border-b border-separator/60 px-2 py-1 align-top"))
                            ),
                        )
                    ),
                    class_name="text-[12.5px]",
                ),
                class_name="scroll-area overflow-auto",
            ),
        ),
        rx.fragment(),
    )


@rx.memo
def markdown(blocks: rx.Var[list[Dict]]) -> rx.Component:
    return rx.el.div(rx.foreach(blocks, _block), class_name="space-y-3 break-words text-[14px] leading-relaxed text-label")


# --- agent steps ----------------------------------------------------------------------------------


def _glyph(llm: Any) -> rx.Component:
    return rx.el.span(
        rx.el.svg(
            rx.cond(
                llm,
                rx.el.svg.path(d="M8 2.5 9.3 6.7 13.5 8 9.3 9.3 8 13.5 6.7 9.3 2.5 8l4.2-1.3z"),
                rx.el.svg.path(d="M10.3 2.8a3 3 0 0 0-3.9 3.9L2.8 10.3a1.3 1.3 0 0 0 1.9 1.9l3.6-3.6a3 3 0 0 0 3.9-3.9L10.4 6.5 9.5 6.5 9.5 5.6z"),
            ),
            view_box="0 0 16 16",
            class_name="size-3.5",
            custom_attrs=svg_attrs(fill="none", stroke="currentColor", stroke_width="1.5", stroke_linecap="round", stroke_linejoin="round"),
        ),
        class_name=rx.cond(
            llm,
            "mt-0.5 grid size-6 shrink-0 place-items-center rounded-full bg-accent/10 text-accent",
            "mt-0.5 grid size-6 shrink-0 place-items-center rounded-full bg-fill text-label-2",
        ),
        aria_hidden="true",
    )


def _llm_step(e: rx.Var) -> rx.Component:
    return rx.el.li(
        _glyph(True),
        rx.el.div(
            rx.el.div(
                rx.el.span("Model call", class_name="font-medium text-label"),
                rx.el.span(e["model"], class_name=f"text-label-2 {MONO}"),
                rx.el.span(e["stats"], class_name="tabular-nums text-label-3"),
                class_name="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[13px]",
            ),
            rx.match(
                e["mode"],
                ("final", rx.el.p("Wrote the final answer (below).", class_name="mt-1 text-[12.5px] text-label-3")),
                ("text", rx.el.p(e["text"], class_name="mt-1 line-clamp-3 text-[12.5px] text-label-2")),
                rx.fragment(),
            ),
            rx.cond(
                e["calls"] != "",
                rx.el.p("Requested: ", rx.el.span(e["calls"], class_name=MONO), class_name="mt-1 text-[12px] text-label-3"),
            ),
            rx.cond(e["error"] != "", rx.el.p(e["error"], class_name="mt-1 text-[12.5px] text-bad-text")),
            class_name="min-w-0 flex-1",
        ),
        class_name="flex gap-3 py-2.5",
    )


def _label(text: str, trunc: Any) -> rx.Component:
    return rx.el.div(text, " ", rx.cond(trunc, truncated_chip()), class_name="mb-1 flex items-center gap-2 text-[11.5px] font-medium text-label-3")


def _tool_step(e: rx.Var) -> rx.Component:
    return rx.el.li(
        _glyph(False),
        rx.el.div(
            rx.el.details(
                rx.el.summary(
                    chevron("size-2.5 self-center text-label-3"),
                    rx.el.span(e["name"], class_name=f"font-medium text-label {MONO} text-[12.5px]"),
                    rx.cond(
                        e["summary"] != "",
                        rx.el.span(e["summary"], class_name=f"min-w-0 max-w-full truncate text-label-2 {MONO}", title=e["summary"].to(str)),
                    ),
                    segs(e["file"]),
                    rx.cond(e["dur"] != "", rx.el.span(e["dur"], class_name="tabular-nums text-label-3")),
                    rx.cond(e["error"] != "", chip("error", "bad")),
                    class_name="flex cursor-pointer select-none flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[13px] [&::-webkit-details-marker]:hidden",
                ),
                rx.el.div(
                    rx.cond(e["error"] != "", rx.el.p(e["error"], class_name="text-[12.5px] text-bad-text")),
                    rx.cond(
                        e["has_args"],
                        rx.el.div(
                            _label("Arguments", e["args_trunc"]),
                            rx.el.pre(
                                e["args"],
                                class_name="scroll-area max-h-40 overflow-auto rounded-[10px] bg-fill/60 px-3 py-2 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap break-all text-label-2",
                            ),
                        ),
                    ),
                    rx.el.div(
                        _label("Result", e["result_trunc"]),
                        rx.cond(
                            e["result"] != "",
                            rx.el.pre(
                                e["result"],
                                class_name="scroll-area max-h-72 overflow-auto rounded-[10px] bg-fill/60 px-3 py-2 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap break-words text-label",
                            ),
                            rx.el.p("Not captured.", class_name="text-[12.5px] text-label-3"),
                        ),
                    ),
                    class_name="mt-2 space-y-2",
                ),
                class_name="group/step",
            ),
            class_name="min-w-0 flex-1",
        ),
        class_name="flex gap-3 py-2.5",
    )


def _step(e: rx.Var) -> rx.Component:
    e = D(e)
    return rx.cond(e["kind"] == "llm", _llm_step(e), _tool_step(e))


# --- turns ----------------------------------------------------------------------------------------


def _skill_chip(s: rx.Var) -> rx.Component:
    s = D(s)
    return rlink(
        "skill: ",
        s["name"],
        rx.cond(s["version"] != "", rx.el.span(s["version"], class_name=f"text-label-3 {MONO} text-[11px]")),
        href=s["href"].to(str),
        title="Copilot read this skill’s SKILL.md during the turn",
        class_name="press inline-flex items-center gap-1 rounded-full bg-accent/10 px-2.5 py-0.5 text-[12px] font-medium text-info-text hover:bg-accent/16",
    )


@rx.memo
def turn_block(t: rx.Var[Dict]) -> rx.Component:
    captured = t["captured"].to(bool)
    return rx.el.details(
        rx.el.summary(
            chevron("size-2.5 text-label-3"),
            rx.el.span(t["label"], class_name="font-semibold text-label"),
            rx.el.span(t["time"], class_name="tabular-nums"),
            rx.cond(t["model"] != "", rx.el.span(t["model"], class_name=MONO)),
            segs(t["credits"]),
            rx.cond(captured, rx.fragment(), chip("no content", title="Prompt and answer not captured: content capture was off")),
            rx.el.span(
                t["preview"],
                class_name="min-w-0 flex-1 basis-40 truncate text-label-3 group-open/turn:invisible",
                title=t["preview_title"].to(str),
            ),
            rx.foreach(L(t["skills"]), _skill_chip),
            segs(t["trace"]),
            class_name="flex cursor-pointer select-none flex-wrap items-center gap-x-3 gap-y-2 rounded-[24px] px-6 py-4 text-[13px] text-label-2 hover:bg-hover group-open/turn:hover:bg-transparent",
        ),
        rx.el.div(
            rx.cond(
                t["error"] != "",
                rx.el.div(notice("error", "This turn reported an error", rx.el.span(t["error"], class_name=MONO)), class_name="mt-1"),
            ),
            rx.cond(
                captured,
                rx.el.div(
                    rx.el.div(
                        rx.cond(t["prompt"] != "", t["prompt"], rx.el.span("Prompt not captured.", class_name="text-label-3")),
                        rx.cond(t["prompt_trunc"], rx.el.span(truncated_chip(), class_name="ml-2")),
                        class_name="max-w-[85%] rounded-[18px] rounded-br-[6px] bg-accent/10 px-4 py-3 text-[14px] leading-relaxed whitespace-pre-wrap break-words text-label",
                    ),
                    class_name="mt-1 flex justify-end",
                ),
            ),
            rx.cond(
                t["has_steps"],
                rx.el.details(
                    rx.el.summary(
                        chevron("size-2.5"),
                        rx.el.span("Agent steps", class_name="font-medium text-label"),
                        rx.el.span(t["steps_hint"], class_name="tabular-nums text-label-3"),
                        class_name="press flex cursor-pointer select-none items-center gap-2 rounded-[16px] px-4 py-3 text-[13px] hover:bg-hover",
                    ),
                    rx.el.ol(rx.foreach(L(t["steps"]), _step), class_name="divide-y divide-separator/60 px-4 pb-2"),
                    open=t["focused"].to(bool),
                    class_name=rx.cond(
                        captured,
                        "disclosure group rounded-[16px] bg-fill/35 mt-4",
                        "disclosure group rounded-[16px] bg-fill/35 mt-1",
                    ),
                ),
            ),
            rx.cond(
                captured,
                rx.el.div(
                    rx.el.div(
                        rx.cond(
                            t["has_answer"],
                            markdown(blocks=L(t["answer"])),
                            rx.el.p("Answer not captured.", class_name="text-[14px] text-label-3"),
                        ),
                        rx.cond(t["answer_trunc"], rx.el.div(truncated_chip(), class_name="mt-2")),
                        class_name="max-w-[92%] rounded-[18px] rounded-bl-[6px] bg-surface-2 px-5 py-4 shadow-[inset_0_0_0_1px_var(--separator)]",
                    ),
                    class_name="mt-4 flex",
                ),
            ),
            class_name=rx.cond(captured, "px-6 pb-6", "px-6 pb-4"),
        ),
        id="transcript-" + t["id"].to(str),
        open=t["open"].to(bool),
        custom_attrs={"data-turn": ""},
        class_name="disclosure group/turn scroll-mt-24 rounded-[24px] bg-surface shadow-card",
    )


# --- section ------------------------------------------------------------------------------------

ROOT_ID = "transcript"
_SET_TURNS = (
    "(function(open){{var r=document.getElementById('{root}');if(!r)return;if(open&&r.tagName==='DETAILS')r.open=true;"
    "r.querySelectorAll('details[data-turn]').forEach(function(d){{d.open=open}})}})({open})"
)
BUTTON = "press rounded-full px-2.5 py-1 text-[13px] font-medium text-link hover:bg-accent/10"


def transcript_controls() -> rx.Component:
    return rx.el.div(
        rx.el.button(
            "Expand all",
            type="button",
            class_name=BUTTON,
            aria_controls=ROOT_ID,
            on_click=rx.call_script(_SET_TURNS.format(root=ROOT_ID, open="true")),
        ),
        rx.el.button(
            "Collapse all",
            type="button",
            class_name=BUTTON,
            aria_controls=ROOT_ID,
            on_click=rx.call_script(_SET_TURNS.format(root=ROOT_ID, open="false")),
        ),
        class_name="flex items-center gap-0.5",
        role="group",
        aria_label="Transcript turns",
    )


def transcript_section(tx: Any, title: Any, note: Any) -> rx.Component:
    """The whole transcript as one collapsible section with expand/collapse all."""
    tx = D(tx)
    multi = tx["multi"].to(bool)
    return rx.el.section(
        rx.el.details(
            rx.el.summary(
                chevron("size-3.5 text-label-2"),
                rx.el.span(
                    rx.el.span(title, class_name="block font-display text-[20px] font-semibold tracking-[-0.018em] text-label"),
                    rx.el.span(tx["summary"], class_name="mt-0.5 block truncate text-[13px] tabular-nums text-label-2"),
                    class_name="min-w-0",
                ),
                class_name=rx.cond(
                    multi,
                    "press mb-4 flex cursor-pointer select-none items-center gap-3 rounded-[22px] bg-surface/70 px-5 py-4 shadow-card pr-60 hover:bg-hover group-open/transcript:mb-3 group-open/transcript:bg-transparent group-open/transcript:px-1 group-open/transcript:py-1 group-open/transcript:shadow-none",
                    "press mb-4 flex cursor-pointer select-none items-center gap-3 rounded-[22px] bg-surface/70 px-5 py-4 shadow-card  hover:bg-hover group-open/transcript:mb-3 group-open/transcript:bg-transparent group-open/transcript:px-1 group-open/transcript:py-1 group-open/transcript:shadow-none",
                ),
            ),
            rx.cond(note != "", rx.el.p(note, class_name="-mt-1 mb-4 px-1 text-[12.5px] text-label-3")),
            rx.el.div(rx.foreach(L(tx["turns"]), lambda t: turn_block(t=t)), class_name="flex flex-col gap-3"),
            id=ROOT_ID,
            open=tx["open"].to(bool),
            class_name="disclosure group/transcript",
        ),
        rx.cond(
            multi,
            # Outside <summary> so the buttons never toggle the section.
            rx.el.div(
                transcript_controls(),
                class_name="absolute top-4 right-4 group-has-[details[open]#transcript]/tx:top-1.5 group-has-[details[open]#transcript]/tx:right-0",
            ),
        ),
        class_name="group/tx relative",
    )


def scroll_into_view_script(element_id: str) -> str:
    """Scrolls the element into view once rendered (instant when reduced motion is on)."""
    import json

    return (
        "setTimeout(function(){var el=document.getElementById(" + json.dumps(element_id) + ");if(!el)return;"
        "var reduce=window.matchMedia('(prefers-reduced-motion: reduce)').matches;"
        "el.scrollIntoView({block:'start',behavior:reduce?'auto':'smooth'})},150)"
    )
