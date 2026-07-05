"""
================================================================================
📄 بوت تحويل الصور إلى PDF — النسخة الاحترافية
أفضل بوت تحويل صور إلى PDF في العالم
================================================================================
"""

import os
import io
import asyncio
import logging
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from collections import defaultdict

from PIL import Image
import img2pdf
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, letter, legal, landscape, portrait
from reportlab.lib.units import cm

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InputFile, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
from telegram.error import TelegramError

# ================================================================================
# الإعدادات
# ================================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "ضع_توكن_البوت_هنا")
MAX_IMAGES_PER_SESSION = 50  # الحد الأقصى للصور في جلسة واحدة
MAX_FILE_SIZE_MB = 20        # الحد الأقصى لحجم الصورة

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================================================================================
# إجباري الاشتراك
# ================================================================================

REQUIRED_CHANNEL = "@SIXTHCHANNEL27"   # يوزرنيم القناة

async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    try:
        member = await context.bot.get_chat_member(REQUIRED_CHANNEL, user_id)

        if member.status in ["member", "administrator", "creator"]:
            return True

    except Exception:
        pass

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 اشترك بالقناة", url="https://t.me/SIXTHCHANNEL27")],
        [InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_join")]
    ])

    text = (
        "🚫 <b>لا يمكنك استخدام البوت.</b>\n\n"
        "يجب الاشتراك أولاً في القناة التالية:\n"
        "@SIXTHCHANNEL27"
    )

    if update.callback_query:
        await update.callback_query.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=keyboard
        )

    return False
# ================================================================================
# خيارات PDF
# ================================================================================

PAGE_SIZES = {
    "a4":      ("A4", A4),
    "letter":  ("Letter", letter),
    "legal":   ("Legal", legal),
    "original":("حجم الصورة الأصلي", None),
}

ORIENTATIONS = {
    "portrait":  "عمودي ↕️",
    "landscape": "أفقي ↔️",
}

QUALITIES = {
    "high":   ("عالية 🔥", 95),
    "medium": ("متوسطة ⚖️", 75),
    "low":    ("منخفضة 💨", 50),
}

# ================================================================================
# رسائل الترحيب والمساعدة
# ================================================================================

WELCOME_MSG = """
🌟 <b>نـورتـنـا فــي بـوت تـحـويـل الـصـور الـى PDF</b>

📷ارسـلي صـورتـك وراح تـتـحـول فــورا الـى PDF

<b>✨ مـمـيـزات هـذا الـبـوت:</b>
• يـدعـم صـور مـتـعـددة ( 50 صـورة)
• انـت تـخـتـار حـجـم الـصـفـحـة (𝑨𝟒, 𝑳𝒆𝒕𝒕𝒆𝒓, 𝑳𝒆𝒈𝒂𝒍, حـجـم أصـلـي)
• انـت تـخـتـار الاتـجـاه (عـمـودي / أفـقـي)
• انـت تـخـتـار جـودة الـصـورة
• خـصـوصـيـة الـصـور (مـحـد يـشـوف صـورك داخـل الـبـوت نـهـائـيـا)

<b>📌 طريقة الاستخدام:</b>
1. أرسـل الـصـور (واحـدة أو أكـثـر)
2. اخـتـر الإعـدادات الـمـنـاسـبـة
3. اضـغـط <b>تـحـويـل إلـى PDF</b> 🚀

<b>⌨️ الأوامر:</b>
/start - القائمة الرئيسية
/settings - إعدادات PDF
/clear - مسح جميع الصور
/help - المساعدة
"""

HELP_MSG = """
📖 <b>دليل الاستخدام الكامل</b>

<b>1. إضافة الصور:</b>
• أرسل الصور مباشرة في المحادثة
• يمكن إرسال عدة صور دفعة واحدة
• الحد الأقصى: 50 صورة لكل ملف PDF

<b>2. الإعدادات المتاحة:</b>
📐 <b>حجم الصفحة:</b>
   • A4 — الأكثر شيوعاً للطباعة
   • Letter — المعيار الأمريكي
   • Legal — للوثائق القانونية
   • حجم أصلي — يحافظ على أبعاد الصورة

🔄 <b>اتجاه الصفحة:</b>
   • عمودي — مناسب للصور الطولية
   • أفقي — مناسب للصور العرضية

🎨 <b>الجودة:</b>
   • عالية — أفضل وضوح، حجم أكبر
   • متوسطة — توازن مثالي
   • منخفضة — حجم أصغر للمشاركة السريعة

<b>3. الأوامر السريعة:</b>
/clear — مسح الصور والبدء من جديد
/settings — تغيير الإعدادات
/status — عرض الصور المضافة
"""

