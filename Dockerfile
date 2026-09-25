FROM python:3.12-slim

ARG PSTACK_REF=v0.5.1

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch "${PSTACK_REF}" \
        https://github.com/willpower-institute/pstack.git /app \
    && rm -rf /app/.git

WORKDIR /app
RUN pip install --no-cache-dir . 'beautifulsoup4>=4.12,<5'

COPY budget_addons /app/budget_addons
# The production index and source PDFs are intentionally mounted read-only,
# not baked into the image.  See docker-compose.prod.yml.
RUN mkdir -p /app/data /docs

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
