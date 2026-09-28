# Savo SiteScout

Expansion-intelligence platform for Savomart (neighbourhood grocery, Chennai). Built for the
Savomart full-stack hackathon 2026. Design docs: [`docs/`](docs/). Data sources: [`data/MANIFEST.md`](data/MANIFEST.md).

## Run locally

Requires Docker Desktop.

```bash
cp .env.example .env   # then fill in values
make up                # postgis, api, worker, web
make migrate           # create/upgrade the schema
make ingest            # build a data snapshot from data/raw (offline)
make health            # {"status":"ok", ...}
```

- Web: http://localhost:5173
- API: http://localhost:8000 (docs at `/docs`)

_This README is built up phase by phase; run instructions, role switcher, citations, and
trade-offs are completed in Phase 12._
