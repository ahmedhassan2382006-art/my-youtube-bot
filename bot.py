# -*- coding: utf-8 -*-
import os
import re
import logging
import asyncio
import shutil
import tempfile
import uuid
import time
import urllib.request
from typing import Dict, Any, Optional
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup

try:
    from telegram import CopyTextButton
except ImportError:
    CopyTextButton = None

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== إعدادات التوكن والقناة الرسمية ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")

REQUIRED_CHANNEL = os.environ.get("REQUIRED_CHANNEL", "@Basira_Tech")
CHANNEL_URL = os.environ.get("CHANNEL_URL", "https://t.me/Basira_Tech")

# ==================== التحقق من FFmpeg ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def check_ffmpeg() -> bool:
    if shutil.which("ffmpeg"):
        logger.info("✅ FFmpeg متوفر في مسار النظام")
        return True
    ffmpeg_local = os.path.join(BASE_DIR, "ffmpeg.exe")
    if os.path.isfile(ffmpeg_local):
        logger.info("✅ FFmpeg متوفر محلياً")
        return True
    logger.warning("⚠️ FFmpeg غير مثبت.")
    return False

# ==================== التحقق من الكوكيز ====================
COOKIE_FILE = None
local_cookie = os.path.join(BASE_DIR, "cookies.txt")
if os.path.isfile(local_cookie):
    COOKIE_FILE = local_cookie
elif os.environ.get("YTDL_COOKIES"):
    temp_cookie_path = os.path.join(tempfile.gettempdir(), "cookies.txt")
    try:
        with open(temp_cookie_path, "w", encoding="utf-8") as f:
            f.write(os.environ["YTDL_COOKIES"])
        COOKIE_FILE = temp_cookie_path
    except Exception as e:
        logger.warning(f"Could not write cookie file: {e}")

# ==================== إعدادات التحميل ====================
DOWNLOAD_DIR = os.path.join(tempfile.gettempdir(), "tg_media_bot")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MAX_FILE_SIZE = 50 * 1024 * 1024
SAFE_DOWNLOAD_THRESHOLD = 46 * 1024 * 1024

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

YTDL_INFO_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "nocheckcertificate": True,
    "geo_bypass": True,
    "ignoreerrors": False,
}
if COOKIE_FILE:
    YTDL_INFO_OPTS["cookiefile"] = COOKIE_FILE

# ==================== إدارة الذاكرة والعمليات ====================
MEDIA_CACHE: Dict[str, dict] = {}
PLAYLIST_CACHE: Dict[str, dict] = {}
USER_TASK_QUEUES: Dict[int, asyncio.Queue] = {}
USER_CURRENT_TASK: Dict[int, str] = {}
USER_WORKERS: Dict[int, asyncio.Task] = {}
USER_FETCH_LOCKS: Dict[int, asyncio.Lock] = {}

MAX_CONCURRENT_DOWNLOADS = 3
GLOBAL_DOWNLOAD_SEMAPHORE = None

def get_download_semaphore():
    global GLOBAL_DOWNLOAD_SEMAPHORE
    if GLOBAL_DOWNLOAD_SEMAPHORE is None:
        GLOBAL_DOWNLOAD_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
    return GLOBAL_DOWNLOAD_SEMAPHORE

