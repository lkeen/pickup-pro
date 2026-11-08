"""Development server. gunicorn imports wsgi:app instead."""

from app import create_app

app = create_app()

if __name__ == "__main__":
    # Bound to localhost: with debug on, Werkzeug's interactive debugger will
    # evaluate code sent to it, so this must not listen on every interface.
    app.run(host="127.0.0.1", port=5000, debug=app.debug)
