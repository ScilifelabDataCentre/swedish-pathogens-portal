###############################################################################
#                             Development Image                               #
#                      (used only for local development)                      #
###############################################################################

FROM python:3.13-slim-bookworm AS dev

# Set dependency root directory and UV options
ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

# add dependency to PATH and PYTHONPATH
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app/.venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set working dir
WORKDIR /app

# Download curl
RUN apt-get update && apt-get install -y curl

# Download standalone Tailwind CLI into the PATH
RUN curl -sLo /usr/local/bin/tailwindcss \
        https://github.com/tailwindlabs/tailwindcss/releases/download/v4.1.11/tailwindcss-linux-x64 && \
    chmod u+x /usr/local/bin/tailwindcss

# Copy UV executable from UV image
COPY --from=ghcr.io/astral-sh/uv:0.8.2 /uv /usr/local/bin/uv

# Install python project (and dev) dependencies
RUN --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=.python-version,target=.python-version \
    uv sync \
        --locked \
        --dev \
        --no-install-project

###############################################################################
#                                 Runtime Stage                               #
###############################################################################

FROM python:3.13-bookworm AS runtime

# Following are required prerequistes for psycopg[c], by default they are
# all included in full bookworm distro. But keeping here for reference
# in case needed later. We can remove it at the end if not needed
# RUN apt-get update && \
#     apt-get install -y \
#     gcc \
#     python3-dev \
#     postgresql-dev \
#     libpq

# Copy UV executable from UV image
COPY --from=ghcr.io/astral-sh/uv:0.8.2 /uv /usr/local/bin/uv

# Copy relevant files to find dependencies
COPY pyproject.toml uv.lock .python-version ./

# Set dependency root directory and UV options
ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

# Install python dependencies
RUN uv sync \
        --locked \
        --group runtime \
        --no-dev \
        --no-install-project

###############################################################################
#                         Runtime Stage - Production                          #
###############################################################################

FROM python:3.13-bookworm AS production

# Add app venv to PATH and PYTHONPATH
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app/.venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set working dir
WORKDIR /app

# Create non-root group and user `app`.
RUN groupadd --system app && \
    useradd --system --no-user-group --home /app --gid app app

# Copy pre-built dependancy from 'build' stage
# assign ownership to `app` user and group.
COPY --from=build --chown=app:app /app/.venv /app/.venv

# Copy source code to image
COPY --chown=app:app . .
