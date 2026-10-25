/* PDF 책 만들기 — 화면 스크립트 */

const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  token: localStorage.getItem("pdfbook_token") || "",
  names: [],
  order: [],          // 드래그 중 임시 순서
  dragIndex: null,
  selected: localStorage.getItem("pdfbook_selected") || "",
  busy: false,
};

/* ───────── 공통 ───────── */

function toast(msg, kind = "") {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast is-on" + (kind ? " " + kind : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.className = "toast"; }, 2600);
}

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (state.token) headers.Authorization = "Bearer " + state.token;

  const res = await fetch(path, { ...opts, headers });
  if (!res.ok) {
    let msg = "요청을 처리하지 못했습니다.";
    try {
      const d = await res.json();
      msg = d.error || d.detail || msg;
    } catch (_) {}
    toast(msg, "is-warn");
    throw new Error(msg);
  }
  return res;
}

/* ───────── 로그인 ───────── */

function openApp() {
  $("#gate").hidden = true;
  $("#app").hidden = false;
  refresh();
}

$("#gateForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const pw = $("#password").value;
  try {
    const res = await api("/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: pw }),
    });
    const data = await res.json();
    state.token = data.token || "";
    localStorage.setItem("pdfbook_token", state.token);
    openApp();
  } catch (_) {
    $("#password").select();
  }
});

$("#logoutBtn").addEventListener("click", () => {
  localStorage.removeItem("pdfbook_token");
  state.token = "";
  $("#app").hidden = true;
  $("#gate").hidden = false;
  $("#password").value = "";
  $("#password").focus();
});

/* ───────── 설정: 분절 버튼 ───────── */

$$(".seg").forEach((seg) => {
  seg.addEventListener("click", (e) => {
    const btn = e.target.closest(".seg-btn");
    if (!btn) return;
    seg.querySelectorAll(".seg-btn").forEach((b) => b.classList.toggle("is-on", b === btn));
    if (!btn.dataset.size) return;                    /* 이미지 맞춤 분절은 여기서 끝 */
    const custom = seg.parentElement && seg.parentElement.querySelector(".custom-size");
    if (custom) custom.hidden = btn.dataset.size !== "CUSTOM";
    if (btn.dataset.size === "CUSTOM") syncCustomSize();
  });
});

const pageSize  = () => ($('.seg-btn[data-size].is-on')?.dataset.size) || "A4";
const fitMode   = () => ($('.seg-btn[data-fit].is-on')?.dataset.fit) || "contain";

/* 사용자 지정 페이지 크기: 가로(mm) + 세로는 첫 페이지 비율로 자동 */
const pageW = $("#pageW");
const pageH = $("#pageH");
const useFirstRatio = $("#useFirstRatio");
const customRatioEl = $("#customRatio");

const gcd = (a, b) => (b ? gcd(b, a % b) : a);

function firstRatio() {                  /* 첫 페이지의 세로/가로 비율 (없으면 null) */
  const img = $(".page-grid .card img") || $(".card img");
  if (!img || !img.naturalWidth || !img.naturalHeight) return null;
  return img.naturalHeight / img.naturalWidth;
}

function updateCustomRatio() {
  const w = parseFloat(pageW && pageW.value);
  const h = parseFloat(pageH && pageH.value);
  if (!w || !h) {
    customRatioEl.textContent = "가로 · 세로 를 mm 단위로 입력하세요";
    return;
  }
  const rw = Math.round(w), rh = Math.round(h), g = gcd(rw, rh) || 1;
  let text = "가로 " + w + " × 세로 " + h + " mm · 비율 " + (rw / g) + ":" + (rh / g);
  const auto = useFirstRatio && useFirstRatio.checked;
  if (auto) text += firstRatio() ? " (첫 페이지 기준)" : " · 이미지를 올리면 첫 페이지 비율로 맞춥니다";
  customRatioEl.textContent = text;
}

function syncCustomSize() {
  if (!pageW || !pageH) return;
  if (useFirstRatio && useFirstRatio.checked) {
    pageH.readOnly = true;
    const r = firstRatio();
    if (r) {
      const w = parseFloat(pageW.value) || 210;
      pageH.value = String(Math.round(w * r * 10) / 10);
    }
  } else {
    pageH.readOnly = false;
  }
  updateCustomRatio();
}

pageW && pageW.addEventListener("input", syncCustomSize);
pageH && pageH.addEventListener("input", updateCustomRatio);
useFirstRatio && useFirstRatio.addEventListener("change", syncCustomSize);
syncCustomSize();

/* ───────── 업로드 ───────── */

