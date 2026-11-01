from pathlib import Path
import os, sqlite3, hashlib, hmac, secrets, json, asyncio
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, Form, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from passlib.context import CryptContext

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "collabspace.db"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(title="CollabSpace", description="Совместный редактор документов")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "change-this-secret-key-for-local-study-project"), same_site="lax")
app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "app" / "templates")

class RoomManager:
    def __init__(self):
        self.rooms: dict[int, set[WebSocket]] = {}
        self.lock = asyncio.Lock()

    async def connect(self, doc_id: int, ws: WebSocket):
        await ws.accept()
        async with self.lock:
            self.rooms.setdefault(doc_id, set()).add(ws)

    async def disconnect(self, doc_id: int, ws: WebSocket):
        async with self.lock:
            self.rooms.get(doc_id, set()).discard(ws)
            if not self.rooms.get(doc_id):
                self.rooms.pop(doc_id, None)

    async def broadcast(self, doc_id: int, message: dict, sender: WebSocket):
        async with self.lock:
            peers = list(self.rooms.get(doc_id, set()))
        for peer in peers:
            if peer is not sender:
                try:
                    await peer.send_json(message)
                except Exception:
                    await self.disconnect(doc_id, peer)

rooms = RoomManager()

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL DEFAULT 'Новый документ',
            content TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS document_members (
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            PRIMARY KEY(document_id, user_id)
        );
        """)

@app.on_event("startup")
def startup():
    init_db()

def current_user(request: Request):
    uid = request.session.get("user_id")
    if not uid:
        return None
    with db() as conn:
        row = conn.execute("SELECT id, username, email, created_at FROM users WHERE id=?", (uid,)).fetchone()
        return dict(row) if row else None

def get_document(doc_id: int):
    with db() as conn:
        return conn.execute("""
            SELECT d.*, u.username AS owner_name FROM documents d
            JOIN users u ON u.id=d.owner_id WHERE d.id=?
        """, (doc_id,)).fetchone()

def can_access(doc_id: int, user_id: int):
    with db() as conn:
        return conn.execute("""
            SELECT 1 FROM documents d
            LEFT JOIN document_members m ON m.document_id=d.id
            WHERE d.id=? AND (d.owner_id=? OR m.user_id=?) LIMIT 1
        """, (doc_id, user_id, user_id)).fetchone() is not None

def page(request: Request, template: str, **context):
    user = current_user(request)
    return templates.TemplateResponse(request=request, name=template, context={"request": request, "user": user, **context})

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return page(request, "index.html", active="home", title="Пишите вместе. Создавайте быстрее.")

@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    return page(request, "about.html", active="about", title="О проекте")

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    if current_user(request):
        return RedirectResponse("/dashboard", status_code=303)
    return page(request, "auth.html", active="register", mode="register", error=None)

@app.post("/register")
def register(request: Request, username: str = Form(...), email: str = Form(...), password: str = Form(...)):
    username, email = username.strip(), email.strip().lower()
    if len(username) < 3 or len(username) > 32:
        return page(request, "auth.html", active="register", mode="register", error="Имя должно содержать от 3 до 32 символов.")
    if len(password) < 8:
        return page(request, "auth.html", active="register", mode="register", error="Пароль должен содержать не менее 8 символов.")
    if "@" not in email or len(email) > 120:
        return page(request, "auth.html", active="register", mode="register", error="Введите корректный адрес электронной почты.")
    try:
        with db() as conn:
            cur = conn.execute("INSERT INTO users(username,email,password_hash,created_at) VALUES(?,?,?,?)",
                (username, email, pwd_context.hash(password), datetime.now().isoformat(timespec="seconds")))
            user_id = cur.lastrowid
            conn.execute("INSERT INTO documents(owner_id,title,content,updated_at) VALUES(?,?,?,?)",
                (user_id, "Мой первый документ", "Добро пожаловать в CollabSpace! Здесь можно начать писать свои идеи.", datetime.now().isoformat(timespec="seconds")))
        request.session["user_id"] = user_id
        return RedirectResponse("/dashboard", status_code=303)
    except sqlite3.IntegrityError:
        return page(request, "auth.html", active="register", mode="register", error="Такое имя пользователя или email уже зарегистрированы.")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if current_user(request):
        return RedirectResponse("/dashboard", status_code=303)
    return page(request, "auth.html", active="login", mode="login", error=None)

@app.post("/login")
def login(request: Request, identity: str = Form(...), password: str = Form(...)):
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE lower(username)=lower(?) OR lower(email)=lower(?)", (identity.strip(), identity.strip())).fetchone()
    if not user or not pwd_context.verify(password, user["password_hash"]):
        return page(request, "auth.html", active="login", mode="login", error="Неверный логин или пароль.")
    request.session["user_id"] = user["id"]
    return RedirectResponse("/dashboard", status_code=303)

@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = current_user(request)
    if not user: return RedirectResponse("/login", status_code=303)
    with db() as conn:
        docs = conn.execute("""
            SELECT d.*, u.username AS owner_name FROM documents d
            JOIN users u ON u.id=d.owner_id
            WHERE d.owner_id=? OR d.id IN (SELECT document_id FROM document_members WHERE user_id=?)
            ORDER BY d.updated_at DESC
        """, (user["id"], user["id"])).fetchall()
    return page(request, "dashboard.html", active="dashboard", documents=[dict(x) for x in docs])

@app.post("/documents")
def create_document(request: Request, title: str = Form("Новый документ")):
    user = current_user(request)
    if not user: return RedirectResponse("/login", status_code=303)
    title = title.strip()[:100] or "Новый документ"
    with db() as conn:
        cur = conn.execute("INSERT INTO documents(owner_id,title,content,updated_at) VALUES(?,?,?,?)",
            (user["id"], title, "", datetime.now().isoformat(timespec="seconds")))
        doc_id = cur.lastrowid
    return RedirectResponse(f"/documents/{doc_id}", status_code=303)

@app.get("/documents/{doc_id}", response_class=HTMLResponse)
def editor(request: Request, doc_id: int):
    user = current_user(request)
    if not user: return RedirectResponse("/login", status_code=303)
    doc = get_document(doc_id)
    if not doc or not can_access(doc_id, user["id"]):
        raise HTTPException(status_code=404, detail="Документ не найден")
    return page(request, "editor.html", active="dashboard", document=dict(doc))

@app.get("/api/documents/{doc_id}")
def document_data(request: Request, doc_id: int):
    user = current_user(request)
    if not user: raise HTTPException(401, "Требуется вход")
    doc = get_document(doc_id)
    if not doc or not can_access(doc_id, user["id"]): raise HTTPException(404, "Документ не найден")
    return {"id": doc["id"], "title": doc["title"], "content": doc["content"], "updated_at": doc["updated_at"]}

@app.post("/api/documents/{doc_id}/save")
async def save_document(request: Request, doc_id: int):
    user = current_user(request)
    if not user: raise HTTPException(401, "Требуется вход")
    if not can_access(doc_id, user["id"]): raise HTTPException(404, "Документ не найден")
    data = await request.json()
    content = str(data.get("content", ""))[:500000]
    title = str(data.get("title", "Новый документ")).strip()[:100] or "Новый документ"
    now = datetime.now().isoformat(timespec="seconds")
    with db() as conn:
        conn.execute("UPDATE documents SET content=?, title=?, updated_at=? WHERE id=?", (content, title, now, doc_id))
    await rooms.broadcast(doc_id, {"type": "content", "content": content, "title": title, "updated_at": now, "by": user["username"]}, None)
    return {"ok": True, "updated_at": now}

@app.post("/api/documents/{doc_id}/share")
def share_document(request: Request, doc_id: int, username: str = Form(...)):
    user = current_user(request)
    if not user: return RedirectResponse("/login", status_code=303)
    doc = get_document(doc_id)
    if not doc or doc["owner_id"] != user["id"]:
        raise HTTPException(403, "Только владелец может приглашать участников")
    with db() as conn:
        target = conn.execute("SELECT id FROM users WHERE lower(username)=lower(?)", (username.strip(),)).fetchone()
        if not target: return RedirectResponse(f"/documents/{doc_id}?share=notfound", status_code=303)
        conn.execute("INSERT OR IGNORE INTO document_members(document_id,user_id) VALUES(?,?)", (doc_id, target["id"]))
    return RedirectResponse(f"/documents/{doc_id}?share=ok", status_code=303)

@app.post("/documents/{doc_id}/delete")
def delete_document(request: Request, doc_id: int):
    user = current_user(request)
    if not user: return RedirectResponse("/login", status_code=303)
    with db() as conn:
        conn.execute("DELETE FROM documents WHERE id=? AND owner_id=?", (doc_id, user["id"]))
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request):
    user = current_user(request)
    if not user: return RedirectResponse("/login", status_code=303)
    with db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM documents WHERE owner_id=?", (user["id"],)).fetchone()[0]
    return page(request, "profile.html", active="profile", document_count=count)

@app.websocket("/ws/documents/{doc_id}")
async def websocket_document(ws: WebSocket, doc_id: int):
    # SessionMiddleware verifies the signed cookie and exposes the session on the WebSocket scope.
    session = ws.scope.get("session", {})
    user_id = session.get("user_id")
    if not user_id or not can_access(doc_id, int(user_id)):
        await ws.close(code=1008)
        return
    await rooms.connect(doc_id, ws)
    try:
        while True:
            message = await ws.receive_json()
            if message.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        await rooms.disconnect(doc_id, ws)
