"""标注与导出服务。

围绕已有的人脸聚类（persons 表 + faces.person_id）：
  - list_clusters(): 列出所有聚类供标注（代表脸 + 样本脸 + 状态）
  - face_crop_path(): 从原图按 bbox 裁出人脸小图（带磁盘缓存）
  - photos_of_name() / photos_of_person(): 取某人/某聚类出现的全部照片（合照去重）
  - build_person_zip(): 把某人所有照片打成 zip（保持原文件名）
  - export_all(): 同名聚类自动合并，每人一个 zip 落盘 EXPORTS_DIR
"""
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageOps

from . import config, db


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w.\-\u4e00-\u9fff]", "_", name).strip("_") or "unnamed"


# ---------- 人脸小图裁剪 ----------

def face_crop_path(face_id: int) -> Optional[Path]:
    """返回某张脸的裁剪小图路径，不存在则从原图裁出并缓存。"""
    out = config.FACE_CROP_DIR / f"{face_id}.jpg"
    if out.exists():
        return out

    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT f.bbox, p.filename FROM faces f "
            "JOIN photos p ON f.photo_id=p.id WHERE f.id=?",
            (face_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None

    src = config.ORIGINALS_DIR / row["filename"]
    if not src.exists():
        return None
    try:
        img = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    except Exception:
        return None

    x1, y1, x2, y2 = json.loads(row["bbox"])
    w, h = img.size
    # 适当外扩，带点头肩，方便辨认
    bw, bh = (x2 - x1), (y2 - y1)
    pad_x, pad_y = bw * 0.35, bh * 0.45
    cx1 = max(0, int(x1 - pad_x))
    cy1 = max(0, int(y1 - pad_y))
    cx2 = min(w, int(x2 + pad_x))
    cy2 = min(h, int(y2 + pad_y))
    crop = img.crop((cx1, cy1, cx2, cy2))
    crop.thumbnail((config.FACE_CROP_MAX_SIDE, config.FACE_CROP_MAX_SIDE))
    crop.save(out, "JPEG", quality=85)
    return out


# ---------- 聚类列表（供标注） ----------

def list_clusters(sample: int = 12) -> List[dict]:
    """列出所有聚类：编号、名字、状态、张数、若干样本脸(含 face_id/photo_id/order)。

    排序：未标注的在前（按张数降序），已标注/已跳过的在后。
    样本选择：按「检测分 × 脸面积」综合排序，优先挑又大又清晰的脸。
    """
    conn = db.get_conn()
    try:
        prows = conn.execute(
            "SELECT id, name, n_faces, skipped FROM persons ORDER BY n_faces DESC"
        ).fetchall()
        face_rows = conn.execute(
            "SELECT f.id, f.person_id, f.photo_id, f.face_order, f.det_score, f.bbox "
            "FROM faces f WHERE f.person_id IS NOT NULL "
            "ORDER BY f.person_id"
        ).fetchall()
    finally:
        conn.close()

    samples: Dict[int, list] = {}
    for fr in face_rows:
        bbox = json.loads(fr["bbox"])
        area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
        quality = fr["det_score"] * (area ** 0.5)
        lst = samples.setdefault(fr["person_id"], [])
        lst.append(
            {
                "face_id": fr["id"],
                "photo_id": fr["photo_id"],
                "face_order": fr["face_order"],
                "quality": quality,
            }
        )
    for pid in samples:
        samples[pid].sort(key=lambda x: -x["quality"])
        samples[pid] = [
            {k: v for k, v in s.items() if k != "quality"}
            for s in samples[pid][:sample]
        ]

    clusters = []
    for p in prows:
        name = p["name"]
        if name:
            status = "named"
        elif p["skipped"]:
            status = "skipped"
        else:
            status = "todo"
        clusters.append(
            {
                "person_id": p["id"],
                "name": name,
                "status": status,
                "n_faces": p["n_faces"],
                "samples": samples.get(p["id"], []),
            }
        )

    order = {"todo": 0, "named": 1, "skipped": 2}
    clusters.sort(key=lambda c: (order[c["status"]], -c["n_faces"]))
    return clusters


def stats() -> dict:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) total, "
            "SUM(CASE WHEN name IS NOT NULL AND name<>'' THEN 1 ELSE 0 END) named, "
            "SUM(CASE WHEN skipped=1 THEN 1 ELSE 0 END) skipped FROM persons"
        ).fetchone()
        names = conn.execute(
            "SELECT DISTINCT name FROM persons WHERE name IS NOT NULL AND name<>'' "
            "ORDER BY name"
        ).fetchall()
    finally:
        conn.close()
    total = row["total"] or 0
    named = row["named"] or 0
    skipped = row["skipped"] or 0
    return {
        "clusters_total": total,
        "clusters_named": named,
        "clusters_skipped": skipped,
        "clusters_todo": total - named - skipped,
        "distinct_people": len(names),
        "names": [r["name"] for r in names],
    }


