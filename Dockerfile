# syntax=docker/dockerfile:1@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32

ARG PYTHON_IMAGE=python:3.14-slim-trixie@sha256:cae66f2ef0ec51a9891263eeee7f987dacf0a9879e8aa9353d5606e0530619a5

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
 && apt-get upgrade --quiet --assume-yes \
 && apt-get install --quiet --assume-yes --no-install-recommends \
        curl \
        ca-certificates \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Retrieve standalone Tailwind CLI into PATH (pin version) and DaisyUI components
ARG TARGETARCH
RUN case "${TARGETARCH}" in \
        "amd64") TAILWIND_ARCH="x64" ;; \
        "arm64") TAILWIND_ARCH="arm64" ;; \
        *) echo "Unsupported architecture: ${TARGETARCH}"; exit 1 ;; \
    esac; \
    curl --fail --silent --show-error --location --output /usr/local/bin/tailwindcss \
        "https://github.com/tailwindlabs/tailwindcss/releases/download/v4.2.1/tailwindcss-linux-${TAILWIND_ARCH}" \
 && chmod +x /usr/local/bin/tailwindcss \
 && curl --fail --silent --show-error --location --output /usr/local/lib/daisyui.mjs https://github.com/saadeghi/daisyui/releases/download/v5.5.19/daisyui.mjs \
 && curl --fail --silent --show-error --location --output /usr/local/lib/daisyui-theme.mjs https://github.com/saadeghi/daisyui/releases/download/v5.5.19/daisyui-theme.mjs

# Retrieve `uv` from the third-party image (pin version)
COPY --from=ghcr.io/astral-sh/uv:0.10.9@sha256:10902f58a1606787602f303954cea099626a4adb02acbac4c69920fe9d278f82 /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Set `uv` environment variables (https://docs.astral.sh/uv/reference/environment/)
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# Copy required files to install dependancy
COPY .python-version pyproject.toml uv.lock /app/

# Sync common dependencies only (no default group, no project installation)
RUN --mount=type=cache,target=/root/.cache \
    uv sync \
        --locked \
        --no-install-project


###############################################################################
#                             Development Image                               #
#                      (add dev specific dependencies)                        #
###############################################################################
FROM base AS dev

# Set Python environment variables (https://docs.python.org/3/using/cmdline.html#environment-variables)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH

# Sync additional dev dependencies
RUN --mount=type=cache,target=/root/.cache \
    uv sync \
        --locked \
        --no-install-project \
        --group dev

# To use django-extensions 'graph_models' in local dev
ARG with_pygraphviz

RUN --mount=type=cache,target=/root/.cache \
    if [ "$with_pygraphviz" = true ]; then \
        apt-get update --quiet --assume-yes \
        && apt-get install --quiet --assume-yes --no-install-recommends \
            build-essential \
            libgraphviz-dev \
        && uv sync \
            --locked \
            --no-install-project \
            --group extensions; \
    fi


###############################################################################
#                                 Build Stage                                 #
#                     (compile psycopg[c] and build CSS)                      #
###############################################################################
FROM base AS build

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
    uv sync \
        --locked \
        --no-install-project \
        --group prod

# Copy application source. .dockerignore filters out .venv/, logs/, media/,
# the generated portal.css, and any host-side daisyui*.mjs files.
COPY ./ /app/

# Build the CSS bundle. Two preparation steps before invoking Tailwind:
#
#   1. Place the DaisyUI plugin files next to base.css. base.css references
#      them via '@plugin "./daisyui.mjs"' and '@plugin "./daisyui-theme.mjs"',
#      so they must resolve relative to that file. We copy from the
#      image-build cache in /usr/local/lib/.
#
#   2. base.css uses 'source("../../..")' to scope Tailwind's content scan to
#      /app/cms/, so the copied DaisyUI .mjs files now sit *inside* the scanned
#      tree. The host .gitignore (which excludes them) is not in the image, so
#      we need to prevent Tailwind from bloating portal.css if it treats the
#      plugin implementations as content (that would emit every class-like token
#      they contain). base.css guards against this with '@source not "./daisyui.mjs"'
#      and '@source not "./daisyui-theme.mjs"'.
RUN cp /usr/local/lib/daisyui.mjs /app/cms/static/cms/css/daisyui.mjs \
    && cp /usr/local/lib/daisyui-theme.mjs /app/cms/static/cms/css/daisyui-theme.mjs \
    && tailwindcss \
        --input /app/cms/static/cms/css/base.css \
        --output /portal.css \
        --no-cache \
        --minify


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
 && apt-get upgrade --quiet --assume-yes \
 && apt-get install --quiet --assume-yes --no-install-recommends \
        libpq5 \
        ca-certificates \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Create non-root group and user `app`
RUN groupadd --system --gid 800 app \
 && useradd --system --no-user-group --home-dir /app --uid 800 --gid 800 app

# Working directory
WORKDIR /app

# Copy pre-built virtual environment from build stage
COPY --from=build --chown=app:app /app/.venv /app/.venv

# Copy application code (filtered by .dockerignore)
COPY --chown=app:app ./ /app/

# Retrieve compiled CSS from build stage
COPY --from=build --chown=app:app /portal.css /app/cms/static/cms/css/portal.css

# TODO: ensure we bring over the collected, compressed, and hashed static files

# Remove unused files from final build
RUN rm -f pyproject.toml \
          uv.lock \
          cms/static/cms/css/base.css

# Make entrypoint script executable
RUN chmod +x prod-entrypoint.sh

# Switch to non-root user, expose port, and set entrypoint
USER app
EXPOSE 8000
ENTRYPOINT ["./prod-entrypoint.sh"]
