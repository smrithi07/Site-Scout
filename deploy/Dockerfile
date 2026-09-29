# One-container deployment (Render free tier): nginx serves the built frontend and proxies /api to
# the FastAPI app; the job worker runs alongside. Same origin, so no CORS and no cross-service URLs.
# Build context: the repository root (render.yaml: dockerContext: .).

FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
ENV VITE_API_URL=/api
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SITESCOUT_CONFIG=/config/sitescout.yaml UPLOAD_DIR=/uploads
RUN apt-get update && apt-get install -y --no-install-recommends nginx \
    && rm -rf /var/lib/apt/lists/* && rm -f /etc/nginx/sites-enabled/default
WORKDIR /app
COPY backend/pyproject.toml .
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > /tmp/req.txt \
    && pip install --no-cache-dir -r /tmp/req.txt
COPY backend/ .
COPY config/ /config/
COPY --from=web /web/dist /srv/web
COPY deploy/nginx.conf.template /etc/nginx/sitescout.conf.template
COPY deploy/start.sh /start.sh
RUN chmod +x /start.sh && mkdir -p /uploads
EXPOSE 10000
CMD ["/start.sh"]
