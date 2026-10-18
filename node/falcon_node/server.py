"""Signed HTTP control API for the inference node, plus a public status page.

Public (no secrets): GET /  and  GET /api/v1/info
Signed (pairing key): everything else, see docs/SENSOR_NODE.md for the list.
"""

import html
import json
import logging
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from falcon_node.agent import Agent
from falcon_node.auth import AuthError

log = logging.getLogger("falcon-node.api")
MAX_BODY = 64 * 1024


class RequestError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _component_rows(status: dict[str, Any]) -> str:
    rows = []
    for name, item in status["components"].items():
        if not item["present"]:
            state = "not detected"
        elif not item["enabled"]:
            state = "switched off"
        else:
            state = item.get("state") or "ready"
        rows.append(
            f"<tr><th>{html.escape(name.title())}</th><td>{html.escape(item.get('description') or '—')}</td>"
            f"<td>{html.escape(str(state))}</td></tr>"
        )
    return "".join(rows)


def status_page(agent: Agent) -> str:
    status = agent.status()
    stream, system = status["stream"], status["system"]
    contact = "never" if agent.last_contact is None else "within the last minute"
    if agent.last_contact is not None:
        import time

        seconds = time.monotonic() - agent.last_contact
        contact = "within the last minute" if seconds < 60 else f"{seconds / 60:.0f} minutes ago"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="10">
<title>{html.escape(status['name'])} · FALCON sensor node</title>
<style>
:root{{color-scheme:light dark;--bg:#f5f7f9;--card:#fff;--ink:#22303a;--muted:#5d6b77;--line:#d3dce3;--ok:#28603d}}
@media (prefers-color-scheme:dark){{:root{{--bg:#14191e;--card:#1c2329;--ink:#e9edf1;--muted:#adb9c3;--line:#3c4853;--ok:#9bd0b2}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:760px;margin:0 auto;padding:24px 16px}}
h1{{font-size:1.4rem;margin:0}} p{{color:var(--muted);margin:.25rem 0 1.25rem}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:0 0 16px}}
table{{width:100%;border-collapse:collapse}} th,td{{text-align:left;padding:6px 8px;border-top:1px solid var(--line)}}
th{{width:30%;font-weight:600}} .state{{font-weight:700;color:var(--ok)}}
</style></head><body><main>
<h1>{html.escape(status['name'])}</h1>
<p>FALCON sensor node {html.escape(status['version'])} · ID <code>{html.escape(status['node_id'])}</code> ·
{html.escape(system['board'])}</p>
<section><table>
<tr><th>Stream</th><td colspan="2"><span class="state">{html.escape(stream['state'])}</span>
 · rtsp port {stream['rtsp_port']} · {stream['readers']} reader(s)</td></tr>
{_component_rows(status)}
<tr><th>Readings waiting</th><td colspan="2">{status['readings_queued']}</td></tr>
<tr><th>Last FALCON contact</th><td colspan="2">{html.escape(contact)}</td></tr>
<tr><th>Clock</th><td colspan="2">{'synchronized' if status['clock']['synchronized'] else 'not synchronized'}
 ({html.escape(status['clock']['source'])})</td></tr>
<tr><th>Addresses</th><td colspan="2">{html.escape(', '.join(system['addresses']) or '—')}</td></tr>
</table></section>
<p>To connect: in FALCON open <b>Sensors → Add sensor node</b>, enter this node's address and the
pairing key printed by the installer (also in <code>/etc/falcon-node/node.conf</code>).</p>
</main></body></html>"""


def make_handler(agent: Agent) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "falcon-node"
        sys_version = ""

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send(self, status: int, payload: Any, content_type: str = "application/json") -> None:
            body = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> bytes:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise RequestError(411, "Content-Length is required") from None
            if not 0 <= length <= MAX_BODY:
                raise RequestError(413, "Request body is too large")
            return self.rfile.read(length) if length else b""

        def _json(self, body: bytes) -> dict[str, Any]:
            try:
                value = json.loads(body or b"{}")
            except ValueError:
                raise RequestError(400, "Send a JSON object") from None
            if not isinstance(value, dict):
                raise RequestError(400, "Send a JSON object")
            return value

        def _authenticate(self, body: bytes) -> None:
            try:
                ts = agent.verifier.verify(self.headers.get("Authorization"), self.command, self.path, body)
            except AuthError as exc:
                raise RequestError(401, str(exc)) from None
            agent.caller_time(ts)

        def _handle(self) -> None:
            try:
                body = self._body()
                if self.command == "GET" and self.path == "/":
                    self._send(200, status_page(agent), "text/html")
                    return
                if self.command == "GET" and self.path == "/api/v1/info":
                    self._send(200, agent.info())
                    return
                if not self.path.startswith("/api/v1/"):
                    raise RequestError(404, "Not found")
                self._authenticate(body)
                self._send(200, self._route(self.command, self.path[len("/api/v1"):], self._json(body)))
            except RequestError as exc:
                self._send(exc.status, {"detail": str(exc)})
            except (ValueError, KeyError) as exc:
                self._send(422, {"detail": str(exc) if isinstance(exc, ValueError) else "Unknown component"})
            except Exception:
                log.exception("Request failed")
                self._send(500, {"detail": "The sensor node could not complete the request"})

        def _route(self, method: str, path: str, data: dict[str, Any]) -> Any:
            if method == "GET" and path == "/status":
                return agent.status()
            if method == "POST" and path == "/stream":
                agent.set_stream(str(data.get("action")))
                return agent.status()
            if method == "PUT" and (match := re.fullmatch(r"/components/([a-z]+)", path)):
                agent.set_component(match.group(1), data.get("enabled"))  # type: ignore[arg-type]
                return agent.status()
            if method == "PUT" and path == "/camera":
                agent.update_camera(data)
                return agent.status()
            if method == "PUT" and path == "/microphone":
                agent.update_microphone(data)
                return agent.status()
            if method == "POST" and path == "/readings/pull":
                limit = data.get("limit", 200)
                if isinstance(limit, bool) or not isinstance(limit, int):
                    raise ValueError("limit must be a whole number")
                return agent.pull(data.get("ack", []), limit)
            if method == "POST" and path == "/system":
                agent.system_action(str(data.get("action")))
                return {"accepted": True}
            raise RequestError(404, "Not found")

        do_GET = do_POST = do_PUT = _handle

        def do_DELETE(self) -> None:
            self._send(405, {"detail": "Method not allowed"})

    return Handler


def serve(agent: Agent, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, agent.config.api_port), make_handler(agent))
    server.daemon_threads = True
    return server
