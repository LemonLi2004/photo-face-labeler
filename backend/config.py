"""集中配置：路径、阈值、模型参数。"""
from pathlib import Path

# --- 目录 ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
THUMB_DIR = DATA_DIR / "thumbnails"
FACE_CROP_DIR = DATA_DIR / "face_crops"   # 标注界面用的人脸小图缓存（face_id.jpg）
EXPORTS_DIR = DATA_DIR / "exports"        # 一键全导出时每人一个 zip 落盘
DB_PATH = PROJECT_ROOT / "db" / "faces.db"
INDEX_DIR = PROJECT_ROOT / "index"
EMBEDDINGS_PATH = INDEX_DIR / "embeddings.npy"
FACE_IDS_PATH = INDEX_DIR / "face_ids.npy"
FRONTEND_DIR = PROJECT_ROOT / "frontend"

# --- 原图来源 ---
# 真实毕业照已解压到 data/originals
ORIGINALS_DIR = DATA_DIR / "originals"

# --- InsightFace 模型 ---
MODEL_NAME = "buffalo_l"
DET_SIZE = (640, 640)
# 人脸检测置信度阈值：低于此值的脸丢弃（过滤极端侧脸/误检）
DET_SCORE_THRESH = 0.50

# --- 人脸聚类（人物编号）---
# 同一人聚类的相似度阈值：>=此值的脸归为同一人。
# 真实数据双峰分析显示同一人集中在 0.6 以上，取 0.55 较稳。
CLUSTER_THRESHOLD = 0.55
# 重跑聚类时用历史标注的质心自动重认领的阈值。
RECLAIM_THRESHOLD = 0.50
# 后端记录文件：每张照片从左到右的人脸顺序（编号/名字），按原文件名索引。
# 下载的照片保持原文件名，不带人名；人脸顺序信息只存在这个 JSON 里。
FACE_ORDER_JSON = INDEX_DIR / "face_order.json"

# --- 缩略图 ---
THUMB_MAX_SIDE = 1024
THUMB_QUALITY = 82
FACE_CROP_MAX_SIDE = 384   # 人脸小图边长上限（视网膜屏建议 >= 384）

# --- 限流（防爬）---
RATE_LIMIT_DOWNLOAD = "120/minute"     # 单 IP 下载/裁剪请求

for _d in (THUMB_DIR, FACE_CROP_DIR, EXPORTS_DIR, DB_PATH.parent, INDEX_DIR):
    _d.mkdir(parents=True, exist_ok=True)
