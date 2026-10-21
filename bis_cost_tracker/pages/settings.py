"""Settings (`/ajustes`), port of src/app/ajustes/page.tsx."""

from __future__ import annotations

from typing import Any

import reflex as rx

from bis_cost_tracker.components.layout import shell
from bis_cost_tracker.components.ui import LINK, card, code, data_table, disclosure, loading, page_header
from bis_cost_tracker.state import AppState
from bis_cost_tracker.views import settings
from bis_cost_tracker.views.kit import CHIP, CHIP_BASE

BILLING_DOCS = "https://docs.github.com/en/copilot/concepts/billing-and-usage/organizations-and-enterprises/billing"
PRICING_DOCS = "https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing"


@AppState.register
class SettingsState(AppState):
    data: dict[str, Any] = settings.empty()
    loaded: bool = False

    def _build(self) -> None:
        self.data = settings.build()
        self.loaded = True

    @rx.event
    def load(self):
        self._shell("SettingsState")
        self._build()


def chip(text: str, tone: str = "neutral") -> rx.Component:
    return rx.el.span(text, class_name=f"{CHIP_BASE} {CHIP[tone]}")


def b(text: Any) -> rx.Component:
    return rx.el.b(text, class_name="text-label")


TABLE = {"standalone": False, "max_height": "max-h-[28rem]"}
PRICE_COLS = [
    ("Model", False, ""),
    ("Input", True, ""),
    ("Output", True, ""),
    ("Cache read", True, ""),
    ("Cache write", True, ""),
    ("Premium multiplier (legacy)", True, ""),
]
PLAN_COLS = [("Plan", False, ""), ("Price/month", True, ""), ("Included AI credits", True, ""), ("Included premium (legacy)", True, ""), ("Overage / req.", True, "")]


def _capture(d: Any) -> rx.Component:
    return card(
        rx.el.div(
            rx.el.p(
                rx.cond(
                    d["has_content"],
                    rx.fragment(b(d["content_lead"]), d["content_rest"]),
                    rx.fragment(
                        "No turn has captured content. Agent steps without text (",
                        d["events"],
                        ") may still be stored from trace metadata.",
                    ),
                )
            ),
            rx.el.p(
                "Captured content ",
                b("includes source code and possibly secrets"),
                " (file contents, terminal output, tokens pasted in prompts). It is kept in two places: the local SQLite database (",
                code("data/app.db"),
                ", tables ",
                code("turn_content"),
                ", ",
                code("turn_events"),
                ", ",
                code("skill_usage"),
                ") and the LangSmith workspace the traces are exported to, under that workspace’s retention. Long tool results are "
                "truncated locally; LangSmith keeps the full text.",
            ),
            rx.el.p(
                "Capture is opt-in per machine (",
                code("scripts/configure-vscode.ts --capture-content"),
                "). LangSmith masking only applies to its SDKs, so redacting Copilot traces needs an OpenTelemetry Collector in "
                "between. Get data-protection sign-off before enabling it on a shared workspace.",
                class_name="text-[12.5px] text-label-3",
            ),
            class_name="max-w-[92ch] space-y-2 text-[13.5px] text-label-2",
        ),
        title="Content capture",
        subtitle="Prompts, answers, tool arguments and results captured from Copilot Chat",
        action=rx.cond(d["has_content"], chip("Captured content present", "warn"), chip("No captured content", "ok")),
    )


