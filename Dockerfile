###############################################################################
#                                 Build Stage                                 #
###############################################################################

FROM python:3.13-slim AS build

# Copy UV executable from UV image
COPY --from=ghcr.io/astral-sh/uv:0.8.2 /uv /usr/local/bin/uv

# Copy relevant files to find dependencies
COPY pyproject.toml uv.lock .python-version ./

# Set dependency root directory and
# add it to PATH and PYTHONPATH
ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app/.venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install dependencies
RUN uv sync \
        --locked \
        --no-python-downloads \
        --no-install-project \
        --link-mode copy \
        --compile-bytecode

###############################################################################
#                             Development Image                               #
###############################################################################

FROM build AS dev

# Set working dir
WORKDIR /app

# Copy all code
COPY . .

###############################################################################
#                         Runtime Stage - Production                          #
###############################################################################

FROM python:3.13-slim AS production

# Set working dir
WORKDIR /app

# Add app venv to PATH and PYTHONPATH
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app/.venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create non-root group and user `app`.
RUN groupadd --system app && \
    useradd --system --no-user-group --home /app --gid app app

# Copy pre-built dependancy from 'build' stage
# assign ownership to `app` user and group.
COPY --from=build --chown=app:app /app/.venv /app/.venv

# Copy source code to image
COPY --chown=app:app . .
