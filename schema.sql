-- ══════════════════════════════════════════════════════════════
--  منصة السادس التعليمية — PostgreSQL Schema
-- ══════════════════════════════════════════════════════════════

-- Users
CREATE TABLE IF NOT EXISTS users (
    id           SERIAL PRIMARY KEY,
    telegram_id  BIGINT UNIQUE NOT NULL,
    full_name    TEXT   NOT NULL DEFAULT '',
    username     TEXT,
    avatar_url   TEXT,
    role         TEXT   NOT NULL DEFAULT 'student'
                 CHECK (role IN ('student','teacher','admin','owner')),
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMP DEFAULT NOW(),
    last_login   TIMESTAMP
);

-- Student Profiles
CREATE TABLE IF NOT EXISTS student_profiles (
    user_id      INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    school_name  TEXT DEFAULT '',
    course_type  TEXT DEFAULT '15/5',
    bio          TEXT DEFAULT '',
    updated_at   TIMESTAMP DEFAULT NOW()
);

-- XP & Levels
CREATE TABLE IF NOT EXISTS student_levels (
    user_id   INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    xp        INTEGER NOT NULL DEFAULT 0,
    level     INTEGER NOT NULL DEFAULT 1,
    badge     TEXT    NOT NULL DEFAULT '🥉',
    rank_pos  INTEGER,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Lectures (file_id from Telegram)
CREATE TABLE IF NOT EXISTS lectures (
    id           SERIAL PRIMARY KEY,
    title        TEXT    NOT NULL,
    subject_key  TEXT    NOT NULL,
    description  TEXT    DEFAULT '',
    file_id      TEXT    NOT NULL,          -- Telegram file_id
    file_type    TEXT    NOT NULL DEFAULT 'pdf',   -- pdf/video/image
    teacher_name TEXT    DEFAULT '',
    chapter      TEXT    DEFAULT '',
    course_type  TEXT    NOT NULL DEFAULT '15/5',
    is_pinned    BOOLEAN NOT NULL DEFAULT FALSE,
    view_count   INTEGER NOT NULL DEFAULT 0,
    created_by   BIGINT  REFERENCES users(telegram_id),
    created_at   TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_lectures_subject ON lectures(subject_key, course_type);

-- Completed Lectures
CREATE TABLE IF NOT EXISTS completed_lectures (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lecture_id INTEGER NOT NULL REFERENCES lectures(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (user_id, lecture_id)
);

-- Exams
CREATE TABLE IF NOT EXISTS exams (
    id               SERIAL PRIMARY KEY,
    title            TEXT    NOT NULL,
    subject_key      TEXT    NOT NULL DEFAULT 'general',
    course_type      TEXT    NOT NULL DEFAULT '15/5',
    duration_minutes INTEGER NOT NULL DEFAULT 60,
    description      TEXT    DEFAULT '',
    file_id          TEXT,                   -- exam PDF (optional)
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_by       BIGINT  REFERENCES users(telegram_id),
    created_at       TIMESTAMP DEFAULT NOW()
);

-- Exam Submissions
CREATE TABLE IF NOT EXISTS exam_submissions (
    id              SERIAL PRIMARY KEY,
    exam_id         INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    answer_file_id  TEXT,                    -- student's answer file_id
    answer_text     TEXT,
    start_time      TIMESTAMP DEFAULT NOW(),
    end_time        TIMESTAMP,
    submitted_at    TIMESTAMP,
    score           FLOAT,
    feedback        TEXT,
    UNIQUE(exam_id, user_id)
);

-- Authorized Students (للإجابات)
CREATE TABLE IF NOT EXISTS authorized_students (
    telegram_id BIGINT PRIMARY KEY,
    added_by    BIGINT,
    added_at    TIMESTAMP DEFAULT NOW()
);

-- Notifications
CREATE TABLE IF NOT EXISTS notifications (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT    NOT NULL,
    message    TEXT    NOT NULL,
    type       TEXT    DEFAULT 'info',
    is_read    BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Achievements
CREATE TABLE IF NOT EXISTS achievements (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key         TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    icon        TEXT    DEFAULT '🏆',
    earned_at   TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, key)
);

-- Platform Stats
CREATE TABLE IF NOT EXISTS stats (
    key   TEXT PRIMARY KEY,
    value INTEGER DEFAULT 0
);
INSERT INTO stats(key,value) VALUES('messages',0),('lectures',0),('exams',0)
ON CONFLICT DO NOTHING;

-- ══ Seed Subjects ══
CREATE TABLE IF NOT EXISTS subjects (
    key        TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    icon       TEXT DEFAULT '📚',
    color      TEXT DEFAULT '#4f7cff',
    sort_order INTEGER DEFAULT 0
);
INSERT INTO subjects(key,name,icon,color,sort_order) VALUES
    ('arabic',   'اللغة العربية',    '📖','#3498db',1),
    ('islamic',  'التربية الإسلامية','🕌','#2ecc71',2),
    ('english',  'اللغة الإنكليزية','🌍','#95a5a6',3),
    ('math',     'الرياضيات',        '📐','#9b59ff',4),
    ('biology',  'الأحياء',          '🧬','#1abc9c',5),
    ('chemistry','الكيمياء',         '⚗️','#f39c12',6),
    ('physics',  'الفيزياء',         '⚡','#e74c3c',7)
ON CONFLICT (key) DO NOTHING;

-- ══ Update Ranks Function ══
CREATE OR REPLACE FUNCTION update_ranks() RETURNS void AS $$
BEGIN
    UPDATE student_levels sl SET rank_pos = sub.rn
    FROM (
        SELECT user_id,
               ROW_NUMBER() OVER (ORDER BY xp DESC, level DESC, updated_at ASC) AS rn
        FROM student_levels
    ) sub
    WHERE sl.user_id = sub.user_id;
END;
$$ LANGUAGE plpgsql;
