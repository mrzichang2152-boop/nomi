FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN groupadd --gid 65532 nomi \
    && useradd --uid 65532 --gid 65532 --no-create-home --shell /usr/sbin/nologin nomi \
    && mkdir -p /app/data/attachments \
    && chown -R 65532:65532 /app/data

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
