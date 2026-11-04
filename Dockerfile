# CapitalPilot — تصویر Production (Python 3.12، کاربر غیر root، داده در /data)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    APP_ENV=production DOCS_ENABLED=false \
    DATA_DIR=/data BACKUP_DIR=/data/backups LOG_DIR=/data/logs \
    DATABASE_URL=sqlite:////data/capitalpilot.db
WORKDIR /srv/capitalpilot
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt -c requirements.lock \
 || pip install --no-cache-dir -r requirements.txt
COPY VERSION ./
COPY app ./app
RUN groupadd --system cp && useradd --system --gid cp --home-dir /data --shell /usr/sbin/nologin cp \
 && mkdir -p /data && chown cp:cp /data && chmod 700 /data
USER cp
VOLUME ["/data"]
EXPOSE 8000
# اگر Basic Auth فعال باشد، بررسی سلامت با همان اطلاعات انجام می‌شود (از متغیرهای محیطیِ کانتینر).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import os,base64,urllib.request as u;r=u.Request('http://127.0.0.1:8000/api/health');p=os.environ.get('BASIC_AUTH_PASSWORD');p and r.add_header('Authorization','Basic '+base64.b64encode((os.environ.get('BASIC_AUTH_USER','')+':'+p).encode()).decode());u.urlopen(r,timeout=4)"
# فقط یک worker (زمان‌بند دریافت قیمت داخل همین فرایند است). Nginx میزبان جلوی آن قرار می‌گیرد؛ پورت فقط روی 127.0.0.1 میزبان منتشر می‌شود.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*", "--no-server-header", "--no-access-log"]