# ================================================================================
# Health Server
# ================================================================================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK - Image to PDF Bot Running")
    def log_message(self, *args): pass

def run_health():
    port = int(os.getenv("PORT", "8080"))
    HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()

# ================================================================================
# دوال مساعدة
# ================================================================================

def get_session(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """جلب أو إنشاء جلسة للمستخدم"""
    if "session" not in context.user_data:
        context.user_data["session"] = {
            "images": [],        # قائمة الصور [(file_id, file_name, size), ...]
            "page_size": "original",
            "orientation": "portrait",
            "quality": "high",
            "pdf_name": "صوري",
        }
    return context.user_data["session"]

def build_main_keyboard(image_count: int) -> InlineKeyboardMarkup:
    """بناء لوحة المفاتيح الرئيسية"""
    rows = []
    if image_count > 0:
        rows.append([
            InlineKeyboardButton(
                f"🚀 تحويل إلى PDF ({image_count} صورة)",
                callback_data="convert"
            )
        ])
        rows.append([
            InlineKeyboardButton("📋 عرض الصور", callback_data="list_images"),
            InlineKeyboardButton("🗑 مسح الكل", callback_data="clear_confirm"),
        ])
    rows.append([
        InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings"),
        InlineKeyboardButton("❓ المساعدة", callback_data="help"),
    ])
    return InlineKeyboardMarkup(rows)

def build_settings_keyboard(session: dict) -> InlineKeyboardMarkup:
    """بناء لوحة مفاتيح الإعدادات"""
    ps = session["page_size"]
    ori = session["orientation"]
    ql = session["quality"]

    size_row = [
        InlineKeyboardButton(
            f"{'✅' if ps == k else '◻️'} {PAGE_SIZES[k][0]}",
            callback_data=f"size_{k}"
        ) for k in PAGE_SIZES
    ]
    ori_row = [
        InlineKeyboardButton(
            f"{'✅' if ori == k else '◻️'} {v}",
            callback_data=f"ori_{k}"
        ) for k, v in ORIENTATIONS.items()
    ]
    qual_row = [
        InlineKeyboardButton(
            f"{'✅' if ql == k else '◻️'} {QUALITIES[k][0]}",
            callback_data=f"qual_{k}"
        ) for k in QUALITIES
    ]
    return InlineKeyboardMarkup([
        size_row[:2],
        size_row[2:],
        ori_row,
        qual_row,
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")],
    ])

def build_images_list_keyboard(images: list, page: int = 0) -> InlineKeyboardMarkup:
    """بناء لوحة عرض الصور مع إمكانية الحذف"""
    per_page = 8
    start = page * per_page
    chunk = images[start:start + per_page]
    rows = []
    for i, (fid, fname, size) in enumerate(chunk):
        real_idx = start + i
        size_kb = size / 1024
        label = f"{'🖼' if size_kb < 1024 else '📷'} {real_idx+1}. {fname[:20]} ({size_kb:.0f}KB)"
        rows.append([
            InlineKeyboardButton(label, callback_data=f"img_info_{real_idx}"),
            InlineKeyboardButton("❌", callback_data=f"del_img_{real_idx}"),
        ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ السابق", callback_data=f"img_page_{page-1}"))
    if start + per_page < len(images):
        nav.append(InlineKeyboardButton("التالي ▶️", callback_data=f"img_page_{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

async def do_convert(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None):
    """تنفيذ التحويل الفعلي إلى PDF"""
    session = get_session(context)
    images = session["images"]
    if not images:
        msg = "❌ لا توجد صور لتحويلها! أرسل صوراً أولاً."
        if query:
            await query.answer(msg, show_alert=True)
        return

    chat_id = update.effective_chat.id
    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"⏳ <b>جاري التحويل...</b>\n📊 معالجة {len(images)} صورة...",
        parse_mode="HTML"
    )

    try:
        ps_key = session["page_size"]
        ori = session["orientation"]
        ql_key = session["quality"]
        quality = QUALITIES[ql_key][1]
        page_size = PAGE_SIZES[ps_key][1]

        processed_images = []
        total = len(images)

        for idx, (file_id, fname, size) in enumerate(images):
            # تحديث حالة التحويل كل 5 صور
            if idx % 5 == 0:
                try:
                    await status_msg.edit_text(
                        f"⏳ <b>جاري التحويل...</b>\n"
                        f"📊 {idx}/{total} صورة تمت معالجتها\n"
                        f"{'▓' * (idx * 10 // total)}{'░' * (10 - idx * 10 // total)} {idx * 100 // total}%",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

            file = await context.bot.get_file(file_id)
            img_bytes = await file.download_as_bytearray()
            img = Image.open(io.BytesIO(img_bytes))

            # تحويل إلى RGB إذا لزم
            if img.mode in ("RGBA", "P", "LA"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "RGBA":
                    bg.paste(img, mask=img.split()[3])
                else:
                    bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[3])
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")

            processed_images.append(img)

        # بناء PDF
        pdf_buffer = io.BytesIO()

        if ps_key == "original":
            # حجم أصلي — كل صورة بأبعادها
            images_bytes = []
            for img in processed_images:
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=quality, optimize=True)
                images_bytes.append(buf.getvalue())
            pdf_bytes = img2pdf.convert(images_bytes)
            pdf_buffer.write(pdf_bytes)
        else:
            # حجم محدد — استخدام reportlab
            if ori == "landscape":
                page_size = landscape(page_size)
            else:
                page_size = portrait(page_size)

            c = canvas.Canvas(pdf_buffer, pagesize=page_size)
            pw, ph = page_size

            for img in processed_images:
                iw, ih = img.size
                # حساب أبعاد الصورة لتناسب الصفحة مع الحفاظ على النسبة
                margin = 1 * cm
                aw = pw - 2 * margin
                ah = ph - 2 * margin
                ratio = min(aw / iw, ah / ih)
                nw = iw * ratio
                nh = ih * ratio
                x = (pw - nw) / 2
                y = (ph - nh) / 2

                img_buf = io.BytesIO()
                img.save(img_buf, format="JPEG", quality=quality, optimize=True)
                img_buf.seek(0)

                c.drawImage(
                    img_buf, x, y, width=nw, height=nh,
                    preserveAspectRatio=True
                )
                c.showPage()

            c.save()

        pdf_buffer.seek(0)
        pdf_size = pdf_buffer.getbuffer().nbytes

        # اسم الملف
        pdf_name = session.get("pdf_name", "صوري")
        safe_name = "".join(c for c in pdf_name if c.isalnum() or c in " -_") or "output"
        filename = f"{safe_name}.pdf"

        await status_msg.edit_text("✅ <b>اكتمل التحويل! جاري الإرسال...</b>", parse_mode="HTML")

        # إرسال الملف
        await context.bot.send_document(
            chat_id=chat_id,
            document=InputFile(pdf_buffer, filename=filename),
            caption=(
                f"✅ <b>تم التحويل بنجاح!</b>\n"
                f"📄 <b>الملف:</b> {filename}\n"
                f"🖼 <b>عدد الصور:</b> {total}\n"
                f"📐 <b>الحجم:</b> {PAGE_SIZES[ps_key][0]}\n"
                f"🎨 <b>الجودة:</b> {QUALITIES[ql_key][0]}\n"
                f"📦 <b>حجم الملف:</b> {pdf_size / 1024:.1f} KB"
            ),
            parse_mode="HTML"
        )

        await status_msg.delete()

        # اسأل إذا يريد جلسة جديدة
        await context.bot.send_message(
            chat_id=chat_id,
            text="🎉 <b>تم! هل تريد تحويل صور أخرى؟</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🆕 جلسة جديدة", callback_data="new_session"),
                 InlineKeyboardButton("➕ إضافة المزيد", callback_data="keep_session")]
            ])
        )

    except Exception as e:
        logger.error(f"Convert error: {e}")
        try:
            await status_msg.edit_text(
                f"❌ <b>حدث خطأ أثناء التحويل!</b>\n<code>{str(e)[:200]}</code>",
                parse_mode="HTML"
            )
        except Exception:
            pass

