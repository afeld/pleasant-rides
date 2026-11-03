# The app's image for deploying (see fly.toml). Python is the version CI and local development use.
FROM ghcr.io/astral-sh/uv:0.13.6-python3.14-trixie-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1

# dependencies first, so code changes don't reinstall them
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked
COPY . .

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080
# nothing changes the code in place, so don't watch it
CMD ["streamlit", "run", "app.py", "--server.port=8080", "--server.address=0.0.0.0", "--server.headless=true", "--server.runOnSave=false", "--server.fileWatcherType=none"]
