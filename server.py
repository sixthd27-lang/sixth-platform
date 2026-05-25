"""
══════════════════════════════════════════════════════════════
منصة السادس التعليمية — FastAPI Backend
══════════════════════════════════════════════════════════════
"""

import os, asyncio, hashlib, hmac, json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, unquote

import httpx
import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from jose import JWTError, jwt

# ══════════════════════════════════════════════════════════════
#  Config
# ══════════════════════════════════════════════════════════════

DATABASE_URL = os.getenv("DATABASE_URL", "")
SECRET_KEY   = os.getenv("SECRET_KEY", "sadis-ilmi-secret-2024-change-me")
BOT_TOKEN    = os.getenv("BOT_TOKEN", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://graceful-mandazi-d572c0.netlify.app")
ALGORITHM    = "HS256"
TOKEN_DAYS   = 30

LEVEL_THRESHOLDS = [0,100,300,700,1500,3000,5000,8000,12000,18000,25000]
XP_REWARDS = {
    "lecture_view":    10,
    "exam_submit":     30,
    "exam_score_full": 50,
    "daily_login":      5,
    "answer_submit":   15,
}

security = HTTPBearer(auto_error=False)

# ══════════════════════════════════════════════════════════════
#  App
# ══════════════════════════════════════════════════════════════

app = FastAPI(title="منصة السادس API", version="1.0.0", docs_url="/docs")

app.add_middleware(CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:5173", "http://localhost:3000", "*"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ══════════════════════════════════════════════════════════════
#  DB
# ══════════════════════════════════════════════════════════════

def conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

async def q(sql: str, params=(), fetch="all"):
    loop = asyncio.get_running_loop()
    def _run():
        with conn() as c:
            with c.cursor() as cur:
                cur.execute(sql, params)
                c.commit()
                if fetch == "one":  return cur.fetchone()
                if fetch == "all":  return cur.fetchall()
                return None
    return await loop.run_in_executor(None, _run)

# ══════════════════════════════════════════════════════════════
#  Startup — init tables
# ══════════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup():
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    if os.path.exists(schema_path):
        with open(schema_path) as f:
            schema = f.read()
        loop = asyncio.get_running_loop()
        def _init():
            with conn() as c:
                with c.cursor() as cur:
                    cur.execute(schema)
                c.commit()
        try:
            await loop.run_in_executor(None, _init)
            print("✅ Database initialized")
        except Exception as e:
            print(f"⚠️ DB init warning: {e}")

# ══════════════════════════════════════════════════════════════
#  XP Utils
# ══════════════════════════════════════════════════════════════

def calc_level(xp: int) -> int:
    for i in range(len(LEVEL_THRESHOLDS)-1, -1, -1):
        if xp >= LEVEL_THRESHOLDS[i]: return i+1
    return 1

def get_badge(level: int) -> str:
    if level >= 41: return "👑"
    if level >= 26: return "💎"
    if level >= 16: return "🥇"
    if level >= 6:  return "🥈"
    return "🥉"

def xp_progress(xp: int) -> dict:
    t   = LEVEL_THRESHOLDS
    lvl = calc_level(xp)
    if lvl >= len(t): return {"level":lvl,"pct":100,"needed":0,"next_xp":t[-1]}
    cur = t[lvl-1]; nxt = t[lvl]
    pct = min(100, int((xp-cur)/(nxt-cur)*100))
    return {"level":lvl,"pct":pct,"needed":nxt-xp,"next_xp":nxt,"cur_xp":cur}

async def award_xp(user_id: int, action: str) -> dict:
    gained = XP_REWARDS.get(action, 0)
    if not gained:
        return {}
    row = await q("SELECT xp,level FROM student_levels WHERE user_id=%s",(user_id,),"one")
    old_level = (row or {}).get("level", 1)
    new_xp    = (row or {}).get("xp", 0) + gained
    new_level = calc_level(new_xp)
    new_badge = get_badge(new_level)
    await q("""
        INSERT INTO student_levels(user_id,xp,level,badge,updated_at)
        VALUES(%s,%s,%s,%s,NOW())
        ON CONFLICT(user_id) DO UPDATE
        SET xp=EXCLUDED.xp,level=EXCLUDED.level,badge=EXCLUDED.badge,updated_at=NOW()
    """, (user_id, new_xp, new_level, new_badge), "none")
    leveled_up = new_level > old_level
    if leveled_up:
        await q("INSERT INTO notifications(user_id,title,message,type) VALUES(%s,%s,%s,'success')",
                (user_id, f"🎉 ارتقيت للمستوى {new_level}!",
                 f"مبروك! أنت الآن {new_badge} LVL {new_level}"), "none")
    return {"xp":new_xp,"level":new_level,"badge":new_badge,
            "xp_gained":gained,"leveled_up":leveled_up}

# ══════════════════════════════════════════════════════════════
#  Auth
# ══════════════════════════════════════════════════════════════

def make_token(uid: int, role: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=TOKEN_DAYS)
    return jwt.encode({"sub":str(uid),"role":role,"exp":exp}, SECRET_KEY, ALGORITHM)

def verify_tg(raw: str) -> dict | None:
    try:
        params = dict(parse_qsl(raw, keep_blank_values=True))
        h      = params.pop("hash","")
        s      = "\n".join(f"{k}={v}" for k,v in sorted(params.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        ok     = hmac.new(secret, s.encode(), hashlib.sha256).hexdigest() == h
        if ok or not BOT_TOKEN:
            return json.loads(unquote(params.get("user","{}")))
    except Exception:
        pass
    return None

async def current_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    if not creds:
        raise HTTPException(401, "مطلوب تسجيل الدخول")
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        uid = int(payload["sub"])
    except (JWTError, ValueError):
        raise HTTPException(401, "رمز غير صالح")
    user = await q("SELECT * FROM users WHERE id=%s AND is_active=TRUE",(uid,),"one")
    if not user: raise HTTPException(401, "المستخدم غير موجود")
    return dict(user)

def require(*roles):
    async def _check(u=Depends(current_user)):
        if u["role"] not in roles:
            raise HTTPException(403,"لا تملك الصلاحية")
        return u
    return _check

# ══════════════════════════════════════════════════════════════
#  Auth Routes
# ══════════════════════════════════════════════════════════════

class TgLogin(BaseModel):
    init_data: str

@app.post("/auth/telegram")
async def tg_login(body: TgLogin):
    tg_user = verify_tg(body.init_data)
    if not tg_user and BOT_TOKEN:
        raise HTTPException(401, "بيانات Telegram غير صالحة")

    tg_id = tg_user.get("id") if tg_user else 0
    name  = ((tg_user or {}).get("first_name","") + " " + (tg_user or {}).get("last_name","")).strip()

    user = await q("SELECT * FROM users WHERE telegram_id=%s",(tg_id,),"one")
    if not user:
        user = await q("""
            INSERT INTO users(telegram_id,full_name,username,role)
            VALUES(%s,%s,%s,'student') RETURNING *
        """, (tg_id, name or "طالب", tg_user.get("username","") if tg_user else ""), "one")
        uid = user["id"]
        await q("INSERT INTO student_levels(user_id) VALUES(%s) ON CONFLICT DO NOTHING",(uid,),"none")
        await q("INSERT INTO student_profiles(user_id) VALUES(%s) ON CONFLICT DO NOTHING",(uid,),"none")
        await award_xp(uid, "daily_login")
    else:
        uid = user["id"]
        await q("UPDATE users SET last_login=NOW(),full_name=%s WHERE id=%s",(name or user["full_name"],uid),"none")

    token = make_token(uid, user["role"])
    return {"token":token,"user_id":uid,"role":user["role"],"full_name":user["full_name"]}


class BotTokenReq(BaseModel):
    token: str

@app.post("/auth/bot-login")
async def bot_login(body: BotTokenReq):
    """
    يقبل التوكن المُنشأ من البوت ويُرجع JWT للموقع.
    يُستدعى من الموقع عند الدخول عبر رابط البوت.
    """
    try:
        payload = jwt.decode(body.token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "bot_login":
            raise HTTPException(401, "نوع التوكن غير صحيح")
        tg_id = int(payload["sub"])
        name  = payload.get("name", "طالب")
    except Exception:
        raise HTTPException(401, "التوكن غير صالح أو منتهي الصلاحية")

    # جلب أو إنشاء المستخدم
    user = await q("SELECT * FROM users WHERE telegram_id=%s",(tg_id,),"one")
    if not user:
        user = await q("""
            INSERT INTO users(telegram_id,full_name,role)
            VALUES(%s,%s,'student') RETURNING *
        """, (tg_id, name or "طالب"), "one")
        uid = user["id"]
        await q("INSERT INTO student_levels(user_id) VALUES(%s) ON CONFLICT DO NOTHING",(uid,),"none")
        await q("INSERT INTO student_profiles(user_id) VALUES(%s) ON CONFLICT DO NOTHING",(uid,),"none")
    else:
        uid = user["id"]
        await q("UPDATE users SET last_login=NOW() WHERE id=%s",(uid,),"none")

    token = make_token(uid, user["role"])
    return {"token":token,"user_id":uid,"role":user["role"],"full_name":user["full_name"]}

@app.get("/auth/me")
async def me(u=Depends(current_user)):
    lvl = await q("SELECT * FROM student_levels WHERE user_id=%s",(u["id"],),"one")
    prf = await q("SELECT * FROM student_profiles WHERE user_id=%s",(u["id"],),"one")
    return {**u,"level_data":dict(lvl) if lvl else {},"profile":dict(prf) if prf else {}}

# ══════════════════════════════════════════════════════════════
#  Profile
# ══════════════════════════════════════════════════════════════

@app.get("/api/profile")
async def profile(u=Depends(current_user)):
    uid  = u["id"]
    lvl  = await q("SELECT * FROM student_levels WHERE user_id=%s",(uid,),"one")
    prf  = await q("SELECT * FROM student_profiles WHERE user_id=%s",(uid,),"one")
    lc   = await q("SELECT COUNT(*) AS c FROM completed_lectures WHERE user_id=%s",(uid,),"one")
    sc   = await q("SELECT COUNT(*) AS c FROM exam_submissions WHERE user_id=%s AND submitted_at IS NOT NULL",(uid,),"one")
    ach  = await q("SELECT * FROM achievements WHERE user_id=%s ORDER BY earned_at DESC",(uid,))

    xp  = (lvl or {}).get("xp",0)
    pr  = xp_progress(xp)

    return {
        "user_id":      uid,
        "telegram_id":  u["telegram_id"],
        "full_name":    u["full_name"],
        "username":     u.get("username"),
        "role":         u["role"],
        "avatar_url":   u.get("avatar_url"),
        "xp":           xp,
        "level":        (lvl or {}).get("level",1),
        "badge":        (lvl or {}).get("badge","🥉"),
        "rank_pos":     (lvl or {}).get("rank_pos"),
        "progress":     pr,
        "school_name":  (prf or {}).get("school_name",""),
        "course_type":  (prf or {}).get("course_type","15/5"),
        "bio":          (prf or {}).get("bio",""),
        "completed_lec":(lc or {}).get("c",0),
        "total_exams":  (sc or {}).get("c",0),
        "achievements": [dict(a) for a in (ach or [])],
    }

@app.patch("/api/profile")
async def update_profile(data: dict, u=Depends(current_user)):
    uid = u["id"]
    ok  = {"school_name","course_type","bio"}
    upd = {k:v for k,v in data.items() if k in ok}
    if upd:
        sets   = ",".join(f"{k}=%s" for k in upd)
        vals   = list(upd.values()) + [uid]
        await q(f"UPDATE student_profiles SET {sets},updated_at=NOW() WHERE user_id=%s",vals,"none")
    if "full_name" in data:
        await q("UPDATE users SET full_name=%s WHERE id=%s",(data["full_name"],uid),"none")
    return {"ok":True}

# ══════════════════════════════════════════════════════════════
#  Subjects
# ══════════════════════════════════════════════════════════════

@app.get("/api/subjects")
async def subjects():
    rows = await q("SELECT * FROM subjects ORDER BY sort_order")
    return {"subjects":[dict(r) for r in rows]}

# ══════════════════════════════════════════════════════════════
#  Lectures
# ══════════════════════════════════════════════════════════════

@app.get("/api/lectures")
async def get_lectures(course_type:str="15/5", subject_key:str=None, u=Depends(current_user)):
    if subject_key:
        rows = await q("""
            SELECT l.*, s.name AS subject_name, s.icon AS subject_icon
            FROM lectures l LEFT JOIN subjects s ON s.key=l.subject_key
            WHERE l.course_type=%s AND l.subject_key=%s
            ORDER BY l.is_pinned DESC, l.created_at DESC
        """, (course_type, subject_key))
    else:
        rows = await q("""
            SELECT l.*, s.name AS subject_name, s.icon AS subject_icon
            FROM lectures l LEFT JOIN subjects s ON s.key=l.subject_key
            WHERE l.course_type=%s
            ORDER BY l.subject_key, l.is_pinned DESC, l.created_at DESC
        """, (course_type,))

    items   = []
    grouped = {}
    for r in rows:
        item = dict(r)
        item["created_at"] = str(item.get("created_at",""))
        item["file_url"]   = f"/api/file/{item['file_id']}" if item.get("file_id") else None
        items.append(item)
        s = item["subject_key"]
        grouped.setdefault(s,[]).append(item)

    return {"lectures":grouped,"total":len(items)}

@app.post("/api/lectures/{lecture_id}/complete")
async def complete_lecture(lecture_id:int, u=Depends(current_user)):
    uid = u["id"]
    await q("UPDATE lectures SET view_count=view_count+1 WHERE id=%s",(lecture_id,),"none")
    await q("""
        INSERT INTO completed_lectures(user_id,lecture_id) VALUES(%s,%s) ON CONFLICT DO NOTHING
    """, (uid, lecture_id), "none")
    result = await award_xp(uid,"lecture_view")
    return {"ok":True,**result}

# ══════════════════════════════════════════════════════════════
#  File Proxy (Telegram file_id → download)
# ══════════════════════════════════════════════════════════════

@app.get("/api/file/{file_id:path}")
async def get_file(file_id: str, u=Depends(current_user)):
    """يحول file_id من Telegram إلى رابط قابل للتحميل"""
    if not BOT_TOKEN:
        raise HTTPException(503, "BOT_TOKEN غير مضبوط")
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
            params={"file_id": file_id}
        )
        data = res.json()
        if not data.get("ok"):
            raise HTTPException(404, "الملف غير موجود")
        file_path = data["result"]["file_path"]
        dl_url    = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    return RedirectResponse(url=dl_url)

# ══════════════════════════════════════════════════════════════
#  Exams
# ══════════════════════════════════════════════════════════════

@app.get("/api/exams")
async def get_exams(course_type:str="15/5", u=Depends(current_user)):
    rows = await q("""
        SELECT e.*, u2.full_name AS creator_name
        FROM exams e LEFT JOIN users u2 ON u2.telegram_id=e.created_by
        WHERE e.is_active=TRUE AND e.course_type=%s
        ORDER BY e.created_at DESC
    """, (course_type,))
    now   = datetime.now(timezone.utc)
    exams = []
    for r in rows:
        e = dict(r)
        # جلب حالة الطالب مع هذا الامتحان
        sub = await q("""
            SELECT start_time,end_time,submitted_at,score
            FROM exam_submissions WHERE exam_id=%s AND user_id=%s
        """, (e["id"], u["id"]), "one")

        e["created_at"] = str(e.get("created_at",""))
        e["file_url"]   = f"/api/file/{e['file_id']}" if e.get("file_id") else None

        if sub:
            sub = dict(sub)
            end = sub.get("end_time")
            if end:
                if end.tzinfo is None: end = end.replace(tzinfo=timezone.utc)
                rem = int((end - now).total_seconds())
                e["remaining_seconds"] = max(0, rem)
                e["is_expired"]        = rem <= 0
            else:
                e["remaining_seconds"] = e["duration_minutes"]*60
                e["is_expired"]        = False
            e["my_status"] = "submitted" if sub.get("submitted_at") else ("expired" if e["is_expired"] else "started")
            e["my_score"]  = sub.get("score")
        else:
            e["remaining_seconds"] = e["duration_minutes"]*60
            e["is_expired"]        = False
            e["my_status"]         = "not_started"
            e["my_score"]          = None
        exams.append(e)
    return {"exams":exams}

@app.post("/api/exams/{exam_id}/start")
async def start_exam(exam_id:int, u=Depends(current_user)):
    uid  = u["id"]
    exam = await q("SELECT * FROM exams WHERE id=%s AND is_active=TRUE",(exam_id,),"one")
    if not exam: raise HTTPException(404,"الامتحان غير موجود")

    sub = await q("SELECT * FROM exam_submissions WHERE exam_id=%s AND user_id=%s",(exam_id,uid),"one")
    now = datetime.now(timezone.utc)
    if sub:
        sub = dict(sub)
        if sub.get("submitted_at"): return {"status":"already_submitted"}
        end = sub.get("end_time")
        if end:
            if end.tzinfo is None: end = end.replace(tzinfo=timezone.utc)
            rem = int((end-now).total_seconds())
            if rem <= 0: return {"status":"expired","remaining":0}
            return {"status":"active","remaining":rem,"end_time":end.isoformat()}

    end = now + timedelta(minutes=exam["duration_minutes"])
    await q("""
        INSERT INTO exam_submissions(exam_id,user_id,start_time,end_time)
        VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING
    """, (exam_id,uid,now,end), "none")
    return {"status":"started","remaining":exam["duration_minutes"]*60,"end_time":end.isoformat()}

@app.post("/api/exams/{exam_id}/submit")
async def submit_exam(exam_id:int, data:dict, u=Depends(current_user)):
    uid = u["id"]
    sub = await q("SELECT * FROM exam_submissions WHERE exam_id=%s AND user_id=%s",(exam_id,uid),"one")
    if not sub: raise HTTPException(400,"لم تبدأ الامتحان")
    sub = dict(sub)
    if sub.get("submitted_at"): raise HTTPException(400,"لقد سلّمت من قبل")
    now = datetime.now(timezone.utc)
    end = sub.get("end_time")
    if end:
        if end.tzinfo is None: end = end.replace(tzinfo=timezone.utc)
        if now > end: raise HTTPException(400,"انتهى الوقت")
    await q("""
        UPDATE exam_submissions
        SET answer_text=%s, answer_file_id=%s, submitted_at=NOW()
        WHERE exam_id=%s AND user_id=%s
    """, (data.get("answer_text",""), data.get("answer_file_id",""), exam_id, uid), "none")
    result = await award_xp(uid,"exam_submit")
    return {"ok":True,**result}

@app.get("/api/exams/{exam_id}/submissions")
async def exam_submissions(exam_id:int, u=Depends(require("teacher","admin","owner"))):
    rows = await q("""
        SELECT es.*, us.full_name, sl.level, sl.xp, sl.badge
        FROM exam_submissions es
        LEFT JOIN users us ON us.id=es.user_id
        LEFT JOIN student_levels sl ON sl.user_id=es.user_id
        WHERE es.exam_id=%s
        ORDER BY sl.level DESC NULLS LAST, sl.xp DESC, es.submitted_at ASC
    """, (exam_id,))
    subs = []
    for r in rows:
        s = dict(r)
        for f in ("start_time","end_time","submitted_at"):
            v=s.get(f); s[f]=v.isoformat() if hasattr(v,"isoformat") else str(v or "")
        s["answer_url"] = f"/api/file/{s['answer_file_id']}" if s.get("answer_file_id") else None
        subs.append(s)
    return {"submissions":subs}

@app.post("/api/exams/score")
async def score_exam(data:dict, u=Depends(require("teacher","admin","owner"))):
    sub_id = data.get("submission_id")
    score  = float(data.get("score",0))
    fb     = data.get("feedback","")
    sub    = await q("SELECT * FROM exam_submissions WHERE id=%s",(sub_id,),"one")
    if not sub: raise HTTPException(404,"التسليم غير موجود")
    await q("UPDATE exam_submissions SET score=%s,feedback=%s WHERE id=%s",(score,fb,sub_id),"none")
    if score >= 100: await award_xp(sub["user_id"],"exam_score_full")
    await q("""
        INSERT INTO notifications(user_id,title,message,type) VALUES(%s,%s,%s,'success')
    """, (sub["user_id"],f"📊 نتيجة الامتحان",f"درجتك: {score:.1f}/100\n{fb}"), "none")
    return {"ok":True}

# ══════════════════════════════════════════════════════════════
#  Leaderboard
# ══════════════════════════════════════════════════════════════

@app.get("/api/leaderboard")
async def leaderboard(limit:int=20):
    rows = await q("""
        SELECT sl.user_id, sl.xp, sl.level, sl.badge, sl.rank_pos,
               u.full_name, sp.school_name
        FROM student_levels sl
        LEFT JOIN users u  ON u.id=sl.user_id
        LEFT JOIN student_profiles sp ON sp.user_id=sl.user_id
        WHERE u.is_active=TRUE AND u.role='student'
        ORDER BY sl.xp DESC, sl.level DESC
        LIMIT %s
    """, (min(limit,100),))
    return {"leaderboard":[dict(r) for r in rows]}

# ══════════════════════════════════════════════════════════════
#  Notifications
# ══════════════════════════════════════════════════════════════

@app.get("/api/notifications")
async def get_notifs(u=Depends(current_user)):
    rows = await q("""
        SELECT * FROM notifications WHERE user_id=%s
        ORDER BY created_at DESC LIMIT 50
    """, (u["id"],))
    notifs = []
    for r in rows:
        n=dict(r); n["created_at"]=str(n.get("created_at","")); notifs.append(n)
    return {"notifications":notifs,"unread":sum(1 for n in notifs if not n["is_read"])}

@app.post("/api/notifications/read")
async def read_notifs(u=Depends(current_user)):
    await q("UPDATE notifications SET is_read=TRUE WHERE user_id=%s",(u["id"],),"none")
    return {"ok":True}

# ══════════════════════════════════════════════════════════════
#  Admin
# ══════════════════════════════════════════════════════════════

@app.get("/api/admin/stats")
async def admin_stats(u=Depends(require("admin","owner"))):
    tu = await q("SELECT COUNT(*) AS c FROM users WHERE role='student'","()","one") or {}
    tl = await q("SELECT COUNT(*) AS c FROM lectures","()","one") or {}
    te = await q("SELECT COUNT(*) AS c FROM exams","()","one") or {}
    ts = await q("SELECT COUNT(*) AS c FROM exam_submissions WHERE submitted_at IS NOT NULL","()","one") or {}
    top = await q("""
        SELECT u.full_name,sl.xp,sl.level,sl.badge FROM student_levels sl
        JOIN users u ON u.id=sl.user_id ORDER BY sl.xp DESC LIMIT 5
    """)
    return {
        "total_students": tu.get("c",0),
        "total_lectures": tl.get("c",0),
        "total_exams":    te.get("c",0),
        "total_subs":     ts.get("c",0),
        "top_students":   [dict(r) for r in (top or [])],
    }

@app.get("/api/admin/users")
async def admin_users(page:int=1, u=Depends(require("admin","owner"))):
    offset = (page-1)*20
    rows   = await q("""
        SELECT u.id,u.telegram_id,u.full_name,u.username,u.role,u.is_active,u.created_at,
               sl.xp,sl.level,sl.badge,sp.school_name,sp.course_type
        FROM users u
        LEFT JOIN student_levels sl ON sl.user_id=u.id
        LEFT JOIN student_profiles sp ON sp.user_id=u.id
        WHERE u.role='student' ORDER BY u.created_at DESC LIMIT 20 OFFSET %s
    """, (offset,))
    users = []
    for r in rows:
        usr=dict(r); usr["created_at"]=str(usr.get("created_at","")); users.append(usr)
    total = await q("SELECT COUNT(*) AS c FROM users WHERE role='student'","()","one") or {}
    return {"users":users,"total":total.get("c",0),"page":page}

@app.post("/api/admin/broadcast")
async def broadcast(data:dict, u=Depends(require("admin","owner"))):
    title = data.get("title","إشعار")
    msg   = data.get("message","")
    if not msg: raise HTTPException(400,"الرسالة فارغة")
    users = await q("SELECT id FROM users WHERE is_active=TRUE AND role='student'") or []
    for usr in users:
        await q("INSERT INTO notifications(user_id,title,message,type) VALUES(%s,%s,%s,'info')",
                (usr["id"],title,msg),"none")
    return {"ok":True,"sent_to":len(users)}

@app.post("/api/admin/update-ranks")
async def upd_ranks(u=Depends(require("admin","owner"))):
    await q("SELECT update_ranks()","()","none")
    return {"ok":True}

# ══════════════════════════════════════════════════════════════
#  Health
# ══════════════════════════════════════════════════════════════

@app.get("/")
@app.get("/health")
async def health():
    return {"status":"ok","platform":"منصة السادس التعليمية","version":"1.0.0"}
