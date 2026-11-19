# Two stages so the build toolchain never reaches the runtime image.
FROM python:3.13-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Requirements are copied alone so this layer is cached until they change --
# without it, editing any source file reinstalls every dependency.
COPY requirements.txt .
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt


FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_ENV=production

# libpq for psycopg, curl for the container healthcheck. No compilers.
RUN apt-get update \
 && apt-get install --no-install-recommends -y libpq5 curl \
 && rm -rf /var/lib/apt/lists/*

# Never run as root: a container escape should not start from uid 0.
RUN useradd --create-home --shell /usr/sbin/nologin pickup

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=pickup:pickup . .

USER pickup

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

# Two workers per core plus one is the usual starting point for a
# request/response app that spends most of its time waiting on the database.
# --access-logfile - sends logs to stdout, where the container runtime collects
# them; the default is to discard them.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", \
     "--workers", "3", "--threads", "2", \
     "--timeout", "30", "--graceful-timeout", "30", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "wsgi:app"]
