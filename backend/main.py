from datetime import datetime
import json
import os
import sqlite3
import uuid
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="SM — Walqunnamtii Hawaasaa")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


def get_db():
  conn = sqlite3.connect("sm_database.db", check_same_thread=False)
  conn.row_factory = sqlite3.Row
  return conn


def init_db():
  conn = get_db()
  c = conn.cursor()
  c.execute(
      "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT,"
      " full_name TEXT, username TEXT UNIQUE, password TEXT, bio TEXT DEFAULT"
      " '', avatar_url TEXT DEFAULT '')"
  )
  cols = [r["name"] for r in c.execute("PRAGMA table_info(users)").fetchall()]
  if "bio" not in cols:
    c.execute("ALTER TABLE users ADD COLUMN bio TEXT DEFAULT ''")
  if "avatar_url" not in cols:
    c.execute("ALTER TABLE users ADD COLUMN avatar_url TEXT DEFAULT ''")

  c.execute(
      "CREATE TABLE IF NOT EXISTS posts (id INTEGER PRIMARY KEY AUTOINCREMENT,"
      " username TEXT, full_name TEXT, content TEXT, media_url TEXT,"
      " media_type TEXT, likes INTEGER DEFAULT 0, created_at TEXT)"
  )
  c.execute(
      "CREATE TABLE IF NOT EXISTS comments (id INTEGER PRIMARY KEY"
      " AUTOINCREMENT, post_id INTEGER, username TEXT, full_name TEXT,"
      " comment_text TEXT, created_at TEXT)"
  )
  c.execute(
      "CREATE TABLE IF NOT EXISTS stories (id INTEGER PRIMARY KEY AUTOINCREMENT,"
      " username TEXT, full_name TEXT, caption TEXT, media_url TEXT,"
      " created_at TEXT)"
  )
  c.execute(
      "CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT,"
      " sender TEXT, text TEXT, sent_at TEXT)"
  )
  conn.commit()
  conn.close()


init_db()


class UserAuth(BaseModel):
  full_name: str = ""
  username: str
  password: str


class CommentCreate(BaseModel):
  username: str
  full_name: str
  comment_text: str


async def save_upload_file(file: UploadFile) -> tuple[str, str]:
  ext = os.path.splitext(file.filename)[1].lower()
  unique_name = f"{uuid.uuid4().hex}{ext}"
  save_path = os.path.join(UPLOAD_DIR, unique_name)
  data = await file.read()
  with open(save_path, "wb") as f:
    f.write(data)
  url = f"http://192.168.0.108:8000/uploads/{unique_name}"
  m_type = (
      "video" if ext in [".mp4", ".mov", ".avi", ".mkv", ".webm"] else "image"
  )
  return url, m_type


def format_user(row) -> dict:
  return {
      "full_name": row["full_name"],
      "username": row["username"],
      "bio": row["bio"] or "",
      "avatar_url": row["avatar_url"] or "",
  }


@app.post("/register")
def register(user: UserAuth):
  if not user.full_name.strip():
    raise HTTPException(
        status_code=400, detail="Maaloo Maqaa Guutuu kee galchi!"
    )
  conn = get_db()
  try:
    conn.execute(
        "INSERT INTO users (full_name, username, password, bio, avatar_url)"
        " VALUES (?, ?, ?, '', '')",
        (user.full_name.strip(), user.username.strip(), user.password),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ?", (user.username.strip(),)
    ).fetchone()
    return {"status": "success", "user": format_user(row)}
  except sqlite3.IntegrityError:
    raise HTTPException(
        status_code=400, detail="Maqaan fayyadamaa (Username) kun duraan qabameera!"
    )
  finally:
    conn.close()


@app.post("/login")
def login(user: UserAuth):
  conn = get_db()
  row = conn.execute(
      "SELECT * FROM users WHERE username = ? AND password = ?",
      (user.username.strip(), user.password),
  ).fetchone()
  conn.close()
  if not row:
    raise HTTPException(
        status_code=401,
        detail="Username ykn Jecha Icciitii (Password) dogoggora dha!",
    )
  return {"status": "success", "user": format_user(row)}


