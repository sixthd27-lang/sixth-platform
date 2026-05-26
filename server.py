"""
منصة السادس التعليمية — FastAPI Backend
Render + Neon PostgreSQL
"""

import os, asyncio
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row
from passlib.context import CryptContext
from jose import JWTError, jwt
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

# ══════════════════════════════════════
#  Config
# ══════════════════════════════════════
DB_URL     = os.getenv("DATABASE_URL", "")
SECRET     = os.getenv("SECRET_KEY",   "sadis-super-secret-2024")
ORIGINS    = os.getenv("ORIGINS", "*").split(",")
ALGO       = "HS256"
TOKEN_DAYS = 30

THRESHOLDS = [0, 100, 300, 700, 1500, 3000, 5000, 8000, 12000, 18000, 25000]
XP_MAP     = {"lecture": 10, "exam": 30, "exam_full": 50, "login": 5}

pwd  = CryptContext(schemes=["bcrypt"], deprecated="auto")
auth = HTTPBearer(auto_error=False)

# ══════════════════════════════════════
#  App
# ══════════════════════════════════════
app = FastAPI(title="منصة السادس API", docs_url="/docs")
app.add_middleware(CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"],
    allow_headers=["*"], allow_credentials=True)

# ══════════════════════════════════════
#  DB helper
# ══════════════════════════════════════
def get_conn():
    return psycopg.connect(DB_URL, row_factory=dict_row)

async def db(sql: str, params=(), mode="all"):
    loop = asyncio.get_running_loop()
    def _r():
        with get_conn() as c:
            with c.cursor() as cur:
                cur.execute(sql, params)
                c.commit()
                if mode == "one": return cur.fetchone()
                if mode == "all": return cur.fetchall()
    return await loop.run_in_executor(None, _r)

# ══════════════════════════════════════
#  Init DB on startup
# ══════════════════════════════════════
@app.on_event("startup")
async def startup():
    p = os.path.join(os.path.dirname(__file__), "schema.sql")
    if not os.path.exists(p): return
    loop = asyncio.get_running_loop()
    def _init():
        with get_conn() as c:
            with c.cursor() as cur:
                cur.execute(open(p).read())
            c.commit()
    try:
        await loop.run_in_executor(None, _init)
        print("✅ DB ready")
    except Exception as e:
        print(f"⚠️ DB init: {e}")

# ══════════════════════════════════════
#  XP utils
# ══════════════════════════════════════
def calc_level(xp):
    for i in range(len(THRESHOLDS)-1,-1,-1):
        if xp >= THRESHOLDS[i]: return i+1
    return 1

def get_badge(lvl):
    if lvl >= 41: return "👑"
    if lvl >= 26: return "💎"
    if lvl >= 16: return "🥇"
    if lvl >= 6:  return "🥈"
    return "🥉"

def xp_info(xp):
    t   = THRESHOLDS
    lvl = calc_level(xp)
    if lvl >= len(t): return {"level":lvl,"pct":100,"needed":0,"next":t[-1]}
    cur = t[lvl-1]; nxt = t[lvl]
    pct = min(100, int((xp-cur)/(nxt-cur)*100))
    return {"level":lvl,"pct":pct,"needed":nxt-xp,"next":nxt,"cur":cur}

async def give_xp(user_id: int, action: str) -> dict:
    gained = XP_MAP.get(action, 0)
    if not gained: return {}
    row = await db("SELECT xp,level FROM student_data WHERE user_id=%s",(user_id,),"one")
    old_lvl = (row or {}).get("level",1)
    new_xp  = (row or {}).get("xp",0) + gained
    new_lvl = calc_level(new_xp)
    badge   = get_badge(new_lvl)
    await db("""
        INSERT INTO student_data(user_id,xp,level,badge,updated_at)
        VALUES(%s,%s,%s,%s,NOW())
        ON CONFLICT(user_id) DO UPDATE
        SET xp=EXCLUDED.xp,level=EXCLUDED.level,badge=EXCLUDED.badge,updated_at=NOW()
    """, (user_id,new_xp,new_lvl,badge), "all")
    leveled_up = new_lvl > old_lvl
    if leveled_up:
        await db("INSERT INTO notifications(user_id,title,message,type) VALUES(%s,%s,%s,'success')",
                 (user_id,f"🎉 مبروك! وصلت LVL {new_lvl}",f"أنت الآن {badge} LVL {new_lvl}"))
    return {"xp":new_xp,"level":new_lvl,"badge":badge,"gained":gained,"leveled_up":leveled_up}

