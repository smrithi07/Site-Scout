FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SITESCOUT_CONFIG=/config/sitescout.yaml

WORKDIR /app

# Install only the dependencies first so code edits don't bust the layer cache.
COPY pyproject.toml .
RUN python -c "import tomllib; d = tomllib.load(open('pyproject.toml', 'rb'))['project']; \
print('\n'.join(d['dependencies'] + d['optional-dependencies']['dev']))" > /tmp/req.txt \
    && pip install --no-cache-dir -r /tmp/req.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