async function uploadFiles(fileList, insertAt = -1) {
  const files = Array.from(fileList || []).filter((f) => f.type.startsWith("image/"));
  if (!files.length) {
    toast("이미지 파일이 없습니다.", "is-warn");
    return;
  }

  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  form.append("insert_at", String(insertAt));

  toast(files.length + "장 올리는 중…");
  await api("/upload", { method: "POST", body: form });
  toast(files.length + "장 추가됨", "is-good");
  $("#fileInput").value = "";
  refresh();
}

$("#fileInput").addEventListener("change", (e) => uploadFiles(e.target.files));
$("#fileInputM").addEventListener("change", (e) => uploadFiles(e.target.files));

/* ───────── 드롭존 ───────── */

const drop = $("#dropZone");
let dragDepth = 0;

["dragenter", "dragover", "dragleave", "drop"].forEach((ev) => {
  drop.addEventListener(ev, (e) => { e.preventDefault(); e.stopPropagation(); });
});

drop.addEventListener("dragenter", () => {
  dragDepth++;
  drop.classList.add("is-over");
});
drop.addEventListener("dragleave", () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) drop.classList.remove("is-over");
});
drop.addEventListener("drop", (e) => {
  dragDepth = 0;
  drop.classList.remove("is-over");
  uploadFiles(e.dataTransfer?.files);
});

// 창 전체로 파일을 끌어와도 업로드
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => {
  e.preventDefault();
  if (e.dataTransfer?.files?.length) uploadFiles(e.dataTransfer.files);
});

/* ───────── 좌측 미리보기 (선택한 페이지) ───────── */

const stageImg = $("#stageImg");
const stageEmpty = $("#stageEmpty");
const stageNo = $("#stageNo");
const stageName = $("#stageName");
const stageFrame = $("#stageFrame");
const sheet = $("#sheet");
const sheetImg = $("#sheetImg");
const sheetInfo = $("#sheetInfo");
const cropInputs = $$("#cropBox input[data-side]");

/* PDF 만들기와 미리보기가 똑같은 설정을 쓴다 */
function buildSettings() {
  return {
    page_size: pageSize(),
    custom_w: String(parseFloat($("#pageW").value) || 0),
    custom_h: String(parseFloat($("#pageH").value) || 0),
    custom_auto: ($("#useFirstRatio") && $("#useFirstRatio").checked) ? "true" : "false",
    first_page_as_base: $("#firstPageBase").checked ? "true" : "false",
    fit: fitMode(),
    crop_whitespace: $("#cropWhitespace").checked ? "true" : "false",
  };
}

let layoutSeq = 0;
state.layout = null;

/* 서버가 계산한 배치(mm)를 받아 흰 종이 위에 그대로 그린다 */
async function loadLayout() {
  const name = state.selected;
  if (!name) return;
  const seq = ++layoutSeq;
  let L;
  try {
    const qs = new URLSearchParams(buildSettings()).toString();
    L = await (await api("/layout/" + encodeURIComponent(name) + "?" + qs)).json();
  } catch (_) { return; }
  if (seq !== layoutSeq) return;          /* 그 사이 다른 페이지를 골랐으면 버림 */
  state.layout = L;
  cropInputs.forEach((inp) => {
    if (document.activeElement !== inp) inp.value = String(L.crop[inp.dataset.side] || 0);
  });
  $("#cropOrig").textContent = "원본 " + L.orig_w + " × " + L.orig_h + " px";
  drawSheet();
}

