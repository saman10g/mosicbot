"""مدیریت پخش: صف، دانلود (yt-dlp)، رادیو زنده، افکت‌های ffmpeg."""
import asyncio
import html
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pytgcalls import PyTgCalls
from pytgcalls.types import AudioQuality, MediaStream
from pytgcalls.types.stream import StreamEnded

import config

log = logging.getLogger("player")

LIVE_EXT_RE = re.compile(r"\.(m3u8|aac|mpd)(\?|$)", re.I)
DIRECT_AUDIO_RE = re.compile(r"\.(m3u8|aac|mp3|ogg|m4a|opus|flac|wav|mpd)(\?.*)?$", re.I)
URL_RE = re.compile(r"^https?://", re.I)


def fa_num(value) -> str:
    """تبدیل ارقام انگلیسی به فارسی برای نمایش."""
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


@dataclass
class Track:
    source: str
    title: str
    requester: str
    live: bool = False
    duration: Optional[float] = None
    path: Optional[str] = None      # فایل محلی دانلودشده
    url: Optional[str] = None       # آدرس مستقیم استریم

    @property
    def display(self) -> str:
        t = html.escape(self.title)
        if self.duration:
            m, s = divmod(int(self.duration), 60)
            return f"{t} <i>({fa_num(m)}:{fa_num(f'{s:02d}')})</i>"
        return t

    @property
    def media_path(self) -> str:
        return self.path or self.url or self.source


@dataclass
class ChatState:
    chat_id: int
    queue: list = field(default_factory=list)
    index: int = -1
    playing: bool = False
    paused: bool = False
    muted: bool = False
    volume: int = config.DEFAULT_VOLUME
    speed: float = 1.0
    eq: str = "عادی"
    switching: bool = False
    switch_deadline: float = 0.0
    downloading: Optional[str] = None
    error: Optional[str] = None
    started_at: float = 0.0

    @property
    def current(self) -> Optional[Track]:
        if 0 <= self.index < len(self.queue):
            return self.queue[self.index]
        return None


