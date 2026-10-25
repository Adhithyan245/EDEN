# EDEN backend: FastAPI + WebSocket server that also runs npm to install and
# compile the apps it generates, so the image carries both Python and Node.
FROM node:22-bookworm-slim AS node

FROM python:3.11-slim

# Node + npm from the official image (no apt repo setup needed).
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && node --version && npm --version

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Generated code is installed and compiled by this process, so never run as root.
RUN useradd --create-home --uid 10001 eden
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=eden:eden app ./app

USER eden

# Warm npm's cache with the scaffold's dependencies so the first build on a
# fresh instance doesn't wait on a cold download.
RUN python -c "from app.builder.template import scaffold; \
import pathlib; d = pathlib.Path('/tmp/warm'); (d / 'src').mkdir(parents=True); \
[ (d / f.path).write_text(f.content) for f in scaffold('warm') ]" \
 && cd /tmp/warm && npm install --no-audit --no-fund && rm -rf /tmp/warm

ENV EDEN_HOST=0.0.0.0 \
    PORT=8000
EXPOSE 8000

# Render (and most hosts) inject PORT; EDEN_PORT follows it.
CMD ["sh", "-c", "EDEN_PORT=${PORT} exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
