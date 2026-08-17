#!/usr/bin/env python3
"""Serve the Kane Condo browser shell and one external render package on loopback."""

from __future__ import annotations

import argparse
import functools
import ipaddress
import json
import mimetypes
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

CONFIG_FORMAT = "kane-condo-local-runtime-config"
CONFIG_VERSION = 1
MANIFEST_FILENAME = "render-package-manifest.json"


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def validate_loopback_host(host: str) -> str:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("Local runtime host must be an explicit loopback IP address") from exc
    if not address.is_loopback:
        raise ValueError("Local runtime may bind only to a loopback IP address")
    return host


def safe_relative_path(raw_path: str) -> Path:
    decoded = unquote(raw_path)
    if "\\" in decoded or "\x00" in decoded:
        raise ValueError("Invalid local resource path")
    parts = decoded.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Invalid local resource path")
    return Path(*parts)


class KaneLocalRequestHandler(SimpleHTTPRequestHandler):
    server_version = "KaneCondoLocal/1"

    def __init__(self, *args, app_root: Path, package_root: Path, **kwargs):
        self.app_root = app_root.resolve()
        self.package_root = package_root.resolve()
        super().__init__(*args, directory=str(self.app_root), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'",
        )
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if urlsplit(self.path).path == "/config.json":
            self._serve_config(head_only=False)
            return
        super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802
        if urlsplit(self.path).path == "/config.json":
            self._serve_config(head_only=True)
            return
        super().do_HEAD()

    def _serve_config(self, *, head_only: bool) -> None:
        payload = canonical_json_bytes(
            {
                "format": CONFIG_FORMAT,
                "package_manifest_url": f"/package/{MANIFEST_FILENAME}",
                "version": CONFIG_VERSION,
            }
        )
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)

    def translate_path(self, path: str) -> str:
        request_path = urlsplit(path).path
        if request_path == "/":
            return str(self.app_root / "index.html")
        if request_path.startswith("/package/"):
            raw_relative = request_path[len("/package/") :]
            root = self.package_root
        else:
            raw_relative = request_path.lstrip("/")
            root = self.app_root
        try:
            relative = safe_relative_path(raw_relative)
        except ValueError:
            return str(root / ".kane-condo-invalid-path")
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return str(root / ".kane-condo-invalid-path")
        return str(candidate)

    def list_directory(self, path: str):  # type: ignore[override]
        self.send_error(HTTPStatus.NOT_FOUND, "Directory listing is disabled")
        return None

    def guess_type(self, path: str) -> str:
        if path.endswith(".krf"):
            return "application/octet-stream"
        guessed, _ = mimetypes.guess_type(path)
        return guessed or "application/octet-stream"


def build_server(app_root: Path, package_root: Path, host: str, port: int) -> ThreadingHTTPServer:
    validate_loopback_host(host)
    app_root = app_root.resolve()
    package_root = package_root.resolve()
    if not app_root.is_dir():
        raise ValueError(f"Application root is not a directory: {app_root}")
    if not package_root.is_dir():
        raise ValueError(f"Package root is not a directory: {package_root}")
    if not 0 <= port <= 65535:
        raise ValueError("Port must be between 0 and 65535")
    handler = functools.partial(
        KaneLocalRequestHandler,
        app_root=app_root,
        package_root=package_root,
    )
    return ThreadingHTTPServer((host, port), handler)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_directory", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    app_root = Path(__file__).resolve().parents[1]
    try:
        server = build_server(app_root, args.package_directory, args.host, args.port)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    actual_host, actual_port = server.server_address[:2]
    print(f"Kane Condo local runtime: http://{actual_host}:{actual_port}/", flush=True)
    print(f"Render package: {args.package_directory.resolve()}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