function drawSheet() {
  const L = state.layout;
  if (!L || !sheet || sheet.hidden) return;

  const bw = L.box[2] - L.box[0], bh = L.box[3] - L.box[1];
  const cut = L.box[0] > 0 || L.box[1] > 0 || L.box[2] < L.orig_w || L.box[3] < L.orig_h;

  /* 보여 줄 범위(mm): 종이 + (자르기가 있으면) 잘려 나가는 원본 부분까지 */
  const ux = L.img_w / bw, uy = L.img_h / bh;            /* 원본 1px → mm */
  const x0 = (L.page_w - L.img_w) / 2 - L.box[0] * ux, y0 = (L.page_h - L.img_h) / 2 - L.box[1] * uy;
  const minX = cut ? Math.min(0, x0) : 0, maxX = cut ? Math.max(L.page_w, x0 + L.orig_w * ux) : L.page_w;
  const minY = cut ? Math.min(0, y0) : 0, maxY = cut ? Math.max(L.page_h, y0 + L.orig_h * uy) : L.page_h;

  /* 그 범위를 미리보기 칸 안에 비율대로 최대 크기로 */
  const fw = stageFrame.clientWidth - 24, fh = stageFrame.clientHeight - 24;
  const k = Math.min(fw / (maxX - minX), fh / (maxY - minY));   /* mm → 화면 px */
  sheet.style.width = L.page_w * k + "px";
  sheet.style.height = L.page_h * k + "px";
  sheet.style.overflow = cut ? "visible" : "hidden";
  sheet.style.transform = "translate(" + -((minX + maxX) / 2 - L.page_w / 2) * k + "px," +
    -((minY + maxY) / 2 - L.page_h / 2) * k + "px)";

  /* 이미지 칸 = PDF에 놓이는 크기, 그 안에 잘라낸 영역만 보이게 */
  const iw = L.img_w * k, ih = L.img_h * k;
  sheetImg.style.width = iw + "px";
  sheetImg.style.height = ih + "px";
  const sx = iw / bw, sy = ih / bh;
  stageImg.style.width = L.orig_w * sx + "px";
  stageImg.style.height = L.orig_h * sy + "px";
  stageImg.style.left = -L.box[0] * sx + "px";
  stageImg.style.top = -L.box[1] * sy + "px";

  /* 자르기가 있으면 원본 전체를 보여 주고, 남는 영역을 실선으로 표시 */
  const mark = $("#cropMark");
  sheetImg.style.overflow = cut ? "visible" : "hidden";
  mark.hidden = !cut;
  if (cut) {
    mark.style.left = (L.page_w * k - iw) / 2 + "px";
    mark.style.top = (L.page_h * k - ih) / 2 + "px";
    mark.style.width = iw + "px";
    mark.style.height = ih + "px";
  }

  const f1 = (v) => (Math.round(v * 10) / 10).toString();
  const mx = (L.page_w - L.img_w) / 2, my = (L.page_h - L.img_h) / 2;
  sheetInfo.textContent = "페이지 " + f1(L.page_w) + " × " + f1(L.page_h) + " mm · 이미지 " +
    f1(Math.min(L.img_w, L.page_w)) + " × " + f1(Math.min(L.img_h, L.page_h)) + " mm" +
    (mx >= 0.05 || my >= 0.05 ? " · 여백 좌우 " + f1(Math.max(0, mx)) + " / 위아래 " + f1(Math.max(0, my)) + " mm" : " · 여백 없음");
}

window.addEventListener("resize", drawSheet);

function paintStage() {
  const name = state.selected && state.names.includes(state.selected) ? state.selected : "";

  if (!name) {
    if (sheet) sheet.hidden = true;
    if (stageImg) stageImg.removeAttribute("src");
    if (stageEmpty) stageEmpty.hidden = false;
    if (stageNo) stageNo.textContent = "—";
    if (stageName) stageName.textContent = "—";
    if (sheetInfo) sheetInfo.textContent = "—";
    return;
  }

  const idx = state.names.indexOf(name);
  const src = "/view/" + encodeURIComponent(name);
  if (stageImg.getAttribute("src") !== src) {
    stageImg.src = src;
    state.layout = null;
  }
  sheet.hidden = false;
  if (stageEmpty) stageEmpty.hidden = true;
  if (stageNo) stageNo.textContent = String(idx + 1).padStart(2, "0") + " / " + state.names.length;
  if (stageName) stageName.textContent = name;

  $$(".card").forEach((c) => c.classList.toggle("is-active", c.dataset.name === name));
  drawSheet();
  loadLayout();
}

/* 설정이 바뀌면 미리보기 다시 계산 */
$$(".seg").forEach((seg) => seg.addEventListener("click", () => setTimeout(loadLayout, 0)));
["#pageW", "#pageH", "#useFirstRatio", "#firstPageBase", "#cropWhitespace"].forEach((sel) => {
  const el = $(sel);
  el && el.addEventListener("change", loadLayout);
});

/* 자르기: 입력이 멈추면 저장 → 미리보기 갱신 */
let cropTimer = null;
async function saveCrop(values) {
  if (!state.selected) return;
  await api("/crop/" + encodeURIComponent(state.selected), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(values),
  });
  loadLayout();
}
function cropValues() {
  const v = {};
  cropInputs.forEach((inp) => { v[inp.dataset.side] = Math.max(0, parseInt(inp.value, 10) || 0); });
  return v;
}
cropInputs.forEach((inp) => inp.addEventListener("input", () => {
  clearTimeout(cropTimer);
  cropTimer = setTimeout(() => saveCrop(cropValues()), 350);
}));
/* −/+ 버튼: 10px씩, Shift 누르면 1px씩 */
$$("#cropBox button[data-step]").forEach((btn) => btn.addEventListener("click", (e) => {
  const inp = btn.parentElement.querySelector("input");
  const step = Number(btn.dataset.step) * (e.shiftKey ? 1 : 10);
  inp.value = String(Math.max(0, (parseInt(inp.value, 10) || 0) + step));
  inp.dispatchEvent(new Event("input"));
}));

