"""هندلرهای پیام و دکمه‌های تلگرام — مدل کاری: جستجو → کارت نتیجه → کلیک پخش → ویس‌چت."""
import html
import logging
import re
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import (CallbackQuery, InlineKeyboardButton,
                            InlineKeyboardMarkup, Message)

import config
from player import PlayerManager, fa_num

log = logging.getLogger("handlers")

URL_RE = re.compile(r"https?://", re.I)
MEDIA_TYPES = (filters.audio | filters.video | filters.video_note | filters.voice |
               filters.document)


# ---------------------------------------------------------------- کیبوردها
def player_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏸ مکث/ادامه", callback_data="pp"),
         InlineKeyboardButton("⏭ بعدی", callback_data="nx"),
         InlineKeyboardButton("⏹ توقف", callback_data="st")],
        [InlineKeyboardButton("🔇 بی‌صدا", callback_data="mu"),
         InlineKeyboardButton("🔉 -25", callback_data="v-25"),
         InlineKeyboardButton("🔉 -10", callback_data="v-10"),
         InlineKeyboardButton("🔉 +10", callback_data="v+10"),
         InlineKeyboardButton("🔉 +25", callback_data="v+25")],
        [InlineKeyboardButton("🐢 0.5x", callback_data="sp0.5"),
         InlineKeyboardButton("▶️ 1x", callback_data="sp1"),
         InlineKeyboardButton("1.25x", callback_data="sp1.25"),
         InlineKeyboardButton("1.5x", callback_data="sp1.5"),
         InlineKeyboardButton("🐇 2x", callback_data="sp2")],
        [InlineKeyboardButton("🎚 اکولایزر: عادی", callback_data="eq")],
    ])


def results_keyboard(results: list, offset: int = 0) -> InlineKeyboardMarkup:
    rows = []
    for i, r in enumerate(results):
        dur = ""
        if r.get("duration"):
            m, s = divmod(int(r["duration"]), 60)
            dur = f" ({m}:{s:02d})"
        rows.append([InlineKeyboardButton(
            f"{fa_num(offset + i + 1)}. {r['title'][:42]}{dur} ▶",
            callback_data=f"sres:{i}")])
    return InlineKeyboardMarkup(rows)


async def send_status(app: Client, chat_id: int, manager: PlayerManager,
                      extra: str = "", reply_to: int | None = None) -> Message:
    text = manager.status_text(chat_id)
    if extra:
        text = extra + "\n\n" + text
    return await app.send_message(chat_id, text, reply_markup=player_keyboard())


def requester_name(user) -> str:
    if user is None:
        return "نامشخص"
    if user.username:
        return f"@{user.username}"
    return (user.first_name or "کاربر")[:30]


