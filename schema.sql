-- ══════════════════════════════════════════════
--  منصة السادس التعليمية — Neon PostgreSQL
-- ══════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    full_name     TEXT    NOT NULL,
    username      TEXT    UNIQUE NOT NULL,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'student'
                  CHECK (role IN ('student','teacher','admin')),
    class_code    TEXT    DEFAULT '',
    school_name   TEXT    DEFAULT '',
    is_active     BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS student_data (
    user_id   INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    xp        INTEGER NOT NULL DEFAULT 0,
    level     INTEGER NOT NULL DEFAULT 1,
    badge     TEXT    NOT NULL DEFAULT '🥉',
    rank_pos  INTEGER,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS lectures (
    id          SERIAL PRIMARY KEY,
    title       TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    chapter     TEXT DEFAULT '',
    description TEXT DEFAULT '',
    url         TEXT DEFAULT '',
    file_type   TEXT DEFAULT 'link',
    is_pinned   BOOLEAN DEFAULT FALSE,
    view_count  INTEGER DEFAULT 0,
    created_by  INTEGER REFERENCES users(id),
    created_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_lec ON lectures(subject_key);

CREATE TABLE IF NOT EXISTS completed_lectures (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lecture_id INTEGER NOT NULL REFERENCES lectures(id) ON DELETE CASCADE,
    done_at    TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (user_id, lecture_id)
);

CREATE TABLE IF NOT EXISTS exams (
    id               SERIAL PRIMARY KEY,
    title            TEXT NOT NULL,
    subject_key      TEXT NOT NULL DEFAULT 'general',
    duration_minutes INTEGER NOT NULL DEFAULT 60,
    description      TEXT DEFAULT '',
    url              TEXT DEFAULT '',
    is_active        BOOLEAN DEFAULT TRUE,
    created_by       INTEGER REFERENCES users(id),
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS exam_submissions (
    id           SERIAL PRIMARY KEY,
    exam_id      INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    answer_text  TEXT DEFAULT '',
    answer_url   TEXT DEFAULT '',
    start_time   TIMESTAMP DEFAULT NOW(),
    end_time     TIMESTAMP,
    submitted_at TIMESTAMP,
    score        FLOAT,
    feedback     TEXT DEFAULT '',
    UNIQUE(exam_id, user_id)
);

CREATE TABLE IF NOT EXISTS notifications (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    message    TEXT NOT NULL,
    type       TEXT DEFAULT 'info',
    is_read    BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ══ XP Thresholds: 1,100,300,700,1500,3000,5000,8000,12000,18000,25000 ══

CREATE OR REPLACE FUNCTION update_ranks() RETURNS void AS $$
BEGIN
    UPDATE student_data sd SET rank_pos = sub.rn
    FROM (
        SELECT user_id,
               ROW_NUMBER() OVER (ORDER BY xp DESC, updated_at ASC) AS rn
        FROM student_data
    ) sub WHERE sd.user_id = sub.user_id;
END;
$$ LANGUAGE plpgsql;

-- ══ Admin account (change password after first login!) ══
INSERT INTO users(full_name,username,password_hash,role)
VALUES('المدير','admin','$2b$12$placeholder_change_this', 'admin')
ON CONFLICT(username) DO NOTHING;
