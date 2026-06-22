import io
import os
import re
import gc
import json
import time
import math
import hmac
import hashlib
import asyncio
import logging
import aiofiles
import urllib.parse
from collections import OrderedDict
from urllib.parse import quote
from bson.objectid import ObjectId
from aiohttp import web

from hydrogram import Client, raw
from hydrogram.session import Session, Auth
from hydrogram.errors import AuthBytesInvalid, FloodWait
from hydrogram.file_id import FileId, FileType
from hydrogram.types import Message

from info import URL, BIN_CHANNEL, ADMINS, BOT_TOKEN, MAX_WEB_RESULTS, MAX_THUMB_CACHE, IS_PREMIUM, USE_CAPTION_FILTER
from utils import temp, get_size, is_rate_limited, is_premium, get_readable_time
from database.ia_filterdb import COLLECTIONS, get_search_results, get_actor_search_results, actors, db as filter_db
from database.users_chats_db import db, web_db, get_local_now

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()

# ─────────────────────────────────────────────────────────
# 📸 TRUE LRU THUMBNAIL CACHE & SELF-HEALING ENGINE
# ─────────────────────────────────────────────────────────
MAX_CACHE = MAX_THUMB_CACHE
thumb_semaphore = asyncio.Semaphore(15)
thumb_cache = OrderedDict()
thumb_locks = {}
PREFETCH_CACHE = OrderedDict()
TRENDING_CACHE = OrderedDict()
TRENDING_CACHE_TTL = 300

def _build_strict_query(q: str) -> str:
    clean = q.replace('"', '').replace("'", "").strip()
    return " ".join(f'"{w}"' for w in clean.split())

async def chunk_size(length):
    return 2 ** max(min(math.ceil(math.log2(length / 1024)), 10), 2) * 1024

async def offset_fix(offset, chunksize):
    offset -= offset % chunksize
    return offset

async def _get_or_fetch_thumb(fid, col_name="primary", is_retry=False):
    cache_key = f"{col_name}:{fid}"
    if is_retry and thumb_cache.get(cache_key) == "NO_THUMB":
        thumb_cache.pop(cache_key, None)
    if cache_key in thumb_cache:
        thumb_cache.move_to_end(cache_key)
        val = thumb_cache[cache_key]
        return None if val == "NO_THUMB" else val

    lock = thumb_locks.setdefault(cache_key, asyncio.Lock())
    try:
        async with lock:
            if cache_key in thumb_cache:
                thumb_cache.move_to_end(cache_key)
                val = thumb_cache[cache_key]
                return None if val == "NO_THUMB" else val

            async def _fetch():
                if len(thumb_cache) >= MAX_CACHE:
                    thumb_cache.popitem(last=False)
                col = COLLECTIONS.get(col_name, COLLECTIONS["primary"])
                existing = await col.find_one({"_id": fid}, {"thumb_url": 1})
                if existing and existing.get("thumb_url", "").startswith("TG_ID:"):
                    try:
                        file_data = await temp.BOT.download_media(existing["thumb_url"].replace("TG_ID:", ""), in_memory=True)
                        if file_data:
                            img_bytes = file_data.getvalue()
                            thumb_cache[cache_key] = img_bytes
                            return img_bytes
                    except Exception:
                        pass
                for _ in range(5):
                    try:
                        msg = await temp.BOT.send_cached_media(chat_id=BIN_CHANNEL, file_id=fid)
                        t_id = None
                        if msg.video and msg.video.thumbs: t_id = msg.video.thumbs[0].file_id
                        elif msg.document and msg.document.thumbs: t_id = msg.document.thumbs[0].file_id
                        if t_id:
                            file_data = await temp.BOT.download_media(t_id, in_memory=True)
                            if file_data:
                                img_bytes = file_data.getvalue()
                                thumb_cache[cache_key] = img_bytes
                                await col.update_one({"_id": fid}, {"$set": {"thumb_url": f"TG_ID:{t_id}"}})
                                await db.add_to_delete_queue(BIN_CHANNEL, msg.id, 5)
                                return img_bytes
                        else:
                            thumb_cache[cache_key] = "NO_THUMB"
                            await db.add_to_delete_queue(BIN_CHANNEL, msg.id, 5)
                            return None
                    except Exception as e:
                        if "FLOOD_WAIT" in str(e):
                            await asyncio.sleep(25)
                            continue
                        await asyncio.sleep(2)
                return None
            async with thumb_semaphore: return await _fetch()
    finally:
        thumb_locks.pop(cache_key, None)