# ================================================================================
# معالجات الأوامر
# ================================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update, context):
        return

    
    session = get_session(context)
    count = len(session["images"])
    await update.message.reply_text(
        WELCOME_MSG,
        parse_mode="HTML",
        reply_markup=build_main_keyboard(count)
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_MSG, parse_mode="HTML")

async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update, context):
        return
    session = get_session(context)
    ps = PAGE_SIZES[session["page_size"]][0]
    ori = ORIENTATIONS[session["orientation"]]
    ql = QUALITIES[session["quality"]][0]
    await update.message.reply_text(
        f"⚙️ <b>إعدادات PDF الحالية:</b>\n\n"
        f"📐 <b>حجم الصفحة:</b> {ps}\n"
        f"🔄 <b>الاتجاه:</b> {ori}\n"
        f"🎨 <b>الجودة:</b> {ql}\n\n"
        f"اضغط على أي إعداد لتغييره:",
        parse_mode="HTML",
        reply_markup=build_settings_keyboard(session)
    )

async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update, context):
        return
    session = get_session(context)
    count = len(session["images"])
    if count == 0:
        await update.message.reply_text("📭 لا توجد صور في القائمة.")
        return
    await update.message.reply_text(
        f"⚠️ هل أنت متأكد من حذف <b>{count} صورة</b>؟",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ نعم، امسح الكل", callback_data="clear_confirm_yes"),
             InlineKeyboardButton("❌ إلغاء", callback_data="back_main")]
        ])
    )

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update, context):
        return
    session = get_session(context)
    images = session["images"]
    count = len(images)
    if count == 0:
        await update.message.reply_text(
            "📭 <b>لا توجد صور مضافة بعد.</b>\nأرسل صوراً لبدء التحويل!",
            parse_mode="HTML"
        )
        return
    total_size = sum(s for _, _, s in images)
    await update.message.reply_text(
        f"📊 <b>حالة الجلسة الحالية:</b>\n\n"
        f"🖼 <b>عدد الصور:</b> {count}/{MAX_IMAGES_PER_SESSION}\n"
        f"📦 <b>الحجم الإجمالي:</b> {total_size/1024:.1f} KB\n\n"
        f"اضغط <b>تحويل</b> عندما تكون جاهزاً:",
        parse_mode="HTML",
        reply_markup=build_main_keyboard(count)
    )

