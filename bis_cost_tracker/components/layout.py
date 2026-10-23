"""App shell (port of src/app/layout.tsx, src/components/nav.tsx, sync-button.tsx, bis-logo.tsx)."""

from __future__ import annotations

from typing import Any

import reflex as rx

from bis_cost_tracker.components.rich import svg_attrs
from bis_cost_tracker.components.ui import disclosure, rlink
from bis_cost_tracker.state import AppState

# --- logo ----------------------------------------------------------------------------------------

GLOBE_LINES = "M18.9009 34.1632C18.769 34.1632 18.6375 34.1616 18.5061 34.1598V29.8583L10.8479 22.2413H0.0117266C0.00476884 22.1038 0 21.9658 0 21.8272C0 21.6888 0.00476884 21.5512 0.0117266 21.4137H10.8479L18.5061 13.8377V9.49398C18.6375 9.49218 18.769 9.49069 18.9009 9.49069C19.0458 9.49069 19.1901 9.4921 19.3341 9.49421V13.8377L26.9924 21.4137H37.7904C37.7973 21.5511 37.8021 21.6888 37.8021 21.8272C37.8021 21.9658 37.7973 22.1038 37.7904 22.2413H26.9924L19.3341 29.8583V34.1595C19.19 34.1617 19.0458 34.1631 18.9009 34.1631V34.1632Z"
GLOBE = "M26.9925 21.4133L19.3343 13.8374V9.49084C29.3521 9.61507 37.4659 14.8723 37.797 21.4133H26.9925ZM19.3343 34.1632V29.8578L26.9925 22.2409H37.797C37.4659 28.7819 29.3521 34.0392 19.3343 34.1632ZM10.8479 21.4133H0.00195312C0.333192 14.8724 8.48821 9.61507 18.5061 9.49084V13.8374L10.8479 21.4133ZM0.00195312 22.2409H10.8479L18.5061 29.8578V34.1632C8.48821 34.0392 0.333192 28.782 0.00195312 22.2409Z"
LETTERS = "M51.6191 34.18C54.4206 34.18 59.033 33.5651 59.033 27.2444C59.033 23.8621 57.4955 21.7438 53.9765 21.3338V21.1629C57.154 20.4455 58.213 18.3955 58.213 15.3206C58.213 14.8422 58.0764 13.3731 57.2222 12.0407C56.2997 10.6741 55.1381 9.51245 51.7215 9.51245H43.6926V34.18H51.6191V34.18ZM46.8359 22.6321H50.1841C53.3957 22.6321 55.8214 23.3154 55.8214 27.2444C55.8214 29.0552 54.6257 31.4468 51.2774 31.4468H46.8359V22.6321ZM46.8359 12.2457H51.2774C53.9081 12.2457 55.0698 13.9198 55.0698 15.9698C55.0698 18.3614 53.874 19.8647 51.4141 19.8988H46.8359V12.2457ZM68.845 9.51253H65.7018V34.18H68.845V9.51253ZM75.138 26.8344C75.0697 29.1919 75.0697 34.7609 82.3469 34.6925C86.4126 34.6925 90 33.0184 90 27.8252C90 20.0012 78.9303 20.787 78.9303 15.3548C78.9303 12.6898 80.8436 11.7332 82.7227 11.7332C85.6951 11.7332 86.5493 13.5098 86.5151 16.2089H89.795C90 11.1866 87.4717 9 82.9619 9C78.8278 9 75.7188 11.3232 75.7188 15.6965C75.7188 23.1104 86.7884 22.4954 86.7884 27.9618C86.7884 30.9001 84.8752 31.9592 82.3811 31.9592C80.3654 31.9592 78.2471 30.9001 78.2471 27.5519V26.8344H75.138Z"


def bis_logo(class_name: str = "h-6 w-auto") -> rx.Component:
    return rx.el.svg(
        rx.el.svg.path(d=GLOBE_LINES, custom_attrs={"fill": "#D2D4D3"}),
        rx.el.svg.path(d=GLOBE, custom_attrs={"fill": "#AA322F"}),
        rx.el.svg.path(d=LETTERS, custom_attrs={"fill": "currentColor"}),
        view_box="0 8.5 90 26.7",
        class_name=class_name,
        role="img",
        aria_label="BIS",
    )


