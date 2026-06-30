# photo-face-labeler

> 照片人脸标注与按人导出工具 — 基于 InsightFace

把合照批量做人脸检测与聚类，你在网页上逐人标注姓名（不认识的跳过），最后按人导出 zip 压缩包（同名自动合并去重）。

[English](README_en.md)

## 功能特性

- 🔍 **人脸检测** — InsightFace (buffalo_l / RetinaFace)，CPU 推理
- 🧩 **人脸聚类** — 512 维 ArcFace 向量 + 余弦相似度 + 并查集
- 🏷️ **网页标注** — 每个聚类标一次名字，或跳过不认识的人
- 🔄 **同名自动合并** — 同一人被拆成多个聚类也没事，标成同名导出时自动合并去重
- 📦 **按人导出** — 每人一个 zip，内部照片命名为 `人名_001.jpg`、`人名_002.jpg`…
- 📊 **标注自动重认领** — 重跑聚类后，用质心相似度自动把历史标注写回新聚类
- 🚀 **零构建** — 原生 HTML/CSS/JS 前端 + FastAPI 后端，开箱即用

## 工作原理

1. 把照片放进 `data/originals/`
2. 运行 `build_index.py` — 检测人脸、提取特征、生成缩略图
3. 运行 `cluster_persons.py` — 把脸聚成不同的人（一个聚类≈一个人）
4. 启动网页，逐个聚类标名字（或跳过）
5. 一键导出 — 每个已命名的人生成一个 zip 压缩包

## 快速开始

```bash
# 1. 安装依赖
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. 把照片放进 data/originals/
mkdir -p data/originals
# ... 把 JPG/PNG/HEIC 照片拷进去 ...

# 3. 建库（首次运行会下载 ~300MB InsightFace 模型）
python -m scripts.build_index

# 4. 人脸聚类
python -m scripts.cluster_persons

# 5. 启动标注网页
uvicorn backend.app:app --host 127.0.0.1 --port 8000

# 6. 打开 http://127.0.0.1:8000 开始标注
#    点人名标签查看该人全部合照
#    标注完成后点「一键全导出」，zip 输出到 data/exports/
```

## 项目结构

```
backend/
  config.py          # 所有配置：路径、阈值、限流
  db.py              # SQLite schema 与读写
  face_engine.py     # InsightFace 封装（检测 + 提取特征）
  matcher.py         # 人物质心缓存 + 重跑聚类时的标注快照
  annotate.py        # 标注与导出业务逻辑
  naming.py          # 每张照片从左到右人脸顺序记录
  app.py             # FastAPI 应用 + 静态文件托管
frontend/
  index.html         # 标注看板页面
  style.css          # 深色主题样式
  app.js             # 全部前端交互逻辑
scripts/
  build_index.py     # 离线脚本：检测人脸、建库
  cluster_persons.py # 离线脚本：人脸聚类与编号
data/
  originals/         # 原始照片（输入）
  thumbnails/        # 自动生成的缩略图
  face_crops/        # 自动生成的人脸小图（标注界面用）
  exports/           # 导出的 zip 文件
db/
  faces.db           # SQLite 数据库（自动生成）
index/
  embeddings.npy     # 人脸特征向量矩阵（自动生成）
  face_ids.npy       # 对应的人脸 ID（自动生成）
  face_order.json    # 每张照片从左到右人脸顺序记录（自动生成）
```

## 配置说明

所有配置在 `backend/config.py` 中：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `ORIGINALS_DIR` | `data/originals` | 原始照片路径 |
| `MODEL_NAME` | `buffalo_l` | InsightFace 模型包 |
| `DET_SCORE_THRESH` | `0.50` | 人脸检测置信度阈值，低于此值的脸丢弃 |
| `CLUSTER_THRESHOLD` | `0.55` | 聚类相似度阈值 |
| `RECLAIM_THRESHOLD` | `0.50` | 重跑聚类时自动重认领阈值 |
| `FACE_CROP_MAX_SIDE` | `384` | 人脸小图边长上限（像素） |
| `THUMB_MAX_SIDE` | `1024` | 缩略图边长上限（像素） |
| `RATE_LIMIT_DOWNLOAD` | `120/minute` | 单 IP 下载限流 |

**阈值调优建议**：
- 同一个人被拆成很多聚类 → 调低 `CLUSTER_THRESHOLD`
- 不同的人被并到一个聚类 → 调高 `CLUSTER_THRESHOLD`
- 宁可拆多了（同名会自动合并），也别并错了

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/clusters` | 聚类列表（含样本脸），待处理在前 |
| `GET` | `/api/stats` | 标注进度统计 |
| `POST` | `/api/label` | 标注聚类：`{person_id, action: "name"\|"skip"\|"clear", name?}` |
| `POST` | `/api/merge` | 手动合并两个聚类：`{src_id, dst_id}` |
| `GET` | `/api/face_crop/{face_id}` | 人脸小图 |
| `GET` | `/api/thumbnail/{photo_id}` | 照片缩略图 |
| `GET` | `/api/original/{photo_id}?download=1` | 原图下载 |
| `GET` | `/api/photos/person/{person_id}` | 某聚类的照片列表 |
| `GET` | `/api/photos/name?name=` | 某人的照片列表（同名聚类合并去重） |
| `GET` | `/api/export/person/{id}.zip` | 单聚类 zip 下载 |
| `GET` | `/api/export/name.zip?name=` | 单人 zip 下载（同名合并） |
| `POST` | `/api/export/all` | 一键全导出到 `data/exports/` |
| `GET` | `/api/admin/face_order.json` | 每张照片从左到右人脸顺序记录 |

## 部署

```bash
# 生产环境（配合 systemd 或 supervisor）
uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

建议前置 Nginx 处理 HTTPS、静态缓存和额外限流。标注界面是管理端功能，上线后建议加访问口令或 IP 白名单。

## 许可证

MIT — 详见 [LICENSE](LICENSE)
