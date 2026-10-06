"""Entrypoint: `uvicorn energy_usage_app_api.main:create_app --factory`."""

from fastapi import FastAPI

from energy_usage_shared.telemetry import configure_telemetry

from .api.app import create_app as _create_app
from .bootstrap import build_container
from .config import AppApiSettings


def create_app() -> FastAPI:
    settings = AppApiSettings()
    configure_telemetry("app-api", settings.applicationinsights_connection_string, settings.log_level)
    return _create_app(build_container(settings))
