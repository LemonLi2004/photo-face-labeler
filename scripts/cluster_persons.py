"""人脸聚类与人物编号分配。

流程：
  1. 取全库所有脸向量(已归一化)。
  2. 用并查集 + 相似度阈值把同一人的脸连成一个簇
     （连接策略：每张脸与其相似且 >=CLUSTER_THRESHOLD 的脸相连）。
  3. 按"首次出现顺序"给每个簇分配人物编号 1,2,3...
     首次出现 = 该簇中 (photo.filename, face_order) 最小的那张脸。
  4. 写 persons 表(含质心) 和 faces.person_id。
  5. 重跑后用上一轮"已标注/已跳过"的质心自动重认领（名字/跳过状态写回新聚类）。

用法：
  python -m scripts.cluster_persons
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config, db, matcher


class DSU:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def load_faces():
    """返回 face 元数据 + 向量矩阵，按 face.id 顺序。"""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT f.id, f.embedding, f.face_order, p.filename "
            "FROM faces f JOIN photos p ON f.photo_id=p.id ORDER BY f.id"
        ).fetchall()
    finally:
        conn.close()
    ids = [r["id"] for r in rows]
    filenames = [r["filename"] for r in rows]
    orders = [r["face_order"] for r in rows]
    if not rows:
        return ids, filenames, orders, np.zeros((0, 512), np.float32)
    mat = np.stack(
        [np.frombuffer(r["embedding"], dtype=np.float32) for r in rows]
    ).astype(np.float32)
    return ids, filenames, orders, mat


def cluster(mat, threshold):
    """并查集聚类：相似度 >= threshold 的脸对相连。"""
    n = mat.shape[0]
    dsu = DSU(n)
    if n == 0:
        return dsu
    S = mat @ mat.T
    np.fill_diagonal(S, -1.0)
    # 对每张脸，连接所有 >=阈值 的脸（传递闭包由并查集保证）
    for i in range(n):
        js = np.where(S[i] >= threshold)[0]
        for j in js:
            if j > i:
                dsu.union(i, int(j))
    return dsu


def auto_reclaim(conn, snapshot):
    """用上一轮标注快照给新聚类自动重认领名字 / 跳过状态。

    snapshot: List[(name, skipped, centroid)]，来自重置前的 persons。
    对每条历史标注，找与之最相似的新聚类质心，>=RECLAIM_THRESHOLD 则套用。
    """
    if not snapshot:
        return 0
    prows = conn.execute(
        "SELECT id, centroid FROM persons WHERE centroid IS NOT NULL"
    ).fetchall()
    if not prows:
        return 0
    pids = [r["id"] for r in prows]
    pmat = np.stack(
        [np.frombuffer(r["centroid"], dtype=np.float32) for r in prows]
    ).astype(np.float32)

    reclaimed = 0
    taken = set()
    for name, skipped, emb in snapshot:
        sims = pmat @ emb
        order = np.argsort(-sims)
        for k in order:
            k = int(k)
            if sims[k] < config.RECLAIM_THRESHOLD:
                break
            if pids[k] in taken:
                continue
            if skipped:
                db.skip_person(conn, pids[k])
            elif name:
                db.claim_person(conn, pids[k], name)
            taken.add(pids[k])
            reclaimed += 1
            break
    return reclaimed


def main():
    db.init_db()
    ids, filenames, orders, mat = load_faces()
    n = len(ids)
    print(f"Loaded {n} faces.")
    if n == 0:
        print("No faces; run build_index first.")
        return

    dsu = cluster(mat, config.CLUSTER_THRESHOLD)

    # 收集簇 -> 成员索引
    clusters = {}
    for i in range(n):
        root = dsu.find(i)
        clusters.setdefault(root, []).append(i)

    # 每个簇的"首次出现"键：(filename, face_order) 最小
    def first_key(members):
        return min((filenames[i], orders[i]) for i in members)

    ordered = sorted(clusters.values(), key=first_key)

    conn = db.get_conn()
    try:
        snapshot = matcher.labeled_snapshot(conn)  # 重置前先存住上一轮标注
        db.reset_persons(conn)
        for new_id, members in enumerate(ordered, start=1):
            centroid = mat[members].mean(axis=0)
            norm = np.linalg.norm(centroid)
            if norm > 0:
                centroid = centroid / norm
            db.insert_person(conn, new_id, len(members), centroid.astype(np.float32).tobytes())
            for i in members:
                db.set_face_person(conn, ids[i], new_id)
        conn.commit()

        n_persons = len(ordered)
        sizes = sorted((len(m) for m in ordered), reverse=True)
        print(f"Clustered into {n_persons} persons (编号 1..{n_persons}).")
        print(f"  top cluster sizes: {sizes[:10]}")
        print(f"  singletons (只出现1次): {sum(1 for s in sizes if s == 1)}")

        reclaimed = auto_reclaim(conn, snapshot)
        if reclaimed:
            print(f"  auto-reclaimed {reclaimed} labels from previous annotation.")
    finally:
        conn.close()

    from backend import naming
    out = naming.export_json()
    print(f"  face-order record -> {out}")


if __name__ == "__main__":
    main()
