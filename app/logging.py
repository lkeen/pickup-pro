"""Structured logging and request timing.

Flask's default access log is a line of text per request with no timing and no
correlation between the lines belonging to one request. That is fine until
something is slow in production and the only question worth answering is "slow
for whom, and on which request".

Every log line here is JSON with a request id, so a request's lines can be
gathered from a log aggregator by one field. In development the same events are
rendered as readable console lines instead, because JSON is unreadable in a
terminal and a format nobody reads gets ignored.
"""

import logging
import time
import uuid

import structlog
from flask import g, request

# Requests whose timing is noise: health checks fire every 30 seconds and static
# assets are served by a CDN or the reverse proxy in any real deployment.
QUIET_PATHS = ("/healthz", "/static/")

# Above this, a request is worth noticing regardless of what it was doing.
SLOW_REQUEST_MS = 500


def configure(app):
    """Set the log format and install the request hooks."""
    logger = configure_structlog(app)
    install_request_logging(app, logger)
    return logger


def configure_structlog(app):
    """Choose and install the global log format.

    Separate from the request hooks because structlog's configuration is global
    and can be reset at any time, whereas Flask refuses to register a
    before_request handler once an app has served a request.
    """
    json_logs = not app.debug and not app.testing

    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    renderer = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared, structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if app.debug else logging.INFO
        ),
        cache_logger_on_first_use=True,
    )

    app.logger.handlers.clear()
    app.logger.propagate = True

    return structlog.get_logger("pickup")


def install_request_logging(app, logger):
    @app.before_request
    def _start_timer():
        g.request_started = time.perf_counter()
        # Honour an upstream id if the load balancer set one, so a request can
        # be followed across services rather than only within this one.
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        structlog.contextvars.bind_contextvars(request_id=g.request_id)

    @app.after_request
    def _log_request(response):
        started = g.pop("request_started", None)
        if started is None or request.path.startswith(QUIET_PATHS):
            return response

        duration_ms = (time.perf_counter() - started) * 1000
        # Echo the id back so a user reporting a problem can quote it.
        response.headers["X-Request-ID"] = g.get("request_id", "")

        event = {
            # Also bound as a contextvar, which covers log lines emitted from
            # anywhere inside the request. Set explicitly here as well so the
            # access line carries it regardless of processor configuration.
            "request_id": g.get("request_id", ""),
            "method": request.method,
            "path": request.path,
            "status": response.status_code,
            "duration_ms": round(duration_ms, 1),
            "endpoint": request.endpoint,
        }
        if duration_ms >= SLOW_REQUEST_MS:
            logger.warning("slow_request", **event)
        elif response.status_code >= 500:
            logger.error("request_failed", **event)
        else:
            logger.info("request", **event)

        return response

    @app.teardown_request
    def _clear_context(exception=None):
        structlog.contextvars.clear_contextvars()
