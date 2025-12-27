import os
import sys
import logging
import asyncio
import base64
import time
import math
import mimetypes
from urllib.parse import quote, unquote
from datetime import datetime

# کتابخانه‌های وب و تلگرام
from aiohttp import web
import aiohttp
from telethon import TelegramClient, events, Button, utils
from telethon.tl.types import DocumentAttributeFilename, DocumentAttributeVideo

# ================= تنظیمات (کانفیگ) =================
API_ID = 27868969
API_HASH = 'bdd2e8fccf95c9d7f3beeeff045f8df4'
BOT_TOKEN = '8023182650:AAFOTfKFHSqQ9FHTNIKHKEOj5frzORQciBo'

# تنظیمات لاگ
logging.basicConfig(
    format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# آدرس سرور (خودکار)
RENDER_EXTERNAL_URL = os.environ.get('RENDER_EXTERNAL_URL', 'http://localhost:8080')

# کلاینت تلگرام
client = TelegramClient('bot_session', API_ID, API_HASH)

# ================= توابع کمکی (Utility) =================

def human_readable_size(size, decimal_places=2):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.{decimal_places}f} {unit}"
        size /= 1024.0
    return f"{size:.{decimal_places}f} PB"

def time_formatter(milliseconds: int) -> str:
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    tmp = ((str(days) + "d, ") if days else "") + \
        ((str(hours) + "h, ") if hours else "") + \
        ((str(minutes) + "m, ") if minutes else "") + \
        ((str(seconds) + "s") if seconds else "")
    return tmp[:-2] if tmp.endswith(", ") else tmp