# ══════════════════════════════════════
#  Auth utils
# ══════════════════════════════════════
def make_token(uid,role):
    exp = datetime.now(timezone.utc) + timedelta(days=TOKEN_DAYS)
    return jwt.encode({"sub":str(uid),"role":role,"exp":exp}, SECRET, ALGO)

async def get_user(creds: HTTPAuthorizationCredentials = Depends(auth)):
    if not creds: raise HTTPException(401,"يجب تسجيل الدخول")
    try:
        p   = jwt.decode(creds.credentials, SECRET, algorithms=[ALGO])
        uid = int(p["sub"])
    except (JWTError,ValueError):
        raise HTTPException(401,"رمز غير صالح")
    u = await db("SELECT * FROM users WHERE id=%s AND is_active=TRUE",(uid,),"one")
    if not u: raise HTTPException(401,"المستخدم غير موجود")
    return dict(u)

def require(*roles):
    async def _c(u=Depends(get_user)):
        if u["role"] not in roles: raise HTTPException(403,"لا تملك الصلاحية")
        return u
    return _c

# ══════════════════════════════════════
#  Pydantic
# ══════════════════════════════════════
class RegisterReq(BaseModel):
    full_name:   str
    username:    str
    password:    str
    school_name: str = ""
    class_code:  str = ""

class LoginReq(BaseModel):
    username: str
    password: str

class LectureReq(BaseModel):
    title:       str
    subject_key: str
    chapter:     str = ""
    description: str = ""
    url:         str = ""
    file_type:   str = "link"

class ExamReq(BaseModel):
    title:            str
    subject_key:      str
    duration_minutes: int = 60
    description:      str = ""
    url:              str = ""

class SubmitReq(BaseModel):
    exam_id:     int
    answer_text: str = ""
    answer_url:  str = ""

class ScoreReq(BaseModel):
    submission_id: int
    score:         float
    feedback:      str = ""

# ══════════════════════════════════════
#  Auth Routes
# ══════════════════════════════════════
@app.post("/auth/register")
async def register(b: RegisterReq):
    ex = await db("SELECT id FROM users WHERE username=%s",(b.username,),"one")
    if ex: raise HTTPException(400,"اسم المستخدم موجود مسبقاً")
    h   = pwd.hash(b.password)
    u   = await db("""
        INSERT INTO users(full_name,username,password_hash,school_name,class_code)
        VALUES(%s,%s,%s,%s,%s) RETURNING id,role
    """, (b.full_name,b.username,h,b.school_name,b.class_code),"one")
    uid = u["id"]
    await db("INSERT INTO student_data(user_id) VALUES(%s) ON CONFLICT DO NOTHING",(uid,),"all")
    await give_xp(uid,"login")
    token = make_token(uid,u["role"])
    return {"token":token,"user_id":uid,"role":u["role"],"full_name":b.full_name}

@app.post("/auth/login")
async def login(b: LoginReq):
    u = await db("SELECT * FROM users WHERE username=%s AND is_active=TRUE",(b.username,),"one")
    if not u or not pwd.verify(b.password, u["password_hash"] or ""):
        raise HTTPException(401,"اسم المستخدم أو كلمة المرور غير صحيحة")
    uid = u["id"]
    await db("INSERT INTO student_data(user_id) VALUES(%s) ON CONFLICT DO NOTHING",(uid,),"all")
    await give_xp(uid,"login")
    token = make_token(uid,u["role"])
    return {"token":token,"user_id":uid,"role":u["role"],"full_name":u["full_name"]}

@app.get("/auth/me")
async def me(u=Depends(get_user)):
    sd = await db("SELECT * FROM student_data WHERE user_id=%s",(u["id"],),"one")
    return {**u,"xp_data":dict(sd) if sd else {}}

# ══════════════════════════════════════
#  Profile
# ══════════════════════════════════════
@app.get("/api/profile")
async def profile(u=Depends(get_user)):
    uid = u["id"]
    sd  = await db("SELECT * FROM student_data WHERE user_id=%s",(uid,),"one") or {}
    lc  = await db("SELECT COUNT(*) AS c FROM completed_lectures WHERE user_id=%s",(uid,),"one") or {}
    sc  = await db("SELECT COUNT(*) AS c FROM exam_submissions WHERE user_id=%s AND submitted_at IS NOT NULL",(uid,),"one") or {}
    xp  = sd.get("xp",0)
    pr  = xp_info(xp)
    return {
        "user_id":    uid,
        "full_name":  u["full_name"],
        "username":   u["username"],
        "role":       u["role"],
        "school_name":u.get("school_name",""),
        "class_code": u.get("class_code",""),
        "xp":         xp,
        "level":      sd.get("level",1),
        "badge":      sd.get("badge","🥉"),
        "rank_pos":   sd.get("rank_pos"),
        "progress":   pr,
        "done_lec":   lc.get("c",0),
        "done_exam":  sc.get("c",0),
    }

