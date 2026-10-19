# -*- coding: utf-8 -*-
import os
import re
import logging
import asyncio
import shutil
import tempfile
import uuid
import time
from typing import Dict, Any, Optional
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

# جلب التوكن من متغيرات البيئة (GitHub Secrets)
BOT_TOKEN = os.environ.get("BOT_TOKEN")

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
    "noplaylist": True,
    "user_agent": USER_AGENT,
    "nocheckcertificate": True,
}

# ==================== إدارة الذاكرة والعمليات ====================
MEDIA_CACHE: Dict[str, dict] = {}
USER_TASK_QUEUES: Dict[int, asyncio.Queue] = {}
USER_CURRENT_TASK: Dict[int, str] = {}
USER_WORKERS: Dict[int, asyncio.Task] = {}

MAX_CONCURRENT_DOWNLOADS = 3
GLOBAL_DOWNLOAD_SEMAPHORE = None

def get_download_semaphore():
    global GLOBAL_DOWNLOAD_SEMAPHORE
    if GLOBAL_DOWNLOAD_SEMAPHORE is None:
        GLOBAL_DOWNLOAD_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
    return GLOBAL_DOWNLOAD_SEMAPHORE

# ==================== قاموس النصوص (تجربة مستخدم راقية ونظيفة) ====================
I18N = {
    "ar": {
        "welcome": (
            "👋 **مرحباً بك يا {name} في بوت التحميل الذكي!**\n"
            "المطور: **أحمد حسن عبد النبي** 👨‍💻\n\n"
            "أرسل لي رابط أي مقطع من (يوتيوب، فيسبوك، تيك توك، إنستغرام، إكس، بنترست...)\n\n"
            "🎯 **مميزات البوت:**\n"
            "• إرسال المقاطع مباشرة بجودات متعددة صوت وصورة.\n"
            "• روابط تحميل مباشرة وفائقة السرعة للمقاطع الطويلة.\n\n"
            "🚀 أرسل الرابط الآن للبدء مباشرة!"
        ),
        "checking": "⚡ **جاري فحص الرابط وتجهيز الخيارات...**",
        "fetch_error": "❌ **تعذر جلب بيانات الرابط.** يرجى التأكد أن المقطع متاح للجميع وليس خاصاً.",
        "no_formats": "⚠️ لم يتم العثور على صيغ قابلة للتحميل لهذا المقطع.",
        "title": "📌 **العنوان:** `{title}`",
        "platform": "🌐 **المنصة:** `{platform}`",
        "duration": "⏱ **المدة:** {duration}",
        "choose_type": "👇 **اختر ما يناسبك للتحميل:**",
        "btn_video": "🎬 فيديو",
        "btn_audio": "🎵 صوت فقط",
        "btn_back": "🔙 رجوع",
        "btn_download": "⬇️ تحميل المقطع",
        "expired": "⚠️ انتهت صلاحية هذا الخيار، أرسل الرابط مجدداً وسأجهزه لك فوراً.",
        "select_res": "🎬 **اختر الدقة المناسبة لك:**\n`{title}`",
        "select_audio": "🎵 **اختر الامتداد الصوتي المناسب:**\n`{title}`",
        "opt_not_found": "⚠️ هذا الخيار لم يعد متاحاً، أعد إرسال الرابط.",
        "queue_notice": "⏳ جاري استكمال تحميل: **{curr}**\nوسيبدأ تلقائياً تجهيز: **{new}** فور انتهائه مباشرة.",
        "downloading": "⏳ **جاري تجهيز وتحميل ({label})...**\nلحظات وسيكون جاهزاً لديك.",
        "uploading": "📤 **جاري إرسال الملف إليك الآن...**",
        "download_error": "❌ **تعذر تحميل المقطع.** يرجى تجربة جودة أخرى أو المحاولة لاحقاً.",
        "file_not_found": "❌ حدث خطأ غير متوقع أثناء المعالجة، يرجى إعادة المحاولة.",
        "send_error": "❌ تعذر إرسال الملف عبر المحادثة.",
        "link_ready": "✅ **تم تجهيز رابط التحميل المباشر لك بالأسفل 👇**",
        "exceed_limit": (
            "📁 **نظراً لدقة المقطع العالية أو طول مدته، تم إنشاء رابط تحميل سريع ومباشر لك:**\n"
            "اضغط على زر التحميل أدناه لبدء التنزيل فوراً 👇"
        ),
        "link_expire_note": "💡 يُفضل البدء بالتحميل الآن لحفظ المقطع على جهازك.",
        "not_defined": "غير محدد",
        "minutes_seconds": "{m} دقيقة و {sec} ثانية",
        "hours_minutes": "{h} س {m} د {sec} ث",
    },
    "en": {
        "welcome": (
            "👋 **Welcome {name} to Smart Downloader Bot!**\n"
            "Developer: **Ahmed Hassan Abdelnaby** 👨‍💻\n\n"
            "Send any link from (YouTube, Facebook, TikTok, Instagram, X, Pinterest...)\n\n"
            "🎯 **Features:**\n"
            "• Direct video & audio downloads with multiple qualities.\n"
            "• High-speed direct download links for long media.\n\n"
            "🚀 Send your link now to get started!"
        ),
        "checking": "⚡ **Analyzing link and preparing options...**",
        "fetch_error": "❌ **Failed to fetch media.** Please ensure the video or post is public.",
        "no_formats": "⚠️ No downloadable formats found for this link.",
        "title": "📌 **Title:** `{title}`",
        "platform": "🌐 **Platform:** `{platform}`",
        "duration": "⏱ **Duration:** {duration}",
        "choose_type": "👇 **Select your preferred format:**",
        "btn_video": "🎬 Video",
        "btn_audio": "🎵 Audio Only",
        "btn_back": "🔙 Back",
        "btn_download": "⬇️ Download Media",
        "expired": "⚠️ This option has expired. Please resend the link.",
        "select_res": "🎬 **Select your preferred quality:**\n`{title}`",
        "select_audio": "🎵 **Select audio format:**\n`{title}`",
        "opt_not_found": "⚠️ This option is no longer available.",
        "queue_notice": "⏳ Finishing download for: **{curr}**\n**{new}** will start automatically right after.",
        "downloading": "⏳ **Preparing and downloading ({label})...**\nPlease wait.",
        "uploading": "📤 **Sending file to you now...**",
        "download_error": "❌ **Failed to download media.** Please try another quality or try again later.",
        "file_not_found": "❌ An error occurred during processing. Please try again.",
        "send_error": "❌ Failed to send file.",
        "link_ready": "✅ **Direct download link is ready below 👇**",
        "exceed_limit": (
            "📁 **Due to high quality or length, a fast direct download link was generated for you:**\n"
            "Click the download button below to start downloading directly 👇"
        ),
        "link_expire_note": "💡 It is recommended to download now to save it to your device.",
        "not_defined": "Undefined",
        "minutes_seconds": "{m}m {sec}s",
        "hours_minutes": "{h}h {m}m {sec}s",
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
        if not url.startswith("http") or ".m3u8" in url:
            continue

        vcodec = f.get("vcodec") or "none"
        acodec = f.get("acodec") or "none"
        ext = (f.get("ext") or "mp4").lower()
        height = f.get("height")
        size = f.get("filesize") or f.get("filesize_approx") or 0

        if vcodec not in ("none", ""):
            label = f"{height}p" if height else "Standard"
            if label not in video_options:
                video_options[label] = {
                    "height": height,
                    "size": size,
                    "ext": ext,
                }

        if vcodec not in ("none", "") and acodec not in ("none", ""):
            h = height or 0
            if h > best_progressive_height:
                best_progressive_height = h
                best_progressive = {
                    "url": url,
                    "ext": ext,
                    "size": size,
                    "height": h,
                }

        if vcodec in ("none", "") and acodec not in ("none", ""):
            audio_label = ext.upper()
            if audio_label not in audio_formats:
                audio_formats[audio_label] = {
                    "ext": ext,
                    "size": size,
                    "direct_url": url,
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

# ==================== أوامر ومعالجات البوت ====================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name or "صديقي"
    msg = t(update, "welcome", name=user_name)
    await update.message.reply_text(msg, parse_mode="Markdown")

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    url_match = re.search(r'(https?://[^\s]+)', text)
    if not url_match:
        return

    target_url = url_match.group(1)
    status_msg = await update.message.reply_text(t(update, "checking"), parse_mode="Markdown")

    def fetch():
        with yt_dlp.YoutubeDL(YTDL_INFO_OPTS) as ydl:
            return ydl.extract_info(target_url, download=False)

    try:
        info = await asyncio.to_thread(fetch)
    except Exception as e:
        logger.error(f"Error fetching url: {e}")
        await status_msg.edit_text(t(update, "fetch_error"), parse_mode="Markdown")
        return

    video_opts, audio_fmts, best_prog = parse_media_data(info)
    if not video_opts and not audio_fmts:
        await status_msg.edit_text(t(update, "no_formats"))
        return

    media_id = uuid.uuid4().hex[:8]
    MEDIA_CACHE[media_id] = {
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

# ==================== إرسال رابط التحميل المباشر ====================
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

    is_webpage = (direct_url == media["webpage_url"])
    size_str = format_size(predicted_size) if predicted_size else ""
    title_short = (media.get("title") or "media")[:70]

    text = (
        f"{t(update, 'title', title=title_short)}\n"
        f"{t(update, 'platform', platform=media.get('platform', 'Web'))}\n"
        f"{t(update, 'duration', duration=format_duration_str(media.get('duration', 0), update))}\n"
        f"🎯 **الجودة:** {label}{size_str}\n\n"
        f"{t(update, 'exceed_limit')}\n\n"
        f"{t(update, 'link_expire_note')}"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(update, "btn_download"), url=direct_url)]
    ])

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

# ==================== معالجة طابور المستخدم المتتابع ====================
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

# ==================== التحميل الفعلي والإرسال ====================
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
        audio_ext = option["ext"]
        format_selector = f"bestaudio[ext={audio_ext}]/bestaudio/best"
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
        "outtmpl": outtmpl,
        "format": format_selector,
        "merge_output_format": "mp4",
        "user_agent": USER_AGENT,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 4,
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
    await query.answer()
    data = query.data

    # 1) استعراض خيارات الفيديو: sv:{media_id}
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
            return int(m.group(1)) if m else -1

        for label in sorted(opts.keys(), key=sort_key, reverse=True):
            size_str = format_size(opts[label].get("size"))
            keyboard.append([InlineKeyboardButton(f"🖥 {label}{size_str}", callback_data=f"rv:{mid}:{label}")])
        keyboard.append([InlineKeyboardButton(t(update, "btn_back"), callback_data=f"bm:{mid}")])

        await query.edit_message_text(
            t(update, "select_res", title=media['title'][:60]),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    # 2) استعراض خيارات الصوت: sa:{media_id}
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

    # 3) طلب تحميل جودة فيديو: rv:{media_id}:{label}
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

    # 4) طلب تحميل صيغة صوت: ra:{media_id}:{label}
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

    # 5) العودة للقائمة الرئيسية: bm:{media_id}
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

# ==================== التشغيل ====================
async def on_startup(app):
    check_ffmpeg()
    print("🚀 تم تشغيل بوت التحميل الذكي بأقصى أداء وتجربة مستخدم نقية!")

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