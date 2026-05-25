"""
══════════════════════════════════════════════════════════════
منصة السادس — Telegram Bot
يدير: رفع المحاضرات، الامتحانات، الإشعارات، إدارة الطلاب
══════════════════════════════════════════════════════════════
"""

import os, asyncio, logging, time
import psycopg
from psycopg.rows import dict_row
from datetime import datetime, timezone

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters, ContextTypes
)

# ══════════════════════════════════════════════════════════════
#  Config
# ══════════════════════════════════════════════════════════════

BOT_TOKEN    = os.getenv("BOT_TOKEN",    "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
WEBAPP_URL   = os.getenv("WEBAPP_URL",   "https://graceful-mandazi-d572c0.netlify.app")
ADMIN_IDS    = [int(x) for x in os.getenv("ADMIN_IDS","7434897852,6304254841,7113698714").split(",")]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUBJECTS = {
    "arabic":"اللغة العربية","islamic":"التربية الإسلامية",
    "english":"اللغة الإنكليزية","math":"الرياضيات",
    "biology":"الأحياء","chemistry":"الكيمياء","physics":"الفيزياء",
}

# ConversationHandler states
(
    LEC_TITLE, LEC_SUBJECT, LEC_DESC, LEC_CHAPTER, LEC_FILE,
    EXAM_TITLE, EXAM_SUBJECT, EXAM_DURATION, EXAM_DESC, EXAM_FILE,
    BROADCAST_MSG,
) = range(11)

# ══════════════════════════════════════════════════════════════
#  DB
# ══════════════════════════════════════════════════════════════

def get_conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

async def q(sql, params=(), fetch="all"):
    loop = asyncio.get_running_loop()
    def _run():
        with get_conn() as c:
            with c.cursor() as cur:
                cur.execute(sql, params)
                c.commit()
                if fetch=="one":  return cur.fetchone()
                if fetch=="all":  return cur.fetchall()
    return await loop.run_in_executor(None, _run)

async def ensure_user(tg_user):
    """يضمن وجود المستخدم في DB"""
    existing = await q("SELECT id FROM users WHERE telegram_id=%s",(tg_user.id,),"one")
    if existing: return existing["id"]
    name = (tg_user.first_name or "") + " " + (tg_user.last_name or "")
    user = await q("""
        INSERT INTO users(telegram_id,full_name,username,role)
        VALUES(%s,%s,%s,'student') RETURNING id
    """, (tg_user.id, name.strip(), tg_user.username or ""), "one")
    uid = user["id"]
    await q("INSERT INTO student_levels(user_id) VALUES(%s) ON CONFLICT DO NOTHING",(uid,),"none")
    await q("INSERT INTO student_profiles(user_id) VALUES(%s) ON CONFLICT DO NOTHING",(uid,),"none")
    return uid

# ══════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def main_menu_kb(user_id: int = 0) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🟦 المحاضرات",      callback_data="s_lectures"),
         InlineKeyboardButton("🟩 الامتحانات",     callback_data="s_exams")],
        [InlineKeyboardButton("🟥 إرسال جواب",     callback_data="s_answer"),
         InlineKeyboardButton("🟨 لوحة الأوائل",  callback_data="s_leaderboard")],
        [InlineKeyboardButton("🌐 فتح التطبيق",    web_app=WebAppInfo(url=WEBAPP_URL))],
    ]
    if is_admin(user_id):
        rows.append([InlineKeyboardButton("👨‍🏫 لوحة الإدارة", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)

def admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 إضافة محاضرة",   callback_data="add_lecture"),
         InlineKeyboardButton("📝 إضافة امتحان",   callback_data="add_exam")],
        [InlineKeyboardButton("👥 الطلاب",          callback_data="view_students"),
         InlineKeyboardButton("📊 الإحصائيات",     callback_data="view_stats")],
        [InlineKeyboardButton("📢 بث جماعي",        callback_data="broadcast"),
         InlineKeyboardButton("🏆 تحديث الترتيب",  callback_data="update_ranks")],
        [InlineKeyboardButton("🔙 القائمة",         callback_data="main_menu")],
    ])

