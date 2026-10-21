"""BIS AI Cost Tracker (Reflex port of the Next.js POC): app, theme and routes."""

import reflex as rx

from bis_core.sync import load_local_env

from bis_cost_tracker.pages import overview, team, teams

# Same variables as the Next app (`.env.local`: LangSmith / GitHub / DB_PATH).
load_local_env()

TITLE = "BIS AI Cost Tracker"


def _title(section: str | None) -> str:
    return f"{section} · {TITLE}" if section else TITLE


app = rx.App(
    stylesheets=["/styles.css"],
    head_components=[
        rx.el.meta(name="theme-color", media="(prefers-color-scheme: light)", content="#f5f5f7"),
        rx.el.meta(name="theme-color", media="(prefers-color-scheme: dark)", content="#000000"),
    ],
)

DESCRIPTION = "Copilot Chat usage and cost attribution by team, project, issue and PR."

app.add_page(overview.page, route="/", title=_title(None), description=DESCRIPTION, on_load=overview.OverviewState.load)
app.add_page(team.page, route="/equipos/[id]", title=_title("Team"), on_load=team.TeamState.load)
app.add_page(teams.page, route="/equipos", title=_title("Teams"), on_load=teams.TeamsState.load)
