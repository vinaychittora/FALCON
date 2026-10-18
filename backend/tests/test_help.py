"""Built-in help pages, search and handbook files."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.help import render_markdown

DOCS = Path(__file__).resolve().parents[2] / "docs"


def test_markdown_is_escaped_and_structured() -> None:
    body, headings = render_markdown(
        "## Live view\n\nPress **Stop** <script>alert(1)</script> and see [guide](SENSOR_NODE.md#checks).\n\n"
        "| Key | Meaning |\n| --- | --- |\n| C | Confirm |\n\n1. First\n   ```\n   make start\n   ```\n2. Second\n",
        lambda label, target: f'<a href="{target}">{label}</a>',
    )
    assert "<script>" not in body and "&lt;script&gt;" in body
    assert '<h2 id="live-view">' in body and headings[0]["id"] == "live-view"
    assert "<strong>Stop</strong>" in body and "<table>" in body and "<pre>make start</pre>" in body
    assert '<a href="SENSOR_NODE.md#checks">guide</a>' in body


def test_help_api_serves_guides_search_and_handbooks(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path, docs_dir=DOCS))
    with TestClient(app) as client:
        index = client.get("/api/help").json()
        assert [guide["slug"] for guide in index["guides"]][:3] == ["start", "user-guide", "sensor-node"]
        assert index["handbooks"][0]["pdf"] == "/api/help/files/FALCON-Node-Build-Handbook.pdf"
        page = client.get("/api/help/guides/user-guide").json()
        assert page["title"] == "Using FALCON" and any(h["id"] == "live" for h in page["headings"])
        assert 'href="#/help/sensor-node"' in client.get("/api/help/guides/user-guide").json()["html"]
        assert client.get("/api/help/guides/unknown").status_code == 404
        start = client.get("/api/help/guides/start").json()
        assert 'href="#/help/sensor-node"' in start["html"] and "flowchart" not in start["html"]
        parts = client.get("/api/help/guides/parts").json()
        assert parts["source"] == "hardware/PARTS.md" and 'href="#/help/sensor-node"' in parts["html"]
        results = client.get("/api/help/search", params={"q": "pairing key"}).json()["results"]
        assert results and results[0]["slug"] in {"sensor-node", "user-guide"}
        pdf = client.get("/api/help/files/FALCON-Node-Build-Handbook.pdf")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
        assert pdf.headers["x-frame-options"] == "SAMEORIGIN" and "inline" in pdf.headers["content-disposition"]
        book = client.get("/api/help/files/FALCON-Node-Build-Handbook.html")
        assert "default-src 'none'" in book.headers["content-security-policy"]
        assert "fonts.googleapis.com" not in book.text and "Node build handbook" in book.text
        assert client.get("/api/help/files/..%2F..%2FREADME.md").status_code == 404
        assert client.get("/api/help/files/secrets.pdf").status_code == 404
        assert client.get("/api/help").headers["x-frame-options"] == "DENY"
