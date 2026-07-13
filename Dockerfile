FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY tvtime2yamtrack ./tvtime2yamtrack
COPY webapp ./webapp
COPY migrate.py ./

RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8080

# Single worker + threads: background jobs keep progress state in-process, and
# the SSE stream must reach the same worker. No request timeout (long pushes).
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "8", \
     "--timeout", "0", "webapp.app:app"]
