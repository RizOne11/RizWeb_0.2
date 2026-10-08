from __future__ import annotations

import json
import os
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("PUMA_EXECUTION_MODE", "worker")

import app as legacy
import durable_wsgi as runtime
import puma_worker


_STOP = threading.Event()
_LAST_SYNC = {"at": 0.0, "seen": 0, "error": None}


def health_payload():
    synced = _LAST_SYNC["at"] > 0 and time.time() - _LAST_SYNC["at"] <= max(30.0, puma_worker._poll_seconds() * 3)
    ready = bool(runtime._STORE.enabled and synced and not _LAST_SYNC["error"] and not _STOP.is_set())
    return {
        "ok": not _STOP.is_set(),
        "ready": ready,
        "service": "puma-worker",
        "engine_build": legacy.ENGINE_BUILD,
        "execution_mode": legacy._execution_mode(),
        "durable_storage": ready,
        "last_sync_at": _LAST_SYNC["at"],
        "last_seen_jobs": _LAST_SYNC["seen"],
        "last_error": _LAST_SYNC["error"],
    }


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/healthz":
            self.send_response(404)
            self.end_headers()
            return

        payload = health_payload()
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        # An unconfigured worker intentionally stays alive while waiting for
        # secrets. A configured but unhealthy worker must fail readiness.
        self.send_response(200 if payload["ready"] or not runtime._STORE.enabled else 503)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def worker_loop():
    while not _STOP.is_set():
        try:
            if not runtime._STORE.enabled:
                _LAST_SYNC.update(at=0.0, seen=0, error="storage_not_configured")
                _STOP.wait(puma_worker._poll_seconds())
                continue
            seen = puma_worker.sync_once(runtime=runtime, legacy=legacy)
            _LAST_SYNC.update(at=time.time(), seen=seen, error=None)
        except Exception as exc:
            _LAST_SYNC.update(
                at=time.time(),
                error=type(exc).__name__,
            )
            print(f"PUMA_WORKER_SYNC_ERROR {_LAST_SYNC['error']}", flush=True)
        _STOP.wait(puma_worker._poll_seconds())


def shutdown(*_args):
    _STOP.set()
    puma_worker._shutdown(legacy)


def main() -> int:
    if legacy._execution_mode() != "worker":
        raise SystemExit("PUMA worker service requires PUMA_EXECUTION_MODE=worker")
    port = int(os.getenv("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    thread = threading.Thread(target=worker_loop, name="puma-worker-loop", daemon=True)
    thread.start()

    print(
        f"PUMA_WORKER_SERVICE started build={legacy.ENGINE_BUILD} port={port} "
        f"poll={puma_worker._poll_seconds()}s durable={str(runtime._STORE.enabled).lower()}",
        flush=True,
    )

    try:
        # handle_request has a bounded timeout and observes our stop event;
        # serve_forever would require shutdown from a different thread.
        server.timeout = 0.5
        while not _STOP.is_set():
            server.handle_request()
    finally:
        _STOP.set()
        server.server_close()
        thread.join(timeout=5)

    print("PUMA_WORKER_SERVICE stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