def subject_kb(prefix: str) -> InlineKeyboardMarkup:
    rows = []
    items = list(SUBJECTS.items())
    for i in range(0, len(items), 2):
        row = []
        for key, name in items[i:i+2]:
            row.append(InlineKeyboardButton(name, callback_data=f"{prefix}_{key}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)

async def safe_edit(query, text, markup=None):
    try:
        await query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user   = update.effective_user
    uid    = await ensure_user(user)
    lvl    = await q("SELECT level,badge,xp FROM student_levels WHERE user_id=%s",(uid,),"one")
    badge  = (lvl or {}).get("badge","🥉")
    level  = (lvl or {}).get("level",1)
    xp     = (lvl or {}).get("xp",0)

    text = (
        f"*🎓 منصة السادس التعليمية*\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"مرحباً {user.first_name}! {badge}\n\n"
        f"🏅 المستوى: `LVL {level}`\n"
        f"⭐ XP: `{xp:,}`\n\n"
        f"اختر ما تريد:"
    )
    kb = main_menu_kb(user.id)
    if update.callback_query:
        await safe_edit(update.callback_query, text, kb)
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

# ══════════════════════════════════════════════════════════════
#  Button Handler (main dispatch)
# ══════════════════════════════════════════════════════════════

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    data   = query.data
    user   = update.effective_user
    await query.answer()

    # ── القائمة الرئيسية ──
    if data == "main_menu":
        await start(update, context)
        return

    # ── المحاضرات ──
    if data == "s_lectures":
        rows = await q("SELECT key,name,icon FROM subjects ORDER BY sort_order")
        kb_rows = []
        for r in (rows or []):
            count = await q("SELECT COUNT(*) AS c FROM lectures WHERE subject_key=%s",(r["key"],),"one") or {}
            kb_rows.append([InlineKeyboardButton(
                f"{r['icon']} {r['name']} ({count.get('c',0)})",
                callback_data=f"lec_sub_{r['key']}")])
        kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
        await safe_edit(query, "📚 *المحاضرات*\n\nاختر المادة:", InlineKeyboardMarkup(kb_rows))
        return

    if data.startswith("lec_sub_"):
        subject_key = data[8:]
        subject_name = SUBJECTS.get(subject_key, subject_key)
        rows = await q("""
            SELECT id,title,chapter,file_type,view_count
            FROM lectures WHERE subject_key=%s
            ORDER BY is_pinned DESC, created_at DESC LIMIT 20
        """, (subject_key,))
        if not rows:
            await safe_edit(query, f"📚 *{subject_name}*\n\nلا توجد محاضرات بعد.",
                            InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="s_lectures")]]))
            return
        text = f"📚 *{subject_name}*\n━━━━━━━━━━━━\n\n"
        kb_rows = []
        for r in rows:
            icon = {"pdf":"📄","video":"🎬","image":"🖼️"}.get(r["file_type"],"📎")
            label = f"{icon} {r['title']}"
            if r.get("chapter"): label = f"[{r['chapter']}] {label}"
            kb_rows.append([InlineKeyboardButton(label, callback_data=f"lec_open_{r['id']}")])
        kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="s_lectures")])
        await safe_edit(query, text + f"عدد المحاضرات: {len(rows)}", InlineKeyboardMarkup(kb_rows))
        return

    if data.startswith("lec_open_"):
        lec_id = int(data[9:])
        lec = await q("SELECT * FROM lectures WHERE id=%s",(lec_id,),"one")
        if not lec:
            await query.answer("المحاضرة غير موجودة", show_alert=True)
            return
        lec = dict(lec)
        uid = await ensure_user(user)
        await q("""
            INSERT INTO completed_lectures(user_id,lecture_id) VALUES(%s,%s) ON CONFLICT DO NOTHING
        """, (uid, lec_id), "none")
        await q("UPDATE lectures SET view_count=view_count+1 WHERE id=%s",(lec_id,),"none")

        # إرسال الملف مباشرة من Telegram
        try:
            file_type = lec.get("file_type","pdf")
            caption   = f"📚 *{lec['title']}*\n📖 {SUBJECTS.get(lec['subject_key'],lec['subject_key'])}\n\n{lec.get('description','')}"
            if file_type == "pdf":
                await context.bot.send_document(user.id, lec["file_id"], caption=caption, parse_mode="Markdown")
            elif file_type == "video":
                await context.bot.send_video(user.id, lec["file_id"], caption=caption, parse_mode="Markdown")
            elif file_type == "image":
                await context.bot.send_photo(user.id, lec["file_id"], caption=caption, parse_mode="Markdown")
            await query.answer("✅ تم إرسال المحاضرة!")
        except Exception as e:
            logger.error(f"Error sending lecture: {e}")
            await query.answer("❌ خطأ في إرسال الملف", show_alert=True)
        return

    # ── الامتحانات ──
    if data == "s_exams":
        rows = await q("""
            SELECT id,title,subject_key,duration_minutes,description
            FROM exams WHERE is_active=TRUE ORDER BY created_at DESC LIMIT 10
        """)
        if not rows:
            await safe_edit(query, "📝 *الامتحانات*\n\nلا توجد امتحانات نشطة حالياً.",
                            InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="main_menu")]]))
            return
        kb_rows = []
        for r in rows:
            label = f"📝 {r['title']} | ⏱️{r['duration_minutes']}د"
            kb_rows.append([InlineKeyboardButton(label, web_app=WebAppInfo(url=f"{WEBAPP_URL}/#exam-{r['id']}"))])
        kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
        await safe_edit(query, "📝 *الامتحانات النشطة*\n\nاضغط على امتحان لبدئه في التطبيق:",
                        InlineKeyboardMarkup(kb_rows))
        return

    # ── الأوائل ──
    if data == "s_leaderboard":
        rows = await q("""
            SELECT u.full_name, sl.xp, sl.level, sl.badge
            FROM student_levels sl JOIN users u ON u.id=sl.user_id
            ORDER BY sl.xp DESC LIMIT 10
        """)
        medals = ["🥇","🥈","🥉"]
        lines  = ["👑 *لوحة الأوائل*\n━━━━━━━━━━━━\n"]
        for i, r in enumerate(rows or [], 1):
            m = medals[i-1] if i<=3 else f"{i}."
            lines.append(f"{m} {r['badge']} *{r['full_name']}* — LVL {r['level']} — `{r['xp']:,} XP`\n")
        await safe_edit(query, "".join(lines),
                        InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="main_menu")]]))
        return

    # ── لوحة الإدارة ──
    if data == "admin_panel":
        if not is_admin(user.id):
            await query.answer("⛔ غير مصرح", show_alert=True); return
        await safe_edit(query, "👨‍🏫 *لوحة الإدارة*\n\nاختر العملية:", admin_kb())
        return

    if data == "update_ranks":
        if not is_admin(user.id): return
        await q("SELECT update_ranks()","()","none")
        await query.answer("✅ تم تحديث الترتيب!", show_alert=True)
        return

    if data == "view_stats":
        if not is_admin(user.id): return
        tu = await q("SELECT COUNT(*) AS c FROM users WHERE role='student'","()","one") or {}
        tl = await q("SELECT COUNT(*) AS c FROM lectures","()","one") or {}
        te = await q("SELECT COUNT(*) AS c FROM exams","()","one") or {}
        ts = await q("SELECT COUNT(*) AS c FROM exam_submissions WHERE submitted_at IS NOT NULL","()","one") or {}
        text = (
            f"📊 *إحصائيات المنصة*\n━━━━━━━━━━━━\n\n"
            f"👥 الطلاب: `{tu.get('c',0)}`\n"
            f"📚 المحاضرات: `{tl.get('c',0)}`\n"
            f"📝 الامتحانات: `{te.get('c',0)}`\n"
            f"✅ الإجابات: `{ts.get('c',0)}`\n"
        )
        await safe_edit(query, text,
                        InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="admin_panel")]]))
        return

    if data == "view_students":
        if not is_admin(user.id): return
        rows = await q("""
            SELECT u.full_name,u.telegram_id,sl.level,sl.xp,sl.badge
            FROM users u LEFT JOIN student_levels sl ON sl.user_id=u.id
            WHERE u.role='student' ORDER BY sl.xp DESC LIMIT 15
        """)
        lines = [f"👥 *قائمة الطلاب ({len(rows or [])})*\n━━━━━━━━━━━━\n\n"]
        for r in (rows or []):
            badge = r.get("badge","🥉"); lvl=r.get("level",1); xp=r.get("xp",0)
            lines.append(f"{badge} *{r['full_name']}* | LVL{lvl} | {xp:,}XP\n`{r['telegram_id']}`\n\n")
        await safe_edit(query, "".join(lines),
                        InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="admin_panel")]]))
        return

    if data == "cancel":
        context.user_data.clear()
        await safe_edit(query, "✅ تم الإلغاء.", InlineKeyboardMarkup([[InlineKeyboardButton("🏠 القائمة",callback_data="main_menu")]]))
        return

