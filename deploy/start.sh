#!/usr/bin/env bash
# Start the deployment container: migrations (idempotent), then API, job worker and nginx. If any of
# the three exits, the container exits so the host restarts it (Render does).
set -e
cd /app
alembic upgrade head

sed "s/__PORT__/${PORT:-10000}/" /etc/nginx/sitescout.conf.template > /etc/nginx/nginx.conf

uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers &
python -m app.jobs.worker &
nginx -g 'daemon off;' &

wait -n
exit 1
