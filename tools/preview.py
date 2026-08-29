"""Serve the portfolio locally so you can see exactly what visitors will see."""
from __future__ import annotations

import contextlib
import functools
import sys
import http.server
import socket
import socketserver
import threading
import webbrowser

from common import C, ROOT, banner, ok, say


def free_port(preferred: int = 8765) -> int:
    for port in range(preferred, preferred + 20):
        with contextlib.closing(socket.socket()) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return 0


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: A002
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main() -> None:
    banner("Local preview")
    port = free_port()
    handler = functools.partial(Quiet, directory=str(ROOT))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        url = f"http://localhost:{port}/"
        ok(f"serving your portfolio at {C['b']}{C['cy']}{url}{C['r']}")
        say(f"{C['dim']}This is only on your computer - nobody else can see it.{C['r']}")
        say(f"{C['dim']}Close this window (or press Ctrl+C) when you are done.{C['r']}")
        if "--no-open" not in sys.argv:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  preview stopped")


if __name__ == "__main__":
    main()
