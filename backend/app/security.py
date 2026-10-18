"""Browser isolation, bounded control requests, and optional upload limits."""

from starlette.datastructures import Headers
from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

LOCAL_ORIGINS = frozenset(
    f"http://{host}:{port}"
    for host in ("localhost", "127.0.0.1", "[::1]")
    for port in (5173, 8000)
)
MAX_JSON_BYTES = 1024**2
# Added only when an explicit file-size limit is configured.
MULTIPART_OVERHEAD_BYTES = 1024**2


def local_browser_request(headers: Headers) -> bool:
    # Origin-less local tools remain supported. Browsers cannot forge these
    # headers; Host validation independently prevents DNS rebinding.
    origin = headers.get("origin")
    return (
        (not origin or origin in LOCAL_ORIGINS)
        and headers.get("sec-fetch-site") != "cross-site"
    )


class LocalRequestPolicyMiddleware:
    def __init__(self, app: ASGIApp, upload_limit_bytes: int | None = None):
        self.app = app
        self.upload_request_limit = (
            upload_limit_bytes + MULTIPART_OVERHEAD_BYTES
            if upload_limit_bytes is not None else None
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        private_api = scope.get("path", "").startswith("/api/")
        help_file = scope.get("path", "").startswith("/api/help/files/")
        pdf = help_file and scope.get("path", "").endswith(".pdf")
        if private_api and not scope.get("falcon.remote_authenticated") and not local_browser_request(headers):
            await JSONResponse(
                {"detail": "Requests must originate from the local application"}, status_code=403
            )(scope, receive, send)
            return
        limit = (
            self.upload_request_limit
            if scope.get("path") == "/api/videos/upload"
            else MAX_JSON_BYTES
        )
        rejection = JSONResponse(
            {"detail": "Request exceeds the local upload or request size limit"}, status_code=413
        )
        if length := headers.get("content-length"):
            try:
                if int(length) < 0:
                    raise ValueError()
                oversized = limit is not None and int(length) > limit
            except ValueError:
                await JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)(
                    scope, receive, send
                )
                return
            if oversized:
                await rejection(scope, receive, send)
                return
        consumed = 0
        exceeded = False
        rejected = False

        async def bounded_receive() -> Message:
            nonlocal consumed, exceeded
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if limit is not None and consumed > limit:
                    exceeded = True
                    # Starlette closes partial spooled uploads on parsing
                    # errors. Its normal 400 is replaced by 413 below.
                    raise MultiPartException("Request body exceeds the size limit")
            return message

        async def secure_send(message: Message) -> None:
            nonlocal rejected
            if exceeded:
                if not rejected:
                    rejected = True
                    await rejection(scope, receive, send)
                return
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                if help_file:
                    # Handbooks may be shown inside FALCON's own Help page, and only there.
                    # The HTML handbook may not fetch anything (such as web fonts) from outside.
                    framing = [
                        (b"x-frame-options", b"SAMEORIGIN"),
                        (b"content-security-policy", b"frame-ancestors 'self'" if pdf else
                         b"default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'self'"),
                    ]
                else:
                    framing = [
                        (b"x-frame-options", b"DENY"),
                        (b"content-security-policy", b"frame-ancestors 'none'"),
                    ]
                response_headers += [
                    (b"x-content-type-options", b"nosniff"),
                    *framing,
                    (b"referrer-policy", b"no-referrer"),
                ]
                if private_api:
                    # Saved profiles, observations, and camera frames must not
                    # remain in the browser cache after the application closes.
                    response_headers = [
                        (key, value)
                        for key, value in response_headers
                        if key.lower() != b"cache-control"
                    ]
                    response_headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": response_headers}
            await send(message)

        try:
            await self.app(scope, bounded_receive, secure_send)
        except MultiPartException:
            if not exceeded:
                raise
            if not rejected:
                await rejection(scope, receive, send)