$("#cropReset").addEventListener("click", () => {
  cropInputs.forEach((inp) => { inp.value = "0"; });
  saveCrop({ l: 0, t: 0, r: 0, b: 0 });
});

function selectPage(name) {
  state.selected = name || "";
  try { localStorage.setItem("pdfbook_selected", state.selected); } catch (_) {}
  paintStage();
}

function stepPage(step) {
  if (!state.names.length) return;
  const cur = state.names.indexOf(state.selected);
  const next = cur < 0 ? 0 : Math.min(state.names.length - 1, Math.max(0, cur + step));
  selectPage(state.names[next]);
  const card = $$(".card").find((c) => c.dataset.name === state.names[next]);
  if (card) card.scrollIntoView({ block: "nearest" });
}

$("#stagePrev") && $("#stagePrev").addEventListener("click", () => stepPage(-1));
$("#stageNext") && $("#stageNext").addEventListener("click", () => stepPage(1));

document.addEventListener("keydown", (e) => {
  const app = $("#app");
  if (!app || app.hidden) return;
  const t = e.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
  if (e.key === "ArrowLeft") { e.preventDefault(); stepPage(-1); }
  if (e.key === "ArrowRight") { e.preventDefault(); stepPage(1); }
});

/* ───────── PC에서 끌어온 파일을 원하는 자리에 끼워 넣기 ───────── */

const isFileDrag = (e) => state.dragIndex === null && Array.from(e.dataTransfer?.types || []).includes("Files");

/* 마우스 위치 기준 삽입 자리: 카드 가운데보다 위면 그 카드 앞 */
function insertIndexAt(y) {
  const cards = $$("#pageGrid .card");
  for (let i = 0; i < cards.length; i++) {
    const r = cards[i].getBoundingClientRect();
    if (y < r.top + r.height / 2) return i;
  }
  return cards.length;
}

function showInsertMark(at) {
  const cards = $$("#pageGrid .card");
  cards.forEach((c, i) => {
    c.classList.toggle("is-insert-before", i === at);
    c.classList.toggle("is-insert-after", at === cards.length && i === cards.length - 1);
  });
}

const pageGridEl = $("#pageGrid");
pageGridEl.addEventListener("dragover", (e) => {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = "copy";
  showInsertMark(insertIndexAt(e.clientY));
});
pageGridEl.addEventListener("dragleave", (e) => {
  if (!pageGridEl.contains(e.relatedTarget)) showInsertMark(-1);
});
pageGridEl.addEventListener("drop", (e) => {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  e.stopPropagation();
  const at = insertIndexAt(e.clientY);
  showInsertMark(-1);
  uploadFiles(e.dataTransfer.files, at);
});

/* ───────── 목록 ───────── */