async def rename_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update, context):
        return
    context.user_data["waiting_rename"] = True
    await update.message.reply_text(
        "✏️ <b>أرسل الاسم الجديد لملف PDF:</b>\n\n<i>مثال: صور العائلة 2024</i>",
        parse_mode="HTML"
    )

# ================================================================================
# معالج الصور
# ================================================================================

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update, context):
        return

    
    session = get_session(context)
    images = session["images"]

    if len(images) >= MAX_IMAGES_PER_SESSION:
        await update.message.reply_text(
            f"⚠️ <b>وصلت للحد الأقصى ({MAX_IMAGES_PER_SESSION} صورة)!</b>\n"
            f"اضغط <b>تحويل إلى PDF</b> الآن أو احذف بعض الصور.",
            parse_mode="HTML",
            reply_markup=build_main_keyboard(len(images))
        )
        return

    # استقبال الصورة
    photo = update.message.photo[-1]  # أعلى جودة
    file_size = photo.file_size or 0

    if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
        await update.message.reply_text(
            f"❌ حجم الصورة كبير جداً! الحد الأقصى {MAX_FILE_SIZE_MB}MB."
        )
        return

    fname = f"صورة_{len(images)+1}.jpg"
    images.append((photo.file_id, fname, file_size))
    count = len(images)

    # رسالة تأكيد ذكية
    if count == 1:
        msg = f"✅ <b>تمت إضافة الصورة الأولى!</b>\nأرسل المزيد أو اضغط تحويل."
    elif count % 5 == 0:
        msg = f"📸 <b>{count} صورة جاهزة!</b>\nأرسل المزيد أو اضغط تحويل."
    else:
        msg = f"✅ صورة {count} أُضيفت."

    await update.message.reply_text(
        msg,
        parse_mode="HTML",
        reply_markup=build_main_keyboard(count)
    )

