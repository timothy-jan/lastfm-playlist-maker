"""WSGI entry point for production servers."""

from src.web.app import create_app

app = create_app()
