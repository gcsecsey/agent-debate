"""HTTP server for the debate viewer."""

from __future__ import annotations

import json
import logging
import webbrowser
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

logger = logging.getLogger(__name__)

DEBATE_SUBDIR = ".context/debate"


def scan_debates(cwd: str) -> list[dict]:
    """Scan for debate.json files and return summaries sorted newest first."""
    debate_root = Path(cwd) / DEBATE_SUBDIR
    if not debate_root.is_dir():
        return []

    summaries = []
    for debate_json in sorted(debate_root.glob("*/debate.json"), reverse=True):
        try:
            data = json.loads(debate_json.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Skipping malformed %s", debate_json)
            continue

        meta = data.get("meta", {})
        dedup = data.get("dedup") or {}
        disagreements = dedup.get("disagreements", [])

        summaries.append({
            "timestamp": debate_json.parent.name,
            "prompt": meta.get("prompt", ""),
            "providers": meta.get("providers", []),
            "disagreements_count": len(disagreements),
            "started_at": meta.get("started_at", ""),
        })

    return summaries


def load_debate(cwd: str, timestamp: str) -> dict | None:
    """Load a full debate.json by timestamp directory name."""
    debate_json = Path(cwd) / DEBATE_SUBDIR / timestamp / "debate.json"
    if not debate_json.is_file():
        return None
    try:
        return json.loads(debate_json.read_text())
    except (json.JSONDecodeError, OSError):
        return None


class DebateViewerHandler(BaseHTTPRequestHandler):
    """Routes requests to the viewer HTML and JSON API endpoints."""

    def __init__(self, cwd: str, *args, **kwargs):
        self.cwd = cwd
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        if self.path == "/api/debates":
            self._json_response(scan_debates(self.cwd))
        elif self.path.startswith("/api/debates/"):
            timestamp = self.path.split("/api/debates/", 1)[1]
            if "/" in timestamp or "\\" in timestamp or timestamp.startswith("."):
                self._error(HTTPStatus.BAD_REQUEST, "Invalid timestamp")
                return
            data = load_debate(self.cwd, timestamp)
            if data is None:
                self._error(HTTPStatus.NOT_FOUND, "Debate not found")
            else:
                self._json_response(data)
        elif self.path == "/" or self.path == "/index.html":
            self._serve_viewer()
        else:
            self._error(HTTPStatus.NOT_FOUND, "Not found")

    def _json_response(self, data: object) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_viewer(self) -> None:
        viewer_path = Path(__file__).parent / "viewer" / "index.html"
        if not viewer_path.is_file():
            self._error(HTTPStatus.NOT_FOUND, "Viewer not found")
            return
        body = viewer_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: HTTPStatus, message: str) -> None:
        body = json.dumps({"error": message}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Suppress default stderr logging."""
        pass


def start_server(
    cwd: str,
    port: int = 0,
    open_browser: bool = True,
) -> HTTPServer:
    """Create and return an HTTPServer (does not call serve_forever)."""
    handler = partial(DebateViewerHandler, cwd)
    server = HTTPServer(("127.0.0.1", port), handler)
    actual_port = server.server_address[1]

    if open_browser:
        webbrowser.open(f"http://localhost:{actual_port}")

    return server