# ---------------------------------------------------------------- ثبت
def register(app: Client, manager: PlayerManager) -> None:
    # ============ ۱) متن آزاد در گروه/پیوی = جستجوی آهنگ ============
    @app.on_message(filters.text & ~filters.media & (filters.group | filters.private))
    async def _text_search(client: Client, msg: Message):
        if not config.SEARCH_ON_TEXT:
            return
        if msg.from_user and msg.from_user.is_bot:
            return
        text = (msg.text or "").strip()
        if not text or len(text) < 2:
            return
        if text.startswith(("/", ".", "!", "#", "@")):
            return

        # لینک (یوتیوب یا هر لینک دیگر) → کارت پخش با یک دکمه
        if URL_RE.match(text):
            await _send_play_card(client, manager, msg.chat.id, text,
                                  requester_name(msg.from_user),
                                  "🎬 لینک پیدا شد — برای پخش دکمه رو بزن:")
            return

        # اسم آهنگ → جستجو
        try:
            results = await manager.search(text, limit=config.SEARCH_LIMIT)
        except Exception as e:  # noqa: BLE001
            await msg.reply_text(f"⚠️ جستجو ناموفق بود: {str(e)[:150]}")
            return
        if not results:
            await msg.reply_text(f"🔍 برای «{html.escape(text)}» چیزی پیدا نکردم.")
            return
        manager.searches[msg.chat.id] = results
        await msg.reply_text(
            f"🎧 <b>نتایج جستجو برای «{html.escape(text)}»</b>\n"
            "یکی رو انتخاب کن تا توی ویس‌چت پخش بشه:",
            reply_markup=results_keyboard(results))

    # ============ ۲) ویدیو/فایل صوتی در گروه = دکمه‌ی پخش ============
    @app.on_message(MEDIA_TYPES & filters.group)
    async def _media_arrived(_: Client, msg: Message):
        if msg.from_user and msg.from_user.is_bot:
            return
        name = ""
        for attr in ("video", "video_note", "audio", "voice", "document"):
            obj = getattr(msg, attr, None)
            if obj is not None:
                name = getattr(obj, "file_name", None) or "فایل ارسالی"
                break
        text = "🎬 این رو توی ویس‌چت پخش کنم؟"
        if name:
            text = f"🎬 <b>{html.escape(name[:60])}</b>\nاین رو توی ویس‌چت پخش کنم؟"
        await msg.reply(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("▶ پخش در ویس‌چت", callback_data=f"mplay:{msg.id}")]]))

    # ============ ۳) دستورات کلاسیک (اختیاری) ============
    @app.on_message(filters.command(["start", "help", "کمک", "راهنما", "دستور"]))
    async def _help(_: Client, msg: Message):
        await msg.reply_text(config.TEXT_HELP)

    @app.on_message(filters.command(["id", "ایدی"]))
    async def _id(_: Client, msg: Message):
        if msg.from_user:
            await msg.reply_text(f"🆔 آیدی عددی شما: <code>{msg.from_user.id}</code>")

    @app.on_message(filters.command(["ping", "پینگ"]))
    async def _ping(_: Client, msg: Message):
        await msg.reply_text(f"🏓 پونگ! ({datetime.now().strftime('%H:%M:%S')})")

    @app.on_message(filters.command(["play", "pl", "پخش", "بزن", "جستجو", "سرچ"]))
    async def _play(client: Client, msg: Message):
        if msg.from_user and msg.from_user.is_bot:
            return
        if msg.command and len(msg.command) > 1:
            query = " ".join(msg.command[1:])
            try:
                results = await manager.search(query, limit=config.SEARCH_LIMIT)
            except Exception as e:  # noqa: BLE001
                await msg.reply_text(f"⚠️ جستجو ناموفق بود: {str(e)[:150]}")
                return
            if not results:
                await msg.reply_text(f"🔍 برای «{html.escape(query)}» چیزی پیدا نکردم.")
                return
            manager.searches[msg.chat.id] = results
            await msg.reply_text(
                f"🎧 <b>نتایج جستجو برای «{html.escape(query)}»</b>",
                reply_markup=results_keyboard(results))
            return
        await msg.reply_text("مثلاً: /پخش ساعت تندار محسن چاوشی")

    @app.on_message(filters.command(["pause", "مکث"]))
    async def _pause(client: Client, msg: Message):
        r = await manager.toggle_pause(msg.chat.id)
        await send_status(client, msg.chat.id, manager, extra=r)

    @app.on_message(filters.command(["resume", "ادامه", "پلی"]))
    async def _resume(client: Client, msg: Message):
        if manager.state(msg.chat.id).paused:
            await manager.toggle_pause(msg.chat.id)
        await send_status(client, msg.chat.id, manager, extra="▶️ ادامه داده شد.")

    @app.on_message(filters.command(["stop", "end", "توقف", "خروج", "تمام"]))
    async def _stop(client: Client, msg: Message):
        await manager.stop(msg.chat.id)
        await msg.reply_text("⏹ پخش متوقف شد و از وویس‌چت خارج شدم.")

    @app.on_message(filters.command(["next", "skip", "بعدی", "سکیپ", "رد"]))
    async def _next(client: Client, msg: Message):
        r = await manager.next_track(msg.chat.id, manual=True)
        await send_status(client, msg.chat.id, manager, extra=r)

    @app.on_message(filters.command(["mute", "بی‌صدا", "سکوت"]))
    async def _mute(client: Client, msg: Message):
        r = await manager.toggle_mute(msg.chat.id)
        await send_status(client, msg.chat.id, manager, extra=r)

    @app.on_message(filters.command(["unmute", "صدا", "وصل"]))
    async def _unmute(client: Client, msg: Message):
        if manager.state(msg.chat.id).muted:
            await manager.toggle_mute(msg.chat.id)
        await send_status(client, msg.chat.id, manager, extra="🔊 صدا وصل شد.")

    @app.on_message(filters.command(["volume", "میزان", "ولوم", "بلندی"]))
    async def _volume(client: Client, msg: Message):
        if msg.command and len(msg.command) > 1:
            try:
                r = await manager.set_volume(msg.chat.id, int(msg.command[1].replace("%", "")))
                await send_status(client, msg.chat.id, manager, extra=r)
                return
            except ValueError:
                pass
        await msg.reply_text("مثال: /میزان 120 (۰ تا ۲۰۰)")

    @app.on_message(filters.command(["speed", "سرعت", "نرخ"]))
    async def _speed(client: Client, msg: Message):
        if msg.command and len(msg.command) > 1:
            try:
                r = await manager.change_speed(msg.chat.id, float(msg.command[1].replace("x", "").replace("X", "")))
                await send_status(client, msg.chat.id, manager, extra=r)
                return
            except ValueError:
                pass
        await msg.reply_text("مثال: /سرعت 1.5 (۰.۵ تا ۲)")

    @app.on_message(filters.command(["eq", "equalizer", "ایکولایزر"]))
    async def _eq(client: Client, msg: Message):
        if msg.command and len(msg.command) > 1:
            r = await manager.set_eq(msg.chat.id, msg.command[1])
        else:
            r = await manager.cycle_eq(msg.chat.id)
        await send_status(client, msg.chat.id, manager, extra=r)

    @app.on_message(filters.command(["seek", "jump", "پرش", "جلو"]))
    async def _seek(client: Client, msg: Message):
        if msg.command and len(msg.command) > 1:
            try:
                r = await manager.seek(msg.chat.id, int(msg.command[1]))
                await send_status(client, msg.chat.id, manager, extra=r)
                return
            except ValueError:
                pass
        await msg.reply_text("مثال: /پرش 90")

    @app.on_message(filters.command(["queue", "صف"]))
    async def _queue(client: Client, msg: Message):
        st = manager.state(msg.chat.id)
        if not st.queue:
            await msg.reply_text("🗒 صف خالی است.")
            return
        lines = [f"🗒 <b>صف پخش ({fa_num(len(st.queue))} ترک)</b>"]
        for i, t in enumerate(st.queue):
            mark = "▶️" if i == st.index else f"{fa_num(i + 1)}."
            lines.append(f"{mark} {html.escape(t.title)}")
        await msg.reply_text("\n".join(lines))

    @app.on_message(filters.command(["now", "np", "وضعیت", "حال"]))
    async def _now(client: Client, msg: Message):
        await send_status(client, msg.chat.id, manager)

    @app.on_message(filters.command(["radio", "رادیو", "زنده"]))
    async def _radio(_: Client, msg: Message):
        await msg.reply_text(
            "📻 برای پخش رادیوی زنده، لینک مستقیم m3u8 یا aac رو بفرست:\n"
            "/پخش https://example.com/radio.m3u8")

    # ============ ۴) دکمه‌ها ============
    @app.on_callback_query()
    async def _buttons(client: Client, cq: CallbackQuery):
        chat_id = cq.message.chat.id
        data = cq.data or ""

        # --- انتخاب نتیجه‌ی جستجو → دانلود و پخش
        if data.startswith("sres:"):
            idx = int(data.split(":")[1])
            results = manager.searches.get(chat_id, [])
            if idx >= len(results):
                await cq.answer("این نتیجه منقضی شده — دوباره جستجو کن.", show_alert=True)
                return
            entry = results[idx]
            await cq.answer()
            try:
                await cq.message.edit_text("⏳ در حال دانلود و آماده‌سازی…")
            except Exception:  # noqa: BLE001
                pass
            try:
                track, added = await manager.play_from_chat(
                    chat_id, entry.get("webpage_url") or entry["url"], requester_name(cq.from_user))
            except Exception as e:  # noqa: BLE001
                await cq.message.edit_text(f"⚠️ {e}")
                return
            await _finish_play_card(client, cq.message, manager, chat_id, track, added)
            return

        # --- پخش فایل/ویدیوی ارسال‌شده به گروه
        if data.startswith("mplay:"):
            mid = int(data.split(":")[1])
            await cq.answer("⏳ در حال آماده‌سازی…")
            await _play_telegram_media(client, manager, cq, chat_id, mid)
            return

        # --- پخش لینک (یوتیوب/رادیو) از کارت لینک
        if data.startswith("purl:"):
            url = manager.pending_urls.pop(cq.message.id, None)
            if not url:
                await cq.answer("این کارت منقضی شده — دوباره لینک رو بفرست.", show_alert=True)
                return
            await cq.answer()
            try:
                await cq.message.edit_text("⏳ در حال دانلود و آماده‌سازی…")
            except Exception:  # noqa: BLE001
                pass
            try:
                track, added = await manager.play_from_chat(
                    chat_id, url, requester_name(cq.from_user))
            except Exception as e:  # noqa: BLE001
                await cq.message.edit_text(f"⚠️ {e}")
                return
            await _finish_play_card(client, cq.message, manager, chat_id, track, added)
            return

        # --- کنترل‌های پلیر
        st = manager.state(chat_id)
        extra = ""
        try:
            if data == "pp":
                extra = await manager.toggle_pause(chat_id)
            elif data == "nx":
                extra = await manager.next_track(chat_id, manual=True)
            elif data == "st":
                await manager.stop(chat_id)
                await cq.answer("متوقف شد ✅")
                try:
                    await cq.message.edit_text("⏹ پخش متوقف شد.")
                except Exception:  # noqa: BLE001
                    pass
                return
            elif data == "mu":
                extra = await manager.toggle_mute(chat_id)
            elif data.startswith("v-"):
                extra = await manager.set_volume(chat_id, st.volume - int(data[1:]))
            elif data.startswith("v+"):
                extra = await manager.set_volume(chat_id, st.volume + int(data[1:]))
            elif data.startswith("sp"):
                try:
                    extra = await manager.change_speed(chat_id, float(data[2:]))
                except ValueError:
                    extra = ""
            elif data == "eq":
                extra = await manager.cycle_eq(chat_id)
            await cq.answer()
            text = manager.status_text(chat_id)
            if extra:
                text = extra + "\n\n" + text
            try:
                await cq.message.edit_text(text, reply_markup=player_keyboard())
            except Exception:  # noqa: BLE001
                await client.send_message(chat_id, text, reply_markup=player_keyboard())
        except Exception as e:  # noqa: BLE001
            log.warning("callback error: %s", e)
            await cq.answer(f"❌ خطا: {str(e)[:80]}", show_alert=True)


