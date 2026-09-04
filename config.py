"""تنظیمات ربات — همه‌چیز از طریق متغیرهای محیطی (Secrets) خوانده می‌شود."""
import os
from pathlib import Path

# ---------- داده‌های اجباری تلگرام ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
# در صورت نبود متغیر محیطی، از اعتبارنامه‌ی رسمی «تلگرام دسکتاپ» استفاده می‌شود
# (برای کاربردهایی که دسترسی به my.telegram.org ندارند؛ مثل ایران)
API_ID = int(os.environ.get("API_ID", "2040") or 2040)
API_HASH = os.environ.get("API_HASH", "b18441a1ff607e10a989891a5462e627").strip()

# ---------- تنظیمات عمومی ----------
PORT = int(os.environ.get("PORT", "7860") or 7860)  # Hugging Face روی ۷۸۶۰ است
HOST = os.environ.get("HOST", "0.0.0.0")

# پوشه‌ها (در داخل کانتینر؛ روی هر rebuild پاک می‌شود)
WORK_DIR = Path(os.environ.get("WORK_DIR", "/tmp/musicbot"))


def _ensure_dir(path: Path, fallback: Path) -> Path:
    """اگر پوشه قابل ساخت/نوشتن نبود، به مسیر جایگزین برمی‌گردیم."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except Exception:  # noqa: BLE001
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


WORK_DIR = _ensure_dir(WORK_DIR, Path("/tmp/musicbot_fallback"))
PLAYLIST_DIR = _ensure_dir(Path(os.environ.get("PLAYLIST_DIR", "/data/playlists")),
                           WORK_DIR / "playlists")

# فقط این کاربران (با آیدی عددی که /ایدی می‌دهد) اجازه‌ی کنترل دارند؟
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
# اگر خالی باشد: همه می‌توانند کنترل کنند. اگر پر باشد: فقط همین آیدی‌ها.
# اگر "ADMIN_ONLY_GROUPS=true" باشد در گروه‌ها فقط ادمین‌های گروه کنترل می‌کنند.
ADMIN_ONLY_GROUPS = os.environ.get("ADMIN_ONLY_GROUPS", "false").lower() == "true"

# حجم پیش‌فرض (۰ تا ۲۰۰)
DEFAULT_VOLUME = int(os.environ.get("DEFAULT_VOLUME", "100") or 100)
DEFAULT_VOLUME = max(0, min(200, DEFAULT_VOLUME))

# کیفیت صدا: HIGH آهنگ = استریو ۴۸k، MEDIUM مونو ۳۶k (سبک‌تر)
AUDIO_QUALITY = os.environ.get("AUDIO_QUALITY", "HIGH").upper()  # HIGH / MEDIUM / LOW

# مدل کاری: هر متن ساده در گروه = جستجوی آهنگ (true) یا فقط با /پخش (false)
SEARCH_ON_TEXT = os.environ.get("SEARCH_ON_TEXT", "true").lower() == "true"
# تعداد نتایج جستجو در هر کارت
SEARCH_LIMIT = int(os.environ.get("SEARCH_LIMIT", "5") or 5)
# سقف دانلود فایل تلگرام (محدودیت Bot API حدود ۲۰ مگابایت است)
MAX_TG_DOWNLOAD_MB = int(os.environ.get("MAX_TG_DOWNLOAD_MB", "20") or 20)

# تعداد کارگر Async (affinity با تعداد هسته‌ها)
WORKERS = int(os.environ.get("WORKERS", "4") or 4)

# پیام‌های متنی
TEXT_HELP = (
    "🎧 <b>پلیر تلگرام</b> (موسیقی + رادیو + ویدیو)\n\n"
    "<b>🧠 روش استفاده (خیلی ساده):</b>\n"
    "• <b>اسم آهنگ</b> رو مستقیم توی گروه بنویس (مثلاً: ساعت تندار محسن چاوشی)\n"
    "   → ربات جستجو می‌کنه و <b>کارت نتایج</b> رو می‌فرسته → روی یکی بزن → پخش!\n"
    "• <b>لینک یوتیوب</b> یا لینک رادیو (m3u8) رو بفرست → دکمه‌ی پخش\n"
    "• <b>ویدیو/فایل صوتی</b> توی گروه بفرست → دکمه‌ی «▶ پخش در ویس‌چت»\n\n"
    "<b>🎛 دستورات کنترلی:</b>\n"
    "• /مکث — توقف موقت      • /ادامه — ادامه\n"
    "• /توقف — خروج از پخش      • /بعدی — ترک بعدی\n"
    "• /بی‌صدا — قطع صدا      • /صدا — وصل صدا\n"
    "• /میزان <۰ تا ۲۰۰> — بلندی صدا (مثلاً /میزان 120)\n"
    "• /سرعت <0.5 تا 2> — سرعت پخش (مثلاً /سرعت 1.5)\n"
    "• /ایکولایزر <عادی|باس|شاد|نرم> — اکولایزر\n"
    "• /پرش <ثانیه> — پرش (مثلاً /پرش 90)\n"
    "• /صف — لیست پخش      • /وضعیت — وضعیت فعلی\n"
    "• /پخش <اسم یا لینک> — جستجوی دستی      • /پینگ — تست زنده بودن\n\n"
    "همه‌ی کنترل‌ها روی خودِ کارتِ پخش هم با دکمه هست. 🎶"
)

EQUALIZERS = ["عادی", "باس", "شاد", "نرم"]

EQ_FILTERS = {
    "عادی": "",
    "باس": "bass=g=10:f=120:w=0.7",
    "شاد": "treble=g=8:f=4000:w=0.6",
    "نرم": "bass=g=6:f=200:w=0.6,treble=g=5:f=7000:w=0.5",
}
