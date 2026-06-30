"use strict";

const $ = (id) => document.getElementById(id);
const api = (url, opts) => fetch(url, opts);

let clusters = [];
let mergeSrc = null; // 待合并的源聚类 person_id

// ---------- 加载 ----------
async function loadAll() {
  const [cRes, sRes] = await Promise.all([
    api("/api/clusters"),
    api("/api/stats"),
  ]);
  clusters = await cRes.json();
  renderStats(await sRes.json());
  renderBoard();
}

function renderStats(s) {
  $("stats").innerHTML =
    `共 <b>${s.clusters_total}</b> 个聚类 · ` +
    `已命名 <b class="ok">${s.clusters_named}</b> · ` +
    `跳过 <b class="muted">${s.clusters_skipped}</b> · ` +
    `待处理 <b class="warn">${s.clusters_todo}</b> · ` +
    `去重后 <b>${s.distinct_people}</b> 人`;
}

async function refreshStats() {
  const s = await (await api("/api/stats")).json();
  renderStats(s);
}

// ---------- 看板渲染 ----------
function renderBoard() {
  const board = $("board");
  const hideHandled = $("hideHandled").checked;
  board.innerHTML = "";
  const shown = clusters.filter((c) => !(hideHandled && c.status !== "todo"));
  $("empty").classList.toggle("hidden", clusters.length > 0);

  shown.forEach((c) => board.appendChild(renderCluster(c)));
}

function renderCluster(c) {
  const card = document.createElement("div");
  card.className = `cluster status-${c.status}`;
  card.dataset.pid = c.person_id;

  // 头部：编号 + 状态徽标 + 张数
  const head = document.createElement("div");
  head.className = "cluster-head";
  const badge = document.createElement("span");
  if (c.status === "named") {
    badge.className = "tag ok clickable";
    badge.textContent = c.name;
    badge.title = "点击查看全部照片";
    badge.addEventListener("click", () => openGallery(c));
  } else if (c.status === "skipped") {
    badge.className = "tag muted";
    badge.textContent = "已跳过";
  } else {
    badge.className = "tag warn";
    badge.textContent = "待处理";
  }
  const pidSpan = document.createElement("span");
  pidSpan.className = "pid";
  pidSpan.textContent = `#${c.person_id}`;
  const nSpan = document.createElement("span");
  nSpan.className = "nfaces";
  nSpan.textContent = `${c.n_faces} 张脸`;
  head.appendChild(pidSpan);
  head.appendChild(badge);
  head.appendChild(nSpan);
  card.appendChild(head);

  // 人脸样本图
  const faces = document.createElement("div");
  faces.className = "faces";
  c.samples.forEach((f) => {
    const im = document.createElement("img");
    im.loading = "lazy";
    im.src = `/api/face_crop/${f.face_id}`;
    im.title = `照片 ${f.photo_id} · 第 ${f.face_order + 1} 个脸`;
    im.addEventListener("click", () => openLightbox(f.photo_id, c));
    faces.appendChild(im);
  });
  card.appendChild(faces);

  // 操作区：命名输入 + 跳过 + 查看全部 + 合并
  const ops = document.createElement("div");
  ops.className = "ops";

  const input = document.createElement("input");
  input.type = "text";
  input.maxLength = 40;
  input.placeholder = "输入名字…";
  input.value = c.name || "";
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") doName(c.person_id, input.value);
  });

  const saveBtn = btn("保存", "btn-primary sm", () => doName(c.person_id, input.value));
  const skipBtn = btn("跳过", "btn-ghost sm", () => doAction(c.person_id, "skip"));
  const seeBtn = btn("查看全部", "btn-ghost sm", () => openGallery(c));

  const row1 = document.createElement("div");
  row1.className = "op-row";
  row1.append(input, saveBtn);

  const row2 = document.createElement("div");
  row2.className = "op-row";
  row2.append(skipBtn, seeBtn);

  // 合并按钮：选源 -> 选目标
  const mergeBtn = btn(
    mergeSrc === c.person_id ? "取消合并" : "合并到…",
    mergeSrc === c.person_id ? "btn-ghost sm active" : "btn-ghost sm",
    () => onMergeClick(c.person_id)
  );
  if (mergeSrc !== null && mergeSrc !== c.person_id) {
    mergeBtn.textContent = `← 并入此处`;
    mergeBtn.className = "btn-primary sm";
  }
  row2.append(mergeBtn);

  if (c.status !== "todo") {
    const clearBtn = btn("撤销", "btn-ghost sm", () => doAction(c.person_id, "clear"));
    row2.append(clearBtn);
  }

  ops.append(row1, row2);
  card.appendChild(ops);
  return card;
}

function btn(text, cls, onClick) {
  const b = document.createElement("button");
  b.className = cls;
  b.textContent = text;
  b.addEventListener("click", onClick);
  return b;
}