class TGCustomYield:
    @staticmethod
    async def generate_file_properties(msg: Message):
        media = msg.document or msg.video or msg.audio
        file_id_obj = FileId.decode(media.file_id)
        setattr(file_id_obj, "file_size", getattr(media, "file_size", 0))
        setattr(file_id_obj, "mime_type", getattr(media, "mime_type", ""))
        setattr(file_id_obj, "file_name", getattr(media, "file_name", ""))
        return file_id_obj

    async def yield_file(self, file_id_obj: FileId, offset: int, first_part_cut: int, last_part_cut: int, part_count: int, chunk_size: int):
        client = temp.BOT
        media_session = client.media_sessions.get(file_id_obj.dc_id, None)
        if media_session is None:
            is_test = await client.storage.test_mode()
            if file_id_obj.dc_id != await client.storage.dc_id():
                media_session = Session(client, file_id_obj.dc_id, await Auth(client, file_id_obj.dc_id, is_test).create(), is_test, is_media=True)
                await media_session.start()
                for _ in range(3):
                    exp = await client.invoke(raw.functions.auth.ExportAuthorization(dc_id=file_id_obj.dc_id))
                    try: await media_session.send(raw.functions.auth.ImportAuthorization(id=exp.id, bytes=exp.bytes))
                    except AuthBytesInvalid: continue
                    else: break
            else:
                media_session = Session(client, file_id_obj.dc_id, await client.storage.auth_key(), is_test, is_media=True)
                await media_session.start()
            client.media_sessions[file_id_obj.dc_id] = media_session

        current_part = 1
        loc = raw.types.InputPhotoFileLocation(id=file_id_obj.media_id, access_hash=file_id_obj.access_hash, file_reference=file_id_obj.file_reference, thumb_size=file_id_obj.thumbnail_size) if file_id_obj.file_type == FileType.PHOTO else raw.types.InputDocumentFileLocation(id=file_id_obj.media_id, access_hash=file_id_obj.access_hash, file_reference=file_id_obj.file_reference, thumb_size=file_id_obj.thumbnail_size)
        r = await media_session.send(raw.functions.upload.GetFile(location=loc, offset=offset, limit=chunk_size))
        if isinstance(r, raw.types.upload.File):
            while current_part <= part_count:
                chunk = r.bytes
                if not chunk: break
                offset += chunk_size
                if part_count == 1:
                    yield chunk[first_part_cut:last_part_cut]
                    break
                if current_part == 1: yield chunk[first_part_cut:]
                if 1 < current_part <= part_count: yield chunk
                r = await media_session.send(raw.functions.upload.GetFile(location=loc, offset=offset, limit=chunk_size))
                current_part += 1

# ─────────────────────────────────────────────────────────
# 🔒 SECURE AUTHENTICATION ENGINE (Mini-App & Cookies)
# ─────────────────────────────────────────────────────────
def verify_telegram_init_data(init_data: str) -> dict | None:
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash: return None
        check_str = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        if hmac.compare_digest(hmac.new(secret, check_str.encode(), hashlib.sha256).hexdigest(), received_hash):
            return json.loads(parsed.get("user", "{}"))
    except Exception: pass
    return None

async def get_auth(req):
    init_data = req.headers.get("X-Telegram-Init-Data", "").strip()
    if init_data:
        user = verify_telegram_init_data(init_data)
        if user and int(user.get("id", 0)):
            tg_id = int(user["id"])
            if tg_id in ADMINS: return "admin", tg_id
            if await is_premium(tg_id) or not IS_PREMIUM: return "user", tg_id
        return None, None
    s_user = req.cookies.get("user_session")
    if s_user and hasattr(temp, "USER_SESSIONS") and s_user in temp.USER_SESSIONS:
        session = temp.USER_SESSIONS[s_user]
        if session.get("expiry", 0) > time.time():
            tg_id = session["tg_id"]
            if tg_id in ADMINS: return "admin", tg_id
            if await is_premium(tg_id) or not IS_PREMIUM: return "user", tg_id
    return None, None

