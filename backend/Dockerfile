# Backend image: used for BOTH the API and the worker (different commands in docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY start.py ./start.py

# never run as root; /tmp is writable for the worker heartbeat file
RUN useradd --create-home --uid 10001 synaxys && chown -R synaxys /app
USER synaxys

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"

CMD ["sh", "-c", "alembic upgrade head && exec python start.py"]
