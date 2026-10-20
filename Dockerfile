# Single image for every environment (R1.6). Configuration and secrets are injected
# as environment variables at run time; nothing secret is copied into the image (R2.7).
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install the locked runtime dependencies first, so this layer is reused between builds.
COPY pyproject.toml uv.lock .python-version README.md ./
COPY src/dimonapp/__init__.py src/dimonapp/__init__.py
RUN uv sync --frozen --no-dev

COPY alembic.ini ./
COPY .streamlit/config.toml .streamlit/config.toml
COPY src ./src

# Serve the iOS home screen icon, link it from Streamlit's page and replace Streamlit's
# default browser tab icon (R18.3).
RUN python -m dimonapp.ios_icon

# Serve the Android home screen icons and the web app manifest that names them (R18.10).
RUN python -m dimonapp.web_app_manifest

# Make the date picker French in every browser: French names, weeks starting on Monday (R18.1).
RUN python -m dimonapp.page_locale

# Run as an unprivileged user that can write the generated Streamlit secrets file and the
# local document storage (the default STORAGE_FOLDER; in GCP the files go to a bucket).
RUN useradd --create-home dimonapp \
    && mkdir local_storage \
    && chown dimonapp:dimonapp /app/.streamlit /app/local_storage
USER dimonapp

EXPOSE 8080

CMD ["python", "-m", "dimonapp.startup"]