# ─────────────────────────────────────────────────────────
# 🎨 MASTER VIEW UI ENGINE & SCRIPTS (Pre-compiled Asset Matrices)
# ─────────────────────────────────────────────────────────
CSS = "*{box-sizing:border-box;margin:0;padding:0}:root{--bg:#0a0a0c;--bg2:#111116;--bg3:#1d1d26;--bg4:#2a2a38;--accent:#e50914;--accent-hover:#b30710;--text:#ffffff;--muted:#a0a0b0;--border:#262636;--card:#14141f;--sidebar-w:260px}.light{--bg:#f4f5f7;--bg2:#ffffff;--bg3:#eef0f4;--bg4:#dbdee6;--text:#0a0a0c;--muted:#62627a;--border:#d2d5df;--card:#ffffff}body{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;overflow-x:hidden;transition:.2s}.topbar{background:var(--bg2);padding:0 4%;display:flex;align-items:center;height:68px;position:sticky;top:0;z-index:100;gap:15px;box-shadow:0 4px 20px rgba(0,0,0,0.4);border-bottom:1px solid var(--border)}.logo{font-size:18px;font-weight:900;letter-spacing:1px;color:var(--accent);display:flex;align-items:center;gap:8px;text-decoration:none;flex:1}.nf-icon{background:var(--accent);color:#fff;padding:2px 7px;border-radius:3px;font-size:18px;line-height:1}.theme-btn{margin-left:auto;background:0 0;border:1px solid var(--border);border-radius:4px;padding:6px 12px;font-size:12px;font-weight:700;color:var(--text);cursor:pointer}.theme-btn:hover{background:var(--bg3)}.sidebar{position:fixed;top:0;left:0;height:100%;width:var(--sidebar-w);background:var(--bg2);border-right:1px solid var(--border);z-index:160;display:flex;flex-direction:column;transform:translateX(-100%);transition:.3s}.sidebar.open{transform:translateX(0)}.sb-header{padding:20px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between}.sb-logo{font-size:14px;font-weight:900;color:var(--accent);display:flex;align-items:center;gap:8px}.sb-close{background:0 0;border:0;color:var(--muted);font-size:22px;cursor:pointer}.sb-nav{padding:15px 10px;flex:1}.sb-link{display:flex;padding:12px 15px;border-radius:4px;text-decoration:none;color:var(--muted);font-size:15px;font-weight:500;margin-bottom:4px}.sb-link.active{background:var(--accent);color:#fff}.sb-footer{padding:15px 10px;border-top:1px solid var(--border)}.sb-logout{display:block;padding:12px;border-radius:4px;text-align:center;text-decoration:none;color:var(--text);font-weight:700;border:1px solid var(--border)}.main{padding:20px 4% 40px;max-width:1400px;margin:0 auto}.search-zone{display:flex;flex-direction:column;gap:12px;margin-bottom:20px}.search-wrap{display:flex;background:var(--bg3);border:1.5px solid var(--border);border-radius:12px;padding:0 12px;align-items:center;height:42px}.search-input{flex:1;background:0 0;border:none;outline:none;color:var(--text);font-size:14px;font-weight:600}.search-btn{background:var(--accent);color:#fff;border:none;border-radius:12px;padding:0 24px;height:42px;font-size:14px;font-weight:700;cursor:pointer}.res-grid{display:grid;grid-template-columns:1fr;gap:12px}@media(min-width:600px){.res-grid{grid-template-columns:repeat(3,1fr);gap:16px}}.file-card{background:var(--card);border-radius:8px;overflow:hidden;border:1px solid var(--border);cursor:pointer;transition:transform .2s}.file-card:hover{transform:translateY(-4px);border-color:rgba(229,9,20,.4)}.poster-box{position:relative;padding-top:56.25%;background:var(--bg4);overflow:hidden}.fc-poster{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .2s}.fc-poster.loaded{opacity:1}.fc-body{padding:12px}.fc-name{font-size:13px;font-weight:700;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.poster-top{position:absolute;top:8px;left:8px;right:8px;display:flex;gap:5px}.type-chip,.size-chip{background:rgba(0,0,0,.7);padding:3px 6px;border-radius:4px;font-size:9px;font-weight:800;border:1px solid rgba(255,255,255,.1)}.source-pill{margin-left:auto;background:rgba(20,83,45,.8);color:#4ade80;border:1px solid #22c55e;padding:2px 6px;border-radius:10px;font-size:9px;font-weight:700}.pagination{display:none;justify-content:center;align-items:center;gap:15px;margin-top:20px}.pg-btn{background:var(--bg4);color:var(--text);border:1px solid var(--border);padding:8px 18px;border-radius:6px;font-size:12px;font-weight:700;cursor:pointer}.pg-btn:disabled{opacity:.4;cursor:not-allowed}.login-bg{background:#000;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}.login-card{background:var(--card);border:1px solid var(--border);padding:40px;border-radius:12px;width:100%;max-width:420px}.login-card h2{font-size:26px;margin-bottom:20px;text-align:center}.login-card input,.login-card select,.login-card textarea{width:100%;background:var(--bg);border:1px solid var(--border);padding:12px;color:var(--text);margin-bottom:12px;border-radius:6px;outline:none;font-family:inherit}.submit-btn{width:100%;background:var(--accent);color:#fff;border:none;padding:14px;font-weight:700;border-radius:6px;cursor:pointer}.err-box{background:#e87c03;color:#fff;padding:10px;border-radius:4px;margin-bottom:12px;font-size:13px;text-align:center}.success-box{background:#28a745;color:#fff;padding:10px;border-radius:4px;margin-bottom:12px;font-size:13px;text-align:center}.dir-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}@media(min-width:768px){.dir-grid{grid-template-columns:repeat(5,1fr);gap:20px}}.act-card{background:var(--card);border:1px solid var(--border);border-radius:10px;overflow:hidden;cursor:pointer;transition:.2s}.act-card:hover{transform:translateY(-5px);border-color:var(--accent)}.actor-tab-bar{display:flex;gap:10px;border-bottom:2px solid var(--border);margin-bottom:20px}.actor-tab{background:0 0;border:none;color:var(--muted);padding:10px 15px;font-weight:700;cursor:pointer}.actor-tab.active{color:var(--text);border-bottom:2px solid var(--accent)}.actor-panel{display:none}.actor-panel.active{display:block}"
JS = "(function(){if(localStorage.getItem('theme')==='light')document.documentElement.classList.add('light')})();function toggleThemeFixed(){var l=document.documentElement.classList.toggle('light');localStorage.setItem('theme',l?'light':'dark');}var curQ='',curOff=0,nextOff='',curCol='all',curPage=1;var LIMIT_VAL = __LIMIT_PLACEHOLDER__;".replace("__LIMIT_PLACEHOLDER__", str(MAX_WEB_RESULTS))

