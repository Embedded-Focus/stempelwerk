FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim@sha256:7cf77f594be8042dab6daa9fe326f90962252268b4f120a7f5dccce4d947e6c1

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV PATH="/app/.venv/bin:${PATH}"

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY demo ./demo

RUN uv sync --frozen --no-dev

EXPOSE 8765

CMD ["uvicorn", "stempelwerk.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8765"]
