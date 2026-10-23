"""Issues (`/issues`) and Pull requests (`/prs`), ports of src/app/issues/page.tsx and src/app/prs/page.tsx."""

from __future__ import annotations

from typing import Any

import reflex as rx

from bis_cost_tracker.components.layout import shell
from bis_cost_tracker.components.rich import inline
from bis_cost_tracker.components.ui import LINK, code, confidence_help, data_table, empty_note, empty_state, loading, page_header, rlink
from bis_cost_tracker.state import AppState
from bis_cost_tracker.views import issues


@AppState.register
class IssuesState(AppState):
    data: dict[str, Any] = issues.empty()
    loaded: bool = False

    def _build(self) -> None:
        self.data = issues.build_issues(self._query())
        self.loaded = True

    @rx.event
    def load(self):
        self._shell("IssuesState")
        self._build()


@AppState.register
class PrsState(AppState):
    data: dict[str, Any] = issues.empty()
    loaded: bool = False

    def _build(self) -> None:
        self.data = issues.build_prs(self._query())
        self.loaded = True

    @rx.event
    def load(self):
        self._shell("PrsState")
        self._build()


def _cols(first: str, links: str) -> list[tuple[str, bool, str]]:
    return [(first, False, ""), ("Turns", True, ""), ("AI credits", True, ""), ("Subscription", True, ""), (links, False, ""), ("sr:Details", False, "w-12")]


def _content(d: Any, title: str, first: str, links: str, none_text: str, help_: rx.Component) -> rx.Component:
    return rx.cond(
        d["empty"],
        rx.fragment(page_header(title, d["subtitle"]), empty_state(d["db_empty"])),
        rx.fragment(
            page_header(
                title,
                rx.fragment(d["subtitle"], inline(d["stats"], "mt-1.5 block text-[13.5px] text-label-3")),
            ),
            rx.cond(d["has_rows"], data_table(_cols(first, links), d["rows"]), empty_note(none_text)),
            help_,
        ),
    )


def issues_page() -> rx.Component:
    d = IssuesState.data
    help_ = confidence_help(
        "“Not synced”: the issue was inferred (branch or manual assignment) but isn’t in the database; run ",
        code("npm run sync:github"),
        ". PRs = those seen in its turns plus the synced PRs that link to it.",
        rx.cond(
            d["has_no_issue"],
            rx.fragment(" The cost with no issue, by project, is in ", rlink("Projects", href=d["projects_href"].to(str), class_name=LINK), "."),
        ),
    )
    body = _content(d, "Issues", "Issue", "PRs", "No turn in this period has been attributed to an issue yet.", help_)
    return shell("/issues", rx.cond(IssuesState.loaded, body, loading()))


def prs_page() -> rx.Component:
    help_ = confidence_help(
        "A turn is attributed to a PR if its branch is the PR’s head branch, if its commit belongs to the PR, or by manual "
        "assignment. Issues = those linked in the PR (“Closes #n”) plus those seen in its turns."
    )
    body = _content(PrsState.data, "Pull requests", "Pull request", "Issues", "No turn in this period has been attributed to a PR yet.", help_)
    return shell("/prs", rx.cond(PrsState.loaded, body, loading()))
