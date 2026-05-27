FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      chromium \
      ca-certificates \
      fonts-liberation \
      fonts-noto-cjk \
      fonts-noto-color-emoji \
      fluxbox \
      novnc \
      websockify \
      x11vnc \
      xvfb \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY start-runtime.sh ./start-runtime.sh
RUN chmod +x ./start-runtime.sh

EXPOSE 6080
CMD ["./start-runtime.sh"]