# ══════════════════════════════════════════════════════════════
#  Conversation: إضافة محاضرة
# ══════════════════════════════════════════════════════════════

async def add_lecture_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.callback_query.answer("⛔ غير مصرح", show_alert=True); return ConversationHandler.END
    await update.callback_query.edit_message_text(
        "📚 *إضافة محاضرة جديدة*\n\n*الخطوة 1/5*\nاكتب *عنوان* المحاضرة:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء",callback_data="cancel_conv")]]))
    return LEC_TITLE

async def lec_get_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["lec_title"] = update.message.text.strip()
    await update.message.reply_text(
        f"✅ العنوان: *{context.user_data['lec_title']}*\n\n*الخطوة 2/5*\nاختر *المادة*:",
        parse_mode="Markdown", reply_markup=subject_kb("lec_sub"))
    return LEC_SUBJECT

async def lec_get_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    context.user_data["lec_subject"] = data.replace("lec_sub_","")
    await update.callback_query.edit_message_text(
        f"✅ المادة: *{SUBJECTS[context.user_data['lec_subject']]}*\n\n*الخطوة 3/5*\nاكتب *وصف* المحاضرة (أو أرسل ─ لتخطيه):",
        parse_mode="Markdown")
    return LEC_DESC

async def lec_get_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["lec_desc"] = update.message.text.strip() if update.message.text != "─" else ""
    await update.message.reply_text("*الخطوة 4/5*\nاكتب *اسم الفصل* (مثال: الفصل الأول) أو أرسل ─ لتخطيه:", parse_mode="Markdown")
    return LEC_CHAPTER

