"""نقطه‌ی ورود ربات: تلگرام + pytgcalls + داشبورد وضعیت، همه در یک حلقه‌ی asyncio."""
import asyncio
import logging
import os
import sys
import time

import uvicorn
from pyrogram import Client
from pyrogram.enums import ParseMode
from pytgcalls import PyTgCalls

import config
import handlers
import player
import server

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("bot")
# لاگ‌ها هم در فایل و هم در داشبورد
_fh = logging.FileHandler("bot.log", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logging.getLogger().addHandler(_fh)
logging.getLogger().addHandler(server.LogCapture())

client: Client | None = None
call: PyTgCalls | None = None
manager: player.PlayerManager | None = None
online = False


async def ensure_online() -> bool:
    """اتصال (یا اتصال مجدد) به تلگرام — اگر شکست خورد، بعداً دوباره تلاش می‌شود."""
    global online
    if online:
        return True
    try:
        await call.start()  # pyrogram را هم خودش استارت می‌کند
        me = await client.get_me()
        online = True
        server.BOT_STATUS = {
            "online": True,
            "detail": f"ربات آنلاین است. نام: {me.first_name} (@{me.username}) — "
                      f"آخرین بررسی: {time.strftime('%H:%M:%S')}",
        }
        log.info("bot online as @%s", me.username)
        return True
    except Exception as e:  # noqa: BLE001
        server.BOT_STATUS = {"online": False,
                             "detail": f"⚠️ اتصال برقرار نشد: {e} — تلاش مجدد تا ۶۰ ثانیه دیگر…"}
        log.warning("startup failed: %s", e)
        online = False
        return False


async def watchdog() -> None:
    """نگهبانی: اتصال را زیر نظر می‌گیرد و در صورت مرگ کامل، پروسه را از نو اجرا می‌کند."""
    fails = 0
    while True:
        await asyncio.sleep(60)
        if not config.BOT_TOKEN or not config.API_ID or not config.API_HASH:
            continue
        try:
            if await ensure_online():
                await client.get_me()  # تست اتصال
                fails = 0
        except Exception as e:  # noqa: BLE001
            fails += 1
            log.warning("connection check failed (%s/3): %s", fails, e)
            server.BOT_STATUS = {"online": False, "detail": f"اتصال قطع شد ({fails}/3): {e}"}
            online = False
            if fails >= 3:
                log.error("restarting process after connection failures…")
                os.execv(sys.executable, [sys.executable] + sys.argv)


async def main() -> None:
    global client, call, manager

    if config.API_ID and config.BOT_TOKEN and config.API_HASH:
        client = Client(
            "musicbot",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            bot_token=config.BOT_TOKEN,
            workers=config.WORKERS,
            parse_mode=ParseMode.HTML,
        )
        call = PyTgCalls(client)
        manager = player.PlayerManager(call)
        player.register_pytgcalls_events(call, manager)
        handlers.register(client, manager)
        server.BOT_STATUS = {"online": False, "detail": "راه‌اندازی ربات…"}
    else:
        server.BOT_STATUS = {
            "online": False,
            "detail": "BOT_TOKEN / API_ID / API_HASH تعریف نشده است — از مسیر "
                      "Settings → Variables and secrets روی صفحه‌ی Space مقدارها را بده.",
        }

    app = server.create_app(manager)
    uvi = uvicorn.Server(uvicorn.Config(app, host=config.HOST, port=config.PORT, log_level="warning"))

    tasks = [asyncio.create_task(uvi.serve())]
    if manager:
        tasks.append(asyncio.create_task(ensure_online()))
        tasks.append(asyncio.create_task(watchdog()))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:  # noqa: BLE001
        log.exception("fatal: %s", e)
        sys.exit(1)
