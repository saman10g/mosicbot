"""داشبورد وضعیت + نقطه‌ی بیدار نگه‌داشتن (keep-alive) — روی پورت ۷۸۶۰."""
import html
import logging
import time
from collections import deque

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse

import config

log = logging.getLogger("server")

RECENT_LOGS: deque = deque(maxlen=300)
START_TIME = time.time()
BOT_STATUS = {"online": False, "detail": "در حال راه‌اندازی…"}


class LogCapture(logging.Handler):
    def emit(self, record: logging.LogRecord):
        try:
            RECENT_LOGS.append(
                f"{time.strftime('%H:%M:%S', time.localtime(record.created))} "
                f"[{record.levelname}] {record.getMessage()}"
            )
        except Exception:  # noqa: BLE001
            pass


def create_app(manager=None) -> FastAPI:
    app = FastAPI(title="Telegram Music Bot Status")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        rows = []
        if manager:
            for chat_id, st in manager.states.items():
                track = st.current
                title = html.escape(track.title) if track else "—"
                status = (
                    "🔇 بی‌صدا" if st.muted else
                    ("⏸ مکث" if st.paused else "▶️ در حال پخش")
                ) if st.playing else "⏹ غیرفعال"
                rows.append(
                    f"<tr><td><code>{chat_id}</code></td><td>{title}</td>"
                    f"<td>{html.escape(status)}</td><td>{st.volume}%</td>"
                    f"<td>{st.speed}x</td><td>{html.escape(st.eq)}</td>"
                    f"<td>{len(st.queue)}</td></tr>"
                )
        chats_html = "\n".join(rows) or "<tr><td colspan=7 style='color:#888'>— هیچ پخشی فعال نیست —</td></tr>"
        logs_html = "<br>".join(html.escape(x) for x in list(RECENT_LOGS)[-120:]) or "—"
        status = BOT_STATUS
        uptime = int(time.time() - START_TIME)
        h, m = divmod(uptime // 60, 60)
        page = f"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>وضعیت ربات موسیقی</title>
<style>
 body{{font-family:Tahoma,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:24px}}
 .card{{background:#1e293b;border-radius:14px;padding:20px;margin-bottom:18px;box-shadow:0 4px 18px rgba(0,0,0,.35)}}
 h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:15px;margin:0 0 10px;color:#94a3b8}}
 .ok{{color:#4ade80}} .bad{{color:#f87171}}
 table{{border-collapse:collapse;width:100%;font-size:13px}}
 th,td{{padding:7px 10px;border-bottom:1px solid #334155;text-align:right}}
 th{{color:#94a3b8;font-weight:normal}}
 .logs{{font-family:monospace;font-size:11px;direction:ltr;text-align:left;color:#cbd5e1;line-height:1.7}}
 .pill{{display:inline-block;padding:3px 12px;border-radius:99px;background:#334155;font-size:12px;margin-left:6px}}
</style>
<meta http-equiv="refresh" content="10">
</head>
<body>
 <div class="card"><h1>🎧 ربات موسیقی تلگرام</h1>
  <p><span class="pill">وضعیت ربات: <b class="{ 'ok' if status['online'] else 'bad' }">{ 'آنلاین ✅' if status['online'] else 'آفلاین ❌' }</b></span>
     <span class="pill">آپتایم: {h} دقیقه و {m} ثانیه</span></p>
  <p style="color:#94a3b8;font-size:13px">{html.escape(status['detail'])}</p>
 </div>
 <div class="card"><h2>پخش‌های فعال</h2>
  <table><tr><th>گروه</th><th>ترک</th><th>وضعیت</th><th>میزان صدا</th><th>سرعت</th><th>اکولایزر</th><th>صف</th></tr>
  {chats_html}</table>
 </div>
 <div class="card"><h2>آخرین لاگ‌ها</h2><div class="logs">{logs_html}</div></div>
</body></html>"""
        return page

    @app.get("/healthz")
    async def healthz():
        return {
            "ok": True,
            "bot_online": BOT_STATUS["online"],
            "uptime_seconds": int(time.time() - START_TIME),
        }

    @app.get("/wake")
    async def wake():
        return {"wake": True, "time": int(time.time())}

    @app.get("/logs", response_class=PlainTextResponse)
    async def logs():
        return "\n".join(RECENT_LOGS)

    return app