# ==================== نصوص البوت ====================
I18N = {
    "ar": {
        "welcome": (
            "👋 **مرحباً بك يا {name} في بوت التحميل!**\n"
            "المطور: **أحمد حسن عبد النبي** 👨‍💻\n\n"
            "أرسل لي رابط أي مقطع أو قائمة تشغيل من (يوتيوب، فيسبوك، تيك توك، إنستغرام، إكس، بنترست...)\n\n"
            "🎯 **الخدمات المتاحة:**\n"
            "• إرسال المقاطع مباشرة بجودات وصيغ صوتية متعددة.\n"
            "• روابط تحميل مباشرة للمقاطع التي تتجاوز حجم 50 ميجابايت.\n"
            "• تصفح واختيار مقاطع قوائم التشغيل بمعلوماتها الكاملة.\n\n"
            "أرسل الرابط للبدء الآن 🚀"
        ),
        "sub_required": (
            "⚠️ **عذراً، يجب عليك الانضمام إلى قناتنا أولاً لاستخدام البوت!**\n\n"
            "📢 **قناة Basira Tech:**\n"
            "قناة مخصصة لنشر ومشاركة مشاريعنا البرمجية القادمة (برامج كمبيوتر، تطبيقات أندرويد، بوتات وأدوات تقنية).\n\n"
            "انضم إلينا لتصلك مشاريعنا وتحديثاتها أولاً بأول 👇"
        ),
        "checking": "🔍 **جاري فحص الرابط وتجهيز الخيارات...**",
        "fetch_error": "❌ **تعذر جلب بيانات الرابط.** يرجى التأكد أن المقطع متاح للجميع وليس خاصاً.",
        "no_formats": "⚠️ لم يتم العثور على صيغ قابلة للتحميل لهذا المقطع.",
        "title": "📌 **العنوان:** `{title}`",
        "platform": "🌐 **المنصة:** `{platform}`",
        "duration": "⏱ **المدة:** {duration}",
        "choose_type": "👇 **اختر نوع التحميل المطلوب:**",
        "btn_video": "🎬 فيديو",
        "btn_audio": "🎵 صوت فقط",
        "btn_back": "🔙 رجوع",
        "btn_download": "⬇️ تحميل المقطع",
        "btn_copy": "📋 نسخ الرابط",
        "btn_join": "📢 الانضمام إلى قناة Basira Tech",
        "btn_verify_sub": "🔄 تحقق من الاشتراك",
        "expired": "⚠️ انتهت صلاحية هذا الخيار، أرسل الرابط مجدداً.",
        "select_res": "🎬 **اختر الدقة المطلوبة:**\n`{title}`",
        "select_audio": "🎵 **اختر الامتداد الصوتي:**\n`{title}`",
        "opt_not_found": "⚠️ هذا الخيار لم يعد متاحاً، أعد إرسال الرابط.",
        "queue_notice": "⏳ جاري استكمال: **{curr}**\nوسيبدأ تلقائياً تجهيز: **{new}** فور انتهائه.",
        "downloading": "⏳ **جاري تجهيز ({label})...**\nلحظات وسيكون جاهزاً لديك.",
        "uploading": "📤 **جاري إرسال الملف إليك...**",
        "download_error": "❌ **تعذر تحميل المقطع.** يرجى تجربة جودة أخرى.",
        "file_not_found": "❌ حدث خطأ أثناء المعالجة، يرجى المحاولة لاحقاً.",
        "send_error": "❌ تعذر إرسال الملف عبر المحادثة.",
        "link_ready": "✅ **تم تجهيز رابط التحميل بالأسفل 👇**",
        "exceed_limit": (
            "📁 **نظراً لتجاوز الملف حد تيليجرام (50MB)، تم إنشاء رابط تحميل مباشر لك:**\n"
            "اضغط على زر التحميل للتنزيل أو زر النسخ للحفظ عندك 👇"
        ),
        "link_expire_note": "💡 يفضل البدء بالتحميل الآن لحفظ المقطع على جهازك.",
        "not_defined": "غير محدد",
        "minutes_seconds": "{m} دقيقة و {sec} ثانية",
        "hours_minutes": "{h} س {m} د {sec} ث",
        "playlist_header": (
            "📋 **قائمة تشغيل:** `{title}`\n"
            "🌐 **المنصة:** `{platform}`\n"
            "🔢 **عدد المقاطع:** {count} | 📄 **الصفحة:** {page}/{total_pages}\n\n"
            "👇 **تفاصيل المقاطع في هذه الصفحة:**\n"
        ),
    },
    "en": {
        "welcome": (
            "👋 **Welcome {name} to Downloader Bot!**\n"
            "Developer: **Ahmed Hassan Abdelnaby** 👨‍💻\n\n"
            "Send any link or playlist from (YouTube, Facebook, TikTok, Instagram, X...)\n\n"
            "🎯 **Features:**\n"
            "• Direct video & audio downloads.\n"
            "• Fast direct links for media exceeding 50MB.\n"
            "• Playlist browser with detailed video metadata.\n\n"
            "Send your link to start 🚀"
        ),
        "sub_required": (
            "⚠️ **You must join our channel to use the bot!**\n\n"
            "📢 **Basira Tech Channel:**\n"
            "A channel dedicated to publishing our upcoming software projects, desktop apps, Android apps, and bots.\n\n"
            "Join us to stay updated with all our releases 👇"
        ),
        "checking": "🔍 **Analyzing link and preparing options...**",
        "fetch_error": "❌ **Failed to fetch media.** Please ensure the link is public.",
        "no_formats": "⚠️ No downloadable formats found for this link.",
        "title": "📌 **Title:** `{title}`",
        "platform": "🌐 **Platform:** `{platform}`",
        "duration": "⏱ **Duration:** {duration}",
        "choose_type": "👇 **Select content type:**",
        "btn_video": "🎬 Video",
        "btn_audio": "🎵 Audio Only",
        "btn_back": "🔙 Back",
        "btn_download": "⬇️ Download Media",
        "btn_copy": "📋 Copy Link",
        "btn_join": "📢 Join Basira Tech Channel",
        "btn_verify_sub": "🔄 Check Subscription",
        "expired": "⚠️ This option has expired. Please resend the link.",
        "select_res": "🎬 **Select resolution:**\n`{title}`",
        "select_audio": "🎵 **Select audio format:**\n`{title}`",
        "opt_not_found": "⚠️ Option no longer available.",
        "queue_notice": "⏳ Finishing: **{curr}**\n**{new}** will start automatically.",
        "downloading": "⏳ **Preparing ({label})...**\nPlease wait.",
        "uploading": "📤 **Sending file...**",
        "download_error": "❌ **Download failed.** Please try another option.",
        "file_not_found": "❌ An error occurred during processing.",
        "send_error": "❌ Failed to send file.",
        "link_ready": "✅ **Direct download link is ready below 👇**",
        "exceed_limit": (
            "📁 **Due to exceeding Telegram's 50MB limit, a direct link was generated:**\n"
            "Click download below to start or copy to save it 👇"
        ),
        "link_expire_note": "💡 You can start downloading now to save it to your device.",
        "not_defined": "Undefined",
        "minutes_seconds": "{m}m {sec}s",
        "hours_minutes": "{h}h {m}m {sec}s",
        "playlist_header": (
            "📋 **Playlist:** `{title}`\n"
            "🌐 **Platform:** `{platform}`\n"
            "🔢 **Total Videos:** {count} | 📄 **Page:** {page}/{total_pages}\n\n"
            "👇 **Videos list on this page:**\n"
        ),
    }
}