def build_page(title, body, cls="", active_tab="", role=None):
    nav = ""
    if role:
        links = f'<a href="/dashboard" class="sb-link {"active" if active_tab=="dash" else ""}">Home</a><a href="/actors" class="sb-link {"active" if active_tab=="actors" else ""}">🎭 Actors</a>'
        nav = f'<div class="topbar"><a class="logo" href="/dashboard"><span class="nf-icon">F</span> FAST FINDER</a><div style="display:flex;gap:15px;">{links}<button class="theme-btn" onclick="toggleThemeFixed()">Theme</button></div></div>'
    else:
        nav = '<div class="topbar"><a class="logo" href="/"><span class="nf-icon">F</span> FAST FINDER</a><button class="theme-btn" onclick="toggleThemeFixed()">Theme</button></div>'
    return web.Response(text=f'<!DOCTYPE html><html><head><title>{title}</title><meta name="viewport" content="width=device-width,initial-scale=1"><link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700;900&display=swap" rel="stylesheet"><style>{CSS}</style><script>{JS}</script></head><body class="{cls}">{nav}{body}</body></html>', content_type='text/html', charset='utf-8')

def form_wrapper(title, content, err="", msg=""):
    e = f'<div class="err-box">{err}</div>' if err else ""
    m = f'<div class="success-box">{msg}</div>' if msg else ""
    return f'<div class="login-wrap"><div class="login-card"><h2>{title}</h2>{e}{m}{content}</div></div>'

# ─────────────────────────────────────────────────────────
# 🌐 ROUTE CONTROLLERS (Unified Dashboard, Search & Actor Engine)
# ─────────────────────────────────────────────────────────

@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.Response(text='<h1 align="center"><b>🚀 Ultra-Smart Unified Web Server Active</b></h1>', content_type='text/html')

@routes.get("/health")
async def koyeb_health_check(request):
    return web.json_response({"status": "alive", "engine": "unified_v3"})

@routes.get('/login')
async def login_user(req):
    content = '<form action="/api/login" method="post"><input type="email" name="email" placeholder="Email Address" required><input type="password" name="password" placeholder="Password" required><button class="submit-btn" type="submit">Sign In</button></form>'
    return build_page("Sign In", form_wrapper("Sign In", content, req.query.get('err',''), req.query.get('msg','')), "login-bg")

