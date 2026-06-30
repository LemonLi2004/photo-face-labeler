# photo-face-labeler

> Face annotation & per-person photo export for group photos — powered by InsightFace.

Upload your group photos, let AI detect and cluster faces, then label each person by hand. Export a zip file per person with all their group photos, deduplicated and neatly named.

[中文](README.md)

## Features

- 🔍 **Face Detection** — InsightFace (buffalo_l / RetinaFace) with CPU inference
- 🧩 **Face Clustering** — 512-dim ArcFace embeddings + cosine similarity + union-find
- 🏷️ **Web Annotation UI** — label each cluster with a name, or skip unknown faces
- 🔄 **Auto-merge** — same name across clusters → one zip (deduplicated)
- 📦 **Per-person Export** — zip with `Name_001.jpg`, `Name_002.jpg`, ...
- 📊 **Carry-over** — re-clustering preserves labels via centroid similarity
- 🚀 **No build step** — vanilla HTML/CSS/JS frontend, FastAPI backend

## How It Works

1. Place your photos in `data/originals/`
2. Run `build_index.py` — detects faces, extracts embeddings, generates thumbnails
3. Run `cluster_persons.py` — groups faces into clusters (≈ one person per cluster)
4. Start the web UI and label each cluster (name or skip)
5. Export — each named person gets a zip with all their group photos

## Quick Start

```bash
# 1. Install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Put your photos in
mkdir -p data/originals
# ... copy your JPG/PNG/HEIC photos here ...

# 3. Build the face index (first run downloads ~300MB InsightFace model)
python -m scripts.build_index

# 4. Cluster faces into persons
python -m scripts.cluster_persons

# 5. Start the annotation web UI
uvicorn backend.app:app --host 127.0.0.1 --port 8000

# 6. Open http://127.0.0.1:8000 and label!
#    Click a name to view all photos of that person.
#    When done, click "Export All" — zips go to data/exports/
```

## Project Structure

```
backend/
  config.py          # All paths, thresholds, limits
  db.py              # SQLite schema & queries
  face_engine.py     # InsightFace wrapper (detect + embed)
  matcher.py         # Person centroid cache + carry-over snapshot
  annotate.py        # Annotation & export logic
  naming.py          # Face-order JSON record
  app.py             # FastAPI app + static hosting
frontend/
  index.html         # Annotation board UI
  style.css          # Dark theme
  app.js             # All client logic
scripts/
  build_index.py     # Offline: detect faces, build index
  cluster_persons.py # Offline: cluster faces into persons
data/
  originals/         # Your source photos (input)
  thumbnails/        # Generated thumbnails (auto)
  face_crops/        # Generated face crops for UI (auto)
  exports/           # Exported zip files (auto)
db/
  faces.db           # SQLite database (auto)
index/
  embeddings.npy     # Face embedding matrix (auto)
  face_ids.npy       # Corresponding face IDs (auto)
  face_order.json    # Per-photo face order record (auto)
```

## Configuration

All settings live in `backend/config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `ORIGINALS_DIR` | `data/originals` | Path to source photos |
| `MODEL_NAME` | `buffalo_l` | InsightFace model pack |
| `DET_SCORE_THRESH` | `0.50` | Face detection confidence threshold |
| `CLUSTER_THRESHOLD` | `0.55` | Cosine similarity threshold for clustering |
| `RECLAIM_THRESHOLD` | `0.50` | Carry-over similarity threshold |
| `FACE_CROP_MAX_SIDE` | `384` | Face crop resolution (px) |
| `THUMB_MAX_SIDE` | `1024` | Thumbnail max side (px) |
| `RATE_LIMIT_DOWNLOAD` | `120/minute` | Per-IP download rate limit |

**Threshold tuning tips:**
- If the same person is split into multiple clusters — lower `CLUSTER_THRESHOLD`
- If different people are merged into one cluster — raise `CLUSTER_THRESHOLD`
- It's safer to over-split (same-name auto-merge handles it) than over-merge

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/clusters` | List all clusters with sample faces |
| `GET` | `/api/stats` | Annotation progress stats |
| `POST` | `/api/label` | Label a cluster: `{person_id, action: "name"\|"skip"\|"clear", name?}` |
| `POST` | `/api/merge` | Merge two clusters: `{src_id, dst_id}` |
| `GET` | `/api/face_crop/{face_id}` | Face crop image |
| `GET` | `/api/thumbnail/{photo_id}` | Photo thumbnail |
| `GET` | `/api/original/{photo_id}?download=1` | Original photo download |
| `GET` | `/api/photos/person/{person_id}` | Photos of a cluster |
| `GET` | `/api/photos/name?name=` | Photos of a person (merged across clusters) |
| `GET` | `/api/export/person/{id}.zip` | Download zip for one cluster |
| `GET` | `/api/export/name.zip?name=` | Download zip for one person (merged) |
| `POST` | `/api/export/all` | Export all named people to `data/exports/` |
| `GET` | `/api/admin/face_order.json` | Per-photo face order record |

## Deployment

```bash
# Production with systemd or similar
uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

For production, put Nginx in front for HTTPS, static caching, and additional rate limiting.
The annotation UI is admin-only — add basic auth or IP whitelisting.

## License

MIT — see [LICENSE](LICENSE) for details.
