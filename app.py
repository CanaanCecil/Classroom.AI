#!/usr/bin/env python3
import csv
import datetime as dt
import json
import os
import re
import sqlite3
import threading
import urllib.error
import urllib.request
import uuid
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "classroom_ai.db"
STATIC_DIR = BASE_DIR / "static"

DEFAULT_JOIN_CODE = "ABC123"

BAD_WORDS = {
    "hate",
    "kill",
    "weapon",
    "bomb",
    "explicit",
    "sex",
    "drugs",
    "violence",
}

STOPWORDS = {
    "the", "a", "an", "is", "are", "to", "and", "of", "in", "for", "on", "with", "how", "what",
    "why", "when", "where", "i", "we", "you", "it", "do", "does", "can", "could", "would", "should",
    "my", "our", "me", "this", "that", "explain", "help"
}

DB_LOCK = threading.Lock()
SESSION_LOCK = threading.Lock()
TEACHER_SESSIONS = {}

TEACHER_USERNAME = "Teacher"
TEACHER_PASSWORD = "Teacher123"
SESSION_COOKIE = "teacher_session"


def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS classrooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                join_code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                ai_enabled INTEGER NOT NULL DEFAULT 1,
                grade_level TEXT NOT NULL DEFAULT '6-8',
                tone TEXT NOT NULL DEFAULT 'simple',
                topic_limit TEXT NOT NULL DEFAULT '',
                custom_bad_words TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                classroom_id INTEGER NOT NULL,
                student_name TEXT,
                is_anonymous INTEGER NOT NULL,
                question TEXT NOT NULL,
                ai_response TEXT NOT NULL,
                moderation_status TEXT NOT NULL DEFAULT 'visible',
                is_flagged INTEGER NOT NULL DEFAULT 0,
                is_blocked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (classroom_id) REFERENCES classrooms (id)
            );

            CREATE TABLE IF NOT EXISTS broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                classroom_id INTEGER NOT NULL,
                interaction_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (classroom_id) REFERENCES classrooms (id),
                FOREIGN KEY (interaction_id) REFERENCES interactions (id)
            );
            """
        )
        classroom_cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(classrooms)").fetchall()
        }
        if "custom_bad_words" not in classroom_cols:
            conn.execute(
                "ALTER TABLE classrooms ADD COLUMN custom_bad_words TEXT NOT NULL DEFAULT '[]'"
            )
        now = dt.datetime.utcnow().isoformat()
        conn.execute(
            """
            INSERT OR IGNORE INTO classrooms (join_code, name, created_at)
            VALUES (?, ?, ?)
            """,
            (DEFAULT_JOIN_CODE, "Default Classroom", now),
        )
        conn.commit()


def json_response(handler, status, payload):
    data = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def bytes_response(handler, status, payload, content_type):
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def text_response(handler, status, text, content_type="text/plain; charset=utf-8"):
    bytes_response(handler, status, text.encode("utf-8"), content_type)


def read_json(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b"{}"
    return json.loads(raw.decode("utf-8"))


def parse_cookies(cookie_header):
    cookies = {}
    if not cookie_header:
        return cookies
    for chunk in cookie_header.split(";"):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        cookies[key.strip()] = value.strip()
    return cookies


def is_teacher_authenticated(handler):
    cookies = parse_cookies(handler.headers.get("Cookie", ""))
    token = cookies.get(SESSION_COOKIE)
    if not token:
        return False
    with SESSION_LOCK:
        return token in TEACHER_SESSIONS


def require_teacher_auth(handler):
    if is_teacher_authenticated(handler):
        return True
    json_response(handler, HTTPStatus.UNAUTHORIZED, {"error": "Teacher login required."})
    return False


def login_teacher(payload):
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", "")).strip()
    if username != TEACHER_USERNAME or password != TEACHER_PASSWORD:
        return HTTPStatus.UNAUTHORIZED, {"error": "Invalid teacher credentials."}, None

    token = uuid.uuid4().hex
    with SESSION_LOCK:
        TEACHER_SESSIONS[token] = {"created_at": dt.datetime.utcnow().isoformat()}
    return HTTPStatus.OK, {"ok": True}, token


def logout_teacher(handler):
    cookies = parse_cookies(handler.headers.get("Cookie", ""))
    token = cookies.get(SESSION_COOKIE)
    if token:
        with SESSION_LOCK:
            TEACHER_SESSIONS.pop(token, None)


def find_classroom(join_code):
    with DB_LOCK, db_connect() as conn:
        row = conn.execute(
            "SELECT * FROM classrooms WHERE join_code = ?", (join_code,)
        ).fetchone()
        return dict(row) if row else None


def is_inappropriate(question):
    return is_inappropriate_for_words(question, BAD_WORDS)


def normalize_custom_bad_words(words):
    normalized = []
    seen = set()
    for raw in words:
        token = re.sub(r"\s+", " ", str(raw).strip().lower())
        if not token or token in seen:
            continue
        seen.add(token)
        normalized.append(token)
    return normalized


def parse_custom_bad_words(raw_value):
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except ValueError:
        parsed = []
    if not isinstance(parsed, list):
        return []
    return normalize_custom_bad_words(parsed)


def get_classroom_bad_words(classroom):
    custom_words = parse_custom_bad_words(classroom.get("custom_bad_words", "[]"))
    return set(BAD_WORDS) | set(custom_words)


def is_inappropriate_for_words(question, bad_words):
    q = question.lower()
    return any(w in q for w in bad_words)


def within_topic(question, topic_limit):
    if not topic_limit.strip():
        return True
    tokens = set(re.findall(r"[a-zA-Z0-9]+", question.lower()))
    required = set(re.findall(r"[a-zA-Z0-9]+", topic_limit.lower()))
    return bool(tokens & required)


def local_ai_response(question, grade_level, tone):
    prefix = {
        "simple": "Simple explanation:",
        "detailed": "Detailed explanation:",
        "step-by-step": "Step-by-step explanation:",
    }.get(tone, "Explanation:")

    explanation = (
        f"{prefix} For grade {grade_level}, start by identifying what the question asks, "
        "connect it to class notes, and solve one part at a time. "
        f"For your question ('{question}'), try: 1) define key terms, "
        "2) apply the relevant rule/formula, 3) check your answer with an example."
    )
    return explanation


def call_openai(question, grade_level, tone, topic_limit):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    system = (
        "You are a classroom-safe K-12 AI tutor. Avoid harmful/inappropriate content, "
        "be concise, and do not browse the internet."
    )
    config = (
        f"Grade level: {grade_level}. Tone: {tone}. "
        f"Curriculum restriction: {topic_limit or 'none'}"
    )
    payload = {
        "model": "gpt-4.1-mini",
        "input": [
            {"role": "system", "content": system},
            {"role": "system", "content": config},
            {"role": "user", "content": question},
        ],
    }

    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "output_text" in data and data["output_text"]:
                return data["output_text"].strip()
            parts = []
            for item in data.get("output", []):
                for content in item.get("content", []):
                    txt = content.get("text")
                    if txt:
                        parts.append(txt)
            return "\n".join(parts).strip() or None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
        return None


def generate_ai_response(question, grade_level, tone, topic_limit):
    return call_openai(question, grade_level, tone, topic_limit) or local_ai_response(
        question, grade_level, tone
    )


def post_question(payload):
    join_code = str(payload.get("joinCode", "")).strip().upper()
    name = str(payload.get("studentName", "")).strip()
    anonymous = bool(payload.get("anonymous", False))
    question = str(payload.get("question", "")).strip()

    if not join_code or not question:
        return HTTPStatus.BAD_REQUEST, {"error": "joinCode and question are required."}

    classroom = find_classroom(join_code)
    if not classroom:
        return HTTPStatus.NOT_FOUND, {"error": "Invalid classroom join code."}

    if not classroom["ai_enabled"]:
        return HTTPStatus.FORBIDDEN, {"error": "AI is turned off by teacher."}

    blocked = False
    if is_inappropriate_for_words(question, get_classroom_bad_words(classroom)):
        blocked = True
        response = "Your question was blocked by the classroom safety filter. Please rephrase respectfully."
    elif not within_topic(question, classroom["topic_limit"]):
        blocked = True
        response = (
            "Your question appears outside the current curriculum restriction. "
            f"Allowed topic: {classroom['topic_limit']}"
        )
    else:
        response = generate_ai_response(
            question,
            classroom["grade_level"],
            classroom["tone"],
            classroom["topic_limit"],
        )

    now = dt.datetime.utcnow().isoformat()
    student_name = None if anonymous else (name or "Student")

    with DB_LOCK, db_connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO interactions (
                classroom_id, student_name, is_anonymous, question, ai_response,
                moderation_status, is_flagged, is_blocked, created_at
            ) VALUES (?, ?, ?, ?, ?, 'visible', 0, ?, ?)
            """,
            (
                classroom["id"],
                student_name,
                1 if anonymous else 0,
                question,
                response,
                1 if blocked else 0,
                now,
            ),
        )
        interaction_id = cursor.lastrowid
        conn.commit()

    return HTTPStatus.OK, {
        "interactionId": interaction_id,
        "question": question,
        "response": response,
        "blocked": blocked,
        "timestamp": now,
    }


