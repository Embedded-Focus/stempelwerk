FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV PATH="/app/.venv/bin:${PATH}"

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY demo ./demo

RUN uv sync --frozen --no-dev

EXPOSE 8765

CMD ["uvicorn", "org_clock_calendar.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8765"]