async def handle_document_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update, context):
        return
    """معالجة الصور المرسلة كملفات (بدون ضغط)"""
    doc = update.message.document
    if not doc or not doc.mime_type or not doc.mime_type.startswith("image/"):
        return

    session = get_session(context)
    images = session["images"]

    if len(images) >= MAX_IMAGES_PER_SESSION:
        await update.message.reply_text(f"⚠️ وصلت للحد الأقصى ({MAX_IMAGES_PER_SESSION} صورة)!")
        return

    if doc.file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
        await update.message.reply_text(f"❌ حجم الملف كبير جداً! الحد الأقصى {MAX_FILE_SIZE_MB}MB.")
        return

    fname = doc.file_name or f"صورة_{len(images)+1}.jpg"
    images.append((doc.file_id, fname, doc.file_size))
    count = len(images)

    await update.message.reply_text(
        f"✅ <b>{fname}</b> أُضيفت (صورة {count})",
        parse_mode="HTML",
        reply_markup=build_main_keyboard(count)
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update, context):
        return
    """معالجة النصوص — اسم الملف أو رسائل أخرى"""
    if context.user_data.get("waiting_rename"):
        name = (update.message.text or "").strip()[:50]
        if name:
            session = get_session(context)
            session["pdf_name"] = name
            context.user_data["waiting_rename"] = False
            await update.message.reply_text(
                f"✅ <b>تم تغيير اسم الملف إلى:</b>\n📄 {name}.pdf",
                parse_mode="HTML",
                reply_markup=build_main_keyboard(len(session["images"]))
            )
        else:
            await update.message.reply_text("⚠️ الاسم غير صالح، حاول مجدداً.")
        return

    session = get_session(context)
    count = len(session["images"])
    await update.message.reply_text(
        f"📸 <b>أرسل صوراً لتحويلها إلى PDF!</b>",
        parse_mode="HTML",
        reply_markup=build_main_keyboard(count)
    )

