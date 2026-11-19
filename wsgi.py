"""WSGI entry point.

manage.py runs the development server. This is what gunicorn imports, and it
deliberately does not call app.run(): a production server manages its own
workers and binding.
"""

from app import create_app

app = create_app()
