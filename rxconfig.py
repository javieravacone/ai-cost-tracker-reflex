import os
from pathlib import Path

import reflex as rx

# SQLite (WAL mode) touches data/app.db-wal and -shm on every read; Reflex's dev hot reload does
# not ignore those extensions, so watching data/ would restart the backend on each page view.
if Path("data").is_dir():
    os.environ.setdefault("REFLEX_HOT_RELOAD_EXCLUDE_PATHS", "data")

# Semantic colour tokens from the Next app's `@theme inline` block, mapped to the CSS variables
# defined in assets/styles.css (light and dark values switch there via prefers-color-scheme).
_COLORS = {
    "bg": "var(--bg)",
    "surface": "var(--surface)",
    "surface-2": "var(--surface-2)",
    "label": "var(--label)",
    "label-2": "var(--label-2)",
    "label-3": "var(--label-3)",
    "separator": "var(--separator)",
    "separator-strong": "var(--separator-strong)",
    "fill": "var(--fill)",
    "fill-2": "var(--fill-2)",
    "hover": "var(--hover)",
    "material": "var(--material)",
    "seg-thumb": "var(--seg-thumb)",
    "accent": "var(--accent)",
    "accent-hover": "var(--accent-hover)",
    "link": "var(--link)",
    "ok": "var(--sys-green)",
    "ok-text": "var(--sys-green-text)",
    "warn": "var(--sys-orange)",
    "warn-text": "var(--sys-orange-text)",
    "bad": "var(--sys-red)",
    "bad-text": "var(--sys-red-text)",
    "info-text": "var(--sys-blue-text)",
    "conf-manual": "var(--sys-purple)",
    "conf-branch": "var(--sys-green)",
    "conf-pr": "var(--sys-indigo)",
    "conf-commit": "var(--sys-teal)",
    "conf-inferred": "var(--sys-orange)",
    "conf-project": "var(--sys-gray)",
}

config = rx.Config(
    app_name="bis_cost_tracker",
    telemetry_enabled=False,
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(
            config={
                # Class names are also built in Python (view models), so scan the app package.
                "content": [
                    "./app/**/*.{js,ts,jsx,tsx}",
                    "./utils/**/*.{js,ts,jsx,tsx}",
                    "../bis_cost_tracker/**/*.py",
                ],
                "theme": {
                    "extend": {
                        "colors": _COLORS,
                        "fontFamily": {
                            "sans": "var(--font-sans)",
                            "display": "var(--font-display)",
                            "mono": "var(--font-mono)",
                        },
                        "boxShadow": {
                            "card": "var(--shadow-card)",
                            "glass": "var(--shadow-glass)",
                            "control": "var(--shadow-control)",
                        },
                    }
                },
                "plugins": ["@tailwindcss/typography@0.5.20"],
            }
        ),
        # Radix stays for its primitives but never restyles the page (see assets/styles.css).
        rx.plugins.RadixThemesPlugin(theme=rx.theme(appearance="inherit", has_background=False, accent_color="red")),
    ],
)
