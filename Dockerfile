# AgenticSales API (the Python backend). The console (web/) deploys separately to Vercel.
# NOT yet build-tested: Docker Desktop's engine was not running when this was written.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AGENTIC_DATA_DIR=/data \
    PORT=8000

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir fastapi uvicorn

COPY agentic_sales ./agentic_sales
COPY examples ./examples

# Tenant databases, secrets, media and the search index live on a mounted volume, never in the image.
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown app:app /data
USER app
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'),timeout=4)"

CMD ["sh", "-c", "uvicorn agentic_sales.server.app:_default_app --factory --host 0.0.0.0 --port ${PORT} --proxy-headers"]