// ---------- 标注动作 ----------
async function doName(pid, name) {
  name = (name || "").trim();
  if (!name) { toast("请输入名字", true); return; }
  const res = await api("/api/label", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ person_id: pid, action: "name", name }),
  });
  if (!res.ok) { toast((await res.json()).detail || "保存失败", true); return; }
  updateLocal(pid, { status: "named", name });
  toast(`#${pid} → ${name}`);
  refreshStats();
}

async function doAction(pid, action) {
  const res = await api("/api/label", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ person_id: pid, action }),
  });
  if (!res.ok) { toast("操作失败", true); return; }
  if (action === "skip") updateLocal(pid, { status: "skipped", name: null });
  if (action === "clear") updateLocal(pid, { status: "todo", name: null });
  refreshStats();
}

function updateLocal(pid, patch) {
  const c = clusters.find((x) => x.person_id === pid);
  if (c) Object.assign(c, patch);
  renderBoard();
}

// ---------- 合并 ----------
function onMergeClick(pid) {
  if (mergeSrc === null) {
    mergeSrc = pid;
    toast(`已选 #${pid} 为源，点目标聚类的「并入此处」`);
    renderBoard();
  } else if (mergeSrc === pid) {
    mergeSrc = null;
    renderBoard();
  } else {
    doMerge(mergeSrc, pid);
  }
}

async function doMerge(src, dst) {
  const res = await api("/api/merge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ src_id: src, dst_id: dst }),
  });
  if (!res.ok) { toast("合并失败", true); return; }
  mergeSrc = null;
  toast(`#${src} 已并入 #${dst}`);
  loadAll();
}

// ---------- 查看该人全部照片（平铺视图） ----------
let currentGallery = null;
async function openGallery(c) {
  currentGallery = c;
  $("galleryTitle").textContent = c.name ? c.name : `聚类 #${c.person_id}`;
  const zipUrl = c.name
    ? `/api/export/name.zip?name=${encodeURIComponent(c.name)}`
    : `/api/export/person/${c.person_id}.zip`;
  $("galleryZip").onclick = () => downloadUrl(zipUrl);

  const photos = await fetchPersonPhotos(c);
  $("galleryCount").textContent = `共 ${photos.length} 张`;
  const grid = $("galleryGrid");
  grid.innerHTML = "";
  photos.forEach((p) => {
    const cell = document.createElement("div");
    cell.className = "cell";
    const im = document.createElement("img");
    im.loading = "lazy";
    im.src = `/api/thumbnail/${p.photo_id}`;
    im.addEventListener("click", () => openLightbox(p.photo_id, c, p.filename));
    cell.appendChild(im);
    grid.appendChild(cell);
  });
  $("board").classList.add("hidden");
  $("empty").classList.add("hidden");
  $("gallery").classList.remove("hidden");
  window.scrollTo(0, 0);
}

function closeGallery() {
  $("gallery").classList.add("hidden");
  $("board").classList.remove("hidden");
  renderBoard();
  currentGallery = null;
}

// 取该人/该聚类涉及的照片列表（合照去重）。有名字则跨同名聚类合并。
async function fetchPersonPhotos(c) {
  const url = c.name
    ? `/api/photos/name?name=${encodeURIComponent(c.name)}`
    : `/api/photos/person/${c.person_id}`;
  const res = await api(url);
  if (!res.ok) return [];
  return res.json();
}

$("galleryBack").addEventListener("click", closeGallery);

// ---------- 灯箱（看合照原图） ----------
let lbPhoto = null;
function openLightbox(photoId, c, filename) {
  lbPhoto = { photoId, filename };
  $("lbImg").src = `/api/thumbnail/${photoId}`;
  $("lbInfo").textContent = filename ? filename : `照片 ${photoId}`;
  $("lightbox").classList.remove("hidden");
}
$("lbClose").addEventListener("click", () => $("lightbox").classList.add("hidden"));
$("lightbox").addEventListener("click", (e) => {
  if (e.target.id === "lightbox") $("lightbox").classList.add("hidden");
});
$("lbDownload").addEventListener("click", async () => {
  if (!lbPhoto) return;
  downloadUrl(`/api/original/${lbPhoto.photoId}?download=1`);
});

// ---------- 顶部动作 ----------
$("reloadBtn").addEventListener("click", loadAll);
$("hideHandled").addEventListener("change", renderBoard);
$("exportAllBtn").addEventListener("click", async () => {
  const btn = $("exportAllBtn");
  btn.disabled = true;
  btn.textContent = "导出中…";
  try {
    const res = await api("/api/export/all", { method: "POST" });
    const data = await res.json();
    toast(`已导出 ${data.people} 人 → ${data.dir}`);
  } catch (e) {
    toast("导出失败", true);
  } finally {
    btn.disabled = false;
    btn.textContent = "一键全导出";
  }
});

// ---------- 工具 ----------
function downloadUrl(url) {
  const a = document.createElement("a");
  a.href = url;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

let toastTimer = null;
function toast(msg, isErr) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast" + (isErr ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 2600);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

loadAll();
