###############################################################################
#                             Base Stage                                      #
#     (prepare common dependencies and environment for dev and prod)          #
###############################################################################
FROM python:3.13-slim-bookworm AS base

# Sets default shell to `sh -exc`:
# -e  exit on error
# -x  write commands to standard error
# -c  read commands from the command_string operand
SHELL ["sh", "-exc"]

# Avoid interactive prompts during package operations
ENV DEBIAN_FRONTEND=noninteractive

# Copy `uv` from the third-party image into the base container
COPY --from=ghcr.io/astral-sh/uv:0.8.6 /uv /usr/local/bin/uv

# Set `uv` environment variables (https://docs.astral.sh/uv/reference/environment/)
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# DO NOT add development tools here
RUN apt-get update --quiet --assume-yes && \
    apt-get install --quiet --assume-yes \
        --option APT::Install-Recommends=0 \
        --option APT::Install-Suggests=0 \
        curl

# Download standalone Tailwind CLI into PATH
RUN curl --silent --location --output /usr/local/bin/tailwindcss \
        https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-x64 && \
    chmod +x /usr/local/bin/tailwindcss

# Synchronise common dependencies WITHOUT the application itself.
# This layer is cached until uv.lock or pyproject.toml change, which are only
# temporarily mounted into the base container since we don't need them in production.
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
    PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app/.venv

# Synchronise additional dev dependencies
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
#            (compile necessary dependencies and prepare for prod)            #
###############################################################################
FROM base AS build

# Work in application directory
WORKDIR /app

# Copy source code into build container
COPY . /app

# Compile and minify CSS (scan templates for purge)
RUN tailwindcss \
    --input core/static/global/css/base.css \
    --output core/static/global/css/portal.css \
    --minify

# Compile psycopg[c] for faster PostgreSQL in production
RUN apt-get update --quiet --assume-yes && \
    apt-get install --quiet --assume-yes \
        --option APT::Install-Recommends=0 \
        --option APT::Install-Suggests=0 \
        build-essential \
        libpq-dev \
        pkg-config

# Sync prod dependency group (this compiles psycopg[c])
RUN --mount=type=cache,target=/root/.cache \
    --mount=type=bind,source=./.python-version,target=.python-version \
    --mount=type=bind,source=./uv.lock,target=uv.lock \
    --mount=type=bind,source=./pyproject.toml,target=pyproject.toml \
    uv sync \
        --locked \
        --no-group dev \
        --group prod \
        --no-install-project


# NOTE: collectstatic is not run here because settings lack STATIC_ROOT.
# Consider adding Whitenoise and STATIC_ROOT for future optimisation


###############################################################################
#                             Production Image                                #
#                      (build minimal and clean image)                        #
###############################################################################
# TODO No perfect choice here because of different python compilation strategies
# Must profile our application and investigate python/alpine/ubuntu/debian
FROM python:3.13-slim-bookworm AS production

# Sets default shell to `sh -exc`.
SHELL ["sh", "-exc"]

# Set Python environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app/.venv

# Install runtime libraries required by psycopg[c]
RUN apt-get update --quiet --assume-yes && \
    apt-get install --quiet --assume-yes \
        --option APT::Install-Recommends=0 \
        --option APT::Install-Suggests=0 \
        libpq5 \
        ca-certificates

# Clean up package lists to reduce image size
RUN apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Create non-root group and user `app`
RUN groupadd --system app && \
    useradd --system --no-user-group --home-dir /app --gid app app

# Working directory
WORKDIR /app

# Copy entrypoint script into container and make it executable
COPY prod-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Copy pre-built virtualenv (includes compiled psycopg[c])
COPY --from=build --chown=app:app /app/.venv /app/.venv

# Copy application code
# NOTE: exclude tailwind input base.css?
# NOTE: exclude static if whitenoise?
COPY --chown=app:app . /app

# Bring in compiled CSS from build stage
# NOTE: other static assets if whitenoise?
COPY --from=build --chown=app:app /app/core/static/global/css/portal.css /app/core/static/global/css/portal.css

# Switch to non-root user
USER app

# Set entrypoint script and stop signal for the container
ENTRYPOINT ["/docker-entrypoint.sh"]
