FROM python:3.12-slim

WORKDIR /app

RUN sed -ri \
      -e 's|http://deb.debian.org/debian-security|https://mirrors.tuna.tsinghua.edu.cn/debian-security|g' \
      -e 's|http://deb.debian.org/debian|https://mirrors.tuna.tsinghua.edu.cn/debian|g' \
      /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 -o Acquire::https::Timeout=30 update \
    && apt-get -o Acquire::Retries=5 -o Acquire::https::Timeout=30 install -y --no-install-recommends \
      chromium \
      ca-certificates \
      fonts-liberation \
      fonts-noto-cjk \
      fonts-noto-color-emoji \
      fluxbox \
      novnc \
      websockify \
      xdotool \
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