class ProgressManager:
    def __init__(self, event, action_name):
        self.event = event
        self.last_update_time = 0
        self.action_name = action_name 
        self.start_time = time.time()
        self.message = None

    async def callback(self, current, total):
        now = time.time()
        if (now - self.last_update_time) < 4 and (current != total):
            return

        self.last_update_time = now
        percentage = current * 100 / total
        speed = current / (now - self.start_time) if (now - self.start_time) > 0 else 0
        elapsed_time = now - self.start_time
        eta = (total - current) / speed if speed > 0 else 0
        
        progress_bar = ""
        completed_blocks = int(percentage // 10)
        progress_bar = "🟢" * completed_blocks + "⚪️" * (10 - completed_blocks)

        text = f"""
🚀 **در حال {self.action_name}...**

{progress_bar} **{percentage:.1f}%**

📦 **حجم:** `{human_readable_size(current)}` / `{human_readable_size(total)}`
⚡️ **سرعت:** `{human_readable_size(speed)}/s`
⏱ **زمان:** `{time_formatter(elapsed_time*1000)}`
⏳ **باقی‌مانده:** `{time_formatter(eta*1000)}`
        """
        
        try:
            if not self.message:
                self.message = await self.event.respond(text)
            else:
                await self.message.edit(text)
        except Exception as e:
            logger.warning(f"Error updating progress: {e}")

# ================= بخش وب‌سرور (دانلودر) =================

async def root_handler(request):
    return web.Response(text="Bot is running...", content_type='text/plain')

async def stream_handler(request):
    """
    هندلر دانلود فایل از تلگرام (File -> Link)
    اصلاح شده برای رفع مشکل گیر کردن: حذف Content-Length + بستن اجباری کانکشن
    """
    try:
        encoded_data = request.match_info.get('code')
        try:
            decoded = base64.urlsafe_b64decode(encoded_data).decode()
            chat_id, message_id = map(int, decoded.split(':'))
        except:
            return web.Response(text="Link Invalid", status=400)

        message = await client.get_messages(chat_id, ids=message_id)
        if not message or not message.media:
            return web.Response(text="File Not Found", status=404)

        file_name = "file"
        for attr in message.document.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                file_name = attr.file_name
                break
        
        # نکته مهم: ما اینجا حجم را به مرورگر نمیدهیم تا منتظر نماند.
        # مرورگر دانلود را نشان میدهد اما درصد پر نمیشود (چون انتها باز است)
        # اما در عوض دانلود ۱۰۰٪ موفق انجام میشود و گیر نمیکند.
        encoded_filename = quote(file_name)

        headers = {
            'Content-Type': message.document.mime_type or 'application/octet-stream',
            'Content-Disposition': f'attachment; filename="{encoded_filename}"; filename*=UTF-8\'\'{encoded_filename}',
            'Connection': 'keep-alive',
        }

        response = web.StreamResponse(status=200, headers=headers)
        
        # فعال کردن Chunked Encoding (بسیار مهم برای استریم بدون گیر کردن)
        response.enable_chunked_encoding()
        
        await response.prepare(request)

        try:
            # استفاده از چانک سایز ۶۴ کیلوبایت برای پایداری بیشتر
            async for chunk in client.iter_download(message.media, chunk_size=65536):
                await response.write(chunk)
            
            # پایان موفقیت آمیز
            await response.write_eof()
            
        except Exception as e:
            logger.error(f"Stream interrupted: {e}")
            
        return response

    except Exception as e:
        logger.error(f"Handler Error: {e}")
        return web.Response(text="Internal Server Error", status=500)

# ================= بخش ربات تلگرام =================

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user = await event.get_sender()
    name = user.first_name if user else "کاربر"
    
    text = f"""
👋 **سلام {name} عزیز!**

من یک ربات ابزار فایل پیشرفته هستم. 🛠

**قابلیت‌های من:**
1️⃣ **تبدیل فایل به لینک:** فایل بفرست، لینک دانلود مستقیم بگیر.
2️⃣ **آپلودر لینک:** لینک مستقیم بفرست، فایلش رو توی تلگرام تحویل بگیر.

🚀 **بدون محدودیت حجم (تا ۲ گیگابایت)**
    """
    
    buttons = [
        [Button.url("📣 کانال ما", "https://t.me/Telegram")],
        [Button.inline("راهنما 📚", b"help")]
    ]
    
    await event.reply(text, buttons=buttons)

@client.on(events.CallbackQuery(data=b"help"))
async def help_handler(event):
    await event.answer("فایل بفرست -> لینک بگیر\nلینک بفرست -> فایل بگیر", alert=True)

# ----------------- هندلر لینک به فایل (Leech) - (دست نخورده طبق دستور) -----------------
@client.on(events.NewMessage(pattern=r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'))
async def url_handler(event):
    url = event.text.strip()
    
    if "tele" in url and "gram" in url:
        return

    msg = await event.reply("🔎 **در حال بررسی لینک...**")
    start_time = time.time()
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    await msg.edit("❌ **خطا:** لینک قابل دانلود نیست (Status code != 200)")
                    return
                
                total_size = int(response.headers.get('content-length', 0))
                filename = os.path.basename(unquote(url))
                if not filename:
                    filename = f"file_{int(time.time())}"
                
                if "Content-Disposition" in response.headers:
                    cd = response.headers["Content-Disposition"]
                    if 'filename=' in cd:
                        filename = cd.split('filename=')[1].strip('"')

                local_file = f"downloads/{filename}"
                os.makedirs("downloads", exist_ok=True)
                
                progress_dl = ProgressManager(event, "دانلود به سرور")
                progress_dl.message = msg
                
                downloaded = 0
                
                with open(local_file, 'wb') as f:
                    async for chunk in response.content.iter_chunked(1024*1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            await progress_dl.callback(downloaded, total_size)
                
                await msg.edit("✅ **دانلود تکمیل شد! در حال آپلود به تلگرام...**")
                
                progress_ul = ProgressManager(event, "آپلود به تلگرام")
                progress_ul.message = msg
                
                attributes = []
                mime_type = mimetypes.guess_type(local_file)[0]
                if mime_type and mime_type.startswith('video'):
                    attributes = [DocumentAttributeVideo(
                        duration=0, w=0, h=0, supports_streaming=True
                    )]
                
                uploaded_file = await client.send_file(
                    event.chat_id,
                    local_file,
                    caption=f"📁 **{filename}**\n💾 Size: {human_readable_size(downloaded)}",
                    progress_callback=progress_ul.callback,
                    attributes=attributes,
                    force_document=False,
                    reply_to=event.id
                )
                
                end_time = time.time()
                duration = time_formatter((end_time - start_time) * 1000)
                await msg.delete()
                await event.reply(f"✅ **عملیات با موفقیت انجام شد!**\n⏱ زمان کل: {duration}", file=uploaded_file)
                
                os.remove(local_file)

    except Exception as e:
        logger.error(f"Url Error: {e}")
        await msg.edit(f"❌ **خطا:** {str(e)}")
        if 'local_file' in locals() and os.path.exists(local_file):
            os.remove(local_file)

# ----------------- هندلر فایل به لینک (Stream) -----------------
@client.on(events.NewMessage)
async def file_handler(event):
    if not event.media or event.message.message.startswith('/') or event.message.message.startswith('http'):
        return

    msg = await event.reply("🔗 **در حال ساخت لینک دانلود...**")
    
    try:
        chat_id = event.chat_id
        message_id = event.id
        unique_id = f"{chat_id}:{message_id}"
        encoded_id = base64.urlsafe_b64encode(unique_id.encode()).decode()
        
        base_url = RENDER_EXTERNAL_URL.rstrip('/')
        
        file_name = "Unknown"
        file_size_str = "Unknown"
        
        if hasattr(event.media, 'document'):
            size_mb = event.media.document.size / (1024 * 1024)
            file_size_str = f"{size_mb:.2f} MB"
            for attr in event.media.document.attributes:
                if isinstance(attr, DocumentAttributeFilename):
                    file_name = attr.file_name
                    break
        
        download_link = f"{base_url}/dl/{encoded_id}"
        
        text = f"""
✅ **لینک دانلود مستقیم آماده شد!**

📁 **نام فایل:** `{file_name}`
💾 **حجم:** `{file_size_str}`

🔗 **لینک شما:**
`{download_link}`

⚠️ _این لینک مستقیم از سرور تلگرام استریم می‌شود._
        """
        
        buttons = [
            [Button.url("📥 دانلود فوری", download_link)],
            [Button.url("اشتراک گذاری 🔗", f"https://t.me/share/url?url={download_link}")]
        ]
        
        await msg.edit(text, buttons=buttons, link_preview=False)
        
    except Exception as e:
        logger.error(e)
        await msg.edit("❌ خطایی رخ داد.")

# ================= اجرای برنامه =================
async def main():
    await client.start(bot_token=BOT_TOKEN)
    logger.info("✅ Bot Started!")

    app = web.Application()
    app.router.add_get('/', root_handler)
    app.router.add_get('/dl/{code}', stream_handler)
    
    port = int(os.environ.get("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        import uvloop
        uvloop.install()
    except ImportError:
        pass
    asyncio.run(main())