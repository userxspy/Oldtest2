import io
import os
import re
import gc
import json
import time
import math
import uuid
import asyncio
import logging
import aiofiles
from collections import OrderedDict
from urllib.parse import quote
from aiohttp import web

from hydrogram import Client, raw
from hydrogram.session import Session, Auth
from hydrogram.errors import AuthBytesInvalid
from hydrogram.file_id import FileId, FileType
from hydrogram.types import Message

# Dynamically importing variables directly from your info.py config
from info import URL, BIN_CHANNEL, ADMINS, MAX_WEB_RESULTS, MAX_THUMB_CACHE
from utils import temp, get_size
from database.ia_filterdb import Media, get_search_results, get_file_details

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()

# ─────────────────────────────────────────────────────────
# 📸 TRUE LRU THUMBNAIL CACHE ENGINE (Uses MAX_THUMB_CACHE)
# ─────────────────────────────────────────────────────────
MAX_CACHE = MAX_THUMB_CACHE
thumb_semaphore = asyncio.Semaphore(15)
thumb_cache = OrderedDict()
thumb_locks = {}

async def _get_or_fetch_thumb(fid, is_retry=False):
    cache_key = f"thumb:{fid}"
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
                
                # Querying your native single Media collection
                existing = await Media.find_one({"_id": fid}, {"thumb_url": 1})
                if existing and existing.get("thumb_url", "").startswith("TG_ID:"):
                    try:
                        file_data = await temp.BOT.download_media(existing["thumb_url"].replace("TG_ID:", ""), in_memory=True)
                        if file_data:
                            img_bytes = file_data.getvalue()
                            thumb_cache[cache_key] = img_bytes
                            return img_bytes
                    except Exception: pass

                # Self-healing on-the-fly thumbnail auto-refresher gateway
                for _ in range(3):
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
                                await Media.update_one({"_id": fid}, {"$set": {"thumb_url": f"TG_ID:{t_id}"}})
                                return img_bytes
                        else:
                            thumb_cache[cache_key] = "NO_THUMB"
                            return None
                    except Exception:
                        await asyncio.sleep(1)
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
        loc = raw.types.InputDocumentFileLocation(id=file_id_obj.media_id, access_hash=file_id_obj.access_hash, file_reference=file_id_obj.file_reference, thumb_size=file_id_obj.thumbnail_size)
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
# 🔒 COOKIE SESSIONS GATEWAY
# ─────────────────────────────────────────────────────────
async def get_auth(req):
    s_user = req.cookies.get("user_session")
    if s_user and hasattr(temp, "USER_SESSIONS") and s_user in temp.USER_SESSIONS:
        if temp.USER_SESSIONS[s_user].get("expiry", 0) > time.time():
            return "admin", temp.USER_SESSIONS[s_user]["tg_id"]
    return None, None

# ─────────────────────────────────────────────────────────
# 🎨 DYNAMIC VIEW WEB ASSET PORTALS
# ─────────────────────────────────────────────────────────
CSS_STACK = """
*{box-sizing:border-box;margin:0;padding:0}:root{--bg:#0a0a0c;--bg2:#111116;--bg3:#1d1d26;--accent:#e50914;--text:#ffffff;--muted:#a0a0b0;--border:#262636;--card:#14141f}body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;padding:20px}.topbar{background:var(--bg2);padding:15px 4%;display:flex;align-items:center;justify-content:between;border-bottom:1px solid var(--border);margin-bottom:20px;border-radius:8px}.logo{font-size:18px;font-weight:900;color:var(--accent);text-decoration:none}.search-zone{display:flex;gap:10px;margin-bottom:25px}.search-wrap{flex:1;background:var(--bg3);border:1.5px solid var(--border);border-radius:10px;padding:0 15px;display:flex;align-items:center;height:44px}.search-input{width:100%;background:transparent;border:none;outline:none;color:var(--text);font-size:14px;font-weight:600}.search-btn{background:var(--accent);color:#fff;border:none;border-radius:10px;padding:0 24px;height:44px;font-size:14px;font-weight:700;cursor:pointer}.res-grid{display:grid;grid-template-columns:1fr;gap:12px}@media(min-width:600px){.res-grid{grid-template-columns:repeat(3,1fr);gap:16px}}.file-card{background:var(--card);border-radius:8px;overflow:hidden;border:1px solid var(--border);cursor:pointer;transition:transform .2s}.file-card:hover{transform:translateY(-4px);border-color:var(--accent)}.poster-box{position:relative;padding-top:56.25%;background:#000;overflow:hidden}.fc-poster{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .2s}.fc-poster.loaded{opacity:1}.fc-body{padding:12px}.fc-name{font-size:13px;font-weight:700;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.poster-top{position:absolute;top:8px;left:8px;right:8px;display:flex;gap:5px;z-index:2}.type-chip,.size-chip{background:rgba(0,0,0,.7);padding:3px 6px;border-radius:4px;font-size:9px;font-weight:800;border:1px solid rgba(255,255,255,.1)}.pagination{display:none;justify-content:center;align-items:center;gap:15px;margin-top:20px}.pg-btn{background:var(--bg3);color:var(--text);border:1px solid var(--border);padding:8px 18px;border-radius:6px;font-size:12px;font-weight:700;cursor:pointer}.pg-btn:disabled{opacity:.4;cursor:not-allowed}
"""