def _help(d: Any) -> rx.Component:
    return rx.el.div(
        disclosure(
            "How do I change this data?",
            rx.el.div(
                rx.el.p(
                    "These tables live in SQLite (",
                    code("data/app.db"),
                    " or ",
                    code("$DB_PATH"),
                    "). To change them, edit ",
                    code("scripts/seed.ts"),
                    " and run ",
                    code("npm run seed"),
                    " (it wipes and regenerates everything!), or edit the database directly (e.g. ",
                    code("sqlite3 data/app.db"),
                    ", tables ",
                    code("model_prices"),
                    ", ",
                    code("seat_plans"),
                    ", ",
                    code("repo_mappings"),
                    ", ",
                    code("teams"),
                    ", ",
                    code("projects"),
                    ", ",
                    code("members"),
                    "). Changes show up on reload.",
                ),
                rx.el.p(
                    "VS Code → LangSmith setup: ",
                    code("docs/vscode-setup.md"),
                    ". Keys go in ",
                    code(".env.local"),
                    " (see ",
                    code(".env.example"),
                    "); then run ",
                    code("npm run sync"),
                    " and ",
                    code("npm run sync:github"),
                    ".",
                ),
                rx.el.p(
                    "Prices and plans are illustrative. Manual assignments are edited from each session (",
                    d["manual_count"],
                    " currently).",
                    class_name="text-[12.5px] text-label-3",
                ),
                class_name="max-w-[92ch] space-y-2 text-[13.5px] text-label-2",
            ),
            hint=d["manual_hint"],
            surface=True,
        ),
        disclosure(
            "GitHub AI credits",
            rx.el.div(
                rx.el.p(
                    "On each model call (",
                    code("chat"),
                    " span) Copilot Chat reports the ",
                    code("copilot_chat.copilot_usage_nano_aiu"),
                    " attribute, which arrives in LangSmith as ",
                    code('metadata["otel.span.copilot_chat.copilot_usage_nano_aiu"]'),
                    ". It is summed per turn (including subagents and background calls).",
                ),
                rx.el.p(
                    b(d["credit_rule"]),
                    ". The figure is ",
                    b("gross, at list price and before the included pool"),
                    ": each seat adds its monthly included credits (Business 1,900, Enterprise 3,900; individual Pro 1,500, Pro+ 7,000) "
                    "to a pool shared by the billing entity, and only usage above it is paid, at $0.01 per credit. Since June 1, 2026, "
                    "credits are the actual billing unit for Copilot Business/Enterprise.",
                ),
                rx.el.p(
                    "A turn without the attribute (legacy plan, BYOK or older client) shows as ",
                    chip("no data", "warn"),
                    ", never as $0. ",
                    b("Premium requests"),
                    " and their multiplier are the ",
                    b("legacy"),
                    " model (only older annual Pro/Pro+ plans); they are kept as an estimate. Copilot appears to bill uncached input "
                    "at the cache-write rate, so actual usage can exceed the API equivalent.",
                ),
                rx.el.p(
                    "Sources: ",
                    rx.el.a("Copilot billing", href=BILLING_DOCS, target="_blank", rel="noreferrer", class_name=LINK),
                    " · ",
                    rx.el.a("models and pricing", href=PRICING_DOCS, target="_blank", rel="noreferrer", class_name=LINK),
                    ".",
                    class_name="text-[12.5px] text-label-3",
                ),
                class_name="max-w-[92ch] space-y-2 text-[13.5px] text-label-2",
            ),
            hint="How actual Copilot usage is measured",
            surface=True,
        ),
        class_name="flex flex-col gap-3",
    )


def _tables(d: Any) -> rx.Component:
    return rx.el.div(
        card(data_table(PRICE_COLS, d["prices"], **TABLE), title="Model prices", subtitle=d["prices_subtitle"], flush=True, class_name="xl:col-span-2"),
        card(data_table(PLAN_COLS, d["plans"], **TABLE), title="Seat plans", subtitle=d["plans_subtitle"], flush=True, class_name="xl:col-span-2"),
        card(
            data_table([("Repo", False, ""), ("Project", False, "")], d["mappings"], **TABLE),
            title="Repos → project",
            subtitle=d["mappings_subtitle"],
            flush=True,
        ),
        card(
            data_table([("Type", False, ""), ("Id", False, ""), ("Name", False, "")], d["entities"], **TABLE),
            title="Teams and projects",
            subtitle=d["entities_subtitle"],
            flush=True,
        ),
        card(
            data_table([("User", False, ""), ("Name", False, ""), ("Team", False, ""), ("Plan", False, "")], d["members"], **TABLE),
            title="Members",
            subtitle=d["members_subtitle"],
            flush=True,
            class_name="xl:col-span-2",
        ),
        class_name="stagger grid items-start gap-4 xl:grid-cols-2",
    )


def _content(d: Any) -> rx.Component:
    return rx.fragment(
        page_header("Settings", "Reference data used by the calculation (read-only in this POC)"),
        _capture(d),
        _help(d),
        _tables(d),
    )


def page() -> rx.Component:
    return shell("/ajustes", rx.cond(SettingsState.loaded, _content(SettingsState.data), loading()))
