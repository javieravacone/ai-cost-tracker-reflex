"""Skills (`/skills`), port of src/app/skills/page.tsx."""

from __future__ import annotations

from typing import Any

import reflex as rx

from bis_cost_tracker.components.layout import shell
from bis_cost_tracker.components.ui import card, code, data_table, empty_state, kpi_tiles, loading, page_header
from bis_cost_tracker.state import AppState
from bis_cost_tracker.views import skills


@AppState.register
class SkillsState(AppState):
    data: dict[str, Any] = skills.empty()
    loaded: bool = False

    def _build(self) -> None:
        self.data = skills.build(self._query())
        self.loaded = True

    @rx.event
    def load(self):
        self._shell("SkillsState")
        self._build()


COLS = [
    ("Skill", False, ""),
    ("Turns", True, ""),
    ("Credits / turn", True, ""),
    ("Tool calls / turn", True, ""),
    ("Error rate", True, ""),
    ("sr:Versions", False, "w-12"),
]


def _no_capture() -> rx.Component:
    return rx.el.div(
        rx.el.h2("No captured content in this period", class_name="text-[20px] font-semibold tracking-[-0.016em]"),
        rx.el.p(
            "Skills are detected from what Copilot reads, so they need content capture. Run ",
            code("npx tsx scripts/configure-vscode.ts --capture-content"),
            ", use Copilot, then press Sync. Captured content includes code and possibly secrets.",
            class_name="mt-2 max-w-xl text-[14px] text-label-2",
        ),
        class_name="flex flex-col items-center rounded-[24px] bg-surface px-8 py-16 text-center shadow-card",
    )


def _content(d: Any) -> rx.Component:
    header = page_header("Skills", d["subtitle"])
    return rx.cond(
        d["empty"],
        rx.fragment(header, empty_state(d["db_empty"])),
        rx.cond(
            d["no_capture"],
            rx.fragment(header, _no_capture()),
            rx.fragment(
                header,
                kpi_tiles(d["tiles"], cols4=False),
                rx.cond(
                    d["has_skills"],
                    data_table(COLS, d["rows"]),
                    card(
                        rx.el.p(
                            "No skill was read in the ",
                            d["none_text"],
                            " of this period. Skills live in ",
                            code(".github/skills/<name>/SKILL.md"),
                            " (also ",
                            code(".claude"),
                            ", ",
                            code(".agents"),
                            " or ",
                            code("~/.copilot/skills"),
                            ").",
                            class_name="text-[14px] text-label-2",
                        )
                    ),
                ),
                rx.el.p(
                    "Baseline: turns of the same teams in this period with captured content where Copilot read no SKILL.md. Credits are "
                    "averaged over turns that reported them. Small samples are noisy: compare only with enough turns on each side.",
                    class_name="px-1 text-[12.5px] text-label-3",
                ),
            ),
        ),
    )


def page() -> rx.Component:
    return shell("/skills", rx.cond(SkillsState.loaded, _content(SkillsState.data), loading()))
