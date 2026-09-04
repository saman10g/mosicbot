from python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# ffmpeg: هسته‌ی پخش صدا (atemo/اکولایزر/…) — git: برای به‌روزرسانی yt-dlp
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hugging Face Spaces همیشه روی ۷۸۶۰ منتظر است
EXPOSE 7860

CMD ["python", "bot.py"]