function cardEl(name, index) {
  const li = document.createElement("li");
  li.className = "card";
  li.draggable = true;
  li.dataset.index = String(index);
  li.dataset.name = name;
  li.title = name;

  const no = String(index + 1).padStart(2, "0");

  li.innerHTML = `
    <div class="card-frame">
      <span class="card-no">${no}</span>
      <button class="card-del" type="button" title="이 페이지 삭제" aria-label="${name} 삭제">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round">
          <path d="M18 6 6 18M6 6l12 12"/>
        </svg>
      </button>
      <img alt="" loading="lazy" />
    </div>
    <div class="card-name"></div>
  `;

  li.querySelector(".card-name").textContent = name;

  /* 카드를 누르면 좌측 미리보기에 이 페이지를 띄운다 */
  li.addEventListener("click", () => selectPage(name));
  if (state.selected === name) li.classList.add("is-active");

  const img = li.querySelector("img");
  const skeleton = document.createElement("div");
  skeleton.className = "card-skeleton";
  li.querySelector(".card-frame").appendChild(skeleton);

  img.addEventListener("load", () => {
    skeleton.remove();
    if (index === 0) syncCustomSize();   /* 첫 페이지 비율이 잡히면 세로 자동 계산 */
  });
  img.addEventListener("error", () => {
    skeleton.remove();
    img.remove();
  });
  img.src = "/thumb/" + encodeURIComponent(name);

  li.querySelector(".card-del").addEventListener("click", async (e) => {
    e.stopPropagation();
    await api("/files/" + encodeURIComponent(name), { method: "DELETE" });
    toast("삭제했습니다.");
    refresh();
  });

  /* 드래그 순서 변경 */
  li.addEventListener("dragstart", (e) => {
    state.dragIndex = index;
    li.classList.add("is-dragging");
    e.dataTransfer.effectAllowed = "move";
    try { e.dataTransfer.setData("text/plain", name); } catch (_) {}
  });

  li.addEventListener("dragend", () => {
    state.dragIndex = null;
    li.classList.remove("is-dragging");
    $$(".card").forEach((c) => c.classList.remove("is-target"));
  });

  /* PC에서 끌어온 파일은 목록(#pageGrid)이 받는다 */
  li.addEventListener("dragover", (e) => {
    if (isFileDrag(e)) return;
    if (state.dragIndex === null || state.dragIndex === index) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    li.classList.add("is-target");
  });

  li.addEventListener("dragleave", () => li.classList.remove("is-target"));

  li.addEventListener("drop", async (e) => {
    if (isFileDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    li.classList.remove("is-target");

    const from = state.dragIndex;
    const to = index;
    if (from === null || from === to) return;

    const names = state.names.slice();
    const [moved] = names.splice(from, 1);
    names.splice(to, 0, moved);

    state.names = names;
    render();

    try {
      await api("/reorder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(names),
      });
      toast("순서를 저장했습니다.", "is-good");
    } catch (_) {
      refresh();
    }
  });

  return li;
}

function render() {
  const grid = $("#pageGrid");
  grid.innerHTML = "";

  state.names.forEach((name, i) => grid.appendChild(cardEl(name, i)));

  const n = state.names.length;

  /* 선택 유지: 없어졌으면 첫 페이지로 */
  if (!n) state.selected = "";
  else if (!state.names.includes(state.selected)) state.selected = state.names[0];
  try { localStorage.setItem("pdfbook_selected", state.selected); } catch (_) {}
  paintStage();
  $("#countText").textContent = n + "장";
  $("#emptyState").hidden = n > 0;

  const pill = $("#pillCount");
  pill.hidden = n === 0;
  pill.textContent = n + "장 준비됨";
}

async function refresh() {
  const res = await api("/files");
  const data = await res.json();
  state.names = data.files || [];
  render();
}

/* ───────── 전체를 파일 이름순으로 ───────── */

$("#sortNameBtn").addEventListener("click", async () => {
  if (!state.names.length) return;
  if (!confirm("지금 순서를 버리고 파일 이름순으로 다시 정렬할까요?")) return;
  await api("/sort-by-name", { method: "POST" });
  toast("파일 이름순으로 정렬했습니다.", "is-good");
  refresh();
});

/* ───────── 전체 삭제 ───────── */

$("#clearBtn").addEventListener("click", async () => {
  if (!state.names.length) {
    toast("비울 페이지가 없습니다.");
    return;
  }
  if (!confirm("페이지 " + state.names.length + "장을 모두 삭제할까요? 되돌릴 수 없습니다.")) return;
  await api("/clear", { method: "POST" });
  toast("모두 비웠습니다.");
  refresh();
});

/* ───────── PDF 만들기 ───────── */

$$(".js-build").forEach((buildBtn) => buildBtn.addEventListener("click", async () => {
  if (state.busy) return;
  if (!state.names.length) {
    toast("먼저 이미지를 올려주세요.", "is-warn");
    return;
  }

  const btn = buildBtn;
  const label = btn.querySelector(".btn-label");
  const labelText = label.textContent;
  state.busy = true;
  btn.classList.add("is-busy");
  btn.disabled = true;
  label.textContent = "만드는 중…";

  try {
    const form = new FormData();
    form.append("title", $("#title").value.trim());
    Object.entries(buildSettings()).forEach(([k, v]) => form.append(k, v));

    const res = await api("/build", { method: "POST", body: form });
    const blob = await res.blob();

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = ($("#title").value.trim() || "book") + ".pdf";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);

    toast(state.names.length + "장 · PDF 다운로드 시작", "is-good");
  } catch (_) {
    toast("PDF를 만들지 못했습니다.", "is-warn");
  } finally {
    state.busy = false;
    btn.classList.remove("is-busy");
    btn.disabled = false;
    label.textContent = labelText;
  }
}));

/* ───────── 시작 ───────── */

/* 비밀번호 화면 없이 바로 시작 */
(function boot() {
  $("#logoutBtn").style.display = "none";
  openApp();
})();