# ---------------------------------------------------------------- کمکی‌ها
async def _finish_play_card(client: Client, message: Message, manager: PlayerManager,
                            chat_id: int, track, added: bool) -> None:
    """به‌روزرسانی کارت به کارت پلیر بعد از شروع پخش."""
    text = manager.status_text(chat_id)
    header = f"✅ {track.display}" if added else f"➕ به صف اضافه شد:\n{track.display}"
    if added:
        text = "▶️ <b>پخش شروع شد!</b>\n\n" + text
    else:
        text = header + "\n\n" + text
    try:
        await message.edit_text(
            "▶️ <b>پخش شروع شد!</b>\n\n" + manager.status_text(chat_id),
            reply_markup=player_keyboard())
    except Exception:  # noqa: BLE001
        await client.send_message(chat_id,
                                  "▶️ <b>پخش شروع شد!</b>\n\n" + manager.status_text(chat_id),
                                  reply_markup=player_keyboard())


async def _send_play_card(client: Client, manager: PlayerManager, chat_id: int,
                          url: str, user: str, caption: str) -> None:
    """برای لینک‌های مستقیم (یوتیوب/رادیو): کارت با دکمه‌ی پخش."""
    try:
        info = await manager.peek(url)
    except Exception as e:  # noqa: BLE001
        log.debug("peek failed: %s", e)
        info = {"title": url.rsplit("/", 1)[-1][:40], "duration": None}
    title = html.escape(info.get("title") or url)
    if info.get("duration"):
        m, s = divmod(int(info["duration"]), 60)
        title += f" <i>({fa_num(m)}:{fa_num(f'{s:02d}')})</i>"
    msg = await client.send_message(
        chat_id,
        f"{caption}\n\n🎵 {title}\n👤 {html.escape(user)}")
    # دکمه را بعد از ارسال اضافه می‌کنیم تا شناسه‌ی پیام را داشته باشیم
    manager.pending_urls[msg.id] = url
    try:
        await msg.edit_reply_markup(InlineKeyboardMarkup([
            [InlineKeyboardButton("▶ پخش در ویس‌چت", callback_data=f"purl:{msg.id}")]]))
    except Exception:  # noqa: BLE001
        pass


