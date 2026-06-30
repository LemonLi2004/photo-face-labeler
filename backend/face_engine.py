"""人脸引擎：封装 InsightFace 检测 + 特征提取，含 EXIF 矫正与图像读取。

设计要点：
- 单例加载模型，避免重复初始化。
- 统一用 BGR ndarray 喂给 InsightFace。
- 提取的脸按 bbox 中心 x 从左到右排序，赋 face_order。
- 向量做 L2 归一化，比对时直接点积即余弦相似度。
"""
from __future__ import annotations

import io
from typing import List, Optional

import numpy as np
from PIL import Image, ImageOps

# 支持 HEIC（iPhone 照片）
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:
    pass

from . import config

_APP = None


def get_app():
    """惰性加载 InsightFace 模型（单例）。"""
    global _APP
    if _APP is None:
        from insightface.app import FaceAnalysis

        app = FaceAnalysis(name=config.MODEL_NAME, providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=-1, det_size=config.DET_SIZE)
        _APP = app
    return _APP


def load_image_bgr(source) -> Optional[np.ndarray]:
    """从路径或 bytes 读取图片，矫正 EXIF 方向，返回 BGR ndarray。"""
    try:
        if isinstance(source, (bytes, bytearray)):
            img = Image.open(io.BytesIO(source))
        else:
            img = Image.open(source)
        img = ImageOps.exif_transpose(img)  # 矫正旋转
        img = img.convert("RGB")
    except Exception:
        return None
    rgb = np.array(img)
    bgr = rgb[:, :, ::-1].copy()  # RGB -> BGR
    return bgr


def normalize(vec: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(vec)
    if n == 0:
        return vec.astype(np.float32)
    return (vec / n).astype(np.float32)


class DetectedFace:
    __slots__ = ("bbox", "det_score", "embedding", "face_order")

    def __init__(self, bbox, det_score, embedding, face_order=0):
        self.bbox = bbox            # [x1,y1,x2,y2] float
        self.det_score = det_score  # float
        self.embedding = embedding  # np.float32 (512,) 已归一化
        self.face_order = face_order


def detect_faces(bgr: np.ndarray) -> List[DetectedFace]:
    """检测所有人脸，过滤低置信度，按从左到右排序并赋 face_order。"""
    app = get_app()
    faces = app.get(bgr)
    result = []
    for f in faces:
        if float(f.det_score) < config.DET_SCORE_THRESH:
            continue
        emb = normalize(np.asarray(f.normed_embedding, dtype=np.float32))
        result.append(
            DetectedFace(
                bbox=[float(x) for x in f.bbox],
                det_score=float(f.det_score),
                embedding=emb,
            )
        )
    # 按 bbox 中心 x 从左到右
    result.sort(key=lambda d: (d.bbox[0] + d.bbox[2]) / 2.0)
    for i, d in enumerate(result):
        d.face_order = i
    return result
