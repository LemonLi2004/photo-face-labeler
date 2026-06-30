"""每张照片的人脸顺序记录。

下载的照片保持原文件名（不带人名）。人脸的从左到右顺序信息只保存在后端：
  - build_roster_rows(): 每张照片的从左到右名册（管理员总览/前端标注用）
  - export_json(): 写 face_order.json，按【原文件名】索引每张照片的人脸顺序，
    供之后离线给照片归类/命名时查阅。

face_order.json 结构：
{
  "generated_at": "2026-06-30T13:00:00",
  "photos": {
    "IMG_8660.JPG": {
      "photo_id": 729,
      "n_faces": 3,
      "faces": [
        {"face_order": 0, "person_id": 1, "name": null},
        {"face_order": 1, "person_id": 2, "name": "张三"},
        {"face_order": 2, "person_id": 3, "name": null}
      ]
    },
    ...
  }
}
"""
import json
from datetime import datetime
from typing import List, Dict

from . import config, db


def _display(name, person_id) -> str:
    """前端/总览展示用：真名 或 '#编号' 或 '?'。"""
    if name:
        return name
    if person_id:
        return f"#{person_id}"
    return "?"


def build_roster_rows() -> List[dict]:
    """返回每张照片：原名 + 从左到右名册（含展示串）。"""
    conn = db.get_conn()
    try:
        photos = conn.execute(
            "SELECT id, filename, n_faces FROM photos ORDER BY filename"
        ).fetchall()
        face_rows = conn.execute(
            "SELECT f.photo_id, f.face_order, f.person_id, p.name AS pname "
            "FROM faces f LEFT JOIN persons p ON f.person_id=p.id "
            "ORDER BY f.photo_id, f.face_order"
        ).fetchall()
    finally:
        conn.close()

    roster_by_photo: Dict[int, list] = {}
    for fr in face_rows:
        roster_by_photo.setdefault(fr["photo_id"], []).append(
            {
                "face_order": fr["face_order"],
                "person_id": fr["person_id"],
                "name": fr["pname"],
                "display": _display(fr["pname"], fr["person_id"]),
            }
        )

    rows = []
    for p in photos:
        roster = roster_by_photo.get(p["id"], [])
        roster.sort(key=lambda x: x["face_order"])
        rows.append(
            {
                "photo_id": p["id"],
                "filename": p["filename"],
                "n_faces": p["n_faces"],
                "roster": roster,
            }
        )
    return rows


def export_json(path=None) -> str:
    """写 face_order.json：按原文件名索引每张照片的从左到右人脸顺序。"""
    path = path or config.FACE_ORDER_JSON
    rows = build_roster_rows()
    photos = {}
    for r in rows:
        photos[r["filename"]] = {
            "photo_id": r["photo_id"],
            "n_faces": r["n_faces"],
            "faces": [
                {
                    "face_order": x["face_order"],
                    "person_id": x["person_id"],
                    "name": x["name"],
                }
                for x in r["roster"]
            ],
        }
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "count": len(photos),
        "photos": photos,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return str(path)


if __name__ == "__main__":
    out = export_json()
    print(f"Face-order JSON exported -> {out}")
