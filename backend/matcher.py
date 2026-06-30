"""人物质心缓存（标注版）。

标注流程下不再做"自拍匹配"，matcher 只负责：
  - 加载 persons 质心矩阵到内存（聚类/合并后刷新）。
  - 提供已标注聚类的 (name, centroid) 快照，供重跑聚类时把标注结果"自动重认领"过去。
"""
import threading
from typing import List, Tuple

import numpy as np

from . import config, db

_LOCK = threading.Lock()
_PERSON_MAT = None  # (P,512) 人物质心
_PERSON_IDS = None  # (P,)


def load_index(force: bool = False):
    """加载人物质心矩阵。"""
    global _PERSON_MAT, _PERSON_IDS
    with _LOCK:
        if _PERSON_MAT is not None and not force:
            return
        _load_persons_locked()


def _load_persons_locked():
    global _PERSON_MAT, _PERSON_IDS
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, centroid FROM persons WHERE centroid IS NOT NULL ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    if rows:
        _PERSON_IDS = np.array([r["id"] for r in rows], dtype=np.int64)
        _PERSON_MAT = np.stack(
            [np.frombuffer(r["centroid"], dtype=np.float32) for r in rows]
        ).astype(np.float32)
    else:
        _PERSON_IDS = np.zeros((0,), dtype=np.int64)
        _PERSON_MAT = np.zeros((0, 512), dtype=np.float32)


def refresh_persons():
    """聚类/合并后刷新人物质心（无需重启）。"""
    with _LOCK:
        _load_persons_locked()


def labeled_snapshot(conn) -> List[Tuple[str, int, np.ndarray]]:
    """重跑聚类前的快照：已标注(name)聚类的 (name, skipped, centroid)。"""
    rows = conn.execute(
        "SELECT name, skipped, centroid FROM persons "
        "WHERE centroid IS NOT NULL AND "
        "((name IS NOT NULL AND name<>'') OR skipped=1)"
    ).fetchall()
    out = []
    for r in rows:
        out.append(
            (
                r["name"],
                int(r["skipped"] or 0),
                np.frombuffer(r["centroid"], dtype=np.float32),
            )
        )
    return out
