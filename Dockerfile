from python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# ffmpeg: هسته‌ی پخش صدا (atempo/اکولایزر/…) — git: برای به‌روزرسانی yt-dlp
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# SnapDeploy و پلتفرم‌های مشابه روی پورت ۸۰۰۰ شماره‌گذاری می‌کنند
EXPOSE 8000

CMD ["python", "bot.py"]