def bis_mark(class_name: str = "size-6") -> rx.Component:
    return rx.el.svg(
        rx.el.svg.path(d=GLOBE_LINES, custom_attrs={"fill": "#D2D4D3"}),
        rx.el.svg.path(d=GLOBE, custom_attrs={"fill": "#AA322F"}),
        view_box="-0.5 2.5 39 39",
        class_name=class_name,
        role="img",
        aria_label="BIS",
    )


# --- navigation ------------------------------------------------------------------------------------

_P = rx.el.svg.path
_C = rx.el.svg.circle
_R = rx.el.svg.rect


def _icon_children(href: str) -> list[rx.Component]:
    if href == "/":
        return [_R(x="4", y="4", width="7", height="7", rx="2"), _R(x="13", y="4", width="7", height="7", rx="2"), _R(x="4", y="13", width="7", height="7", rx="2"), _R(x="13", y="13", width="7", height="7", rx="2")]
    if href == "/equipos":
        return [_C(cx="9", cy="8.5", r="3"), _P(d="M3.5 19c.6-3 2.8-4.6 5.5-4.6s4.9 1.6 5.5 4.6"), _C(cx="16.5", cy="9.5", r="2.4"), _P(d="M15.6 14.5c2.3 0 4.2 1.4 4.8 4")]
    if href == "/proyectos":
        return [_P(d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z")]
    if href == "/issues":
        return [_C(cx="12", cy="12", r="8"), _C(cx="12", cy="12", r="2", custom_attrs={"fill": "currentColor", "stroke": "none"})]
    if href == "/prs":
        return [_C(cx="6.5", cy="6", r="2.2"), _C(cx="6.5", cy="18", r="2.2"), _C(cx="17.5", cy="18", r="2.2"), _P(d="M6.5 8.2v7.6M17.5 15.8V10a3 3 0 0 0-3-3h-4M12.5 4.8 10.3 7l2.2 2.2")]
    if href == "/personas":
        return [_C(cx="12", cy="12", r="8.5"), _C(cx="12", cy="10", r="3"), _P(d="M6.6 18.2c1.1-2.2 3-3.3 5.4-3.3s4.3 1.1 5.4 3.3")]
    if href == "/sesiones":
        return [
            _P(d="M4 6.5a2.5 2.5 0 0 1 2.5-2.5h8A2.5 2.5 0 0 1 17 6.5v4a2.5 2.5 0 0 1-2.5 2.5H9l-3.5 3v-3A2.5 2.5 0 0 1 4 10.5z"),
            _P(d="M19.5 9.5a2 2 0 0 1 .5 1.3v3.7a2.5 2.5 0 0 1-2 2.4V20l-3.3-2.9H12"),
        ]
    if href == "/skills":
        return [_P(d="M12 3.5 14.4 8.4l5.3.8-3.85 3.75.9 5.3L12 15.75 7.25 18.25l.9-5.3L4.3 9.2l5.3-.8z")]
    return [
        _P(d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h11M19 17h1"),
        _C(cx="15", cy="7", r="2"),
        _C(cx="9", cy="12", r="2"),
        _C(cx="17", cy="17", r="2"),
    ]


def nav_icon(href: str) -> rx.Component:
    return rx.el.svg(
        *_icon_children(href),
        view_box="0 0 24 24",
        class_name="size-[18px] shrink-0",
        custom_attrs=svg_attrs(fill="none", stroke="currentColor", stroke_width="1.7", stroke_linecap="round", stroke_linejoin="round"),
        aria_hidden="true",
    )


SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Cost", [("/", "Overview"), ("/equipos", "Teams"), ("/proyectos", "Projects"), ("/personas", "People")]),
    ("Work", [("/issues", "Issues"), ("/prs", "Pull requests"), ("/sesiones", "Sessions"), ("/skills", "Skills")]),
    ("Configuration", [("/ajustes", "Settings")]),
]
LABELS = {href: label for _, links in SECTIONS for href, label in links}


def _href_with_days(href: str) -> Any:
    return href + AppState.days_q


def sidebar_nav(active: str) -> rx.Component:
    return rx.el.nav(
        *[
            rx.el.div(
                rx.el.div(title, class_name="mb-1.5 px-3 text-[11.5px] font-semibold tracking-[0.01em] text-label-3"),
                rx.el.ul(
                    *[
                        rx.el.li(
                            rlink(
                                rx.el.span(nav_icon(href), class_name="text-accent" if href == active else "text-label-2"),
                                label,
                                href=_href_with_days(href),
                                aria_current="page" if href == active else None,
                                class_name="press flex items-center gap-3 rounded-[12px] px-3 py-2 text-[14px] "
                                + ("bg-accent/12 font-semibold text-accent" if href == active else "font-medium text-label hover:bg-hover"),
                            )
                        )
                        for href, label in links
                    ],
                    class_name="flex flex-col gap-0.5",
                ),
            )
            for title, links in SECTIONS
        ],
        aria_label="Sections",
        class_name="flex flex-col gap-6",
    )


def compact_nav(active: str) -> rx.Component:
    return rx.el.nav(
        *[
            rlink(
                nav_icon(href),
                label,
                href=_href_with_days(href),
                aria_current="page" if href == active else None,
                class_name="press flex shrink-0 items-center gap-1.5 rounded-full px-3.5 py-1.5 text-[13px] font-medium "
                + ("bg-accent text-white" if href == active else "text-label-2 hover:bg-hover hover:text-label"),
            )
            for _, links in SECTIONS
            for href, label in links
        ],
        aria_label="Sections",
        class_name="scroll-area -mx-1 flex gap-1 overflow-x-auto px-1 pb-0.5",
    )


def period_picker() -> rx.Component:
    return rx.el.div(
        rx.el.span("Period", class_name="hidden text-[13px] text-label-2 sm:inline"),
        rx.el.div(
            rx.el.span(
                aria_hidden="true",
                class_name="absolute top-[3px] bottom-[3px] left-[3px] rounded-[8px] bg-seg-thumb shadow-control transition-transform duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
                style={"width": "calc((100% - 6px) / 4)", "transform": AppState.period_tx},
            ),
            rx.foreach(
                AppState.period,
                lambda p: rlink(
                    p["label"],
                    href=p["href"].to(str),
                    aria_current=rx.cond(p["selected"], "true", None),
                    class_name=rx.cond(
                        p["selected"],
                        "relative z-[1] min-w-[3.25rem] rounded-[8px] px-2 py-[5px] whitespace-nowrap sm:min-w-[3.75rem] sm:px-3 text-center text-[13px] font-medium tabular-nums transition-colors duration-200 text-label",
                        "relative z-[1] min-w-[3.25rem] rounded-[8px] px-2 py-[5px] whitespace-nowrap sm:min-w-[3.75rem] sm:px-3 text-center text-[13px] font-medium tabular-nums transition-colors duration-200 text-label-2 hover:text-label",
                    ),
                ),
            ),
            class_name="relative grid grid-cols-4 rounded-[11px] bg-fill p-[3px]",
        ),
        role="group",
        aria_label="Period",
        class_name="inline-flex items-center gap-3",
    )


def current_section(active: str) -> rx.Component:
    if active not in LABELS:
        return rx.fragment()
    return rx.el.span(
        rx.el.span(nav_icon(active), class_name="text-accent"),
        LABELS[active],
        class_name="inline-flex items-center gap-2 text-[14px] font-semibold text-label",
    )


# --- sync button -----------------------------------------------------------------------------------


def refresh_icon() -> rx.Component:
    return rx.el.svg(
        _P(d="M20 11.5A8 8 0 0 0 6.3 6.3L4 8.5"),
        _P(d="M4 4v4.5h4.5"),
        _P(d="M4 12.5a8 8 0 0 0 13.7 5.2L20 15.5"),
        _P(d="M20 20v-4.5h-4.5"),
        view_box="0 0 24 24",
        class_name=rx.cond(AppState.syncing, "size-[15px] shrink-0 spin", "size-[15px] shrink-0"),
        custom_attrs=svg_attrs(fill="none", stroke="currentColor", stroke_width="2", stroke_linecap="round", stroke_linejoin="round"),
        aria_hidden="true",
    )


def sync_toast() -> rx.Component:
    t = AppState.toast
    return rx.el.div(
        rx.cond(t["lead"] != "", rx.el.div(t["lead"], class_name="text-label-2 tabular-nums")),
        rx.foreach(t["lines"].to(list[str]), lambda line: rx.el.div(line, class_name="font-medium tabular-nums " + t["tone"].to(str))),
        class_name="toast glass w-max max-w-[min(26rem,calc(100vw-2rem))] rounded-[14px] px-3.5 py-2.5 text-[12.5px] leading-snug",
    )


def sync_button() -> rx.Component:
    ls = AppState.last_sync
    title = rx.cond(
        ls["known"],
        "Fetches turns from LangSmith and issues/PRs from GitHub · Last: " + ls["title"].to(str),
        "Fetches turns from LangSmith and issues/PRs from GitHub",
    )
    return rx.el.div(
        rx.el.button(
            refresh_icon(),
            rx.el.span(rx.cond(AppState.syncing, "Syncing…", "Sync"), class_name="hidden md:inline"),
            type="button",
            on_click=AppState.sync_now,
            disabled=AppState.syncing,
            aria_busy=AppState.syncing,
            aria_label=rx.cond(AppState.syncing, "Syncing…", "Sync"),
            title=title,
            class_name="press inline-flex h-8 items-center gap-1.5 rounded-full bg-accent/10 px-2.5 text-[13px] font-semibold whitespace-nowrap text-accent hover:bg-accent/16 disabled:cursor-progress disabled:opacity-75 md:px-3.5",
        ),
        rx.el.span(
            rx.el.span("Last synced: ", class_name="hidden xl:inline"),
            rx.el.span(ls["label"], class_name=rx.cond(ls["never"], "text-label-3", "text-label")),
            rx.cond(ls["known"], rx.el.span(ls["clock"], class_name="hidden text-label-3 xl:inline")),
            class_name="hidden text-[12.5px] whitespace-nowrap text-label-2 tabular-nums md:inline",
            title=ls["title"].to(str),
        ),
        rx.el.div(
            rx.cond(t_show(), sync_toast()),
            role="status",
            aria_live="polite",
            class_name="absolute top-[calc(100%+20px)] right-0 z-40",
        ),
        class_name="relative flex items-center gap-3",
    )


def t_show() -> Any:
    return AppState.toast["show"].to(bool)


# --- sidebar pieces --------------------------------------------------------------------------------


def source_status() -> rx.Component:
    s = AppState.source
    return rx.el.div(
        rx.el.div(
            rx.el.span(class_name=s["dot"].to(str), aria_hidden="true"),
            s["title"],
            class_name="flex items-center gap-2 font-semibold text-label",
        ),
        rx.cond(
            s["has_counts"],
            rx.el.div(
                rx.el.div(s["langsmith"]),
                rx.el.div(s["seed"]),
                class_name="mt-1.5 space-y-0.5 tabular-nums text-label-2",
            ),
        ),
        rx.cond(
            s["project_url"] != "",
            rx.el.div(
                rx.el.a(
                    "LangSmith project",
                    rx.el.span("↗", aria_hidden="true", class_name="ml-0.5 text-[0.85em] font-normal opacity-75"),
                    href=s["project_url"].to(str),
                    target="_blank",
                    rel="noreferrer",
                    title="Tracing project in LangSmith",
                    class_name="text-link hover:underline underline-offset-2 decoration-1 relative z-[1] whitespace-nowrap",
                ),
                class_name="mt-1.5",
            ),
        ),
        class_name="rounded-[16px] bg-fill/70 px-3.5 py-3 text-[12px]",
    )


def brand(compact: bool = False) -> rx.Component:
    return rlink(
        bis_mark("size-7 shrink-0") if compact else bis_logo("h-[28px] w-auto shrink-0 text-label"),
        rx.el.span(
            rx.el.span("AI Cost Tracker", class_name="block text-[14px] font-semibold tracking-[-0.01em]"),
            rx.el.span("Copilot Chat · POC", class_name="block text-[12px] text-label-2"),
            class_name="whitespace-nowrap leading-tight " + ("hidden sm:block" if compact else ""),
        ),
        href="/",
        aria_label="BIS AI Cost Tracker, home",
        class_name="press flex rounded-[12px] " + ("items-center gap-3" if compact else "flex-col items-start gap-2"),
    )


def cost_assumptions() -> rx.Component:
    return disclosure(
        "How is this calculated?",
        rx.el.ul(
            rx.el.li(
                "API-equivalent cost = tokens × list price. Input tokens ",
                rx.el.b("include"),
                " cached ones (cache reads/writes are billed at their own rate); reasoning is already part of the output.",
            ),
            rx.el.li(
                "Actual Copilot usage = AI credits reported by Copilot on each model call (1 credit = $0.01), gross at list "
                "price and before the included credit pool. When missing it shows “no data”, never $0."
            ),
            rx.el.li("Premium requests (legacy) = 1 per turn × model multiplier (estimate; model with no price = ×1)."),
            rx.el.li(
                "Subscription cost = seat + premium request overage for the month, prorated across each member-month’s "
                "turns (by premium requests). Unused seats are charged for the fraction of the month that falls in the "
                "period. Users who aren’t members get no subscription cost."
            ),
            rx.el.li(
                "Prices and plans are illustrative and editable (see ",
                rlink("Settings", href="/ajustes", class_name="text-link hover:underline"),
                "). Dates in UTC.",
            ),
            class_name="max-w-[80ch] list-outside list-disc space-y-1.5 pl-4 text-[12.5px] leading-relaxed text-label-2 marker:text-label-3",
        ),
        hint="API cost, actual usage, premium requests and subscription",
    )


SHELL = "mx-auto w-full max-w-[1320px] px-6 lg:px-10"


def shell(active: str, *children: Any) -> rx.Component:
    """Sidebar + sticky toolbar + page content + footer. `active` is the section href."""
    return rx.el.div(
        rx.el.aside(
            rx.el.div(
                rx.el.div(brand(), class_name="mb-8 px-2"),
                rx.el.div(sidebar_nav(active), class_name="scroll-area -mx-1 flex-1 overflow-y-auto px-1"),
                rx.el.div(source_status(), class_name="mt-4"),
                class_name="glass flex h-full flex-col rounded-[24px] px-3 pt-6 pb-3",
            ),
            class_name="sticky top-0 hidden h-screen w-[248px] shrink-0 p-3 pr-0 lg:block",
        ),
        rx.el.div(
            rx.el.header(
                rx.el.div(
                    rx.el.div(
                        rx.el.div(brand(compact=True), class_name="lg:hidden"),
                        rx.el.div(current_section(active), class_name="hidden lg:block"),
                        rx.el.div(sync_button(), period_picker(), class_name="ml-auto flex items-center gap-3 lg:gap-5"),
                        class_name="flex h-14 items-center gap-4 px-4 lg:px-5",
                    ),
                    rx.el.div(compact_nav(active), class_name="px-3 pb-2.5 lg:hidden"),
                    class_name="glass rounded-[18px]",
                ),
                class_name="sticky top-0 z-30 px-3 pt-3 lg:px-4",
            ),
            rx.el.main(
                rx.el.div(*children, class_name="page-flow flex flex-col gap-8"),
                class_name=f"{SHELL} flex-1 pt-10 pb-16 lg:pt-12",
            ),
            rx.el.footer(
                rx.el.div(
                    cost_assumptions(),
                    rx.el.div(source_status(), class_name="lg:hidden"),
                    class_name="flex flex-col gap-6",
                ),
                class_name=f"{SHELL} pb-12",
            ),
            class_name="flex min-w-0 flex-1 flex-col",
        ),
        class_name="flex min-h-screen font-sans text-label antialiased",
    )