def t(update: Update, key: str, **kwargs) -> str:
    lang = "ar"
    try:
        user = update.effective_user
        if user and user.language_code and not user.language_code.startswith("ar"):
            lang = "en"
    except Exception:
        pass
    text = I18N[lang].get(key, I18N["ar"].get(key, ""))
    if kwargs:
        return text.format(**kwargs)
    return text

# ==================== التحقق الدقيق من الاشتراك الإجباري ====================
async def check_user_subscription(bot, user_id: int):
    """
    التحقق من اشتراك المستخدم
    يعيد: (is_subscribed: bool, admin_error: Optional[str])
    """
    if not REQUIRED_CHANNEL:
        return True, None
    try:
        member = await bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=user_id)
        
        status = str(getattr(member, "status", "")).lower()
        if "." in status:
            status = status.split(".")[-1]
            
        logger.info(f"User {user_id} channel status: '{status}'")

        # يشمل المالك (creator / owner)، المشرفين، الأعضاء العاديين
        if status in ("creator", "administrator", "member", "restricted", "owner"):
            return True, None
            
        return False, None
    except Exception as e:
        err_msg = str(e).lower()
        logger.error(f"Subscription verification error for user {user_id}: {e}")
        
        # إذا كان السبب نقص صلاحية البوت في القناة
        if any(keyword in err_msg for keyword in ("chat not found", "bot is not a member", "not enough rights", "admin")):
            note = "⚠️ تنبيه للمسؤول: البوت ليس مشرفاً (Admin) داخل القناة @Basira_Tech! يجب إضافته كأدمن حتى يستطيع التحقق."
            return False, note
            
        return False, None

def get_sub_markup(update: Update) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(t(update, "btn_join"), url=CHANNEL_URL)],
        [InlineKeyboardButton(t(update, "btn_verify_sub"), callback_data="check_sub")]
    ]
    return InlineKeyboardMarkup(buttons)

async def require_subscription_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, admin_err: Optional[str] = None):
    msg = t(update, "sub_required")
    if admin_err:
        msg += f"\n\n⚙️ **{admin_err}**"
        
    markup = get_sub_markup(update)
    if update.message:
        await update.message.reply_text(msg, reply_markup=markup, parse_mode="Markdown")
    elif update.callback_query:
        try:
            await update.callback_query.message.reply_text(msg, reply_markup=markup, parse_mode="Markdown")
        except Exception:
            pass

# ==================== دوال مساعدة ====================
def format_size(bytes_val) -> str:
    if not bytes_val:
        return ""
    mb = bytes_val / (1024 * 1024)
    if mb >= 1024:
        return f" ({mb / 1024:.1f} GB)"
    return f" ({mb:.1f} MB)"

def format_duration_str(seconds, update: Update) -> str:
    if not seconds:
        return t(update, "not_defined")
    try:
        s = int(seconds)
    except (ValueError, TypeError):
        return t(update, "not_defined")
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h > 0:
        return t(update, "hours_minutes", h=h, m=m, sec=sec)
    return t(update, "minutes_seconds", m=m, sec=sec)

def format_duration_compact(seconds) -> str:
    if not seconds:
        return "--:--"
    try:
        s = int(seconds)
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        if h > 0:
            return f"{h:02d}:{m:02d}:{sec:02d}"
        return f"{m:02d}:{sec:02d}"
    except Exception:
        return "--:--"