@app.get("/users")
def list_users():
  conn = get_db()
  rows = conn.execute(
      "SELECT full_name, username, bio, avatar_url FROM users ORDER BY id DESC"
  ).fetchall()
  conn.close()
  return [dict(r) for r in rows]


@app.get("/profile/{username}")
def get_profile(username: str):
  conn = get_db()
  user = conn.execute(
      "SELECT * FROM users WHERE username = ?", (username,)
  ).fetchone()
  if not user:
    conn.close()
    raise HTTPException(status_code=404, detail="Fayyadamaan hin argamne!")
  post_count = conn.execute(
      "SELECT COUNT(*) AS cnt FROM posts WHERE username = ?", (username,)
  ).fetchone()["cnt"]
  conn.close()
  data = format_user(user)
  data["post_count"] = post_count
  return data


@app.post("/profile/update")
async def update_profile(
    username: str = Form(...),
    full_name: str = Form(...),
    bio: str = Form(""),
    avatar: UploadFile | None = File(None),
):
  if not full_name.strip():
    raise HTTPException(
        status_code=400, detail="Maqaan guutuu duwwaa ta'uu hin danda'u!"
    )
  conn = get_db()
  user = conn.execute(
      "SELECT * FROM users WHERE username = ?", (username,)
  ).fetchone()
  if not user:
    conn.close()
    raise HTTPException(status_code=404, detail="Fayyadamaan hin argamne!")

  avatar_url = user["avatar_url"] or ""
  if avatar and avatar.filename:
    avatar_url, _ = await save_upload_file(avatar)

  conn.execute(
      "UPDATE users SET full_name = ?, bio = ?, avatar_url = ? WHERE username"
      " = ?",
      (full_name.strip(), bio.strip(), avatar_url, username),
  )
  conn.execute(
      "UPDATE posts SET full_name = ? WHERE username = ?",
      (full_name.strip(), username),
  )
  conn.execute(
      "UPDATE comments SET full_name = ? WHERE username = ?",
      (full_name.strip(), username),
  )
  conn.execute(
      "UPDATE stories SET full_name = ? WHERE username = ?",
      (full_name.strip(), username),
  )
  conn.commit()
  updated = conn.execute(
      "SELECT * FROM users WHERE username = ?", (username,)
  ).fetchone()
  post_count = conn.execute(
      "SELECT COUNT(*) AS cnt FROM posts WHERE username = ?", (username,)
  ).fetchone()["cnt"]
  conn.close()

  result = format_user(updated)
  result["post_count"] = post_count
  return {"status": "success", "user": result}


@app.get("/stories")
def get_stories():
  conn = get_db()
  rows = conn.execute(
      "SELECT * FROM stories ORDER BY id DESC LIMIT 20"
  ).fetchall()
  conn.close()
  return [dict(r) for r in rows]


@app.post("/stories")
async def create_story(
    username: str = Form(...),
    full_name: str = Form(...),
    caption: str = Form(""),
    file: UploadFile | None = File(None),
):
  media_url = ""
  if file and file.filename:
    media_url, _ = await save_upload_file(file)
  if not media_url and not caption.strip():
    raise HTTPException(
        status_code=400, detail="Suuraa filadhu ykn jecha seenaa barreessi!"
    )
  now = datetime.now().strftime("%H:%M")
  conn = get_db()
  conn.execute(
      "INSERT INTO stories (username, full_name, caption, media_url,"
      " created_at) VALUES (?, ?, ?, ?, ?)",
      (username, full_name, caption.strip(), media_url, now),
  )
  conn.commit()
  conn.close()
  return {"status": "success"}