async def lec_get_chapter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["lec_chapter"] = update.message.text.strip() if update.message.text != "─" else ""
    await update.message.reply_text(
        f"✅ الفصل: {context.user_data['lec_chapter'] or '─'}\n\n*الخطوة 5/5*\nأرسل *الملف* (PDF أو فيديو أو صورة):",
        parse_mode="Markdown")
    return LEC_FILE

async def lec_get_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg  = update.message
    d    = context.user_data
    name = update.effective_user.full_name

    # تحديد نوع الملف
    if msg.document:
        file_id   = msg.document.file_id
        file_type = "pdf" if "pdf" in (msg.document.mime_type or "").lower() else "document"
    elif msg.video:
        file_id   = msg.video.file_id
        file_type = "video"
    elif msg.photo:
        file_id   = msg.photo[-1].file_id
        file_type = "image"
    else:
        await msg.reply_text("⚠️ أرسل ملف PDF أو فيديو أو صورة.")
        return LEC_FILE

    await q("""
        INSERT INTO lectures(title,subject_key,description,file_id,file_type,chapter,teacher_name,course_type,created_by)
        VALUES(%s,%s,%s,%s,%s,%s,%s,'15/5',%s)
    """, (d["lec_title"],d["lec_subject"],d.get("lec_desc",""),
          file_id,file_type,d.get("lec_chapter",""),name,update.effective_user.id), "none")

    await msg.reply_text(
        f"✅ *تمت إضافة المحاضرة بنجاح!*\n\n"
        f"📚 العنوان: {d['lec_title']}\n"
        f"📖 المادة: {SUBJECTS[d['lec_subject']]}\n"
        f"📂 الفصل: {d.get('lec_chapter','─')}\n"
        f"🗂️ النوع: {file_type.upper()}\n\n"
        f"ستظهر في التطبيق فوراً! ✨",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 القائمة",callback_data="main_menu")]]))

    context.user_data.clear()
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════
#  Conversation: إضافة امتحان
# ══════════════════════════════════════════════════════════════

async def add_exam_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.callback_query.answer("⛔", show_alert=True); return ConversationHandler.END
    await update.callback_query.edit_message_text(
        "📝 *إضافة امتحان جديد*\n\n*الخطوة 1/4*\nاكتب *عنوان* الامتحان:", parse_mode="Markdown")
    return EXAM_TITLE

async def exam_get_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["exam_title"] = update.message.text.strip()
    await update.message.reply_text("*الخطوة 2/4*\nاختر *المادة*:", parse_mode="Markdown",
                                    reply_markup=subject_kb("exam_sub"))
    return EXAM_SUBJECT

async def exam_get_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["exam_subject"] = update.callback_query.data.replace("exam_sub_","")
    await update.callback_query.edit_message_text("*الخطوة 3/4*\nكم *مدة الامتحان* بالدقائق؟ (مثال: 60):", parse_mode="Markdown")
    return EXAM_DURATION

async def exam_get_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        duration = int(update.message.text.strip())
        if duration < 1 or duration > 300: raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ أدخل رقماً صحيحاً بين 1 و300.")
        return EXAM_DURATION
    context.user_data["exam_duration"] = duration
    await update.message.reply_text("*الخطوة 4/4*\nأرسل *ملف الامتحان* (PDF) أو اكتب وصفاً نصياً:", parse_mode="Markdown")
    return EXAM_FILE

async def exam_get_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = context.user_data
    file_id = None
    desc    = ""

    if update.message.document:
        file_id = update.message.document.file_id
    elif update.message.text:
        desc = update.message.text.strip()

    await q("""
        INSERT INTO exams(title,subject_key,duration_minutes,description,file_id,course_type,is_active,created_by)
        VALUES(%s,%s,%s,%s,%s,'15/5',TRUE,%s)
    """, (d["exam_title"],d["exam_subject"],d["exam_duration"],desc,file_id,update.effective_user.id), "none")

    await update.message.reply_text(
        f"✅ *تم إنشاء الامتحان بنجاح!*\n\n"
        f"📝 العنوان: {d['exam_title']}\n"
        f"📖 المادة: {SUBJECTS[d['exam_subject']]}\n"
        f"⏱️ المدة: {d['exam_duration']} دقيقة\n\n"
        f"الامتحان متاح الآن في التطبيق! 🚀",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 القائمة",callback_data="main_menu")]]))
    context.user_data.clear()
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════
#  Conversation: بث جماعي
# ══════════════════════════════════════════════════════════════

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.callback_query.answer("⛔", show_alert=True); return ConversationHandler.END
    await update.callback_query.edit_message_text("📢 *بث جماعي*\n\nاكتب الرسالة التي تريد إرسالها لجميع الطلاب:", parse_mode="Markdown")
    return BROADCAST_MSG

async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg   = update.message.text.strip()
    users = await q("SELECT id FROM users WHERE is_active=TRUE AND role='student'") or []
    for u in users:
        await q("INSERT INTO notifications(user_id,title,message,type) VALUES(%s,'📢 إشعار',%s,'info')",
                (u["id"],msg),"none")
    # محاولة إرسال مباشر لمن لديهم telegram_id
    tg_users = await q("SELECT telegram_id FROM users WHERE is_active=TRUE AND role='student'") or []
    sent = 0
    for u in tg_users:
        try:
            await context.bot.send_message(u["telegram_id"],f"📢 *إشعار من المنصة*\n\n{msg}",parse_mode="Markdown")
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass

    await update.message.reply_text(f"✅ *تم الإرسال!*\nوصل إلى: {sent}/{len(tg_users)} طالب",
                                    parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠",callback_data="main_menu")]]))
    return ConversationHandler.END

async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer("إلغاء")
        await update.callback_query.edit_message_text("✅ تم الإلغاء.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠",callback_data="main_menu")]]))
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════
#  General message handler (للطلاب)
# ══════════════════════════════════════════════════════════════

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحباً! اضغط /start للقائمة الرئيسية.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 القائمة",callback_data="main_menu")]]))

