# Build context: repo root (uv workspace). See azure.yaml.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_NO_CACHE=1
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY shared/pyproject.toml shared/
COPY services/energy-service/pyproject.toml services/energy-service/
COPY services/app-api/pyproject.toml services/app-api/
RUN uv sync --frozen --no-dev --package energy-usage-energy-service --no-install-workspace
COPY shared shared
COPY services/energy-service services/energy-service
RUN uv sync --frozen --no-dev --package energy-usage-energy-service --no-editable

FROM python:3.12-slim
RUN useradd --uid 10001 --no-create-home app
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
USER 10001
EXPOSE 8000
CMD ["uvicorn", "energy_usage_energy.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