@routes.post('/api/login')
async def api_login_user(req):
    d = await req.post()
    user = await web_db.verify_login(d.get('email'), d.get('password'))
    if user:
        await web_db.col.update_one({"tg_id": user['tg_id']}, {"$set": {"last_login": get_local_now()}})
        s = str(uuid.uuid4())
        if not hasattr(temp, 'USER_SESSIONS'): temp.USER_SESSIONS = {}
        temp.USER_SESSIONS[s] = {'tg_id': user['tg_id'], 'expiry': time.time() + 604800}
        res = web.HTTPFound('/dashboard')
        res.set_cookie('user_session', s, max_age=604800)
        return res
    return web.HTTPFound('/login?err=Invalid Credentials')

@routes.get('/logout')
async def logout(req):
    s = req.cookies.get('user_session')
    if s and hasattr(temp, 'USER_SESSIONS') and s in temp.USER_SESSIONS: del temp.USER_SESSIONS[s]
    res = web.HTTPFound('/login')
    res.del_cookie('user_session')
    return res

@routes.get('/dashboard')
async def dash(req):
    role, tg_id = await get_auth(req)
    if not role: return web.HTTPFound('/login')
    
    body = f"""
    <div class="main">
        <div class="search-zone">
            <div class="search-wrap">
                <input class="search-input" id="q" placeholder="Search movies, documents, series...">
            </div>
            <button class="search-btn" onclick="doSearch(0)">Search Matrix</button>
        </div>
        <div id="results" class="res-grid"></div>
        <div class="pagination" id="pageBox">
            <button class="pg-btn" id="pBtn" onclick="prev()" disabled>Previous</button>
            <span class="pg-info" id="pgInfo">Page 1</span>
            <button class="pg-btn" id="nBtn" onclick="next()">Next</button>
        </div>
    </div>
    <script>
    async function doSearch(o){{
        var q=document.getElementById('q').value.trim(); if(!q) return;
        curQ=q; curOff=o; if(o===0) curPage=1;
        var rDiv=document.getElementById('results'); rDiv.innerHTML='<div style="grid-column:1/-1;text-align:center;padding:40px;">Searching Cross-Network Database...</div>';
        try{{
            var r=await fetch('/api/search?q='+encodeURIComponent(q)+'&offset='+o);
            var d=await r.json();
            if(!d.results.length){{ rDiv.innerHTML='<div style="grid-column:1/-1;text-align:center;padding:40px;">No Assets Found.</div>'; return; }}
            var h='';
            d.results.forEach(f=>{{
                h+='<div class="file-card" onclick="window.open(\''+f.watch+'\',\'_blank\')"><div class="poster-box"><img src="'+f.tg_thumb+'" class="fc-poster" onload="this.classList.add(\'loaded\')" loading="lazy"><div class="poster-top"><span class="type-chip">'+f.type+'</span><span class="size-chip">'+f.size+'</span></div></div><div class="fc-body"><div class="fc-name">'+f.name+'</div></div></div>';
            }});
            rDiv.innerHTML=h;
            nextOff=d.next_offset; document.getElementById('pageBox').style.display='flex';
            document.getElementById('pBtn').disabled=(o===0); document.getElementById('nBtn').disabled=!nextOff;
            document.getElementById('pgInfo').textContent='Page '+curPage;
        }}catch(e){{rDiv.innerHTML='Search Timeout Exception.';}}
    }}
    function next(){{if(nextOff){{curPage++;doSearch(nextOff);}}}}
    function prev(){{if(curPage>1){{curPage--;doSearch(Math.max(0,curOff-LIMIT_VAL));}}}}
    </script>
    """
    return build_page("Dashboard - Engine Active", body, "", "dash", role)

