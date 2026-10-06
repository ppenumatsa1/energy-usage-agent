"""App Insights export: health probes are not traced and chat traces are not sampled away."""

import logging
import os
import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from energy_usage_shared import telemetry


@pytest.fixture
def fresh(monkeypatch):
    monkeypatch.setattr(telemetry, "_configured", False)
    for name in (*telemetry.TELEMETRY_ENV_DEFAULTS, "OTEL_SERVICE_NAME"):
        monkeypatch.delenv(name, raising=False)
    calls = []
    fake = types.ModuleType("azure.monitor.opentelemetry")
    fake.configure_azure_monitor = lambda **kw: calls.append(kw)
    monkeypatch.setitem(sys.modules, "azure.monitor.opentelemetry", fake)
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield calls
    root.handlers, root.level = handlers, level


def test_defaults_applied_before_azure_monitor(fresh):
    telemetry.configure_telemetry("svc", "InstrumentationKey=00000000-0000-0000-0000-000000000000")
    assert fresh, "configure_azure_monitor not called"
    for name, value in telemetry.TELEMETRY_ENV_DEFAULTS.items():
        assert os.environ[name] == value


def test_environment_overrides_win(fresh, monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_SAMPLER_ARG", "0.25")
    telemetry.configure_telemetry("svc", "InstrumentationKey=00000000-0000-0000-0000-000000000000")
    assert os.environ["OTEL_TRACES_SAMPLER_ARG"] == "0.25"


def test_no_export_without_connection_string(fresh):
    telemetry.configure_telemetry("svc", None)
    assert fresh == []


def test_contrib_fastapi_instrumentor_disabled(fresh):
    telemetry.configure_telemetry("svc", "InstrumentationKey=00000000-0000-0000-0000-000000000000")
    assert fresh[0]["instrumentation_options"] == {"fastapi": {"enabled": False}}


def test_healthz_is_not_traced():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    app = FastAPI(telemetry={**telemetry.FASTAPI_TELEMETRY, "tracer_provider": provider})

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/status")
    def status() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(app)
    client.get("/healthz")
    assert exporter.get_finished_spans() == ()
    client.get("/api/status")
    assert any(s.name == "GET /api/status" for s in exporter.get_finished_spans())
