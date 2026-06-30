"""离线建库脚本。

流程：
  遍历 ORIGINALS_DIR 中的图片
   -> EXIF 矫正读取
   -> InsightFace 检测所有人脸（已按从左到右排序）
   -> 写 photos / faces 表
   -> 生成缩略图到 data/thumbnails
   -> 导出 embeddings.npy + face_ids.npy 供快速比对

特性：
  - 断点续跑：已入库的文件名跳过
  - 无人脸的图也记录（n_faces=0），但不产生 face 行
  - 进度条

用法：
  python -m scripts.build_index            # 增量建库
  python -m scripts.build_index --rebuild  # 清空重建
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from tqdm import tqdm

# 允许以 `python -m scripts.build_index` 运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config, db
from backend.face_engine import load_image_bgr, detect_faces

IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"}


def make_thumbnail(src_bgr_image_path: Path, photo_id: int):
    """生成缩略图，文件名用 photo_id.jpg 便于接口直接取。"""
    try:
        from PIL import ImageOps

        img = Image.open(src_bgr_image_path)
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((config.THUMB_MAX_SIDE, config.THUMB_MAX_SIDE))
        out = config.THUMB_DIR / f"{photo_id}.jpg"
        img.save(out, "JPEG", quality=config.THUMB_QUALITY)
    except Exception as e:
        print(f"  [warn] thumbnail failed for {src_bgr_image_path.name}: {e}")


def export_embeddings():
    """把全库人脸向量导出为矩阵，供运行时快速比对。"""
    conn = db.get_conn()
    try:
        rows = conn.execute("SELECT id, embedding FROM faces ORDER BY id").fetchall()
    finally:
        conn.close()
    if not rows:
        print("No faces in DB; skip export.")
        return
    ids = np.array([r["id"] for r in rows], dtype=np.int64)
    mat = np.stack(
        [np.frombuffer(r["embedding"], dtype=np.float32) for r in rows]
    ).astype(np.float32)
    np.save(config.EMBEDDINGS_PATH, mat)
    np.save(config.FACE_IDS_PATH, ids)
    print(f"Exported {mat.shape[0]} embeddings -> {config.EMBEDDINGS_PATH}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true", help="清空重建")
    ap.add_argument("--src", default=str(config.ORIGINALS_DIR), help="原图目录")
    args = ap.parse_args()

    db.init_db()

    if args.rebuild:
        conn = db.get_conn()
        conn.executescript("DELETE FROM faces; DELETE FROM photos;")
        conn.commit()
        conn.close()
        for f in config.THUMB_DIR.glob("*.jpg"):
            f.unlink()
        print("Rebuild: cleared photos/faces/thumbnails.")

    src_dir = Path(args.src)
    files = sorted(
        p for p in src_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMG_EXTS
    )
    print(f"Found {len(files)} images in {src_dir}")

    conn = db.get_conn()
    n_new, n_faces_total, n_skip = 0, 0, 0
    try:
        for path in tqdm(files, desc="Building index"):
            if db.photo_exists(conn, path.name):
                n_skip += 1
                continue
            bgr = load_image_bgr(path)
            if bgr is None:
                continue
            h, w = bgr.shape[:2]
            faces = detect_faces(bgr)
            photo_id = db.insert_photo(conn, path.name, w, h, len(faces))
            for face in faces:
                db.insert_face(
                    conn, photo_id, face.face_order, face.bbox,
                    face.det_score, face.embedding.tobytes(),
                )
            conn.commit()
            make_thumbnail(path, photo_id)
            n_new += 1
            n_faces_total += len(faces)
    finally:
        conn.close()

    print(f"Done. new photos={n_new}, faces={n_faces_total}, skipped={n_skip}")
    export_embeddings()


if __name__ == "__main__":
    main()