@routes.get("/api/search")
async def api_search(req):
    role, tg_id = await get_auth(req)
    if not role: return web.json_response({"error": "Unauthorized"}, status=403)
    if is_rate_limited(tg_id, "web_search", 1): return web.json_response({"error": "Rate limited"}, status=429)

    q, off = req.query.get("q", "").strip(), req.query.get("offset", "0")
    if not q: return web.json_response({"results": [], "next_offset": ""})
    try: off = max(0, int(off))
    except: off = 0

    lim = MAX_WEB_RESULTS
    strict_q = _build_strict_query(q)
    all_m, next_offset, _, _ = await get_search_results(strict_q, lim, offset=off, collection_type="all", bypass_count=True)

    results_list = [{
        "file_id": d["_id"], "name": d.get("file_name", "Unknown"), "size": get_size(d.get("file_size", 0)),
        "type": d.get("file_type", "document").upper(), "tg_thumb": f"/api/thumb?file_id={d['_id']}&col={d.get('source_col', 'primary')}&v={int(time.time()/3600)}",
        "watch": f"/setup_stream?file_id={d.get('file_ref') or d['_id']}&mode=watch"
    } for d in all_m]

    return web.json_response({"results": results_list, "next_offset": next_offset, "is_admin": role == "admin"})

@routes.get("/api/thumb")
async def get_telegram_thumb(req):
    fid, col = req.query.get("file_id"), req.query.get("col", "primary").lower()
    is_retry = req.query.get("retry", "false").lower() == "true"
    if not fid: return web.Response(status=400)

    res = await _get_or_fetch_thumb(fid, col_name=col, is_retry=is_retry)
    if res is None: return web.Response(status=404)
    return web.Response(body=res, content_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})

@routes.get("/setup_stream")
async def setup_stream(req):
    role, _ = await get_auth(req)
    if not role: return web.Response(text="Unauthorized", status=403)
    fid, mode = req.query.get("file_id"), req.query.get("mode", "watch")
    if not fid: return web.Response(text="Missing File target reference ID", status=400)
    try:
        msg = await temp.BOT.send_cached_media(chat_id=BIN_CHANNEL, file_id=fid)
        await db.add_to_delete_queue(BIN_CHANNEL, msg.id, 3600)
        if mode == "watch": await db.track_video_play()
        return web.HTTPFound(f"/{mode}/{msg.id}")
    except Exception as e: return web.Response(text=f"Tunnel Exception: {e}", status=500)

# ─────────────────────────────────────────────────────────
# 🎬 ULTRA-LIGHT MODULAR PLAYER FRAMEWORK
# ─────────────────────────────────────────────────────────
@routes.get("/watch/{message_id}")
async def watch_handler(request):
    try:
        m_id = int(request.match_info['message_id'])
        msg = await temp.BOT.get_messages(BIN_CHANNEL, m_id)
        if not msg or msg.empty: return web.Response(text="File Deleted from Storage Node.", status=404)

        props = await TGCustomYield.generate_file_properties(msg)
        mime = props.mime_type or 'video/mp4'
        if mime.split('/')[0].strip() != 'video': return web.Response(text="Unsupported Stream Type Matrix")

        src = f"{URL}download/{m_id}"
        async with aiofiles.open('web/template/watch.html', mode='r', encoding='utf-8') as r:
            html_template = await r.read()
            
        return web.Response(text=html_template.format(heading=props.file_name, file_name=props.file_name, src=src, mime_type=mime), content_type='text/html')
    except Exception as e: return web.Response(text=f"Watch Pipeline Fault: {e}", status=500)

@routes.get("/download/{message_id}")
async def download_handler(request):
    try:
        m_id = int(request.match_info['message_id'])
        msg = await temp.BOT.get_messages(BIN_CHANNEL, m_id)
        if not msg or msg.empty: return web.Response(text="File Block Missing.", status=404)

        props = await TGCustomYield.generate_file_properties(msg)
        media_obj = msg.document or msg.video or msg.audio
        f_size = props.file_size

        range_hdr = request.headers.get('Range', 0)
        if range_hdr:
            f_b, u_b = range_hdr.replace('bytes=', '').split('-')
            f_b = int(f_b)
            u_b = int(u_b) if u_b else f_size - 1
        else:
            f_b = request.http_range.start or 0
            u_b = request.http_range.stop or f_size - 1

        req_len = u_b - f_b + 1
        c_size = await chunk_size(req_len)
        offset = await offset_fix(f_b, c_size)
        
        body = TGCustomYield().yield_file(FileId.decode(media_obj.file_id), offset, f_b - offset, (u_b % c_size) + 1, math.ceil(req_len / c_size), c_size)
        return web.Response(status=206 if range_hdr else 200, body=body, headers={
            "Content-Type": props.mime_type or 'application/octet-stream',
            "Content-Range": f"bytes {f_b}-{u_b}/{f_size}",
            "Content-Disposition": f"attachment; filename=\"{props.file_name}\"; filename*=UTF-8''{quote(props.file_name)}",
            "Accept-Ranges": "bytes"
        })
    except Exception as e: return web.Response(text=f"Core Stream Drop: {e}", status=500)

