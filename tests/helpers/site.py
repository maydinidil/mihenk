"""A small website on 127.0.0.1 for tests. The network guard allows only loopback."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


@dataclass
class Route:
    status: int = 200
    body: bytes = b""
    content_type: str = "text/html; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)
    delay_s: float = 0.0


class LocalSite:
    def __init__(self) -> None:
        self.routes: dict[str, Route] = {}
        self.hits: list[str] = []
        self._server: ThreadingHTTPServer | None = None

    def add(
        self,
        path: str,
        body: str | bytes = b"",
        *,
        status: int = 200,
        content_type: str = "text/html; charset=utf-8",
        headers: dict[str, str] | None = None,
        delay_s: float = 0.0,
    ) -> None:
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.routes[path] = Route(status, data, content_type, dict(headers or {}), delay_s)

    def add_file(
        self, path: str, file: Path, content_type: str = "text/html; charset=utf-8"
    ) -> None:
        self.add(path, file.read_bytes(), content_type=content_type)

    def redirect(self, path: str, to: str, status: int = 302) -> None:
        self.add(path, b"", status=status, headers={"Location": to})

    @property
    def base_url(self) -> str:
        assert self._server is not None
        port = self._server.server_address[1]
        return f"http://127.0.0.1:{port}"

    def url(self, path: str) -> str:
        return self.base_url + path

    def __enter__(self) -> LocalSite:
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self._serve(head=False)

            def do_HEAD(self) -> None:
                self._serve(head=True)

            def _serve(self, *, head: bool) -> None:
                path = self.path.split("?", 1)[0]
                site.hits.append(path)
                route = site.routes.get(path)
                if route is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if route.delay_s:
                    time.sleep(route.delay_s)
                self.send_response(route.status)
                self.send_header("Content-Type", route.content_type)
                self.send_header("Content-Length", str(len(route.body)))
                for name, value in route.headers.items():
                    self.send_header(name, value)
                self.end_headers()
                if not head:
                    self.wfile.write(route.body)

            def log_message(self, format: str, *args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc: object) -> None:
        assert self._server is not None
        self._server.shutdown()
        self._server.server_close()
