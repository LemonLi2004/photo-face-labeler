"""SQLite 访问层：schema 初始化 + 基础读写。"""
import sqlite3
import json
from pathlib import Path
from typing import Optional

from . import config


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filename    TEXT UNIQUE NOT NULL,
    width       INTEGER,
    height      INTEGER,
    n_faces     INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS faces (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id    INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    face_order  INTEGER NOT NULL,          -- 从左到右序号(0起)
    bbox        TEXT NOT NULL,             -- json [x1,y1,x2,y2]
    det_score   REAL,
    embedding   BLOB NOT NULL,             -- float32 512维 原始字节
    person_id   INTEGER,                   -- 聚类后所属人物编号(persons.id)
    label_name  TEXT                       -- 匹配后回填的人名
);

-- 人物：编号(id)即每个聚类的序号，标注后写 name；skipped=1 表示"不认识/跳过"
CREATE TABLE IF NOT EXISTS persons (
    id          INTEGER PRIMARY KEY,       -- 聚类编号 1,2,3...
    name        TEXT,                      -- 标注后回填的真名
    n_faces     INTEGER DEFAULT 0,         -- 该聚类含多少张脸
    centroid    BLOB,                      -- float32 512维 平均向量(重认领用)
    skipped     INTEGER DEFAULT 0,         -- 1=标注时跳过(不认识)
    claimed_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_faces_photo ON faces(photo_id);
CREATE INDEX IF NOT EXISTS idx_faces_label ON faces(label_name);
"""


def _migrate(conn):
    """对早期库做平滑迁移：补 faces.person_id / persons.skipped；建 person 索引。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(faces)")}
    if "person_id" not in cols:
        conn.execute("ALTER TABLE faces ADD COLUMN person_id INTEGER")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_faces_person ON faces(person_id)")
    pcols = {r["name"] for r in conn.execute("PRAGMA table_info(persons)")}
    if pcols and "skipped" not in pcols:
        conn.execute("ALTER TABLE persons ADD COLUMN skipped INTEGER DEFAULT 0")


def init_db():
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


def insert_photo(conn, filename: str, width: int, height: int, n_faces: int) -> int:
    cur = conn.execute(
        "INSERT INTO photos(filename,width,height,n_faces) VALUES(?,?,?,?)",
        (filename, width, height, n_faces),
    )
    return cur.lastrowid


def insert_face(conn, photo_id, face_order, bbox, det_score, embedding_bytes):
    conn.execute(
        "INSERT INTO faces(photo_id,face_order,bbox,det_score,embedding) "
        "VALUES(?,?,?,?,?)",
        (photo_id, face_order, json.dumps(bbox), float(det_score), embedding_bytes),
    )


def photo_exists(conn, filename: str) -> bool:
    row = conn.execute("SELECT 1 FROM photos WHERE filename=?", (filename,)).fetchone()
    return row is not None


def reset_persons(conn):
    """清空人物聚类结果（重跑聚类前）。"""
    conn.execute("DELETE FROM persons")
    conn.execute("UPDATE faces SET person_id=NULL")
    conn.commit()


def insert_person(conn, person_id: int, n_faces: int, centroid_bytes: bytes):
    conn.execute(
        "INSERT INTO persons(id,n_faces,centroid) VALUES(?,?,?)",
        (person_id, n_faces, centroid_bytes),
    )


def set_face_person(conn, face_id: int, person_id: int):
    conn.execute("UPDATE faces SET person_id=? WHERE id=?", (person_id, face_id))


def claim_person(conn, person_id: int, name: str):
    """把聚类标注为真名（清除 skipped），并回填该聚类所有脸的 label_name。"""
    conn.execute(
        "UPDATE persons SET name=?, skipped=0, claimed_at=datetime('now') WHERE id=?",
        (name, person_id),
    )
    conn.execute("UPDATE faces SET label_name=? WHERE person_id=?", (name, person_id))
    conn.commit()


def skip_person(conn, person_id: int):
    """把聚类标记为'不认识/跳过'：清名字、置 skipped=1。"""
    conn.execute(
        "UPDATE persons SET name=NULL, skipped=1, claimed_at=datetime('now') WHERE id=?",
        (person_id,),
    )
    conn.execute("UPDATE faces SET label_name=NULL WHERE person_id=?", (person_id,))
    conn.commit()


def unlabel_person(conn, person_id: int):
    """撤销标注：清名字、skipped=0，回到未标注状态。"""
    conn.execute(
        "UPDATE persons SET name=NULL, skipped=0, claimed_at=NULL WHERE id=?",
        (person_id,),
    )
    conn.execute("UPDATE faces SET label_name=NULL WHERE person_id=?", (person_id,))
    conn.commit()


def merge_persons(conn, src_id: int, dst_id: int):
    """把 src 聚类并入 dst：迁移所有脸的 person_id，删除 src，更新 dst.n_faces。"""
    if src_id == dst_id:
        return
    conn.execute("UPDATE faces SET person_id=? WHERE person_id=?", (dst_id, src_id))
    conn.execute("DELETE FROM persons WHERE id=?", (src_id,))
    n = conn.execute(
        "SELECT COUNT(*) c FROM faces WHERE person_id=?", (dst_id,)
    ).fetchone()["c"]
    conn.execute("UPDATE persons SET n_faces=? WHERE id=?", (n, dst_id))
    conn.commit()


if __name__ == "__main__":
    init_db()
    print(f"DB initialized at {config.DB_PATH}")
