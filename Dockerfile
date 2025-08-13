# syntax=docker/dockerfile:1

ARG PYTHON_IMAGE=python:3.13-slim-bookworm

###############################################################################
#                             Base Stage                                      #
#     (prepare common dependencies and environment for dev and prod)          #
###############################################################################
FROM ${PYTHON_IMAGE} AS base

# Sets default shell to `sh -exc`:
# -e  exit on error
# -x  write commands to standard error
# -c  read commands from the command_string operand
SHELL ["sh", "-exc"]

# Avoid interactive prompts during package operations
ENV DEBIAN_FRONTEND=noninteractive

# Install curl and CA certs, clean in same layer (no development tools here)
RUN apt-get update --quiet --assume-yes \
 && apt-get install --quiet --assume-yes --no-install-recommends \
        curl \
        ca-certificates \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Retrieve `uv` from the third-party image (pin version)
COPY --from=ghcr.io/astral-sh/uv:0.8.10 /uv /usr/local/bin/uv

# Set `uv` environment variables (https://docs.astral.sh/uv/reference/environment/)
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# Retrieve standalone Tailwind CLI into PATH (pin version)
RUN curl --fail --silent --show-error --location --output /usr/local/bin/tailwindcss \
        "https://github.com/tailwindlabs/tailwindcss/releases/download/v4.1.11/tailwindcss-linux-x64" \
 && chmod +x /usr/local/bin/tailwindcss

# Sync common dependencies only (no dev group, no project installation)
# NOTE: This layer is cached until uv.lock or pyproject.toml change, which are only
#       temporarily mounted into the base container since we don't need them in production
RUN --mount=type=cache,target=/root/.cache \
    --mount=type=bind,source=./.python-version,target=.python-version \
    --mount=type=bind,source=./uv.lock,target=uv.lock \
    --mount=type=bind,source=./pyproject.toml,target=pyproject.toml \
    uv sync \
        --locked \
        --no-group dev \
        --no-install-project


###############################################################################
#                             Development Image                               #
#                      (add dev specific dependencies)                        #
###############################################################################
FROM base AS dev

# Switch to application working directory
WORKDIR /app

# Set Python environment variables (https://docs.python.org/3/using/cmdline.html#environment-variables)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH

# Sync additional dev dependencies
RUN --mount=type=cache,target=/root/.cache \
    --mount=type=bind,source=./.python-version,target=.python-version \
    --mount=type=bind,source=./uv.lock,target=uv.lock \
    --mount=type=bind,source=./pyproject.toml,target=pyproject.toml \
    uv sync \
        --locked \
        --group dev \
        --no-install-project


###############################################################################
#                                 Build Stage                                 #
#                     (compile psycopg[c] and build CSS)                      #
###############################################################################
FROM base AS build

# Work in application directory
WORKDIR /app

# Build dependencies for psycopg[c]
RUN apt-get update --quiet --assume-yes \
 && apt-get install --quiet --assume-yes --no-install-recommends \
        gcc \
        libc6-dev \
        libpq-dev \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Sync prod group (this compiles psycopg[c] into .venv)
RUN --mount=type=cache,target=/root/.cache \
    --mount=type=bind,source=./.python-version,target=.python-version \
    --mount=type=bind,source=./uv.lock,target=uv.lock \
    --mount=type=bind,source=./pyproject.toml,target=pyproject.toml \
    uv sync \
        --locked \
        --no-group dev \
        --group prod \
        --no-install-project

# Compile and minify CSS (bind-mount content so Tailwind can scan templates)
RUN --mount=type=bind,source=./tailwind.config.js,target=tailwind.config.js \
    --mount=type=bind,source=./core/static/css/base.css,target=base.css \
    --mount=type=bind,source=./core/templates,target=core/templates \
    --mount=type=bind,source=./pages,target=pages \
    tailwindcss \
        --input base.css \
        --output portal.css \
        --minify


# NOTE: collectstatic is not run here because settings lack STATIC_ROOT.
# Consider adding Whitenoise and STATIC_ROOT for future optimisation


###############################################################################
#                             Production Image                                #
#                      (build minimal and clean image)                        #
###############################################################################
# TODO No perfect choice here because of different python compilation strategies
# Must profile our application and investigate python/alpine/ubuntu/debian
FROM ${PYTHON_IMAGE} AS production

# Set shell defaults
SHELL ["sh", "-exc"]

# Set Python runtime environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONOPTIMIZE=1 \
    PATH=/app/.venv/bin:$PATH

# Install runtime libraries required by psycopg[c] and clean up
RUN apt-get update --quiet --assume-yes \
 && apt-get install --quiet --assume-yes --no-install-recommends \
        libpq5 \
        ca-certificates \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Create non-root group and user `app`
RUN groupadd --system app \
 && useradd --system --no-user-group --home-dir /app --gid app app

# Working directory
WORKDIR /app

# Copy pre-built virtual environment from build stage
COPY --from=build --chown=app:app /app/.venv /app/.venv

# Copy application code (filtered by .dockerignore)
COPY --chown=app:app . /app

# Remove build-time files
RUN rm -f /app/pyproject.toml \
          /app/uv.lock \
          /app/tailwind.config.js \
          /app/core/static/css/base.css

# Retrieve compiled CSS from build stage
COPY --from=build --chown=app:app /app/portal.css /app/core/static/css/portal.css

# Make entrypoint script executable
RUN chmod +x /prod-entrypoint.sh

# NOTE: other static assets if whitenoise?

# Switch to non-root user, expose port, and set entrypoint
USER app
EXPOSE 8000
ENTRYPOINT ["/prod-entrypoint.sh"]
