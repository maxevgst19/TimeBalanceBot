"""Демо-хостинг мини-приложения без регистраций и настройки сайтов.

Поднимает статический сервер с папкой miniapp/ на случайном порту
и пробрасывает его наружу через localhost.run (обычный ssh, без аккаунта).
В результате получается публичный HTTPS-URL, который можно открыть из MAX.
"""

import gzip
import http.server
import logging
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

MINIAPP_DIR = (Path(__file__).resolve().parent.parent / "miniapp").resolve()
URL_RE = re.compile(r"https://[a-z0-9-]+\.lhr\.life", re.IGNORECASE)
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
}


class _AppHandler(http.server.BaseHTTPRequestHandler):
    """Раздаёт файлы из miniapp/, сжимая каждый ответ gzip.

    Сжатие важно: бесплатный туннель обрывает большие ответы. Страница
    собрана в два файла — index.html со встроенным CSS и app.min.js, —
    поэтому даже на медленной связи хватает двух небольших запросов.
    """

    protocol_version = "HTTP/1.1"
    server_version = "TimeBalanceHost"

    def _resolve(self):
        path = self.path.split("?", 1)[0]
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (MINIAPP_DIR / rel).resolve()
        if target != MINIAPP_DIR and MINIAPP_DIR not in target.parents:
            return None
        return target if target.is_file() else None

    def do_GET(self) -> None:
        target = self._resolve()
        if target is None:
            self.send_error(404)
            return

        try:
            body = target.read_bytes()
        except OSError:
            self.send_error(500)
            return

        gzipped = "gzip" in (self.headers.get("Accept-Encoding") or "")
        if gzipped:
            body = gzip.compress(body, 9)

        content_type = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        if content_type.startswith("text/html"):
            cache = "no-cache"
        elif "v=" in self.path:
            cache = "public, max-age=604800, immutable"
        else:
            cache = "public, max-age=60"

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        if gzipped:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_HEAD(self) -> None:
        target = self._resolve()
        if target is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def log_message(self, fmt, *args):  # без спама в консоль
        pass


class DemoHost:
    """Локальный сервер + ssh-туннель. url заполняется после подключения."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self.url: str | None = None
        self.port: int | None = None
        self._server: http.server.ThreadingHTTPServer | None = None
        self._ssh: subprocess.Popen | None = None
        self._ready = threading.Event()

    # ------------------------------------------------------------------ запуск
    def start(self) -> str | None:
        try:
            self._server = http.server.ThreadingHTTPServer(
                ("127.0.0.1", 0), _AppHandler
            )
        except OSError as exc:
            logging.warning("Не удалось поднять локальный сервер: %s", exc)
            return None

        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

        ssh = shutil.which("ssh")
        if not ssh:
            logging.warning("ssh не найден — останется кнопка open_app")
            return None

        cmd = [
            ssh,
            "-o", "StrictHostKeyChecking=no",
            "-o", f"UserKnownHostsFile={os.devnull}",
            "-o", "ServerAliveInterval=30",
            "-R", f"80:127.0.0.1:{self.port}",
            "nokey@localhost.run",
        ]
        try:
            self._ssh = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            logging.warning("Не удалось запустить туннель: %s", exc)
            return None

        threading.Thread(target=self._read_tunnel, daemon=True).start()

        if self._ready.wait(self.timeout):
            return self.url

        logging.warning("Туннель не ответил за %.0f с", self.timeout)
        return None

    def _read_tunnel(self):
        assert self._ssh is not None and self._ssh.stdout is not None
        for line in self._ssh.stdout:
            match = URL_RE.search(line)
            if match and not self.url:
                self.url = match.group(0)
                self._ready.set()

    # ------------------------------------------------------------------ стоп
    def stop(self):
        if self._ssh and self._ssh.poll() is None:
            self._ssh.terminate()
            try:
                self._ssh.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._ssh.kill()
        if self._server:
            self._server.shutdown()
            self._server.server_close()