@app.get("/posts")
def get_posts():
  conn = get_db()
  users_map = {
      r["username"]: (r["avatar_url"] or "")
      for r in conn.execute("SELECT username, avatar_url FROM users").fetchall()
  }
  posts = [
      dict(r)
      for r in conn.execute("SELECT * FROM posts ORDER BY id DESC").fetchall()
  ]
  for p in posts:
    p["author_avatar"] = users_map.get(p["username"], "")
    p["comments"] = [
        dict(c)
        for c in conn.execute(
            "SELECT * FROM comments WHERE post_id = ? ORDER BY id ASC",
            (p["id"],),
        ).fetchall()
    ]
  conn.close()
  return posts


@app.post("/posts")
async def create_post(
    username: str = Form(...),
    full_name: str = Form(...),
    content: str = Form(""),
    file: UploadFile | None = File(None),
):
  media_url = ""
  media_type = ""
  if file and file.filename:
    media_url, media_type = await save_upload_file(file)
  if not content.strip() and not media_url:
    raise HTTPException(
        status_code=400,
        detail="Maaloo yaada barreessi ykn suuraa/viidiyoo filadhu!",
    )
  now = datetime.now().strftime("%Y-%m-%d %H:%M")
  conn = get_db()
  conn.execute(
      "INSERT INTO posts (username, full_name, content, media_url, media_type,"
      " created_at) VALUES (?, ?, ?, ?, ?, ?)",
      (username, full_name, content.strip(), media_url, media_type, now),
  )
  conn.commit()
  conn.close()
  return {"status": "success"}


@app.delete("/posts/{post_id}")
def delete_post(post_id: int, username: str):
  conn = get_db()
  post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
  if not post:
    conn.close()
    raise HTTPException(status_code=404, detail="Maxxansi kun hin argamne!")
  if post["username"] != username:
    conn.close()
    raise HTTPException(
        status_code=403, detail="Maxxansa nama biraa haquu hin dandeessu!"
    )
  conn.execute("DELETE FROM comments WHERE post_id = ?", (post_id,))
  conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
  conn.commit()
  conn.close()
  return {"status": "deleted"}


@app.post("/posts/{post_id}/like")
def like_post(post_id: int):
  conn = get_db()
  conn.execute("UPDATE posts SET likes = likes + 1 WHERE id = ?", (post_id,))
  conn.commit()
  conn.close()
  return {"status": "liked"}


@app.post("/posts/{post_id}/comments")
def add_comment(post_id: int, comment: CommentCreate):
  if not comment.comment_text.strip():
    raise HTTPException(status_code=400, detail="Yaadni duwwaa ta'uu hin danda'u!")
  now = datetime.now().strftime("%Y-%m-%d %H:%M")
  conn = get_db()
  conn.execute(
      "INSERT INTO comments (post_id, username, full_name, comment_text,"
      " created_at) VALUES (?, ?, ?, ?, ?)",
      (
          post_id,
          comment.username,
          comment.full_name,
          comment.comment_text.strip(),
          now,
      ),
  )
  conn.commit()
  conn.close()
  return {"status": "success"}


@app.get("/messages")
def get_messages():
  conn = get_db()
  rows = conn.execute(
      "SELECT * FROM messages ORDER BY id ASC LIMIT 50"
  ).fetchall()
  conn.close()
  return [dict(r) for r in rows]


active_connections = []


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
  await websocket.accept()
  active_connections.append(websocket)
  try:
    while True:
      data = await websocket.receive_text()
      msg = json.loads(data)
      now = datetime.now().strftime("%H:%M")
      conn = get_db()
      conn.execute(
          "INSERT INTO messages (sender, text, sent_at) VALUES (?, ?, ?)",
          (msg["sender"], msg["text"], now),
      )
      conn.commit()
      conn.close()
      out = json.dumps({
          "sender": msg["sender"],
          "text": msg["text"],
          "sent_at": now,
      })
      for connection in active_connections:
        await connection.send_text(out)
  except WebSocketDisconnect:
    active_connections.remove(websocket)
from fastapi.responses import FileResponse

@app.get("/")
def serve_ui():
    return FileResponse(r"C:\Users\Nanbon\SM_app\index.html")
