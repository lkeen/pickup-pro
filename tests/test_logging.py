"""Structured logging and request timing."""

import json

import structlog

from app.logging import configure_structlog


class TestRequestLogging:
    def test_every_response_carries_a_request_id(self, client):
        response = client.get("/")
        assert response.headers.get("X-Request-ID")

    def test_an_upstream_request_id_is_honoured(self, client):
        """So a request can be followed across services, not only within this
        one."""
        response = client.get("/", headers={"X-Request-ID": "upstream-abc123"})
        assert response.headers["X-Request-ID"] == "upstream-abc123"

    def test_ids_differ_between_requests(self, client):
        first = client.get("/").headers["X-Request-ID"]
        second = client.get("/").headers["X-Request-ID"]
        assert first != second

    def test_a_request_is_logged_with_its_duration(self, client):
        with structlog.testing.capture_logs() as logs:
            client.get("/")
        entries = [line for line in logs if line["event"] == "request"]
        assert entries, "no request log line emitted"
        entry = entries[0]
        assert entry["method"] == "GET"
        assert entry["path"] == "/"
        assert entry["status"] == 200
        assert isinstance(entry["duration_ms"], float)
        assert entry["request_id"]

    def test_health_checks_are_not_logged(self, client):
        """They fire every 30 seconds; logging them buries everything else."""
        with structlog.testing.capture_logs() as logs:
            client.get("/healthz")
        assert [line for line in logs if line.get("path") == "/healthz"] == []

    def test_static_assets_are_not_logged(self, client):
        with structlog.testing.capture_logs() as logs:
            client.get("/static/css/main.css")
        assert [line for line in logs if line.get("event") == "request"] == []

    def test_context_does_not_leak_between_requests(self, client):
        """A request id bound in one request must not appear in the next."""
        client.get("/", headers={"X-Request-ID": "first-request"})
        with structlog.testing.capture_logs() as logs:
            client.get("/", headers={"X-Request-ID": "second-request"})
        ids = {line.get("request_id") for line in logs if "request_id" in line}
        assert "first-request" not in ids


class TestLogFormat:
    def test_production_renders_json(self, app):
        """A log aggregator parses fields; it does not parse prose.

        Uses a bare Flask app rather than create_app(): the factory re-runs
        every extension's init_app, which resets the rate limiter that the
        session fixture deliberately switched off, and the fallout lands in
        whichever tests happen to run next.
        """
        from flask import Flask

        probe = Flask(__name__)
        probe.debug = False
        probe.testing = False
        try:
            configure_structlog(probe)
            renderer = structlog.get_config()["processors"][-1]
            assert isinstance(renderer, structlog.processors.JSONRenderer)

            # And that the renderer actually produces parseable JSON.
            rendered = renderer(None, "info", {"event": "probe", "answer": 42})
            assert json.loads(rendered)["answer"] == 42
        finally:
            # structlog.configure() is global; put the test-suite format back.
            configure_structlog(app)

    def test_development_renders_readable_console_lines(self, app):
        """JSON is unreadable in a terminal, and a format nobody reads gets
        ignored."""
        configure_structlog(app)
        renderer = structlog.get_config()["processors"][-1]
        assert isinstance(renderer, structlog.dev.ConsoleRenderer)