# ---------- 取某人的照片 ----------

def _photos_for_person_ids(person_ids: List[int]) -> List[dict]:
    """给定一组聚类编号，返回涉及的去重照片列表（合照只算一次）。"""
    if not person_ids:
        return []
    conn = db.get_conn()
    try:
        q = ",".join("?" * len(person_ids))
        rows = conn.execute(
            f"SELECT DISTINCT p.id, p.filename, p.n_faces "
            f"FROM faces f JOIN photos p ON f.photo_id=p.id "
            f"WHERE f.person_id IN ({q}) ORDER BY p.filename",
            person_ids,
        ).fetchall()
    finally:
        conn.close()
    return [
        {"photo_id": r["id"], "filename": r["filename"], "n_faces": r["n_faces"]}
        for r in rows
    ]


def person_ids_for_name(name: str) -> List[int]:
    """同名的所有聚类编号（同名自动合并的核心）。"""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id FROM persons WHERE name=?", (name,)
        ).fetchall()
    finally:
        conn.close()
    return [r["id"] for r in rows]


def photos_of_name(name: str) -> List[dict]:
    return _photos_for_person_ids(person_ids_for_name(name))


def photos_of_person(person_id: int) -> List[dict]:
    return _photos_for_person_ids([person_id])


# ---------- 打 zip ----------

def _zip_photos(photos: List[dict], arcname_prefix: Optional[str] = None) -> io.BytesIO:
    """把照片打进 zip。

    arcname_prefix: 若提供，zip 内文件名改为「prefix_序号.原扩展名」（3 位补零）。
                    若不提供，保持原文件名。
    """
    buf = io.BytesIO()
    photos_sorted = sorted(photos, key=lambda p: p["filename"])
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        seen = set()
        for idx, ph in enumerate(photos_sorted, start=1):
            fn = ph["filename"]
            if fn in seen:
                continue
            src = config.ORIGINALS_DIR / fn
            if src.exists():
                if arcname_prefix:
                    ext = src.suffix
                    arc = f"{arcname_prefix}_{idx:03d}{ext}"
                else:
                    arc = fn
                zf.write(src, arcname=arc)
                seen.add(fn)
    buf.seek(0)
    return buf


def build_name_zip_bytes(name: str) -> Tuple[bytes, int]:
    photos = photos_of_name(name)
    return _zip_photos(photos, arcname_prefix=name).read(), len(photos)


def build_person_zip_bytes(person_id: int) -> Tuple[bytes, int]:
    photos = photos_of_person(person_id)
    prefix = None
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT name FROM persons WHERE id=?", (person_id,)
        ).fetchone()
        if row and row["name"]:
            prefix = row["name"]
        else:
            prefix = f"person_{person_id}"
    finally:
        conn.close()
    return _zip_photos(photos, arcname_prefix=prefix).read(), len(photos)


def export_all() -> dict:
    """同名聚类自动合并，每人一个 zip 落盘 EXPORTS_DIR。返回汇总。"""
    conn = db.get_conn()
    try:
        names = [
            r["name"]
            for r in conn.execute(
                "SELECT DISTINCT name FROM persons "
                "WHERE name IS NOT NULL AND name<>'' ORDER BY name"
            ).fetchall()
        ]
    finally:
        conn.close()

    # 清空旧导出
    for old in config.EXPORTS_DIR.glob("*.zip"):
        old.unlink()

    result = []
    for name in names:
        photos = photos_of_name(name)
        if not photos:
            continue
        out = config.EXPORTS_DIR / f"{_safe_name(name)}.zip"
        data = _zip_photos(photos, arcname_prefix=name).getvalue()
        out.write_bytes(data)
        result.append({"name": name, "photos": len(photos), "zip": out.name})
    return {"people": len(result), "exports": result, "dir": str(config.EXPORTS_DIR)}
