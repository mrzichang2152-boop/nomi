FROM node:22-bookworm-slim AS opencode-cli

ARG OPENCODE_VERSION=1.17.14
RUN npm install -g "opencode-ai@${OPENCODE_VERSION}" \
    && opencode --version

FROM node:22-bookworm-slim AS file-viewer-assets

WORKDIR /viewer
COPY file_viewer/package.json file_viewer/package-lock.json ./
RUN npm ci --ignore-scripts
COPY file_viewer/build-assets.mjs file_viewer/THIRD_PARTY.md ./
RUN node build-assets.mjs /out/static/vendor/file-viewer

FROM python:3.12-slim-bookworm AS runtime-base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp/nomi

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=opencode-cli /usr/local/lib/node_modules/opencode-ai/bin/opencode.exe /usr/local/bin/opencode
RUN chmod +x /usr/local/bin/opencode \
    && opencode --version

COPY app ./app
COPY scripts ./scripts
COPY opencode_capabilities ./opencode_capabilities
COPY --from=file-viewer-assets /out/static/vendor/file-viewer ./app/static/vendor/file-viewer

RUN groupadd --gid 65532 nomi \
    && useradd --uid 65532 --gid 65532 --no-create-home --shell /usr/sbin/nologin nomi \
    && mkdir -p /app/data/attachments /models /tmp/nomi \
    && chown -R 65532:65532 /app/data /models /tmp/nomi

FROM runtime-base AS api-runtime

USER 65532:65532

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

FROM runtime-base AS attachment-worker-runtime

USER root
RUN set -eux; \
    find /etc/apt/sources.list.d -type f -exec sed -i 's|http://deb.debian.org|https://deb.debian.org|g' {} +; \
    rm -f /etc/apt/apt.conf.d/docker-clean; \
    printf '%s\n' 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-downloaded-packages; \
    for attempt in 1 2 3; do \
        if apt-get -o Acquire::Retries=5 update \
            && apt-get -o Acquire::Retries=5 -o APT::Get::Fix-Missing=true install -y --no-install-recommends \
            fontconfig \
            libreoffice-core \
            libreoffice-writer \
            libreoffice-calc \
            libreoffice-impress \
            poppler-utils \
            && command -v libreoffice \
            && command -v pdftoppm; then \
            break; \
        fi; \
        rm -rf /var/lib/apt/lists/*; \
        if [ "$attempt" = "3" ]; then exit 1; fi; \
        sleep $((attempt * 5)); \
    done; \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb /var/cache/apt/archives/partial/*; \
    rm -f /etc/apt/apt.conf.d/keep-downloaded-packages

USER 65532:65532
CMD ["python", "-m", "app.attachments.worker_entrypoint"]
