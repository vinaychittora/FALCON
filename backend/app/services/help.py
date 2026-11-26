# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Built-in help: the guides in docs/ rendered for the web interface, plus the handbooks.

The Markdown renderer covers what the guides use (headings, paragraphs, lists, tables,
code blocks, quotes, inline code, bold, italics and links). Text is HTML-escaped before
any markup is added, so a guide can never inject script into the interface.
"""

import html
import posixpath
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Guide:
    slug: str
    title: str
    filename: str  # relative to the repository root
    summary: str
    section: str


@dataclass(frozen=True)
class Handbook:
    slug: str
    title: str
    summary: str
    html: str | None
    pdf: str | None


GUIDES = [
    Guide("start", "Start here", "README.md", "What FALCON is, what it does and how to get going", "Get started"),
    Guide("user-guide", "Using FALCON", "docs/USER_GUIDE.md", "Every page explained: Live, Review, Sensors, Export and more", "Get started"),
    Guide("sensor-node", "Sensor node", "docs/SENSOR_NODE.md", "Install, pair, control and troubleshoot the Raspberry Pi node", "Sensor node"),
    Guide("parts", "Parts list", "hardware/PARTS.md", "The node's parts, connections and wiring notes", "Sensor node"),
    Guide("data-export", "Data export", "docs/DATA_EXPORT.md", "The Camtrap DP package and how each field is filled", "Data"),
    Guide("operations", "Data, backups and problems", "docs/OPERATIONS.md", "Where data lives, backups, clocks and troubleshooting", "Data"),
    Guide("install", "Install and update", "docs/INSTALL.md", "Installing FALCON on a computer, automatic start, updates", "Inference computer"),
    Guide("remote-access", "Remote access", "docs/REMOTE_ACCESS.md", "Private access from another device with Tailscale", "Inference computer"),
    Guide("architecture", "How FALCON works", "docs/ARCHITECTURE.md", "The parts, how data flows and the APIs", "Reference"),
    Guide("security", "Security and privacy", "SECURITY.md", "What stays private, the trust model, reporting problems", "Reference"),
    Guide("licenses", "Models and licenses", "docs/model-licenses.md", "Where the models come from and their licenses", "Reference"),
    Guide("maintaining", "Keeping these guides current", "docs/MAINTAINING_DOCS.md", "What to update when hardware or software changes", "Reference"),
]
HANDBOOKS = [
    Handbook(
        "node-build", "Node build handbook", "Parts, wiring, power, 3D-printed enclosure, assembly and first start",
        "FALCON-Node-Build-Handbook.html", "FALCON-Node-Build-Handbook.pdf",
    ),
    Handbook(
        "user-handbook", "User handbook", "All guides in one printable document",
        "FALCON-User-Handbook.html", "FALCON-User-Handbook.pdf",
    ),
]
HANDBOOK_FILES = {name for book in HANDBOOKS for name in (book.html, book.pdf) if name}


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"<[^>]+>", "", text).lower()).strip("-") or "section"


def _inline(text: str, link: Callable[[str, str], str]) -> str:
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append(f"<code>{html.escape(part[1:-1])}</code>")
            continue
        value = html.escape(part, quote=False)
        value = re.sub(
            r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m: link(str(m.group(1)), html.unescape(str(m.group(2)))), value,
        )
        value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)
        value = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", value)
        out.append(value)
    return "".join(out)


def render_markdown(text: str, link: Callable[[str, str], str], heading_offset: int = 0) -> tuple[str, list[dict[str, object]]]:
    """Return (html, headings). `link(label_html, target)` builds each link."""
    lines = text.splitlines()
    out: list[str] = []
    headings: list[dict[str, object]] = []
    used: set[str] = set()
    index = 0

    def inline(value: str) -> str:
        return _inline(value, link)

    def table(rows: list[str]) -> str:
        header = [cell.strip() for cell in rows[0].strip().strip("|").split("|")]
        body = [[cell.strip() for cell in row.strip().strip("|").split("|")] for row in rows[2:]]
        result = "<div class=\"table-wrap\"><table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in header) + "</tr></thead><tbody>"
        result += "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>" for row in body)
        return result + "</tbody></table></div>"

    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith("```"):
            language = stripped[3:].strip()
            block = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                block.append(lines[index])
                index += 1
            index += 1
            if language == "mermaid":
                continue  # GitHub draws these; the architecture page has the same diagram in text.
            out.append("<pre>" + html.escape("\n".join(block)) + "</pre>")
            continue
        heading = re.match(r"(#{1,4})\s+(.*)", stripped)
        if heading:
            level = min(6, len(heading.group(1)) + heading_offset)
            identifier = slugify(heading.group(2))
            base, number = identifier, 2
            while identifier in used:
                identifier, number = f"{base}-{number}", number + 1
            used.add(identifier)
            headings.append({"id": identifier, "text": re.sub(r"[`*]", "", heading.group(2)), "level": level})
            out.append(f'<h{level} id="{identifier}">{inline(heading.group(2))}</h{level}>')
            index += 1
            continue
        if stripped.startswith("|") and index + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[index + 1].strip()):
            rows = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(lines[index])
                index += 1
            out.append(table(rows))
            continue
        if re.match(r"^(\d+\.|-)\s", stripped):
            ordered = stripped[0].isdigit()
            items: list[list[str]] = []
            while index < len(lines):
                current = lines[index]
                match = re.match(r"^\s*(\d+\.|-)\s+(.*)", current)
                indent = len(current) - len(current.lstrip())
                if match and indent < 3:
                    items.append([inline(match.group(2))])
                elif current.strip() and indent >= 2 and items:
                    if current.strip().startswith("```"):
                        block = []
                        index += 1
                        while index < len(lines) and not lines[index].strip().startswith("```"):
                            block.append(lines[index].strip())
                            index += 1
                        items[-1].append("<pre>" + html.escape("\n".join(block)) + "</pre>")
                    elif current.strip().startswith("|"):
                        rows = []
                        while index < len(lines) and lines[index].strip().startswith("|"):
                            rows.append(lines[index].strip())
                            index += 1
                        index -= 1
                        items[-1].append(table(rows))
                    else:
                        items[-1].append(" " + inline(current.strip()))
                elif not current.strip() and index + 1 < len(lines) and lines[index + 1].startswith(("  ", "\t")):
                    pass
                else:
                    break
                index += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{''.join(item)}</li>" for item in items) + f"</{tag}>")
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
    return "\n".join(out), headings


class HelpLibrary:
    def __init__(self, docs_dir: Path):
        self.docs_dir = docs_dir
        self.root = docs_dir.parent

    def _linker(self, guide: Guide) -> Callable[[str, str], str]:
        folder = posixpath.dirname(guide.filename)

        def link(label: str, target: str) -> str:
            if target.startswith(("http://", "https://")):
                return f'<a href="{html.escape(target)}" target="_blank" rel="noopener noreferrer">{label}</a>'
            path, _, anchor = target.partition("#")
            if not path:
                return f'<a href="#/help/{guide.slug}/{html.escape(anchor)}">{label}</a>' if anchor else label
            resolved = posixpath.normpath(posixpath.join(folder, path))
            for other in GUIDES:
                if resolved == other.filename:
                    section = f"/{html.escape(anchor)}" if anchor else ""
                    return f'<a href="#/help/{other.slug}{section}">{label}</a>'
            name = posixpath.basename(resolved)
            for book in HANDBOOKS:
                if name in {book.html, book.pdf}:
                    return f'<a href="#/help/{book.slug}">{label}</a>'
            # Other repository files (source code, CAD) are named, not linked, inside the app.
            return f'<span class="repo-path" title="{html.escape(resolved)}">{label}</span>'

        return link

    def index(self) -> dict[str, object]:
        folder = self.docs_dir / "handbooks"
        return {
            "guides": [
                {"slug": g.slug, "title": g.title, "summary": g.summary, "section": g.section}
                for g in GUIDES if (self.root / g.filename).is_file()
            ],
            "handbooks": [
                {
                    "slug": b.slug, "title": b.title, "summary": b.summary,
                    "html": f"/api/help/files/{b.html}" if b.html and (folder / b.html).is_file() else None,
                    "pdf": f"/api/help/files/{b.pdf}" if b.pdf and (folder / b.pdf).is_file() else None,
                }
                for b in HANDBOOKS
            ],
        }

    def guide(self, slug: str) -> dict[str, object]:
        guide = next((item for item in GUIDES if item.slug == slug), None)
        if guide is None or not (self.root / guide.filename).is_file():
            raise KeyError(slug)
        path = self.root / guide.filename
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"^#\s+.*\n", "", text, count=1)
        body, headings = render_markdown(text, self._linker(guide))
        return {
            "slug": guide.slug, "title": guide.title, "summary": guide.summary, "section": guide.section,
            "source": guide.filename, "html": body, "headings": headings,
        }

    def search(self, query: str, limit: int = 20) -> list[dict[str, object]]:
        words = [word for word in re.findall(r"\w+", query.lower()) if len(word) > 1]
        if not words:
            return []
        results: list[tuple[int, dict[str, object]]] = []
        for guide in GUIDES:
            try:
                page = self.guide(guide.slug)
            except KeyError:
                continue
            sections = re.split(r'(?=<h[2-6] id=")', str(page["html"]))
            for section in sections:
                identifier = re.match(r'<h[2-6] id="([^"]+)">(.*?)</h[2-6]>', section)
                heading = re.sub(r"<[^>]+>", "", identifier.group(2)) if identifier else guide.title
                text = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", section))).strip()
                lowered = text.lower()
                if not all(word in lowered for word in words):
                    continue
                score = sum(lowered.count(word) for word in words) + 5 * sum(word in heading.lower() for word in words)
                position = min(lowered.find(word) for word in words)
                start = max(0, position - 80)
                snippet = ("…" if start else "") + text[start:start + 220] + ("…" if start + 220 < len(text) else "")
                results.append((score, {
                    "slug": guide.slug, "guide": guide.title, "section": identifier.group(1) if identifier else None,
                    "heading": heading, "snippet": snippet,
                }))
        results.sort(key=lambda item: -item[0])
        return [item for _, item in results[:limit]]

    def file(self, name: str) -> Path:
        if name not in HANDBOOK_FILES:
            raise KeyError(name)
        path = self.docs_dir / "handbooks" / name
        if not path.is_file():
            raise KeyError(name)
        return path