def unshorten_url(url: str) -> str:
    clean_url = url.strip()
    if any(dom in clean_url for dom in ("tiktok.com", "fb.watch", "facebook.com", "youtu.be")):
        try:
            req = urllib.request.Request(
                clean_url,
                headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                resolved = resp.geturl()
                if resolved:
                    return resolved
        except Exception:
            pass
    return clean_url

# ==================== تحليل بيانات المقطع ====================
def parse_media_data(info: Dict[str, Any]):
    formats = info.get("formats", []) or []
    video_options: Dict[str, dict] = {}
    audio_formats: Dict[str, dict] = {}
    best_progressive: Optional[dict] = None
    best_progressive_height = -1

    single_url = info.get("url")
    if isinstance(single_url, str) and single_url.startswith("http"):
        video_options["أفضل دقة متاحة"] = {
            "height": info.get("height"),
            "size": info.get("filesize") or info.get("filesize_approx") or 0,
            "single_url": single_url,
            "ext": (info.get("ext") or "mp4").lower(),
        }

    for f in formats:
        url = f.get("url", "") or ""
        if not url.startswith("http"):
            continue

        vcodec = f.get("vcodec")
        acodec = f.get("acodec")
        ext = (f.get("ext") or "mp4").lower()
        height = f.get("height")
        size = f.get("filesize") or f.get("filesize_approx") or 0
        format_note = str(f.get("format_note") or "").upper()
        format_id = str(f.get("format_id") or "").upper()

        is_audio_only = (
            (vcodec == "none" and acodec and acodec != "none")
            or f.get("resolution") == "audio only"
            or ext in ("mp3", "m4a", "aac", "opus", "wav", "flac")
        )

        is_video = not is_audio_only

        if is_video:
            if height:
                label = f"{height}p"
            elif "HD" in format_note or "HD" in format_id:
                label = "HD"
            elif "SD" in format_note or "SD" in format_id:
                label = "SD"
            else:
                label = "Standard"

            if label not in video_options:
                video_options[label] = {
                    "height": height,
                    "size": size,
                    "ext": ext,
                    "single_url": url if ".m3u8" not in url else None,
                }
            else:
                if size > 0 and not video_options[label].get("size"):
                    video_options[label]["size"] = size
                if not video_options[label].get("single_url") and ".m3u8" not in url:
                    video_options[label]["single_url"] = url

            is_progressive = (
                (vcodec and vcodec != "none" and acodec and acodec != "none")
                or (vcodec is None and acodec is None)
            )
            if is_progressive and ".m3u8" not in url:
                h = height or 0
                if h >= best_progressive_height:
                    best_progressive_height = h
                    best_progressive = {
                        "url": url,
                        "ext": ext,
                        "size": size,
                        "height": h,
                    }

        if is_audio_only:
            audio_label = ext.upper() if ext else "AUDIO"
            if audio_label not in audio_formats:
                audio_formats[audio_label] = {
                    "ext": ext,
                    "size": size,
                    "direct_url": url if ".m3u8" not in url else None,
                }

    if not video_options:
        video_options["أفضل دقة متاحة"] = {
            "height": info.get("height"),
            "size": info.get("filesize") or info.get("filesize_approx") or 0,
            "single_url": info.get("url") if (isinstance(info.get("url"), str) and ".m3u8" not in info.get("url")) else None,
            "ext": (info.get("ext") or "mp4").lower(),
        }

    if not audio_formats and video_options:
        audio_formats["MP3"] = {
            "ext": "mp3",
            "size": 0,
            "direct_url": None,
        }

    return video_options, audio_formats, best_progressive

def estimate_size(option: dict, media: dict, mode: str) -> int:
    if mode == "audio":
        sz = option.get("size") or 0
        if sz > 0:
            return int(sz * 1.05)
        duration = media.get("duration", 0) or 0
        if duration > 0:
            return int(128 * 1000 * duration / 8 * 1.1)
        return 0

    if option.get("single_url"):
        sz = option.get("size") or 0
        if sz > 0:
            return int(sz * 1.05)

    video_size = option.get("size") or 0
    audio_size = 0
    for a_info in media.get("audio_fmts", {}).values():
        a_sz = a_info.get("size") or 0
        if a_sz > audio_size:
            audio_size = a_sz

    if video_size > 0:
        return int((video_size + audio_size) * 1.15)

    duration = media.get("duration", 0) or 0
    if duration <= 0:
        return 0

    height = option.get("height") or 0
    if height >= 2160:
        mbps = 40
    elif height >= 1440:
        mbps = 20
    elif height >= 1080:
        mbps = 8
    elif height >= 720:
        mbps = 4
    elif height >= 480:
        mbps = 2
    else:
        mbps = 1

    return int(mbps * duration * 1024 * 1024 / 8 * 1.2)

def _build_main_keyboard(media_id: str, media: dict, update: Update):
    keyboard = []
    row = []
    if media.get("video_opts"):
        row.append(InlineKeyboardButton(t(update, "btn_video"), callback_data=f"sv:{media_id}"))
    if media.get("audio_fmts"):
        row.append(InlineKeyboardButton(t(update, "btn_audio"), callback_data=f"sa:{media_id}"))
    if row:
        keyboard.append(row)
    return keyboard

# ==================== بناء قائمة التشغيل ====================
def _build_playlist_page(pl_id: str, page: int, update: Update, per_page: int = 5):
    pl_data = PLAYLIST_CACHE.get(pl_id)
    if not pl_data:
        return "", []

    entries = pl_data.get("entries", [])
    total = len(entries)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))

    start = page * per_page
    end = min(start + per_page, total)

    header = t(
        update,
        "playlist_header",
        title=pl_data.get("title", "Playlist")[:65],
        platform=pl_data.get("platform", "Web"),
        count=total,
        page=page + 1,
        total_pages=total_pages,
    )

    items_text_list = []
    keyboard = []

    for idx in range(start, end):
        e = entries[idx]
        title = e.get("title") or f"Video {idx+1}"
        dur_raw = e.get("duration") or 0
        dur_compact = format_duration_compact(dur_raw)
        uploader = e.get("uploader") or e.get("channel") or "Unknown"

        items_text_list.append(
            f"🔹 **{idx+1}.** `{title[:55]}`\n"
            f"   ⏱ **المدة:** {dur_compact}  |  👤 **الناشر:** `{uploader[:25]}`\n"
        )

        btn_label = f"{idx+1}. {title[:22]} ⏱{dur_compact}"
        keyboard.append([InlineKeyboardButton(btn_label, callback_data=f"ple:{pl_id}:{idx}")])

    full_text = header + "\n".join(items_text_list)

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("➡️ السابق", callback_data=f"plp:{pl_id}:{page-1}"))
    if end < total:
        nav_row.append(InlineKeyboardButton("التالي ⬅️", callback_data=f"plp:{pl_id}:{page+1}"))
    if nav_row:
        keyboard.append(nav_row)

    return full_text, keyboard

