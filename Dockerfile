FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV APLOS_HOST=0.0.0.0
ENV APLOS_PORT=8776
ENV APLOS_DB_PATH=/app/data/online_platform/aplos.sqlite3
ENV APLOS_STORAGE_ROOT=/app/data/online_platform/storage

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

RUN mkdir -p /app/data/online_platform/storage

EXPOSE 8776

CMD ["python", "online_platform/api_server.py"]