@routes.get("/dashboard")
@routes.get("/miniapp")
async def dashboard_portal(req):
    role, _ = await get_auth(req)
    if not role and req.path == "/dashboard": return web.HTTPFound('/login')
    
    body = f"""
    <style>{CSS_STACK}</style>
    <div class="topbar"><a class="logo" href="#">⚡ FAST FINDER WEB</a></div>
    <div class="main">
        <div class="search-zone">
            <div class="search-wrap"><input class="search-input" id="q" placeholder="Type movie or file name..."></div>
            <button class="search-btn" onclick="doSearch(0)">Search</button>
        </div>
        <div id="results" class="res-grid"></div>
        <div class="pagination" id="pageBox">
            <button class="pg-btn" id="pBtn" onclick="prev()" disabled>Previous</button>
            <span id="pgInfo" style="font-size:12px;font-weight:600;">Page 1</span>
            <button class="pg-btn" id="nBtn" onclick="next()">Next</button>
        </div>
    </div>
    <script>
    var nextOff="",curOff=0,curPage=1;
    var LIMIT_VAL = {MAX_WEB_RESULTS};
    async function doSearch(o){{
        var q=document.getElementById("q").value.trim(); if(!q) return;
        curOff=o; if(o===0) curPage=1;
        var grid=document.getElementById("results"); grid.innerHTML="<div style='grid-column:1/-1;text-align:center;padding:40px;'>Searching Database...</div>";
        try{{
            var r=await fetch("/api/search?q="+encodeURIComponent(q)+"&offset="+o),d=await r.json();
            var h="";
            d.results.forEach(f=>{{
                h+='<div class="file-card" onclick="window.open(\\'/setup_stream?file_id='+f.file_id+'\\',\\'_blank\\')"><div class="poster-box"><img src="'+f.tg_thumb+'" class="fc-poster" onload="this.classList.add(\\'loaded\\')" loading="lazy"><div class="poster-top"><span class="type-chip">'+f.type+'</span><span class="size-chip">'+f.size+'</span></div></div><div class="fc-body"><div class="fc-name">'+f.name+'</div></div></div>';
            }});
            grid.innerHTML=h||"<div style='grid-column:1/-1;text-align:center;'>No results found.</div>";
            nextOff=d.next_offset; document.getElementById("pageBox").style.display=h?'flex':'none';
            document.getElementById("pBtn").disabled=(o===0); document.getElementById("nBtn").disabled=!nextOff;
            document.getElementById("pgInfo").textContent='Page '+curPage;
        }}catch(e){{grid.innerHTML="Search connection timed out.";}}
    }}
    function next(){{if(nextOff){{curPage++;doSearch(nextOff);}}}}
    function prev(){{if(curPage>1){{curPage--;doSearch(Math.max(0,curOff-LIMIT_VAL));}}}}
    </script>
    """
    return web.Response(text=body, content_type='text/html', charset='utf-8')

@routes.get("/api/search")
async def api_search(req):
    q, off = req.query.get("q", "").strip(), req.query.get("offset", "0")
    if not q: return web.json_response({"results": [], "next_offset": ""})
    try: off = max(0, int(off))
    except: off = 0

    files, next_offset, total_results = await get_search_results(q, offset=off)
    
    results_list = []
    for d in files:
        fid = getattr(d, "file_id", getattr(d, "id", d.get("_id") if isinstance(d, dict) else None))
        name = getattr(d, "file_name", d.get("file_name", "Unknown File") if isinstance(d, dict) else "Unknown File")
        size = get_size(getattr(d, "file_size", d.get("file_size", 0) if isinstance(d, dict) else 0))
        f_type = getattr(d, "file_type", d.get("file_type", "video") if isinstance(d, dict) else "video").upper()
        
        results_list.append({
            "file_id": fid, "name": name, "size": size, "type": f_type,
            "tg_thumb": f"/api/thumb?file_id={fid}"
        })
    return web.json_response({"results": results_list, "next_offset": next_offset})

@routes.get("/api/thumb")
async def get_telegram_thumb(req):
    fid = req.query.get("file_id")
    is_retry = req.query.get("retry", "false").lower() == "true"
    if not fid: return web.Response(status=400)
    
    res = await _get_or_fetch_thumb(fid, is_retry=is_retry)
    if res is None: return web.Response(status=404)
    return web.Response(body=res, content_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})

@routes.get("/setup_stream")
async def setup_stream(req):
    fid = req.query.get("file_id")
    try:
        msg = await temp.BOT.send_cached_media(chat_id=BIN_CHANNEL, file_id=fid)
        await db.add_to_delete_queue(BIN_CHANNEL, msg.id, 3600)
        return web.HTTPFound(f"/watch/{msg.id}")
    except Exception as e: return web.Response(text=f"Tunnel Matrix Exception: {e}", status=500)

@routes.get("/watch/{message_id}")
async def watch_handler(request):
    try:
        m_id = int(request.match_info['message_id'])
        msg = await temp.BOT.get_messages(BIN_CHANNEL, m_id)
        props = await TGCustomYield.generate_file_properties(msg)
        src = f"{URL}download/{m_id}"
        async with aiofiles.open('web/template/watch.html', mode='r', encoding='utf-8') as r:
            template = await r.read()
        return web.Response(text=template.format(heading=props.file_name, file_name=props.file_name, src=src, mime_type=props.mime_type or 'video/mp4'), content_type='text/html')
    except Exception as e: return web.Response(text=f"Player Failure: {e}", status=500)

@routes.get("/download/{message_id}")
async def download_handler(request):
    try:
        m_id = int(request.match_info['message_id'])
        msg = await temp.BOT.get_messages(BIN_CHANNEL, m_id)
        props = await TGCustomYield.generate_file_properties(msg)
        media_obj = msg.document or msg.video or msg.audio
        f_size = props.file_size

        range_hdr = request.headers.get('Range', 0)
        if range_hdr:
            f_b, u_b = range_hdr.replace('bytes=', '').split('-')
            f_b, u_b = int(f_b), int(u_b) if u_b else f_size - 1
        else:
            f_b, u_b = 0, f_size - 1

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
