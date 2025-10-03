#!/bin/sh

# THIS IS JUST A ROUGH DRAFT LAYOUT FOR NOW, IT NEEDS TO BE PROPERLY ADAPTED TO OUR PRODUCTION DEPLOYMENT NEEDS.
# Some TODOs:
# - Add proper logging
# - Add proper error handling (e.g. 500 error page)
# - Add proper monitoring (e.g. healthcheck)
# - Add proper security (e.g. SSL)
# - Add proper scalability (e.g. load balancing)

# Exit on error and treat unset variables as errors
set -eu

source ./.env
# Export database URL environment variable
export DATABASE_URL="postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"

# REVIEW: Database connection in production
wait-for-it "${POSTGRES_HOST}:${POSTGRES_PORT}" -t 30

# Prepare database and static files
python manage.py migrate --noinput

# If first arg looks like a flag, assume we want to run gunicorn
if [ "${1:-}" = "" ] || [ "${1#-}" != "$1" ]; then
  set -- gunicorn core.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers ${GUNICORN_WORKERS:-2} \
    --threads ${GUNICORN_THREADS:-4} \
    --worker-class gthread \
    --worker-tmp-dir /dev/shm \
    --forwarded-allow-ips='*' \
    --access-logfile -
fi

exec "$@"