async def _play_telegram_media(client: Client, manager: PlayerManager,
                               cq: CallbackQuery, chat_id: int, msg_id: int) -> None:
    """دانلود فایل/ویدیوی تلگرام و پخش در ویس‌چت."""
    try:
        orig = await client.get_messages(chat_id, msg_id)
        if not orig:
            await cq.message.edit_text("⚠️ پیام اصلی پیدا نشد.")
            return

        size = None
        name = "فایل ارسالی"
        for attr in ("video", "video_note", "audio", "voice", "document"):
            obj = getattr(orig, attr, None)
            if obj is not None:
                size = getattr(obj, "file_size", None)
                name = getattr(obj, "file_name", None) or ("ویدیو" if attr in ("video", "video_note") else "صدا")
                break

        if size and size > config.MAX_TG_DOWNLOAD_MB * 1024 * 1024:
            await cq.message.edit_text(
                f"⚠️ حجم فایل بیشتر از {config.MAX_TG_DOWNLOAD_MB} مگابایته و تلگرام اجازه‌ی دانلودش "
                "را به ربات‌ها نمی‌دهد. لینک یوتیوبِ همین ویدیو رو بفرست — اونو راحت پخش می‌کنم!")
            return

        # برای فایل‌های غیرصوتی/ویدیویی (مثل pdf) رد کن
        if getattr(orig, "document", None) and not orig.document.mime_type.startswith(("audio", "video", "application/octet")):
            await cq.message.edit_text("⚠️ این فایل صوتی/ویدیویی نیست.")
            return

        try:
            await cq.message.edit_text("⏳ در حال دانلود از تلگرام…")
        except Exception:  # noqa: BLE001
            pass
        path = await orig.download(file_name=f"/tmp/tg_{msg_id}_{int(datetime.now().timestamp())}.{_ext_of(orig)}")
        track, added = await manager.play_file(chat_id, path, name, requester_name(cq.from_user))
        await _finish_play_card(client, cq.message, manager, chat_id, track, added)
    except Exception as e:  # noqa: BLE001
        log.warning("telegram media play failed: %s", e)
        try:
            await cq.message.edit_text(f"⚠️ دانلود/پخش نشد: {str(e)[:150]}")
        except Exception:  # noqa: BLE001
            pass


def _ext_of(msg: Message) -> str:
    for attr in ("video", "audio", "document", "voice", "video_note"):
        obj = getattr(msg, attr, None)
        if obj is not None and getattr(obj, "file_name", None):
            return (obj.file_name or "").rsplit(".", 1)[-1] or "mp4"
    return "mp4"
