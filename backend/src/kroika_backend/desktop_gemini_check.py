"""Explicit diagnostic of native credentials and Gemini's real HTTPS/image transport."""

import base64
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import ssl
import sys
from threading import Thread
from types import SimpleNamespace
from uuid import uuid4

from kroika_contracts.resources import resource_root
from .desktop_bridge import DesktopBridge
from .desktop_preferences import Preferences


class GeminiLoopback:
    def __init__(self):
        self.key = "synthetic-diagnostic-" + uuid4().hex
        self.calls = []
        self.server = None
        self.thread = None
        self.original_ca = os.environ.get("SSL_CERT_FILE")
        self.original_no_proxy = {key: os.environ.get(key) for key in ("NO_PROXY", "no_proxy")}
        self.original_socks_proxy = {key: os.environ.get(key) for key in ("ALL_PROXY", "all_proxy")}

    def __enter__(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                content = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                payload = json.loads(content)
                authenticated = hmac.compare_digest(self.headers.get("x-goog-api-key", ""), owner.key)
                owner.calls.append({"path": self.path, "payload": payload, "authenticated": authenticated})
                if not authenticated:
                    response = {"error": {"status": "UNAUTHENTICATED"}}
                else:
                    parts = payload["contents"][0]["parts"]
                    text = "OK"
                    if any("inlineData" in item for item in parts):
                        text = (resource_root() / "examples/v1/example-ai-response.json").read_text(encoding="utf-8")
                    response = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}]}
                encoded = json.dumps(response).encode()
                self.send_response(200 if authenticated else 401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        try:
            self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            fixtures = resource_root() / "packaging/test_resources"
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(fixtures / "gemini-loopback-cert.pem", fixtures / "gemini-loopback-key.pem")
            self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
            self.url = f"https://127.0.0.1:{self.server.server_port}/v1beta"
            os.environ["SSL_CERT_FILE"] = str(fixtures / "gemini-loopback-cert.pem")
            for key in self.original_no_proxy:
                os.environ[key] = "127.0.0.1,localhost"
            for key in self.original_socks_proxy:
                os.environ[key] = "socks5://127.0.0.1:9"
            self.thread = Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            return self
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *_):
        if self.thread is not None:
            self.server.shutdown()
            self.thread.join(timeout=2)
        if self.server is not None:
            self.server.server_close()
        if self.original_ca is None:
            os.environ.pop("SSL_CERT_FILE", None)
        else:
            os.environ["SSL_CERT_FILE"] = self.original_ca
        for key, value in {**self.original_no_proxy, **self.original_socks_proxy}.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def configure_and_check(server, home, upstream, image_refs, request):
    preferences = Preferences(home)
    bridge = DesktopBridge(server, preferences, None)
    bridge._window = SimpleNamespace(get_current_url=lambda: server.url)
    payload = {**Preferences._values(server.settings), "provider": "gemini",
               "key_action": "set", "api_key": upstream.key, "remember": sys.platform == "win32"}
    saved = bridge.save_settings(payload)
    try:
        assert saved["ok"] and saved["value"]["has_key"]
        assert upstream.key not in preferences.path.read_text(encoding="utf-8")
        assert upstream.key not in json.dumps(saved)
        if sys.platform == "win32":
            assert saved["value"]["key_storage"] == "system"
            assert preferences.load(server.settings).gemini_api_key == upstream.key
        assert request("/api/v1/ai/providers")["default_provider"] == "gemini"
        request("/api/v1/ai/providers/gemini/check", "POST")
        analysis = json.loads((resource_root() / "examples/v1/example-ai-request.json").read_text(encoding="utf-8"))
        analysis.update(image_refs=image_refs, image_views=["front", "back"])
        result = request("/api/v1/garments/analyze-image?provider=gemini", "POST", analysis)
        assert result == json.loads((resource_root() / "examples/v1/example-ai-response.json").read_text(encoding="utf-8"))
        call = upstream.calls[-1]
        assert call["authenticated"] and call["path"] == "/v1beta/models/gemini-3.6-flash:generateContent"
        parts = call["payload"]["contents"][0]["parts"]
        photos = [item["inlineData"] for item in parts if "inlineData" in item]
        assert len(photos) == 2
        assert '"image_number":2,"view":"back"' in parts[0]["text"]
        for photo, reference in zip(photos, image_refs, strict=True):
            assert base64.b64decode(photo["data"]) == request(f"/api/v1/images/{reference}", raw=True)
        return preferences
    except BaseException:
        clear_key(preferences)
        raise


def clear_key(preferences):
    key_id = preferences.document.get("key_id")
    if key_id:
        assert preferences.vault.delete(preferences.service, key_id)