# ==================== أوامر ومعالجات البوت ====================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_sub, admin_err = await check_user_subscription(context.bot, user_id)
    if not is_sub:
        await require_subscription_prompt(update, context, admin_err)
        return

    user_name = update.effective_user.first_name or "صديقي"
    msg = t(update, "welcome", name=user_name)
    await update.message.reply_text(msg, parse_mode="Markdown")

async def process_single_link(target_url: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_url = unshorten_url(target_url)
    status_msg = await update.message.reply_text(t(update, "checking"), parse_mode="Markdown")

    def fetch():
        is_youtube = any(d in target_url for d in ("youtube.com", "youtu.be"))
        if is_youtube:
            strategies = [
                {"user_agent": USER_AGENT, "extractor_args": {"youtube": {"player_client": ["android", "ios", "mweb"]}}},
                {"user_agent": USER_AGENT, "extractor_args": {"youtube": {"player_client": ["ios", "mweb", "web"]}}},
                {},
            ]
        else:
            strategies = [
                {},
                {"user_agent": USER_AGENT},
            ]

        last_exception = None
        for strat in strategies:
            opts = dict(YTDL_INFO_OPTS)
            opts.update(strat)
            opts["extract_flat"] = "in_playlist"
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    data = ydl.extract_info(target_url, download=False)
                    if data:
                        return data
            except Exception as err:
                last_exception = err
                continue
        raise last_exception or Exception("Failed to fetch info")

    try:
        info = await asyncio.to_thread(fetch)
    except Exception as e:
        logger.error(f"Error fetching url {target_url}: {e}")
        await status_msg.edit_text(t(update, "fetch_error"), parse_mode="Markdown")
        return

    is_playlist = (
        info.get("_type") == "playlist"
        or ("entries" in info and isinstance(info["entries"], (list, type((x for x in [])))))
    )

    if is_playlist:
        entries = [e for e in info.get("entries", []) if e]
        if not entries:
            await status_msg.edit_text(t(update, "no_formats"))
            return

        pl_id = uuid.uuid4().hex[:8]
        PLAYLIST_CACHE[pl_id] = {
            "id": pl_id,
            "title": info.get("title", "Playlist"),
            "platform": info.get("extractor_key", "Web"),
            "entries": entries,
            "time": time.time(),
        }

        pl_text, keyboard = _build_playlist_page(pl_id, 0, update)
        await status_msg.edit_text(
            pl_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return

    video_opts, audio_fmts, best_prog = parse_media_data(info)
    if not video_opts and not audio_fmts:
        await status_msg.edit_text(t(update, "no_formats"))
        return

    media_id = uuid.uuid4().hex[:8]
    MEDIA_CACHE[media_id] = {
        "id": media_id,
        "title": info.get("title", "media"),
        "platform": info.get("extractor_key", "Web"),
        "duration": info.get("duration", 0),
        "video_opts": video_opts,
        "audio_fmts": audio_fmts,
        "best_progressive": best_prog,
        "webpage_url": info.get("webpage_url") or target_url,
        "time": time.time(),
    }

    if len(MEDIA_CACHE) > 500:
        oldest = sorted(MEDIA_CACHE.keys(), key=lambda k: MEDIA_CACHE[k]["time"])[:100]
        for k in oldest:
            MEDIA_CACHE.pop(k, None)

    dur_str = format_duration_str(info.get("duration", 0), update)
    keyboard = _build_main_keyboard(media_id, MEDIA_CACHE[media_id], update)

    info_text = (
        f"{t(update, 'title', title=info.get('title', 'media')[:70])}\n"
        f"{t(update, 'platform', platform=info.get('extractor_key', 'Web'))}\n"
        f"{t(update, 'duration', duration=dur_str)}\n\n"
        f"{t(update, 'choose_type')}"
    )

    await status_msg.edit_text(
        info_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    is_sub, admin_err = await check_user_subscription(context.bot, user_id)
    if not is_sub:
        await require_subscription_prompt(update, context, admin_err)
        return

    text = update.message.text or ""
    urls = re.findall(r'(https?://[^\s]+)', text)
    if not urls:
        return

    if user_id not in USER_FETCH_LOCKS:
        USER_FETCH_LOCKS[user_id] = asyncio.Lock()

    async with USER_FETCH_LOCKS[user_id]:
        for target_url in urls:
            try:
                await process_single_link(target_url, update, context)
            except Exception as e:
                logger.error(f"Error processing link {target_url}: {e}")

# ==================== إرسال رابط التحميل المباشر مع زر النسخ ====================
async def send_download_link(query, update: Update, media: dict, option: dict, label: str, mode: str, predicted_size: int):
    direct_url = None

    if mode == "audio":
        direct_url = option.get("direct_url")
    elif mode == "video":
        if option.get("single_url"):
            direct_url = option["single_url"]
        else:
            bp = media.get("best_progressive")
            if bp and bp.get("url"):
                direct_url = bp["url"]

    if not direct_url:
        direct_url = media["webpage_url"]

    media["last_direct_url"] = direct_url
    mid = media.get("id", "")

    is_webpage = (direct_url == media["webpage_url"])
    size_str = format_size(predicted_size) if predicted_size else ""
    title_short = (media.get("title") or "media")[:70]

    text = (
        f"{t(update, 'title', title=title_short)}\n"
        f"{t(update, 'platform', platform=media.get('platform', 'Web'))}\n"
        f"{t(update, 'duration', duration=format_duration_str(media.get('duration', 0), update))}\n"
        f"🎯 **الجودة:** {label}{size_str}\n\n"
        f"{t(update, 'exceed_limit')}\n\n"
        f"🔗 **رابط التحميل:**\n`{direct_url}`\n\n"
        f"{t(update, 'link_expire_note')}"
    )

    action_buttons = [InlineKeyboardButton(t(update, "btn_download"), url=direct_url)]

    if CopyTextButton:
        try:
            action_buttons.append(
                InlineKeyboardButton(t(update, "btn_copy"), copy_text=CopyTextButton(text=direct_url))
            )
        except Exception:
            if mid:
                action_buttons.append(
                    InlineKeyboardButton(t(update, "btn_copy"), callback_data=f"cp:{mid}")
                )
    elif mid:
        action_buttons.append(
            InlineKeyboardButton(t(update, "btn_copy"), callback_data=f"cp:{mid}")
        )

    keyboard = InlineKeyboardMarkup([action_buttons])

    try:
        await query.edit_message_text(t(update, "link_ready"), parse_mode="Markdown")
    except Exception:
        pass

    await query.message.reply_text(
        text,
        reply_markup=keyboard,
        parse_mode="Markdown",
        disable_web_page_preview=not is_webpage,
    )

# ==================== طابور التحميل المتتابع ====================
async def user_download_worker(user_id: int):
    q = USER_TASK_QUEUES[user_id]
    while True:
        task = await q.get()
        if task is None:
            break
        query, update, media, mode, label, option = task
        USER_CURRENT_TASK[user_id] = f"{label} ({media.get('title', 'media')[:25]}...)"
        try:
            await perform_download_and_send(query, update, media, mode, label, option)
        except Exception as e:
            logger.error(f"Worker task error: {e}", exc_info=True)
            try:
                await query.message.reply_text(t(update, "send_error"))
            except Exception:
                pass
        finally:
            USER_CURRENT_TASK.pop(user_id, None)
            q.task_done()

def ensure_user_worker(user_id: int):
    worker = USER_WORKERS.get(user_id)
    if worker is None or worker.done():
        if user_id not in USER_TASK_QUEUES:
            USER_TASK_QUEUES[user_id] = asyncio.Queue()
        USER_WORKERS[user_id] = asyncio.create_task(user_download_worker(user_id))

async def enqueue_download(query, update: Update, media: dict, mode: str, label: str, option: dict):
    user_id = query.from_user.id
    ensure_user_worker(user_id)

    if user_id in USER_CURRENT_TASK:
        curr = USER_CURRENT_TASK[user_id]
        new_task = f"{label} ({media.get('title', 'media')[:25]}...)"
        await query.message.reply_text(t(update, "queue_notice", curr=curr, new=new_task), parse_mode="Markdown")

    await USER_TASK_QUEUES[user_id].put((query, update, media, mode, label, option))

# ==================== تنفيذ التحميل والإرسال ====================
async def perform_download_and_send(query, update: Update, media: dict, mode: str, label: str, option: dict):
    est = estimate_size(option, media, mode)
    should_download = False
    if est > 0 and est < SAFE_DOWNLOAD_THRESHOLD:
        should_download = True
    elif est == 0:
        duration = media.get("duration", 0) or 0
        if mode == "audio" or not duration or duration < 300:
            should_download = True

    if not should_download:
        await send_download_link(query, update, media, option, label, mode, est)
        return

    user_id = query.from_user.id
    try:
        status = await query.message.reply_text(t(update, "downloading", label=label), parse_mode="Markdown")
    except Exception:
        status = None

    if mode == "audio":
        format_selector = "bestaudio/best"
    else:
        height = option.get("height")
        if option.get("single_url") or not height:
            format_selector = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
        else:
            format_selector = (
                f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
                f"bestvideo[height<={height}]+bestaudio/"
                f"best[height<={height}]/best"
            )

    base_name = f"{user_id}_{uuid.uuid4().hex[:8]}"
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{base_name}.%(ext)s")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "outtmpl": outtmpl,
        "format": format_selector,
        "merge_output_format": "mp4",
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 4,
    }
    if COOKIE_FILE:
        ydl_opts["cookiefile"] = COOKIE_FILE

    is_youtube = any(d in media["webpage_url"] for d in ("youtube.com", "youtu.be"))
    if is_youtube:
        ydl_opts["user_agent"] = USER_AGENT
        ydl_opts["extractor_args"] = {
            "youtube": {
                "player_client": ["android", "ios", "mweb", "web"],
                "player_skip": ["configs"],
            }
        }

    def do_download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(media["webpage_url"], download=True)
            rd = info.get("requested_downloads") or []
            for r in rd:
                fp = r.get("filepath")
                if fp and os.path.exists(fp):
                    return fp
            filepath = ydl.prepare_filename(info)
            stem = os.path.splitext(filepath)[0]
            for try_ext in (".mp4", ".mkv", ".webm", ".m4a", ".opus", ".mp3"):
                candidate = stem + try_ext
                if os.path.exists(candidate):
                    return candidate
            return filepath

    sem = get_download_semaphore()
    async with sem:
        try:
            filepath = await asyncio.to_thread(do_download)
        except Exception as e:
            logger.error(f"Download error: {e}")
            if status:
                await status.edit_text(t(update, "download_error"), parse_mode="Markdown")
            return

    if not filepath or not os.path.exists(filepath):
        if status:
            await status.edit_text(t(update, "file_not_found"))
        return

    filesize = os.path.getsize(filepath)
    if filesize > MAX_FILE_SIZE:
        try:
            os.remove(filepath)
        except Exception:
            pass
        await send_download_link(query, update, media, option, label, mode, filesize)
        if status:
            try:
                await status.delete()
            except Exception:
                pass
        return

    if filesize > 15 * 1024 * 1024 and status:
        try:
            await status.edit_text(t(update, "uploading"), parse_mode="Markdown")
        except Exception:
            pass

    title = media.get("title") or "media"
    caption = f"📥 {title[:200]}"
    if mode == "video" and label != "أفضل دقة متاحة":
        caption += f"\n🖥 الدقة: {label}"
    elif mode == "audio":
        caption += f"\n🎵 الصيغة: {label}"

    try:
        with open(filepath, "rb") as fh:
            if mode == "audio":
                await query.message.reply_audio(audio=fh, title=title[:60], caption=caption[:1024])
            else:
                await query.message.reply_video(video=fh, caption=caption[:1024], supports_streaming=True)
    except Exception as e:
        logger.error(f"Send error: {e}")
        try:
            with open(filepath, "rb") as fh:
                await query.message.reply_document(document=fh, caption=caption[:1024])
        except Exception as e2:
            logger.error(f"Doc send error: {e2}")
            if status:
                await status.edit_text(t(update, "send_error"))
            return
    finally:
        try:
            os.remove(filepath)
        except Exception:
            pass

    if status:
        try:
            await status.delete()
        except Exception:
            pass

# ==================== معالج الأزرار ====================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    # زر التحقق من الاشتراك
    if data == "check_sub":
        is_sub, admin_err = await check_user_subscription(context.bot, user_id)
        if is_sub:
            await query.answer("✅ تم التحقق بنجاح! أنت الآن مشترك في القناة.", show_alert=True)
            user_name = query.from_user.first_name or "صديقي"
            await query.edit_message_text(t(update, "welcome", name=user_name), parse_mode="Markdown")
        else:
            if admin_err:
                # يظهر التنبيه للمسؤول مباشرة لمعرفة المشكلة
                await query.answer(admin_err, show_alert=True)
            else:
                await query.answer("❌ ما زلت غير منضم لقناة Basira Tech! اشترك أولاً ثم اضغط تحقق.", show_alert=True)
        return

    # التحقق من الاشتراك قبل تنفيذ أي زر آخر
    is_sub, admin_err = await check_user_subscription(context.bot, user_id)
    if not is_sub:
        await query.answer("⚠️ لا يمكنك الاستمرار دون الاشتراك في القناة!", show_alert=True)
        await require_subscription_prompt(update, context, admin_err)
        return

    await query.answer()

    if data.startswith("sv:"):
        mid = data[3:]
        media = MEDIA_CACHE.get(mid)
        if not media:
            await query.edit_message_text(t(update, "expired"))
            return
        opts = media["video_opts"]
        keyboard = []

        def sort_key(k):
            m = re.match(r"(\d+)p", k)
            if m:
                return int(m.group(1))
            if "HD" in k:
                return 1080
            if "SD" in k:
                return 480
            if "أفضل" in k or "Best" in k:
                return 9999
            return 0

        for label in sorted(opts.keys(), key=sort_key, reverse=True):
            size_str = format_size(opts[label].get("size"))
            keyboard.append([InlineKeyboardButton(f"🖥 {label}{size_str}", callback_data=f"rv:{mid}:{label}")])
        keyboard.append([InlineKeyboardButton(t(update, "btn_back"), callback_data=f"bm:{mid}")])

        await query.edit_message_text(
            t(update, "select_res", title=media['title'][:60]),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    elif data.startswith("sa:"):
        mid = data[3:]
        media = MEDIA_CACHE.get(mid)
        if not media:
            await query.edit_message_text(t(update, "expired"))
            return
        audio_fmts = media["audio_fmts"]
        keyboard = []
        for label, item in audio_fmts.items():
            size_str = format_size(item.get("size"))
            keyboard.append([InlineKeyboardButton(f"🎧 {label}{size_str}", callback_data=f"ra:{mid}:{label}")])
        keyboard.append([InlineKeyboardButton(t(update, "btn_back"), callback_data=f"bm:{mid}")])

        await query.edit_message_text(
            t(update, "select_audio", title=media['title'][:60]),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    elif data.startswith("rv:"):
        _, mid, label = data.split(":", 2)
        media = MEDIA_CACHE.get(mid)
        if not media:
            await query.edit_message_text(t(update, "expired"))
            return
        option = media["video_opts"].get(label)
        if not option:
            await query.edit_message_text(t(update, "opt_not_found"))
            return
        await enqueue_download(query, update, media, mode="video", label=label, option=option)

    elif data.startswith("ra:"):
        _, mid, label = data.split(":", 2)
        media = MEDIA_CACHE.get(mid)
        if not media:
            await query.edit_message_text(t(update, "expired"))
            return
        option = media["audio_fmts"].get(label)
        if not option:
            await query.edit_message_text(t(update, "opt_not_found"))
            return
        await enqueue_download(query, update, media, mode="audio", label=label, option=option)

    elif data.startswith("bm:"):
        mid = data[3:]
        media = MEDIA_CACHE.get(mid)
        if not media:
            await query.edit_message_text(t(update, "expired"))
            return
        keyboard = _build_main_keyboard(mid, media, update)
        info_text = (
            f"{t(update, 'title', title=media['title'][:70])}\n\n"
            f"{t(update, 'choose_type')}"
        )
        await query.edit_message_text(info_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("plp:"):
        _, pl_id, page_s = data.split(":", 2)
        page = int(page_s)
        pl_text, keyboard = _build_playlist_page(pl_id, page, update)
        if not pl_text:
            await query.edit_message_text(t(update, "expired"))
            return
        await query.edit_message_text(pl_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("ple:"):
        _, pl_id, idx_s = data.split(":", 2)
        idx = int(idx_s)
        pl_data = PLAYLIST_CACHE.get(pl_id)
        if not pl_data or idx >= len(pl_data.get("entries", [])):
            await query.edit_message_text(t(update, "expired"))
            return

        entry = pl_data["entries"][idx]
        target_url = entry.get("url") or f"https://www.youtube.com/watch?v={entry.get('id')}"

        await query.edit_message_text(t(update, "checking"), parse_mode="Markdown")

        def fetch_entry():
            opts = dict(YTDL_INFO_OPTS)
            opts["extract_flat"] = False
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(target_url, download=False)

        try:
            info = await asyncio.to_thread(fetch_entry)
        except Exception as e:
            logger.error(f"Failed to fetch entry: {e}")
            await query.edit_message_text(t(update, "fetch_error"), parse_mode="Markdown")
            return

        video_opts, audio_fmts, best_prog = parse_media_data(info)
        media_id = uuid.uuid4().hex[:8]
        MEDIA_CACHE[media_id] = {
            "id": media_id,
            "title": info.get("title", "media"),
            "platform": info.get("extractor_key", "Web"),
            "duration": info.get("duration", 0),
            "video_opts": video_opts,
            "audio_fmts": audio_fmts,
            "best_progressive": best_prog,
            "webpage_url": info.get("webpage_url") or target_url,
            "time": time.time(),
        }

        dur_str = format_duration_str(info.get("duration", 0), update)
        keyboard = _build_main_keyboard(media_id, MEDIA_CACHE[media_id], update)
        info_text = (
            f"{t(update, 'title', title=info.get('title', 'media')[:70])}\n"
            f"{t(update, 'platform', platform=info.get('extractor_key', 'Web'))}\n"
            f"{t(update, 'duration', duration=dur_str)}\n\n"
            f"{t(update, 'choose_type')}"
        )
        await query.edit_message_text(info_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("cp:"):
        mid = data[3:]
        media = MEDIA_CACHE.get(mid)
        target_link = media.get("last_direct_url") or (media.get("webpage_url") if media else "")
        if target_link:
            await query.answer("📋 اضغط مطولاً على الرابط لنسخه!")
            await query.message.reply_text(
                f"📋 **اضغط على الرابط بالأسفل لنسخه:**\n`{target_link}`",
                parse_mode="Markdown"
            )
        else:
            await query.answer(t(update, "expired"))

# ==================== التشغيل ====================
async def on_startup(app):
    check_ffmpeg()
    print("🚀 تم تشغيل البوت بنجاح وربطه بقناة @Basira_Tech الرسمية!")

async def on_shutdown(app):
    for worker in USER_WORKERS.values():
        worker.cancel()

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN غير موجود! تأكد من وضعه في Secrets.")

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(16)
        .read_timeout(300)
        .write_timeout(300)
        .connect_timeout(60)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(CallbackQueryHandler(callback_handler))

    app.run_polling(close_loop=False, drop_pending_updates=True)

if __name__ == "__main__":
    main()