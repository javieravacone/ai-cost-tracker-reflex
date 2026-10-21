"""Port of src/lib/markdown.test.ts."""

from __future__ import annotations

from bis_core.markdown import parse_inline, parse_markdown, safe_href


def test_parses_code_bold_italic_and_links_keeping_the_rest_as_text():
    assert parse_inline("Use `npm test` and **read [docs](https://x.dev)** *now*.") == [
        {"t": "text", "v": "Use "},
        {"t": "code", "v": "npm test"},
        {"t": "text", "v": " and "},
        {
            "t": "strong",
            "c": [
                {"t": "text", "v": "read "},
                {"t": "link", "href": "https://x.dev", "target": "https://x.dev", "c": [{"t": "text", "v": "docs"}]},
            ],
        },
        {"t": "text", "v": " "},
        {"t": "em", "c": [{"t": "text", "v": "now"}]},
        {"t": "text", "v": "."},
    ]


def test_never_makes_unsafe_or_relative_targets_clickable():
    assert safe_href("javascript:alert(1)") is None
    assert safe_href("src/lib/a.ts#L1") is None
    [link] = parse_inline("[a.ts](src/lib/a.ts#L1)")
    assert link == {"t": "link", "href": None, "target": "src/lib/a.ts#L1", "c": [{"t": "text", "v": "a.ts"}]}


def test_keeps_html_as_literal_text_and_does_not_treat_a_star_b_star_c_as_italic():
    assert parse_inline("<script>x</script> 2*3*4") == [{"t": "text", "v": "<script>x</script> 2*3*4"}]


def test_splits_paragraphs_headings_lists_fenced_code_quotes_rules_and_tables():
    md = "\n".join(
        [
            "## Title",
            "First line",
            "same paragraph.",
            "",
            "- one",
            "- two `x`",
            "",
            "3. three",
            "4. four",
            "",
            "```ts",
            "const a = '<b>';",
            "",
            "```",
            "> quoted",
            "---",
            "| a | b |",
            "|---|---|",
            "| 1 | 2 |",
        ]
    )
    blocks = parse_markdown(md)
    assert [b["t"] for b in blocks] == ["h", "p", "ul", "ol", "code", "quote", "hr", "table"]
    assert blocks[1] == {"t": "p", "c": [{"t": "text", "v": "First line same paragraph."}]}
    assert blocks[3]["t"] == "ol" and blocks[3]["start"] == 3
    assert blocks[4] == {"t": "code", "lang": "ts", "v": "const a = '<b>';\n"}
    assert blocks[7]["t"] == "table"
    assert blocks[7]["head"] == [[{"t": "text", "v": "a"}], [{"t": "text", "v": "b"}]]


def test_tolerates_an_unclosed_fence_and_crlf_input():
    assert parse_markdown("```\r\ncode\r\n") == [{"t": "code", "lang": None, "v": "code\n"}]