# ─────────────────────────────────────────────────────────
# 🎭 ACTOR DIRECTORY INTERFACE MAPS (Consolidated Matrix)
# ─────────────────────────────────────────────────────────
@routes.get('/actors')
async def actors_directory_page(req):
    role, _ = await get_auth(req)
    if not role: return web.HTTPFound('/login')
    all_a = await actors.find({}).sort("created_at", -1).limit(20).to_list(length=20)
    
    items_html = ""
    for a in all_a:
        items_html += f'<div class="act-card" onclick="window.location.href=\'/actor/{str(a["_id"])}\'"><div style="position:relative;padding-top:135%;overflow:hidden;"><img src="/api/actor/photo?id={str(a["_id"])}" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;"></div><div style="padding:10px;text-align:center;font-weight:700;">{html.escape(a.get("name",""))}</div></div>'
    
    body = f'<div class="main"><div class="dir-grid">{items_html}</div></div>'
    return build_page("Directory Catalog", body, "", "actors", role)

@routes.get('/actor/{id}')
async def actor_profile_display(req):
    role, _ = await get_auth(req)
    if not role: return web.HTTPFound('/login')
    try:
        a_id = req.match_info['id']
        actor = await actors.find_one({"_id": ObjectId(a_id)})
        if not actor: return web.Response(text="Profile Missing", status=404)
    except: return web.Response(status=400)

    body = f"""
    <div class="main">
        <h1 style="margin-bottom:10px;">{html.escape(actor["name"])}</h1>
        <div class="actor-tab-bar"><button class="actor-tab active">🎬 Media Grid Feed</button></div>
        <div id="actor_video_results" class="res-grid"></div>
    </div>
    <script>
    async function loadActorMedia() {{
        var grid = document.getElementById('actor_video_results');
        try {{
            var r = await fetch('/api/actor/search?id={a_id}');
            var d = await r.json();
            var h = '';
            d.results.forEach(f => {{
                h += '<div class="file-card" onclick="window.open(\''+f.watch+'\',\'_blank\')"><div class="poster-box"><img src="'+f.tg_thumb+'" class="fc-poster" onload="this.classList.add(\'loaded\')"></div><div class="fc-body"><div class="fc-name">'+f.name+'</div></div></div>';
            }});
            grid.innerHTML = h || '<p>No linked properties inside catalog.</p>';
        }} catch(e) {{ grid.innerHTML = 'Sync Timeout Error.'; }}
    }}
    document.addEventListener("DOMContentLoaded", loadActorMedia);
    </script>
    """
    return build_page(f"{actor['name']} - Profile", body, "", "actors", role)

@routes.get('/api/actor/search')
async def api_actor_search_handler(req):
    role, _ = await get_auth(req)
    if not role: return web.json_response({"error": "Unauthorized"}, status=403)
    a_id = req.query.get("id")
    if not a_id: return web.json_response({"results": []})
    
    actor = await actors.find_one({"_id": ObjectId(a_id)})
    if not actor: return web.json_response({"results": []})
    
    all_m, next_offset = await get_actor_search_results(actor["name"], actor.get("tags", []), max_results=MAX_WEB_RESULTS, offset=0, collection_type="all")
    results = [{
        "file_id": d["_id"], "name": d.get("file_name", "Unknown File"), "size": get_size(d.get("file_size", 0)),
        "type": d.get("file_type", "document").upper(), "tg_thumb": f"/api/thumb?file_id={d['_id']}&col={d.get('source_col','primary')}",
        "watch": f"/setup_stream?file_id={d.get('file_ref') or d['_id']}&mode=watch"
    } for d in all_m]
    return web.json_response({"results": results, "next_offset": next_offset})

@routes.get('/api/actor/photo')
async def get_actor_photo(req):
    a_id = req.query.get("id")
    if not a_id: return web.Response(status=400)
    doc = await actors.find_one({"_id": ObjectId(a_id)})
    if not doc or not doc.get("photo_url","").startswith("TG_ID:"): return web.Response(status=404)
    
    f_data = await temp.BOT.download_media(doc["photo_url"].replace("TG_ID:", ""), in_memory=True)
    if not f_data: return web.Response(status=404)
    return web.Response(body=f_data.getvalue(), content_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000"})