@app.patch("/api/profile")
async def edit_profile(data: dict, u=Depends(get_user)):
    uid  = u["id"]
    ok   = {"school_name","full_name"}
    upd  = {k:v for k,v in data.items() if k in ok}
    if "full_name" in upd:
        await db("UPDATE users SET full_name=%s WHERE id=%s",(upd.pop("full_name"),uid),"all")
    if "school_name" in upd:
        await db("UPDATE users SET school_name=%s WHERE id=%s",(upd["school_name"],uid),"all")
    return {"ok":True}

# ══════════════════════════════════════
#  Lectures
# ══════════════════════════════════════
@app.get("/api/lectures")
async def get_lectures(subject:str=None, u=Depends(get_user)):
    if subject:
        rows = await db("""
            SELECT l.*,u2.full_name AS teacher FROM lectures l
            LEFT JOIN users u2 ON u2.id=l.created_by
            WHERE l.subject_key=%s ORDER BY l.is_pinned DESC,l.created_at DESC
        """, (subject,))
    else:
        rows = await db("""
            SELECT l.*,u2.full_name AS teacher FROM lectures l
            LEFT JOIN users u2 ON u2.id=l.created_by
            ORDER BY l.subject_key,l.is_pinned DESC,l.created_at DESC LIMIT 200
        """)
    items = []
    for r in (rows or []):
        item = dict(r)
        item["created_at"] = str(item.get("created_at",""))
        items.append(item)
    grouped = {}
    for item in items:
        grouped.setdefault(item["subject_key"],[]).append(item)
    return {"lectures":grouped,"total":len(items)}

@app.post("/api/lectures")
async def add_lecture(b: LectureReq, u=Depends(require("teacher","admin"))):
    r = await db("""
        INSERT INTO lectures(title,subject_key,chapter,description,url,file_type,created_by)
        VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id
    """, (b.title,b.subject_key,b.chapter,b.description,b.url,b.file_type,u["id"]),"one")
    # إشعار جميع الطلاب
    students = await db("SELECT id FROM users WHERE role='student' AND is_active=TRUE")
    for s in (students or []):
        await db("INSERT INTO notifications(user_id,title,message,type) VALUES(%s,%s,%s,'lecture')",
                 (s["id"],f"📚 محاضرة جديدة!",f"{b.title} — {b.subject_key}"),"all")
    return {"id":r["id"],"ok":True}

@app.delete("/api/lectures/{lid}")
async def del_lecture(lid:int, u=Depends(require("teacher","admin"))):
    await db("DELETE FROM lectures WHERE id=%s",(lid,),"all")
    return {"ok":True}

@app.post("/api/lectures/{lid}/done")
async def done_lecture(lid:int, u=Depends(get_user)):
    uid = u["id"]
    await db("UPDATE lectures SET view_count=view_count+1 WHERE id=%s",(lid,),"all")
    await db("INSERT INTO completed_lectures(user_id,lecture_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",(uid,lid),"all")
    result = await give_xp(uid,"lecture")
    return {"ok":True,**result}

# ══════════════════════════════════════
#  Exams
# ══════════════════════════════════════
@app.get("/api/exams")
async def get_exams(u=Depends(get_user)):
    rows = await db("""
        SELECT e.*,u2.full_name AS teacher FROM exams e
        LEFT JOIN users u2 ON u2.id=e.created_by
        WHERE e.is_active=TRUE ORDER BY e.created_at DESC
    """)
    now   = datetime.now(timezone.utc)
    exams = []
    for r in (rows or []):
        e  = dict(r)
        e["created_at"] = str(e.get("created_at",""))
        # جلب حالة الطالب مع الامتحان
        sub = await db("SELECT * FROM exam_submissions WHERE exam_id=%s AND user_id=%s",(e["id"],u["id"]),"one")
        if sub:
            end = sub.get("end_time")
            if end:
                if end.tzinfo is None: end = end.replace(tzinfo=timezone.utc)
                rem = int((end-now).total_seconds())
                e["remaining"] = max(0,rem)
                e["expired"]   = rem <= 0
            else:
                e["remaining"] = e["duration_minutes"]*60
                e["expired"]   = False
            e["my_status"] = "submitted" if sub.get("submitted_at") else ("expired" if e["expired"] else "started")
            e["my_score"]  = sub.get("score")
        else:
            e["remaining"] = e["duration_minutes"]*60
            e["expired"]   = False
            e["my_status"] = "not_started"
            e["my_score"]  = None
        exams.append(e)
    return {"exams":exams}

