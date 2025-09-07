FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# Install uv and dependencies from pyproject.toml
RUN python -m venv .venv \
    && . .venv/bin/activate \
    && pip install --no-cache-dir --upgrade pip \
    && pip install uv \
    && uv sync

# Set the virtual environment as default for the container
ENV PATH="/app/.venv/bin:$PATH"

# Run the application.
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]

EXPOSE 8000