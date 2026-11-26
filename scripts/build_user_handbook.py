#!/usr/bin/env python3
# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Combine the user-facing guides into one printable handbook.

    python scripts/build_user_handbook.py        # docs/handbooks/FALCON-User-Handbook.html (+ .pdf)

The PDF needs Playwright with Chromium (`pip install playwright && playwright install chromium`);
without it only the HTML is written. The Markdown converter covers what the guides use:
headings, paragraphs, lists, tables, code blocks, quotes, inline code, bold, italics and links.
"""

import html
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT = DOCS / "handbooks"
CHAPTERS = [
    ("USER_GUIDE.md", "Using FALCON"),
    ("INSTALL.md", "Installing the inference computer"),
    ("SENSOR_NODE.md", "The sensor node"),
    ("DATA_EXPORT.md", "Data export"),
    ("OPERATIONS.md", "Operation and troubleshooting"),
]


def inline(text: str) -> str:
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append(f"<code>{html.escape(part[1:-1])}</code>")
            continue
        value = html.escape(part, quote=False)
        value = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m: _link(m.group(1), m.group(2)), value)
        value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)
        value = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", value)
        out.append(value)
    return "".join(out)


def _link(label: str, target: str) -> str:
    if target.startswith(("http://", "https://")):
        return f'<a href="{target}">{label}</a>'
    # Links between the bundled chapters become in-document anchors; others stay as text.
    name = target.split("#")[0].split("/")[-1]
    for filename, _ in CHAPTERS:
        if name == filename:
            return f'<a href="#{filename.lower().replace(".md", "")}">{label}</a>'
    return f"{label}"


def markdown(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            block = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                block.append(lines[index])
                index += 1
            out.append("<pre>" + html.escape("\n".join(block)) + "</pre>")
            index += 1
            continue
        heading = re.match(r"(#{1,4})\s+(.*)", stripped)
        if heading:
            level = min(4, len(heading.group(1)) + 1)
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            index += 1
            continue
        if stripped.startswith("|") and index + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[index + 1].strip()):
            header = [cell.strip() for cell in stripped.strip("|").split("|")]
            rows = []
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append([cell.strip() for cell in lines[index].strip().strip("|").split("|")])
                index += 1
            table = "<table><thead><tr>" + "".join(f"<th>{inline(cell)}</th>" for cell in header) + "</tr></thead><tbody>"
            table += "".join("<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in row) + "</tr>" for row in rows)
            out.append(table + "</tbody></table>")
            continue
        if re.match(r"^(\d+\.|-)\s", stripped):
            ordered = stripped[0].isdigit()
            items: list[str] = []
            while index < len(lines):
                current = lines[index]
                match = re.match(r"^\s*(\d+\.|-)\s+(.*)", current)
                if match and (len(current) - len(current.lstrip())) < 3:
                    items.append(match.group(2))
                elif current.strip() and current.startswith((" ", "\t")) and items:
                    if current.strip().startswith("```"):
                        block = []
                        index += 1
                        while index < len(lines) and not lines[index].strip().startswith("```"):
                            block.append(lines[index].strip())
                            index += 1
                        items[-1] += "\x00pre" + "\n".join(block) + "\x00"
                    elif current.strip().startswith("|"):
                        rows = []
                        while index < len(lines) and lines[index].strip().startswith("|"):
                            rows.append(lines[index].strip())
                            index += 1
                        index -= 1
                        items[-1] += "\x00tbl" + "\n".join(rows) + "\x00"
                    else:
                        items[-1] += " " + current.strip()
                elif not current.strip() and index + 1 < len(lines) and lines[index + 1].startswith(("   ", "\t")):
                    pass
                else:
                    break
                index += 1
            tag = "ol" if ordered else "ul"
            rendered = []
            for item in items:
                pieces = item.split("\x00")
                body = ""
                for piece in pieces:
                    if piece.startswith("pre"):
                        body += f"<pre>{html.escape(piece[3:])}</pre>"
                    elif piece.startswith("tbl"):
                        body += markdown(piece[3:])
                    else:
                        body += inline(piece)
                rendered.append(f"<li>{body}</li>")
            out.append(f"<{tag}>" + "".join(rendered) + f"</{tag}>")
            continue
        if stripped.startswith(">"):
            quote = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote.append(lines[index].strip().lstrip("> "))
                index += 1
            out.append("<blockquote>" + inline(" ".join(quote)) + "</blockquote>")
            continue
        if not stripped:
            index += 1
            continue
        paragraph = []
        while index < len(lines) and lines[index].strip() and not re.match(r"^(#|```|\||>|\d+\.\s|-\s)", lines[index].strip()):
            paragraph.append(lines[index].strip())
            index += 1
        out.append("<p>" + inline(" ".join(paragraph)) + "</p>")
    return "\n".join(out)


STYLE = """
:root { color-scheme: light; --ink:#1f2a33; --muted:#5a6873; --line:#d5dde3; --accent:#2b6046; }
* { box-sizing: border-box; }
body { margin: 0; font: 10.5pt/1.55 "Inter", "Segoe UI", system-ui, sans-serif; color: var(--ink); }
.cover { height: 260mm; display: flex; flex-direction: column; justify-content: center; padding: 0 18mm; page-break-after: always; }
.cover h1 { font-size: 34pt; letter-spacing: 6px; margin: 0; color: var(--accent); }
.cover h2 { font-weight: 500; margin: 6px 0 28px; }
.cover p { color: var(--muted); max-width: 120mm; }
nav ol { padding-left: 18px; }
section { page-break-before: always; padding: 0 2mm; }
h2 { font-size: 20pt; color: var(--accent); margin: 0 0 10px; }
h3 { font-size: 13.5pt; margin: 22px 0 6px; }
h4 { font-size: 11.5pt; margin: 16px 0 4px; }
p, li { orphans: 3; widows: 3; }
code { font-family: "Cascadia Mono", "Roboto Mono", monospace; font-size: 9pt; background: #eef2f4; padding: 0 3px; border-radius: 3px; }
pre { font-family: "Cascadia Mono", "Roboto Mono", monospace; font-size: 8.4pt; background: #eef2f4; padding: 8px 10px; border-radius: 6px; white-space: pre-wrap; break-inside: avoid; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 14px; font-size: 9.3pt; break-inside: auto; }
th, td { border: 1px solid var(--line); padding: 4px 7px; text-align: left; vertical-align: top; }
th { background: #f1f5f3; }
tr { break-inside: avoid; }
blockquote { margin: 8px 0; padding: 6px 12px; border-left: 3px solid var(--accent); color: var(--muted); }
a { color: var(--accent); }
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sections, contents = [], []
    for filename, title in CHAPTERS:
        text = (DOCS / filename).read_text(encoding="utf-8")
        text = re.sub(r"^#\s+.*\n", "", text, count=1)
        anchor = filename.lower().replace(".md", "")
        contents.append(f'<li><a href="#{anchor}">{html.escape(title)}</a></li>')
        sections.append(f'<section id="{anchor}"><h2>{html.escape(title)}</h2>{markdown(text)}</section>')
    document = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>FALCON User Handbook</title>
<style>{STYLE}</style></head><body>
<div class="cover"><h1>FALCON</h1><h2>Field Acoustic, Lens &amp; Climate Observation Node<br>User handbook</h2>
<p>Installing the inference computer and the sensor node, using the web interface, reviewing
detections and exporting data. Generated from the guides in <code>docs/</code> on {date.today().isoformat()}.
Developer: Vinay Chittora.</p><nav><ol>{''.join(contents)}</ol></nav></div>
{''.join(sections)}
</body></html>
"""
    target = OUT / "FALCON-User-Handbook.html"
    target.write_text(document, encoding="utf-8")
    print(f"wrote {target.relative_to(ROOT)}")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed; skipped the PDF")
        return
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(target.as_uri())
        page.pdf(
            path=str(OUT / "FALCON-User-Handbook.pdf"), format="A4", print_background=True,
            margin={"top": "15mm", "bottom": "16mm", "left": "15mm", "right": "15mm"},
            display_header_footer=True, header_template="<span></span>",
            footer_template='<div style="font-size:8px;width:100%;text-align:center;color:#888">'
            'FALCON user handbook · <span class="pageNumber"></span></div>',
        )
        browser.close()
    print(f"wrote {(OUT / 'FALCON-User-Handbook.pdf').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