def list_interactions(join_code):
    classroom = find_classroom(join_code)
    if not classroom:
        return HTTPStatus.NOT_FOUND, {"error": "Invalid classroom join code."}

    with DB_LOCK, db_connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM interactions
            WHERE classroom_id = ?
            ORDER BY id DESC
            LIMIT 200
            """,
            (classroom["id"],),
        ).fetchall()

        broadcasts = conn.execute(
            """
            SELECT b.id as broadcast_id, i.*
            FROM broadcasts b
            JOIN interactions i ON i.id = b.interaction_id
            WHERE b.classroom_id = ?
            ORDER BY b.id DESC
            LIMIT 30
            """,
            (classroom["id"],),
        ).fetchall()

    return HTTPStatus.OK, {
        "classroom": classroom,
        "interactions": [dict(r) for r in rows],
        "broadcasts": [dict(r) for r in broadcasts],
    }


def list_broadcasts(join_code):
    classroom = find_classroom(join_code)
    if not classroom:
        return HTTPStatus.NOT_FOUND, {"error": "Invalid classroom join code."}

    with DB_LOCK, db_connect() as conn:
        rows = conn.execute(
            """
            SELECT b.id as broadcast_id, i.*
            FROM broadcasts b
            JOIN interactions i ON i.id = b.interaction_id
            WHERE b.classroom_id = ?
            ORDER BY b.id DESC
            LIMIT 30
            """,
            (classroom["id"],),
        ).fetchall()

    return HTTPStatus.OK, {"broadcasts": [dict(r) for r in rows]}


def update_settings(payload):
    join_code = str(payload.get("joinCode", "")).strip().upper()
    classroom = find_classroom(join_code)
    if not classroom:
        return HTTPStatus.NOT_FOUND, {"error": "Invalid classroom join code."}

    ai_enabled = 1 if payload.get("aiEnabled", classroom["ai_enabled"]) else 0
    grade_level = str(payload.get("gradeLevel", classroom["grade_level"]))
    tone = str(payload.get("tone", classroom["tone"]))
    topic_limit = str(payload.get("topicLimit", classroom["topic_limit"]))
    custom_bad_words = normalize_custom_bad_words(payload.get("customBadWords", []))

    with DB_LOCK, db_connect() as conn:
        conn.execute(
            """
            UPDATE classrooms
            SET ai_enabled = ?, grade_level = ?, tone = ?, topic_limit = ?, custom_bad_words = ?
            WHERE id = ?
            """,
            (
                ai_enabled,
                grade_level,
                tone,
                topic_limit,
                json.dumps(custom_bad_words),
                classroom["id"],
            ),
        )
        conn.commit()

    return HTTPStatus.OK, {"ok": True}


def moderate_interaction(payload):
    interaction_id = int(payload.get("interactionId", 0))
    action = str(payload.get("action", "")).strip()

    if action not in {"approve", "hide", "flag", "broadcast"}:
        return HTTPStatus.BAD_REQUEST, {"error": "Invalid moderation action."}

    with DB_LOCK, db_connect() as conn:
        row = conn.execute(
            "SELECT * FROM interactions WHERE id = ?", (interaction_id,)
        ).fetchone()
        if not row:
            return HTTPStatus.NOT_FOUND, {"error": "Interaction not found."}

        if action == "approve":
            conn.execute(
                "UPDATE interactions SET moderation_status = 'visible' WHERE id = ?",
                (interaction_id,),
            )
        elif action == "hide":
            conn.execute(
                "UPDATE interactions SET moderation_status = 'hidden' WHERE id = ?",
                (interaction_id,),
            )
        elif action == "flag":
            conn.execute(
                "UPDATE interactions SET is_flagged = 1 WHERE id = ?",
                (interaction_id,),
            )
        elif action == "broadcast":
            conn.execute(
                "INSERT INTO broadcasts (classroom_id, interaction_id, created_at) VALUES (?, ?, ?)",
                (row["classroom_id"], interaction_id, dt.datetime.utcnow().isoformat()),
            )
        conn.commit()

    return HTTPStatus.OK, {"ok": True}


def build_analytics(join_code):
    classroom = find_classroom(join_code)
    if not classroom:
        return HTTPStatus.NOT_FOUND, {"error": "Invalid classroom join code."}

    with DB_LOCK, db_connect() as conn:
        rows = conn.execute(
            """
            SELECT student_name, question, created_at
            FROM interactions
            WHERE classroom_id = ?
            ORDER BY created_at DESC
            """,
            (classroom["id"],),
        ).fetchall()

    tokens = []
    student_counts = Counter()
    for r in rows:
        if r["student_name"]:
            student_counts[r["student_name"]] += 1
        words = re.findall(r"[a-zA-Z0-9]+", r["question"].lower())
        tokens.extend([w for w in words if w not in STOPWORDS and len(w) > 2])

    top_concepts = Counter(tokens).most_common(10)
    support_signals = [
        {"student": name, "questionCount": count}
        for name, count in student_counts.most_common(10)
    ]

    return HTTPStatus.OK, {
        "classroom": classroom,
        "totalQuestions": len(rows),
        "topConcepts": top_concepts,
        "supportSignals": support_signals,
    }


def export_weekly_csv(join_code):
    classroom = find_classroom(join_code)
    if not classroom:
        return HTTPStatus.NOT_FOUND, b"Invalid classroom join code.", "text/plain; charset=utf-8"

    start = dt.datetime.utcnow() - dt.timedelta(days=7)
    with DB_LOCK, db_connect() as conn:
        rows = conn.execute(
            """
            SELECT created_at, student_name, is_anonymous, question, ai_response, moderation_status, is_flagged, is_blocked
            FROM interactions
            WHERE classroom_id = ? AND created_at >= ?
            ORDER BY created_at DESC
            """,
            (classroom["id"], start.isoformat()),
        ).fetchall()

    output = []
    header = [
        "created_at",
        "student_name",
        "is_anonymous",
        "question",
        "ai_response",
        "moderation_status",
        "is_flagged",
        "is_blocked",
    ]
    output.append(header)
    for r in rows:
        output.append([r[h] for h in header])

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerows(output)
    data = buf.getvalue().encode("utf-8")
    return HTTPStatus.OK, data, "text/csv; charset=utf-8"


def is_safe_static_path(rel_path):
    candidate = (STATIC_DIR / rel_path).resolve()
    return STATIC_DIR.resolve() in candidate.parents or candidate == STATIC_DIR.resolve()


class ClassroomHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in {"/", "/index.html", "/student", "/preview"}:
            return self.serve_file("student.html", "text/html; charset=utf-8")
        if path in {"/teacher", "/teacher/"}:
            if is_teacher_authenticated(self):
                return self.serve_file("teacher.html", "text/html; charset=utf-8")
            return self.serve_file("teacher_login.html", "text/html; charset=utf-8")
        if path in {"/teacher/login", "/teacher/login/"}:
            return self.serve_file("teacher_login.html", "text/html; charset=utf-8")
        if path == "/health":
            return json_response(self, HTTPStatus.OK, {"ok": True})
        if path == "/favicon.ico":
            return bytes_response(self, HTTPStatus.NO_CONTENT, b"", "image/x-icon")
        if path.startswith("/static/"):
            rel = path[len("/static/"):]
            return self.serve_static(rel)

        if path == "/api/interactions":
            if not require_teacher_auth(self):
                return
            qs = parse_qs(parsed.query)
            join_code = (qs.get("joinCode") or [""])[0].strip().upper()
            status, payload = list_interactions(join_code)
            return json_response(self, status, payload)

        if path == "/api/broadcasts":
            qs = parse_qs(parsed.query)
            join_code = (qs.get("joinCode") or [""])[0].strip().upper()
            status, payload = list_broadcasts(join_code)
            return json_response(self, status, payload)

        if path == "/api/analytics":
            if not require_teacher_auth(self):
                return
            qs = parse_qs(parsed.query)
            join_code = (qs.get("joinCode") or [""])[0].strip().upper()
            status, payload = build_analytics(join_code)
            return json_response(self, status, payload)

        if path == "/api/export":
            if not require_teacher_auth(self):
                return
            qs = parse_qs(parsed.query)
            join_code = (qs.get("joinCode") or [""])[0].strip().upper()
            status, data, ctype = export_weekly_csv(join_code)
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", "attachment; filename=weekly_report.csv")
            self.end_headers()
            self.wfile.write(data)
            return

        # Preview environments often hit unknown frontend paths.
        # Fall back to student UI unless it's clearly an API path.
        if not path.startswith("/api/"):
            return self.serve_file("student.html", "text/html; charset=utf-8")

        return text_response(self, HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        payload = read_json(self)

        if parsed.path == "/auth/login":
            status, body, token = login_teacher(payload)
            if status != HTTPStatus.OK:
                return json_response(self, status, body)
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}={token}; HttpOnly; Path=/; SameSite=Lax")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if parsed.path == "/auth/logout":
            logout_teacher(self)
            data = json.dumps({"ok": True}).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}=; Max-Age=0; Path=/; SameSite=Lax")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if parsed.path == "/api/question":
            status, body = post_question(payload)
            return json_response(self, status, body)

        if parsed.path == "/api/settings":
            if not require_teacher_auth(self):
                return
            status, body = update_settings(payload)
            return json_response(self, status, body)

        if parsed.path == "/api/moderate":
            if not require_teacher_auth(self):
                return
            status, body = moderate_interaction(payload)
            return json_response(self, status, body)

        return text_response(self, HTTPStatus.NOT_FOUND, "Not Found")

    def log_message(self, format, *args):
        return

    def serve_file(self, filename, content_type):
        path = STATIC_DIR / filename
        if not path.exists():
            return text_response(self, HTTPStatus.NOT_FOUND, "Not Found")
        text_response(self, HTTPStatus.OK, path.read_text("utf-8"), content_type)

    def serve_static(self, rel_path):
        if not rel_path or ".." in rel_path or not is_safe_static_path(rel_path):
            return text_response(self, HTTPStatus.BAD_REQUEST, "Invalid static path")

        path = STATIC_DIR / rel_path
        if not path.exists() or not path.is_file():
            return text_response(self, HTTPStatus.NOT_FOUND, "Not Found")

        ctype = "text/plain; charset=utf-8"
        if rel_path.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        elif rel_path.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        elif rel_path.endswith(".html"):
            ctype = "text/html; charset=utf-8"

        data = path.read_bytes()
        bytes_response(self, HTTPStatus.OK, data, ctype)


def main():
    init_db()
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), ClassroomHandler)
    print(f"Classroom AI Assistant running on http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
