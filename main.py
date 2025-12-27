import os
import sys
import logging
import asyncio
import base64
import re
import mimetypes
from urllib.parse import quote

# کتابخانه‌های وب و تلگرام
from aiohttp import web
from telethon import TelegramClient, events, Button, utils
from telethon.tl.types import DocumentAttributeFilename

# ================= تنظیمات (کانفیگ) =================
# مقادیر شما جایگذاری شد
API_ID = 27868969
API_HASH = 'bdd2e8fccf95c9d7f3beeeff045f8df4'
BOT_TOKEN = '8023182650:AAFOTfKFHSqQ9FHTNIKHKEOj5frzORQciBo'

# تنظیمات لاگ برای دیدن خطاها در کنسول رندر
logging.basicConfig(
    format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# تشخیص آدرس سایت در سرور رندر
# رندر به صورت خودکار این متغیر را ست می‌کند
RENDER_EXTERNAL_URL = os.environ.get('RENDER_EXTERNAL_URL')
if not RENDER_EXTERNAL_URL:
    # حالت لوکال برای تست
    RENDER_EXTERNAL_URL = "http://localhost:8080" 
    logger.warning("Running locally or RENDER_URL not found.")

# ================= راه‌اندازی کلاینت تلگرام =================
# استفاده از سشن در حافظه (چون رندر حافظه دائم ندارد)
# اما چون ربات است، نیازی به لاگین مجدد با شماره نیست و توکن کافیست.
client = TelegramClient('bot_session', API_ID, API_HASH)

# ================= بخش وب‌سرور (دانلودر) =================

async def root_handler(request):
    """صفحه اصلی که نشان می‌دهد ربات زنده است"""
    return web.Response(
        text=f"🤖 Bot is running on: {RENDER_EXTERNAL_URL}\nPython Telethon Streamer",
        content_type='text/plain'
    )

async def stream_handler(request):
    """هندلر اصلی برای دانلود فایل"""
    try:
        encoded_data = request.match_info.get('code')
        
        # دیکد کردن اطلاعات فایل از URL
        # فرمت: chat_id:message_id
        try:
            decoded = base64.urlsafe_b64decode(encoded_data).decode()
            chat_id, message_id = map(int, decoded.split(':'))
        except:
            return web.Response(text="❌ لینک نامعتبر یا خراب است.", status=400)

        # دریافت پیام از تلگرام
        message = await client.get_messages(chat_id, ids=message_id)
        
        if not message or not message.media:
            return web.Response(text="❌ فایل یافت نشد یا حذف شده است.", status=404)

        # استخراج نام و سایز فایل
        file_name = "downloaded_file"
        file_size = 0
        mime_type = "application/octet-stream"

        # تلاش برای پیدا کردن نام فایل
        for attr in message.document.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                file_name = attr.file_name
                break
        
        file_size = message.document.size
        mime_type = message.document.mime_type
        
        # انکود کردن نام فایل برای مرورگرها
        encoded_filename = quote(file_name)

        # ساخت هدرهای پاسخ
        headers = {
            'Content-Type': mime_type,
            'Content-Disposition': f'attachment; filename="{encoded_filename}"; filename*=UTF-8\'\'{encoded_filename}',
            'Content-Length': str(file_size)
        }

        # ایجاد پاسخ استریم
        response = web.StreamResponse(status=200, reason='OK', headers=headers)
        await response.prepare(request)

        # دانلود و استریم همزمان (Chunk by Chunk)
        # این جادو باعث می‌شود رم سرور پر نشود
        async for chunk in client.iter_download(message.media):
            await response.write(chunk)

        await response.write_eof()
        return response

    except Exception as e:
        logger.error(f"Download Error: {e}")
        return web.Response(text="❌ خطایی در دانلود رخ داد. لطفا دوباره تلاش کنید.", status=500)

# ================= بخش ربات تلگرام =================

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    """پاسخ به دستور استارت"""
    user = await event.get_sender()
    name = user.first_name if user else "کاربر"
    
    text = f"""
👋 **سلام {name} عزیز! به ربات دانلودر نامحدود خوش آمدی**

🚀 **قدرت گرفته از Telethon و Python**
من می‌تونم فایل‌های خیلی بزرگ (حتی تا ۲ گیگابایت) رو به لینک دانلود مستقیم تبدیل کنم.

📤 **کافیه فایلت رو بفرستی:**
• ویدیو
• آهنگ
• داکیومنت
• و...

⚡️ **سرور:** {RENDER_EXTERNAL_URL}
    """
    
    buttons = [
        [Button.url("📣 کانال ما", "https://t.me/Telegram")],
        [Button.inline("راهنما 📚", b"help")]
    ]
    
    await event.reply(text, buttons=buttons)

@client.on(events.CallbackQuery(data=b"help"))
async def help_handler(event):
    await event.answer("فایلت رو بفرست، لینک تحویل بگیر! همین.", alert=True)

@client.on(events.NewMessage)
async def file_handler(event):
    """پردازش فایل‌های دریافتی"""
    # اگر پیام متنی است یا مدیا ندارد، کاری نکن (مگر اینکه استارت باشد که بالا هندل شد)
    if not event.media or event.message.message.startswith('/'):
        return

    # بررسی نوع مدیا (عکس، ویدیو، داکیومنت و...)
    # ما همه چیز را قبول می‌کنیم
    
    msg = await event.reply("🔄 **در حال پردازش فایل و ساخت لینک...**")
    
    try:
        chat_id = event.chat_id
        message_id = event.id
        
        # ساخت شناسه یکتا برای لینک
        # ترکیب چت آیدی و مسیج آیدی را کد می‌کنیم تا در URL تمیز باشد
        unique_id = f"{chat_id}:{message_id}"
        encoded_id = base64.urlsafe_b64encode(unique_id.encode()).decode()
        
        # ساخت لینک نهایی
        # اگر در انتهای URL رندر اسلش بود یا نبود هندل میکنیم
        base_url = RENDER_EXTERNAL_URL.rstrip('/')
        
        # استخراج نام فایل برای نمایش زیباتر
        file_name = "Unknown File"
        file_size_str = "Unknown Size"
        
        if hasattr(event.media, 'document'):
            file_size = event.media.document.size
            file_size_str = utils.get_extension(event.media) or "File"
            # تبدیل بایت به مگابایت
            size_mb = file_size / (1024 * 1024)
            file_size_str = f"{size_mb:.2f} MB"
            
            for attr in event.media.document.attributes:
                if isinstance(attr, DocumentAttributeFilename):
                    file_name = attr.file_name
                    break
        
        # لینک دانلود
        download_link = f"{base_url}/dl/{encoded_id}"
        
        text = f"""
✅ **لینک دانلود مستقیم آماده شد!**

📁 **نام فایل:** `{file_name}`
💾 **حجم:** `{file_size_str}`

🔗 **لینک شما:**
{download_link}

⚠️ _این لینک تا زمانی که فایل را از اینجا پاک نکنید فعال است._
🚀 _سرعت بالا | بدون فیلتر_
        """
        
        buttons = [
            [Button.url("📥 دانلود فوری", download_link)],
            [Button.url("اشتراک گذاری لینک 🔗", f"https://t.me/share/url?url={download_link}")]
        ]
        
        await msg.edit(text, buttons=buttons, link_preview=False)
        
    except Exception as e:
        logger.error(e)
        await msg.edit(f"❌ خطا: {str(e)}")

# ================= اجرای برنامه =================

async def main():
    # 1. استارت کلاینت تلگرام
    await client.start(bot_token=BOT_TOKEN)
    logger.info("✅ Telegram Bot Started!")

    # 2. تنظیم وب سرور
    app = web.Application()
    app.router.add_get('/', root_handler)
    app.router.add_get('/dl/{code}', stream_handler)
    
    # دریافت پورت از رندر (پیش‌فرض 10000)
    port = int(os.environ.get("PORT", 8080))
    
    # راه‌اندازی وب سرور
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    
    logger.info(f"🌍 Web Server Starting on port {port}...")
    await site.start()

    # نگه داشتن برنامه
    # این دستور باعث می‌شود هم وب سرور و هم ربات با هم کار کنند
    await client.run_until_disconnected()

if __name__ == '__main__':
    # استفاده از uvloop برای سرعت بیشتر (اگر نصب باشد)
    try:
        import uvloop
        uvloop.install()
    except ImportError:
        pass

    asyncio.run(main())