# ══════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Lecture ConversationHandler
    lec_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_lecture_start, pattern="^add_lecture$")],
        states={
            LEC_TITLE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, lec_get_title)],
            LEC_SUBJECT: [CallbackQueryHandler(lec_get_subject, pattern="^lec_sub_")],
            LEC_DESC:    [MessageHandler(filters.TEXT & ~filters.COMMAND, lec_get_desc)],
            LEC_CHAPTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, lec_get_chapter)],
            LEC_FILE:    [MessageHandler(filters.Document.ALL | filters.VIDEO | filters.PHOTO, lec_get_file)],
        },
        fallbacks=[CallbackQueryHandler(cancel_conv,"^cancel_conv$"),
                   CommandHandler("cancel", cancel_conv)],
        per_user=True, per_chat=True,
    )

    # Exam ConversationHandler
    exam_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_exam_start, pattern="^add_exam$")],
        states={
            EXAM_TITLE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, exam_get_title)],
            EXAM_SUBJECT:  [CallbackQueryHandler(exam_get_subject, pattern="^exam_sub_")],
            EXAM_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, exam_get_duration)],
            EXAM_FILE:     [MessageHandler(filters.Document.ALL | filters.TEXT & ~filters.COMMAND, exam_get_file)],
        },
        fallbacks=[CallbackQueryHandler(cancel_conv,"^cancel_conv$")],
        per_user=True, per_chat=True,
    )

    # Broadcast ConversationHandler
    bc_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broadcast_start, pattern="^broadcast$")],
        states={BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)]},
        fallbacks=[CallbackQueryHandler(cancel_conv,"^cancel_conv$")],
        per_user=True, per_chat=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(lec_conv)
    app.add_handler(exam_conv)
    app.add_handler(bc_conv)
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    print("🤖 Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