# ================================================================================
# معالج الأزرار
# ================================================================================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update, context):
        return
    query = update.callback_query
    data = query.data
    if data == "check_join":
        if await check_subscription(update, context):
            await query.message.reply_text(
                "✅ تم التحقق من الاشتراك، يمكنك استخدام البوت الآن."
            )
        return
    session = get_session(context)
    images = session["images"]

    await query.answer()

    # تحويل
    if data == "convert":
        await do_convert(update, context, query)
        return

    # إعدادات
    if data == "settings":
        ps = PAGE_SIZES[session["page_size"]][0]
        ori = ORIENTATIONS[session["orientation"]]
        ql = QUALITIES[session["quality"]][0]
        await query.edit_message_text(
            f"⚙️ <b>إعدادات PDF:</b>\n\n"
            f"📐 الحجم: <b>{ps}</b>\n"
            f"🔄 الاتجاه: <b>{ori}</b>\n"
            f"🎨 الجودة: <b>{ql}</b>",
            parse_mode="HTML",
            reply_markup=build_settings_keyboard(session)
        )
        return

    # تغيير حجم الصفحة
    if data.startswith("size_"):
        key = data.replace("size_", "")
        if key in PAGE_SIZES:
            session["page_size"] = key
            await query.edit_message_reply_markup(build_settings_keyboard(session))
            await query.answer(f"✅ تم الاختيار: {PAGE_SIZES[key][0]}", show_alert=False)
        return

    # تغيير الاتجاه
    if data.startswith("ori_"):
        key = data.replace("ori_", "")
        if key in ORIENTATIONS:
            session["orientation"] = key
            await query.edit_message_reply_markup(build_settings_keyboard(session))
        return

    # تغيير الجودة
    if data.startswith("qual_"):
        key = data.replace("qual_", "")
        if key in QUALITIES:
            session["quality"] = key
            await query.edit_message_reply_markup(build_settings_keyboard(session))
            await query.answer(f"✅ الجودة: {QUALITIES[key][0]}")
        return

    # عرض الصور
    if data == "list_images":
        if not images:
            await query.answer("📭 لا توجد صور!", show_alert=True)
            return
        await query.edit_message_text(
            f"🖼 <b>قائمة الصور ({len(images)} صورة):</b>\nاضغط ❌ لحذف أي صورة:",
            parse_mode="HTML",
            reply_markup=build_images_list_keyboard(images)
        )
        return

    # صفحات قائمة الصور
    if data.startswith("img_page_"):
        page = int(data.replace("img_page_", ""))
        await query.edit_message_reply_markup(build_images_list_keyboard(images, page))
        return

    # حذف صورة محددة
    if data.startswith("del_img_"):
        idx = int(data.replace("del_img_", ""))
        if 0 <= idx < len(images):
            removed = images.pop(idx)
            await query.answer(f"✅ حُذفت: {removed[1]}")
            if images:
                await query.edit_message_text(
                    f"🖼 <b>قائمة الصور ({len(images)} صورة):</b>",
                    parse_mode="HTML",
                    reply_markup=build_images_list_keyboard(images)
                )
            else:
                await query.edit_message_text(
                    "📭 <b>تم حذف جميع الصور.</b>",
                    parse_mode="HTML",
                    reply_markup=build_main_keyboard(0)
                )
        return

    # تأكيد المسح
    if data == "clear_confirm":
        await query.edit_message_text(
            f"⚠️ <b>هل تريد حذف {len(images)} صورة؟</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ نعم، امسح الكل", callback_data="clear_confirm_yes"),
                 InlineKeyboardButton("❌ إلغاء", callback_data="back_main")]
            ])
        )
        return

    if data == "clear_confirm_yes":
        session["images"].clear()
        await query.edit_message_text(
            "🗑 <b>تم مسح جميع الصور.</b>\nأرسل صوراً جديدة للبدء!",
            parse_mode="HTML",
            reply_markup=build_main_keyboard(0)
        )
        return

    # جلسة جديدة
    if data == "new_session":
        session["images"].clear()
        session["pdf_name"] = "ملف PDF"
        session["page_size"] = "original"
        await query.edit_message_text(
            "🆕 <b>تم بدء جلسة جديدة!</b>\nأرسل صورك الآن:",
            parse_mode="HTML",
            reply_markup=build_main_keyboard(0)
        )
        return

    if data == "keep_session":
        await query.edit_message_text(
            f"➕ <b>أرسل المزيد من الصور ({len(images)} صورة حالياً)</b>",
            parse_mode="HTML",
            reply_markup=build_main_keyboard(len(images))
        )
        return

    # رجوع للرئيسية
    if data == "back_main":
        count = len(images)
        await query.edit_message_text(
            f"🏠 <b>القائمة الرئيسية</b>\n"
            f"{'📸 ' + str(count) + ' صورة جاهزة للتحويل' if count > 0 else '📭 لا توجد صور، أرسل صوراً الآن!'}",
            parse_mode="HTML",
            reply_markup=build_main_keyboard(count)
        )
        return

    # مساعدة
    if data == "help":
        await query.edit_message_text(
            HELP_MSG,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data="back_main")
            ]])
        )
        return

# ================================================================================
# معالج الأخطاء
# ================================================================================

async def error_handler(update, context):
    logger.error(f"Error: {context.error}")

# ================================================================================
# التشغيل
# ================================================================================

if __name__ == "__main__":
    # Health server
    threading.Thread(target=run_health, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    # أوامر
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("rename", rename_cmd))

    # صور
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, handle_document_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # أزرار
    app.add_handler(CallbackQueryHandler(button_handler))

    # أخطاء
    app.add_error_handler(error_handler)

    logger.info("🚀 بوت تحويل الصور إلى PDF يعمل الآن!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