@app.post("/api/exams")
async def add_exam(b: ExamReq, u=Depends(require("teacher","admin"))):
    r = await db("""
        INSERT INTO exams(title,subject_key,duration_minutes,description,url,created_by)
        VALUES(%s,%s,%s,%s,%s,%s) RETURNING id
    """, (b.title,b.subject_key,b.duration_minutes,b.description,b.url,u["id"]),"one")
    students = await db("SELECT id FROM users WHERE role='student' AND is_active=TRUE")
    for s in (students or []):
        await db("INSERT INTO notifications(user_id,title,message,type) VALUES(%s,%s,%s,'exam')",
                 (s["id"],f"📝 امتحان جديد!",f"{b.title} — {b.duration_minutes} دقيقة"),"all")
    return {"id":r["id"],"ok":True}

@app.post("/api/exams/{eid}/start")
async def start_exam(eid:int, u=Depends(get_user)):
    uid  = u["id"]
    exam = await db("SELECT * FROM exams WHERE id=%s AND is_active=TRUE",(eid,),"one")
    if not exam: raise HTTPException(404,"الامتحان غير موجود")
    sub = await db("SELECT * FROM exam_submissions WHERE exam_id=%s AND user_id=%s",(eid,uid),"one")
    now = datetime.now(timezone.utc)
    if sub:
        sub = dict(sub)
        if sub.get("submitted_at"): return {"status":"submitted"}
        end = sub.get("end_time")
        if end:
            if end.tzinfo is None: end = end.replace(tzinfo=timezone.utc)
            rem = int((end-now).total_seconds())
            if rem<=0: return {"status":"expired","remaining":0}
            return {"status":"active","remaining":rem,"end_time":end.isoformat()}
    end = now + timedelta(minutes=exam["duration_minutes"])
    await db("INSERT INTO exam_submissions(exam_id,user_id,start_time,end_time) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
             (eid,uid,now,end),"all")
    return {"status":"started","remaining":exam["duration_minutes"]*60,"end_time":end.isoformat()}

@app.post("/api/exams/submit")
async def submit_exam(b: SubmitReq, u=Depends(get_user)):
    uid = u["id"]
    sub = await db("SELECT * FROM exam_submissions WHERE exam_id=%s AND user_id=%s",(b.exam_id,uid),"one")
    if not sub: raise HTTPException(400,"لم تبدأ الامتحان")
    if sub.get("submitted_at"): raise HTTPException(400,"لقد سلّمت من قبل")
    now = datetime.now(timezone.utc)
    end = sub.get("end_time")
    if end:
        if end.tzinfo is None: end = end.replace(tzinfo=timezone.utc)
        if now > end: raise HTTPException(400,"انتهى وقت الامتحان")
    await db("UPDATE exam_submissions SET answer_text=%s,answer_url=%s,submitted_at=NOW() WHERE exam_id=%s AND user_id=%s",
             (b.answer_text,b.answer_url,b.exam_id,uid),"all")
    result = await give_xp(uid,"exam")
    return {"ok":True,**result}

@app.get("/api/exams/{eid}/submissions")
async def exam_subs(eid:int, u=Depends(require("teacher","admin"))):
    rows = await db("""
        SELECT es.*,us.full_name,us.school_name,sd.level,sd.xp,sd.badge
        FROM exam_submissions es
        LEFT JOIN users us ON us.id=es.user_id
        LEFT JOIN student_data sd ON sd.user_id=es.user_id
        WHERE es.exam_id=%s
        ORDER BY sd.level DESC NULLS LAST,sd.xp DESC,es.submitted_at ASC
    """, (eid,))
    subs = []
    for r in (rows or []):
        s = dict(r)
        for f in ("start_time","end_time","submitted_at"):
            v=s.get(f); s[f]=v.isoformat() if hasattr(v,"isoformat") else str(v or "")
        subs.append(s)
    return {"submissions":subs}

@app.post("/api/exams/score")
async def score(b: ScoreReq, u=Depends(require("teacher","admin"))):
    sub = await db("SELECT * FROM exam_submissions WHERE id=%s",(b.submission_id,),"one")
    if not sub: raise HTTPException(404,"غير موجود")
    await db("UPDATE exam_submissions SET score=%s,feedback=%s WHERE id=%s",(b.score,b.feedback,b.submission_id),"all")
    if b.score >= 100: await give_xp(sub["user_id"],"exam_full")
    await db("INSERT INTO notifications(user_id,title,message,type) VALUES(%s,%s,%s,'success')",
             (sub["user_id"],"📊 نتيجة الامتحان",f"درجتك: {b.score:.1f}/100 — {b.feedback}"),"all")
    return {"ok":True}