class PlayerManager:
    def __init__(self, call: PyTgCalls):
        self.call = call
        self.states: dict[int, ChatState] = {}
        self.searches: dict[int, list] = {}      # chat_id → نتایج جستجو
        self.pending_urls: dict[int, str] = {}   # message_id → لینک (کارت لینک)
        self._lock = asyncio.Lock()

    # ---------- ابزار ----------
    def state(self, chat_id: int) -> ChatState:
        if chat_id not in self.states:
            self.states[chat_id] = ChatState(chat_id=chat_id)
        return self.states[chat_id]

    # ---------- جستجو و پیش‌نمایش ----------
    async def search(self, query: str, limit: int = 5) -> list[dict]:
        """جستجوی یوتیوب و برگرداندن چند نتیجه‌ی اول (بدون دانلود)."""
        import yt_dlp

        opts = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "skip_download": True,
            "extract_flat": True,
            "cachedir": str(config.WORK_DIR / "ytdl_cache"),
        }

        def _job() -> list[dict]:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
                out = []
                for e in (info.get("entries") or []):
                    if not e:
                        continue
                    out.append({
                        "title": (e.get("title") or "بدون عنوان").strip(),
                        "duration": e.get("duration"),
                        "id": e.get("id"),
                        "url": e.get("webpage_url") or e.get("url") or "",
                    })
                return out

        return await asyncio.to_thread(_job)

    async def peek(self, url: str) -> dict:
        """فقط متادیتای یک لینک (برای کارت پخش) بدون دانلود."""
        import yt_dlp

        opts = {
            "quiet": True, "no_warnings": True,
            "noprogress": True, "noplaylist": True,
            "skip_download": True, "extract_flat": True,
            "cachedir": str(config.WORK_DIR / "ytdl_cache"),
        }

        def _job() -> dict:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info and "entries" in info and info["entries"]:
                    info = info["entries"][0]
                return {"title": (info.get("title") or "").strip(),
                        "duration": info.get("duration")}

        return await asyncio.to_thread(_job)

    @staticmethod
    def is_live_media(source: str) -> bool:
        return bool(LIVE_EXT_RE.search(source))

    @staticmethod
    def is_direct_audio(source: str) -> bool:
        return bool(DIRECT_AUDIO_RE.search(source))

    @staticmethod
    def build_ffmpeg_params(speed: float, eq: str, seek: int = 0) -> str:
        """ساخت پارامترهای ffmpeg برای pytgcalls.

        قالب pytgcalls: '--audio'، سپس '---start' (قبل از -i، برای -ss)
        و '---mid' (بعد از -i، برای -af و -vn). تأییدشده با ffmpeg واقعی.
        """
        filters: list[str] = []
        eq_f = config.EQ_FILTERS.get(eq, "")
        if eq_f:
            filters.append(eq_f)

        s = float(speed)
        if s < 0.5:
            s = 0.5
        if s > 2.0:
            s = 2.0
        if abs(s - 1.0) > 0.001:
            remaining = s
            while remaining > 2.0:
                filters.append("atempo=2.0")
                remaining /= 2.0
            while remaining < 0.5:
                filters.append("atempo=0.5")
                remaining /= 0.5
            if abs(remaining - 1.0) > 0.001:
                filters.append(f"atempo={remaining:.4f}")

        parts = ["--audio"]
        if seek > 0:
            parts.append(f"---start -ss {int(seek)}")
        mid = "-vn"  # فقط صدا
        if filters:
            mid += " -af " + ",".join(filters)
        parts.append("---mid " + mid)
        return " ".join(parts)

    def make_stream(self, track: Track, st: ChatState, seek: int = 0) -> MediaStream:
        params = self.build_ffmpeg_params(st.speed, st.eq, seek)
        quality = {"HIGH": AudioQuality.HIGH, "MEDIUM": AudioQuality.MEDIUM,
                   "LOW": AudioQuality.LOW}.get(config.AUDIO_QUALITY, AudioQuality.HIGH)
        return MediaStream(
            media_path=track.path or track.url or track.source,
            audio_parameters=quality,
            audio_flags=MediaStream.Flags.REQUIRED,
            video_flags=MediaStream.Flags.IGNORE,
            ffmpeg_parameters=params,
        )

    # ---------- دانلود ----------
    async def resolve_track(self, source: str, requester: str, chat_id: int) -> Track:
        """منبع ورودی را به Track تبدیل می‌کند (رادیو، لینک مستقیم، جستجو/لینک یوتیوب)."""
        source = source.strip().strip("<>")

        if self.is_direct_audio(source):
            title = source.rsplit("/", 1)[-1].split("?")[0]
            return Track(
                source=source,
                title=f"📻 {title}",
                requester=requester,
                live=self.is_live_media(source),
                url=source,
            )

        if URL_RE.match(source):
            # لینک غیرمستقیم (مثل یوتیوب) → دانلود با yt-dlp
            return await self._download(source, requester, chat_id)

        # جستجوی اسم آهنگ
        return await self._download(f"ytsearch1:{source}", requester, chat_id, search=True)

    async def _download(self, url: str, requester: str, chat_id: int, search: bool = False) -> Track:
        import yt_dlp

        st = self.state(chat_id)
        cache_dir = config.PLAYLIST_DIR / str(chat_id)
        cache_dir.mkdir(parents=True, exist_ok=True)
        work_dir = config.WORK_DIR / str(chat_id)
        work_dir.mkdir(parents=True, exist_ok=True)

        opts = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "outtmpl": str(cache_dir / "%(title).120B-%(id)s.%(ext)s"),
            "cachedir": str(config.WORK_DIR / "ytdl_cache"),
            "restrictfilenames": True,
            "extractor_args": {
                "youtube": {"player_client": ["android", "web_safari", "tv"]},
            },
        }

        def _fetch_info() -> dict:
            """مرحله‌ی ۱: شناخت آهنگ (برای جستجو: اولین نتیجه). دانلود نمی‌کند."""
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info and "entries" in info and info["entries"]:
                    info = info["entries"][0]
                return info

        def _download_file(info: dict) -> dict:
            """مرحله‌ی ۲: دانلود واقعی (یا استفاده از فایل کش‌شده)."""
            vid = info.get("id", "song")
            existing = list(cache_dir.glob(f"*{vid}.*"))
            existing = [p for p in existing if p.suffix.lower() not in (".part", ".ytdl", ".json")]
            if existing:
                return info
            # برای نتایج جستجو، آدرس صفحه‌ی ویدیو را بگیر (آدرس googlevideo مستقیم
            # id/عنوان ندارد و نام فایل خراب می‌شود)
            target = info.get("webpage_url") or info.get("url") or url
            opts2 = dict(opts)
            opts2["outtmpl"] = str(cache_dir / f"%(title).40B-{vid}.%(ext)s")
            with yt_dlp.YoutubeDL(opts2) as ydl2:
                return ydl2.extract_info(target, download=True)

        st.downloading = "در حال پیدا کردن آهنگ…"
        try:
            info = await asyncio.to_thread(_fetch_info)
            st.downloading = "در حال دانلود…"
            info = await asyncio.to_thread(_download_file, info)
        except Exception as e:  # noqa: BLE001
            st.downloading = None
            log.warning("yt-dlp failed for %s: %s", url, e)
            raise RuntimeError(
                "نتونستم آهنگ رو پیدا یا دانلود کنم. شاید لینک مشکل داره، یا یوتیوب دسترسی سرور "
                "رو موقتاً مسدود کرده. می‌تونی لینک مستقیم mp3 یا رادیوی m3u8 بدی."
            ) from e
        st.downloading = None

        # تازه‌ترین فایل دانلودشده را پیدا کن
        files = sorted(cache_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        path = None
        for p in files:
            if p.is_file() and p.suffix.lower() not in (".part", ".ytdl", ".json"):
                path = str(p)
                break
        if not path:
            raise RuntimeError("فایل دانلود نشد — پسوندش پشتیبانی نمی‌شه.")

        dur = info.get("duration")
        title = (info.get("title") or Path(path).stem).strip()
        return Track(source=url, title=title, requester=requester,
                     duration=float(dur) if dur else None, path=path)

    # ---------- پخش ----------
    async def play_from_chat(self, chat_id: int, source: str, requester: str) -> tuple[Track, bool]:
        """افزودن به صف و شروع پخش. خروجی: (ترک، آیا تازه اضافه شد یا در صف است)"""
        st = self.state(chat_id)
        track = await self.resolve_track(source, requester, chat_id)
        return await self.play_track(chat_id, track)

    async def play_file(self, chat_id: int, path: str, title: str,
                        requester: str) -> tuple[Track, bool]:
        """پخش فایل محلی (مثلاً ویدیوی دانلودشده از تلگرام)."""
        track = Track(source=path, title=title, requester=requester, path=path)
        return await self.play_track(chat_id, track)

    async def play_track(self, chat_id: int, track: Track) -> tuple[Track, bool]:
        async with self._lock:
            st = self.state(chat_id)
            was_idle = not st.playing
            st.queue.append(track)
            if was_idle or st.index < 0:
                st.index = len(st.queue) - 1
                await self._start(chat_id, st)
                return track, True
            return track, False

    async def _start(self, chat_id: int, st: ChatState, seek: int = 0) -> None:
        track = st.current
        if track is None:
            return
        st.switching = True
        st.switch_deadline = time.time() + 10
        st.error = None
        try:
            media = self.make_stream(track, st, seek=seek)
            await self.call.play(chat_id, media)
            # اعمال میزان صدا و بی‌صدا (متدهای بومی — بدون ری‌استارت)
            try:
                await self.call.change_volume_call(chat_id, st.volume)
            except Exception:  # noqa: BLE001
                pass
            if st.muted:
                try:
                    await self.call.mute(chat_id)
                except Exception:  # noqa: BLE001
                    pass
            st.playing = True
            st.paused = False
            st.started_at = time.time()
        except Exception as e:  # noqa: BLE001
            st.switching = False
            st.error = str(e)
            log.warning("play failed in %s: %s", chat_id, e)
            msg = "❌ پخش شروع نشد!"
            st.playing = False
            if "NoActiveGroupCall" in str(e) or "join" in str(e).lower():
                msg += "\nربات باید ادمین گروه باشه (با حق «صحبت کردن») و گروه باید وویس‌چت فعال داشته باشه."
            raise RuntimeError(msg) from e

    # ---------- کنترل‌ها ----------
    async def toggle_pause(self, chat_id: int) -> str:
        st = self.state(chat_id)
        if not st.playing:
            return "چیزی در حال پخش نیست!"
        try:
            if st.paused:
                await self.call.resume(chat_id)
                st.paused = False
                return "▶️ ادامه داده شد."
            await self.call.pause(chat_id)
            st.paused = True
            return "⏸ مکث شد."
        except Exception as e:  # noqa: BLE001
            return f"خطا: {e}"

    async def toggle_mute(self, chat_id: int) -> str:
        st = self.state(chat_id)
        if not st.playing:
            return "چیزی در حال پخش نیست!"
        try:
            if st.muted:
                await self.call.unmute(chat_id)
                st.muted = False
                return "🔊 صدا وصل شد."
            await self.call.mute(chat_id)
            st.muted = True
            return "🔇 بی‌صدا شد."
        except Exception as e:  # noqa: BLE001
            return f"خطا: {e}"

    async def set_volume(self, chat_id: int, value: int) -> str:
        st = self.state(chat_id)
        value = max(0, min(200, value))
        st.volume = value
        if st.playing:
            try:
                await self.call.change_volume_call(chat_id, value)
                return f"🔊 میزان صدا روی {fa_num(value)}٪ تنظیم شد."
            except Exception as e:  # noqa: BLE001
                return f"خطا: {e}"
        return f"🔊 میزان صدا روی {fa_num(value)}٪ تنظیم شد (برای پخش بعدی)."

    async def change_speed(self, chat_id: int, speed: float) -> str:
        st = self.state(chat_id)
        speed = max(0.5, min(2.0, speed))
        st.speed = round(speed, 2)
        if st.playing:
            await self._restart_current(chat_id, st)
            return f"🐇 سرعت پخش روی {fa_num(st.speed)}x تنظیم شد."
        return f"🐇 سرعت پخش روی {fa_num(st.speed)}x تنظیم شد (برای پخش بعدی)."

    async def cycle_eq(self, chat_id: int) -> str:
        st = self.state(chat_id)
        idx = config.EQUALIZERS.index(st.eq) if st.eq in config.EQUALIZERS else 0
        st.eq = config.EQUALIZERS[(idx + 1) % len(config.EQUALIZERS)]
        if st.playing:
            await self._restart_current(chat_id, st)
        return f"🎚 اکولایزر: {st.eq}"

    async def set_eq(self, chat_id: int, name: str) -> str:
        st = self.state(chat_id)
        if name not in config.EQUALIZERS:
            return "نام اکولایزر باید یکی از: " + " / ".join(config.EQUALIZERS)
        st.eq = name
        if st.playing:
            await self._restart_current(chat_id, st)
        return f"🎚 اکولایزر: {name}"

    async def _restart_current(self, chat_id: int, st: ChatState, seek: int = 0) -> None:
        """ری‌استارت ترک فعلی با پارامترهای جدید ffmpeg."""
        if st.current is None:
            return
        try:
            await self._start(chat_id, st, seek=seek)
        except RuntimeError as e:
            log.warning("restart failed %s: %s", chat_id, e)

    async def seek(self, chat_id: int, seconds: int) -> str:
        st = self.state(chat_id)
        track = st.current
        if not track or track.live or not st.playing:
            return "پرش فقط روی فایل‌های دانلودی ممکنه (نه رادیوی زنده)."
        if seconds < 0:
            seconds = 0
        if st.duration and seconds > st.duration:
            seconds = int(st.duration) - 1
        await self._restart_current(chat_id, st, seek=seconds)
        return f"⏩ پرش به ثانیه‌ی {fa_num(seconds)}."

    async def next_track(self, chat_id: int, manual: bool = True) -> str:
        async with self._lock:
            st = self.state(chat_id)
            if not st.queue:
                return "صف خالی است! اول چیزی پخش کن."
            if st.index + 1 >= len(st.queue):
                if manual:
                    return "این آخرین ترک صف است."
                # پایان طبیعی صف
                st.playing = False
                st.paused = False
                return "🏁 صف تمام شد."
            st.index += 1
            await self._start(chat_id, st)
            return f"⏭ در حال پخش: {st.current.display}"

    async def stop(self, chat_id: int) -> None:
        async with self._lock:
            st = self.state(chat_id)
            st.queue = []
            st.index = -1
            st.playing = False
            st.paused = False
            st.switching = False
            try:
                await self.call.leave_call(chat_id)
            except Exception as e:  # noqa: BLE001
                log.warning("leave_call %s: %s", chat_id, e)

    async def on_stream_ended(self, chat_id: int) -> None:
        """پایان طبیعی یا جابه‌جایی دستی ترک."""
        async with self._lock:
            st = self.state(chat_id)
            if st.switching:
                st.switching = False
                # رویداد پایانِ ترکِ قبلی هنگام سوییچ دستی بود؛
                # اگر بعد از مهلت رسیده باشد، پایانِ واقعیِ ترک فعلی است.
                if time.time() < st.switch_deadline:
                    return
            if st.playing and st.index + 1 < len(st.queue):
                st.index += 1
                await self._start(chat_id, st)
                log.info("auto next in %s -> %s", chat_id, st.current.title if st.current else "?")
            else:
                st.playing = False
                log.info("queue finished in %s", chat_id)

    # ---------- وضعیت ----------
    def status_text(self, chat_id: int) -> str:
        st = self.state(chat_id)
        track = st.current
        if not st.playing or track is None:
            if st.downloading:
                return f"⏳ {st.downloading}…"
            if st.error:
                return f"⚠️ {st.error}"
            return "🎧 چیزی در حال پخش نیست. با /پخش شروع کن."
        lines = [
            "🎧 <b>در حال پخش:</b>",
            track.display,
            f"👤 درخواست‌کننده: {html.escape(track.requester)}",
        ]
        if track.live:
            lines.append("🔴 <b>پخش زنده</b> (رادیو)")
        else:
            pos = fa_num(st.index + 1)
            total = fa_num(len(st.queue))
            lines.append(f"📃 ترک {pos} از {total}")
        lines.append(
            f"⏸ {'مکث‌شده' if st.paused else 'در حال پخش'} • {'🔇 بی‌صدا' if st.muted else f'🔊 {fa_num(st.volume)}٪'} • "
            f"🐇 {fa_num(st.speed)}x • 🎚 {st.eq}"
        )
        if st.index + 1 < len(st.queue):
            nxt = st.queue[st.index + 1]
            lines.append(f"⏭ بعدی: {html.escape(nxt.title)}")
        return "\n".join(lines)


# ---------- اتصال رویداد pytgcalls ----------
def register_pytgcalls_events(call: PyTgCalls, manager: PlayerManager) -> None:
    @call.on_update(StreamEnded)
    async def _on_ended(_, update: StreamEnded):  # noqa: ANN001
        try:
            await manager.on_stream_ended(update.chat_id)
        except Exception as e:  # noqa: BLE001
            log.warning("on_stream_ended error: %s", e)
