"""FastAPI 应用入口（人脸标注 + 按人导出版）。

流程：你自己在网页上按聚类标注每个人（标名字 / 跳过），
最后按人导出 zip（同名聚类自动合并，合照去重，保持原文件名）。

接口：
  GET  /api/clusters             聚类列表（供标注）
  GET  /api/stats                标注进度统计
  POST /api/label                给聚类标名 / 跳过 / 撤销
  POST /api/merge                手动合并两个聚类
  GET  /api/face_crop/{face_id}  人脸小图（标注展示）
  GET  /api/thumbnail/{photo_id} 整张缩略图（看合照）
  GET  /api/original/{photo_id}  原图（下载）
  POST /api/download/batch       多张打 zip
  GET  /api/export/person/{id}.zip  某聚类的照片 zip
  GET  /api/export/name.zip?name=  某人的照片 zip（同名合并）
  POST /api/export/all           每人一个 zip 落盘
  GET  /api/admin/face_order.json 人脸顺序记录
  GET  /                         标注前端页面
"""
import io
import re
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from . import config, db, annotate, matcher

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="毕业照片人脸标注")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

NAME_RE = re.compile(r"^[\w\u4e00-\u9fff .\-]{1,40}$")


@app.on_event("startup")
def _startup():
    db.init_db()
    matcher.load_index(force=True)


# ---------- 标注 ----------

@app.get("/api/clusters")
def api_clusters(request: Request):
    return JSONResponse(annotate.list_clusters())


@app.get("/api/stats")
def api_stats(request: Request):
    return JSONResponse(annotate.stats())


@app.post("/api/label")
async def api_label(request: Request):
    """给聚类标注：{person_id, action: 'name'|'skip'|'clear', name?}"""
    body = await request.json()
    pid = body.get("person_id")
    action = body.get("action", "name")
    if pid is None:
        raise HTTPException(400, "缺少 person_id")
    pid = int(pid)
    conn = db.get_conn()
    try:
        if action == "skip":
            db.skip_person(conn, pid)
        elif action == "clear":
            db.unlabel_person(conn, pid)
        else:
            name = (body.get("name") or "").strip()
            if not NAME_RE.match(name):
                raise HTTPException(400, "名字格式不合法（1-40字，中英文/数字）")
            db.claim_person(conn, pid, name)
    finally:
        conn.close()
    return JSONResponse({"ok": True, "stats": annotate.stats()})


@app.post("/api/merge")
async def api_merge(request: Request):
    """手动合并两个聚类：{src_id, dst_id}（把 src 并入 dst）。"""
    body = await request.json()
    src, dst = body.get("src_id"), body.get("dst_id")
    if src is None or dst is None:
        raise HTTPException(400, "缺少 src_id / dst_id")
    conn = db.get_conn()
    try:
        db.merge_persons(conn, int(src), int(dst))
    finally:
        conn.close()
    matcher.refresh_persons()
    return JSONResponse({"ok": True})


# ---------- 图片 ----------

@app.get("/api/face_crop/{face_id}")
@limiter.limit(config.RATE_LIMIT_DOWNLOAD)
def api_face_crop(request: Request, face_id: int):
    path = annotate.face_crop_path(face_id)
    if not path:
        raise HTTPException(404, "人脸裁剪失败")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/thumbnail/{photo_id}")
@limiter.limit(config.RATE_LIMIT_DOWNLOAD)
def api_thumbnail(request: Request, photo_id: int):
    path = config.THUMB_DIR / f"{photo_id}.jpg"
    if not path.exists():
        raise HTTPException(404, "缩略图不存在")
    return FileResponse(path, media_type="image/jpeg")


def _original_path(photo_id: int) -> Path:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT filename FROM photos WHERE id=?", (photo_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(404, "照片不存在")
    p = config.ORIGINALS_DIR / row["filename"]
    if not p.exists():
        raise HTTPException(404, "原图文件缺失")
    return p


@app.get("/api/original/{photo_id}")
@limiter.limit(config.RATE_LIMIT_DOWNLOAD)
def api_original(request: Request, photo_id: int, download: int = 0):
    p = _original_path(photo_id)
    headers = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{p.name}"'
    return FileResponse(p, headers=headers)


@app.post("/api/download/batch")
@limiter.limit(config.RATE_LIMIT_DOWNLOAD)
async def api_download_batch(request: Request):
    body = await request.json()
    ids = body.get("photo_ids", [])
    if not isinstance(ids, list) or not ids:
        raise HTTPException(400, "photo_ids 不能为空")
    if len(ids) > 1000:
        raise HTTPException(400, "单次最多下载 1000 张")

    def gen():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
            for pid in ids:
                try:
                    p = _original_path(int(pid))
                    zf.write(p, arcname=p.name)
                except HTTPException:
                    continue
        buf.seek(0)
        yield buf.read()

    headers = {"Content-Disposition": 'attachment; filename="photos.zip"'}
    return StreamingResponse(gen(), media_type="application/zip", headers=headers)


# ---------- 某人/某聚类的照片列表（抽屉展示用） ----------

@app.get("/api/photos/person/{person_id}")
def api_photos_person(request: Request, person_id: int):
    return JSONResponse(annotate.photos_of_person(person_id))


@app.get("/api/photos/name")
def api_photos_name(request: Request, name: str):
    name = name.strip()
    if not NAME_RE.match(name):
        raise HTTPException(400, "名字格式不合法")
    return JSONResponse(annotate.photos_of_name(name))


# ---------- 按人导出 ----------

def _zip_response(data: bytes, filename: str) -> Response:
    # 中文文件名用 RFC5987 编码
    disp = f"attachment; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": disp},
    )


@app.get("/api/export/person/{person_id}.zip")
@limiter.limit(config.RATE_LIMIT_DOWNLOAD)
def api_export_person(request: Request, person_id: int):
    data, n = annotate.build_person_zip_bytes(person_id)
    if n == 0:
        raise HTTPException(404, "该聚类没有可导出的照片")
    return _zip_response(data, f"person_{person_id}.zip")


@app.get("/api/export/name.zip")
@limiter.limit(config.RATE_LIMIT_DOWNLOAD)
def api_export_name(request: Request, name: str):
    name = name.strip()
    if not NAME_RE.match(name):
        raise HTTPException(400, "名字格式不合法")
    data, n = annotate.build_name_zip_bytes(name)
    if n == 0:
        raise HTTPException(404, "该姓名下没有照片")
    return _zip_response(data, f"{annotate._safe_name(name)}.zip")


@app.post("/api/export/all")
def api_export_all(request: Request):
    return JSONResponse(annotate.export_all())


@app.get("/api/admin/face_order.json")
def api_admin_face_order(request: Request):
    from . import naming
    out = naming.export_json()
    return FileResponse(out, media_type="application/json", filename="face_order.json")


# 前端静态文件（放在最后，避免覆盖 /api 路由）
app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True), name="static")