# ══════════════════════════════════════
#  Leaderboard
# ══════════════════════════════════════
@app.get("/api/leaderboard")
async def leaderboard(limit:int=20):
    rows = await db("""
        SELECT sd.user_id,sd.xp,sd.level,sd.badge,sd.rank_pos,
               u.full_name,u.school_name
        FROM student_data sd
        LEFT JOIN users u ON u.id=sd.user_id
        WHERE u.is_active=TRUE AND u.role='student'
        ORDER BY sd.xp DESC,sd.level DESC LIMIT %s
    """, (min(limit,100),))
    return {"leaderboard":[dict(r) for r in (rows or [])]}

# ══════════════════════════════════════
#  Notifications
# ══════════════════════════════════════
@app.get("/api/notifications")
async def get_notifs(u=Depends(get_user)):
    rows = await db("""
        SELECT * FROM notifications WHERE user_id=%s
        ORDER BY created_at DESC LIMIT 30
    """, (u["id"],))
    notifs = []
    for r in (rows or []):
        n=dict(r); n["created_at"]=str(n.get("created_at","")); notifs.append(n)
    return {"notifications":notifs,"unread":sum(1 for n in notifs if not n["is_read"])}

@app.post("/api/notifications/read")
async def read_notifs(u=Depends(get_user)):
    await db("UPDATE notifications SET is_read=TRUE WHERE user_id=%s",(u["id"],),"all")
    return {"ok":True}

# ══════════════════════════════════════
#  Admin
# ══════════════════════════════════════
@app.get("/api/admin/stats")
async def stats(u=Depends(require("admin"))):
    ts = await db("SELECT COUNT(*) AS c FROM users WHERE role='student'","()","one") or {}
    tl = await db("SELECT COUNT(*) AS c FROM lectures","()","one") or {}
    te = await db("SELECT COUNT(*) AS c FROM exams","()","one") or {}
    tp = await db("SELECT COUNT(*) AS c FROM exam_submissions WHERE submitted_at IS NOT NULL","()","one") or {}
    top = await db("""
        SELECT u.full_name,sd.xp,sd.level,sd.badge FROM student_data sd
        JOIN users u ON u.id=sd.user_id ORDER BY sd.xp DESC LIMIT 5
    """) or []
    return {"students":ts.get("c",0),"lectures":tl.get("c",0),
            "exams":te.get("c",0),"submissions":tp.get("c",0),
            "top":[dict(r) for r in top]}

@app.get("/api/admin/users")
async def admin_users(page:int=1, u=Depends(require("admin"))):
    offset = (page-1)*20
    rows = await db("""
        SELECT u.id,u.full_name,u.username,u.role,u.school_name,u.is_active,u.created_at,
               sd.xp,sd.level,sd.badge
        FROM users u LEFT JOIN student_data sd ON sd.user_id=u.id
        WHERE u.role='student' ORDER BY u.created_at DESC LIMIT 20 OFFSET %s
    """, (offset,))
    users = []
    for r in (rows or []):
        usr=dict(r); usr["created_at"]=str(usr.get("created_at","")); users.append(usr)
    total = await db("SELECT COUNT(*) AS c FROM users WHERE role='student'","()","one") or {}
    return {"users":users,"total":total.get("c",0)}

@app.post("/api/admin/broadcast")
async def broadcast(data:dict, u=Depends(require("admin"))):
    title = data.get("title","إشعار")
    msg   = data.get("message","")
    if not msg: raise HTTPException(400,"الرسالة فارغة")
    users = await db("SELECT id FROM users WHERE role='student' AND is_active=TRUE") or []
    for usr in users:
        await db("INSERT INTO notifications(user_id,title,message,type) VALUES(%s,%s,%s,'info')",
                 (usr["id"],title,msg),"all")
    return {"ok":True,"sent":len(users)}

@app.post("/api/admin/ranks")
async def upd_ranks(u=Depends(require("admin"))):
    await db("SELECT update_ranks()","()","all")
    return {"ok":True}

@app.patch("/api/admin/users/{uid}")
async def edit_user(uid:int, data:dict, u=Depends(require("admin"))):
    ok = {"role","is_active"}
    for k,v in data.items():
        if k in ok:
            await db(f"UPDATE users SET {k}=%s WHERE id=%s",(v,uid),"all")
    return {"ok":True}

# ══════════════════════════════════════
#  Health
# ══════════════════════════════════════
@app.get("/")
@app.get("/health")
async def health():
    return {"status":"ok","platform":"منصة السادس التعليمية v2"}
