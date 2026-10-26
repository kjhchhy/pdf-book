from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
import shutil, secrets, re, os, base64, io, json, tempfile

from PIL import Image, ImageFilter
from weasyprint import HTML, CSS

app = FastAPI()

# 서버는 /opt/pdf-book, 로컬 테스트는 PDFBOOK_BASE 로 덮어쓴다
# 다른 앱(anime-manager)에 붙여 쓸 때는 PDFBOOK_UPLOADS 로 업로드 폴더만 따로 지정
BASE = Path(os.getenv("PDFBOOK_BASE", "/opt/pdf-book"))
HERE = Path(__file__).resolve().parent   # main.py 옆의 static/, templates/
UPLOAD_DIR = Path(os.getenv("PDFBOOK_UPLOADS") or BASE / "uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ORDER_FILE = UPLOAD_DIR / "_order.json"
CROP_FILE = UPLOAD_DIR / "_crop.json"   # {파일명: {l,t,r,b}} 픽셀 자르기

DPI = 200   # 이미지 픽셀 → mm 환산 기준

app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
templates = Jinja2Templates(directory=str(HERE / "templates"))

PASSWORD = os.getenv("PDFBOOK_PASSWORD", "")

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}

# 썸네일 메모리 캐시 (파일명 + mtime 기준)
_thumb_cache: dict[tuple[str, float], bytes] = {}
_view_cache: dict[tuple[str, float], bytes] = {}


def name_key(name: str):
    """파일 이름 자연 정렬: img2 < img10 (숫자는 숫자로, 글자는 대소문자 무시)."""
    return [(0, int(t), "") if t.isdigit() else (1, 0, t.lower()) for t in re.split(r"(\d+)", name) if t]


def sort_key(path: Path):
    return name_key(path.name)


def _load_order() -> list[str]:
    try:
        data = json.loads(ORDER_FILE.read_text("utf-8"))
        if isinstance(data, list):
            return [str(x) for x in data]
    except Exception:
        pass
    return []


def _save_order(names: list[str]) -> None:
    ORDER_FILE.write_text(json.dumps(names, ensure_ascii=False), "utf-8")


def _load_crops() -> dict:
    try:
        data = json.loads(CROP_FILE.read_text("utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_crops(crops: dict) -> None:
    CROP_FILE.write_text(json.dumps(crops, ensure_ascii=False), "utf-8")


def crop_box(p: Path, crop: dict | None, whitespace: bool) -> tuple[int, int, tuple[int, int, int, int]]:
    """원본 크기와, PDF에 실제로 쓰일 영역 (x0, y0, x1, y1) — 픽셀 자르기 후 흰 여백 자르기."""
    im = Image.open(p)
    ow, oh = im.size
    c = crop or {}
    x0 = min(max(0, int(c.get("l", 0))), ow - 1)
    y0 = min(max(0, int(c.get("t", 0))), oh - 1)
    x1 = max(x0 + 1, ow - max(0, int(c.get("r", 0))))
    y1 = max(y0 + 1, oh - max(0, int(c.get("b", 0))))
    if whitespace:
        part = im.crop((x0, y0, x1, y1)).convert("L").filter(ImageFilter.GaussianBlur(radius=1))
        bbox = part.point(lambda x: 0 if x >= 245 else 255, mode="1").getbbox()
        if bbox:
            x0, y0, x1, y1 = x0 + bbox[0], y0 + bbox[1], x0 + bbox[2], y0 + bbox[3]
    return ow, oh, (x0, y0, x1, y1)


def _image_files() -> list[Path]:
    """업로드 폴더의 실제 이미지 파일만."""
    out = []
    for p in UPLOAD_DIR.iterdir():
        if p.is_file() and p.suffix.lower() in IMAGE_EXT:
            out.append(p)
    return out


def ordered_files() -> list[Path]:
    """저장된 순서 → 신규(번호순) 순으로 정렬된 파일 목록."""
    files = {p.name: p for p in _image_files()}
    order = [n for n in _load_order() if n in files]

    # 순서 파일에 없는 새 파일은 번호순으로 뒤에 붙임
    remaining = [n for n in files if n not in set(order)]
    remaining.sort(key=lambda n: sort_key(files[n]))
    order = order + remaining

    # 사라진 파일 정리
    if order != _load_order():
        _save_order(order)

    return [files[n] for n in order]


def crop_whitespace_impl(p: Path):
    im = Image.open(p)
    if im.mode != "RGB":
        im = im.convert("RGB")
    gray = im.convert("L")
    blur = gray.filter(ImageFilter.GaussianBlur(radius=1))
    mask = blur.point(lambda x: 0 if x >= 245 else 255, mode="1")
    bbox = mask.getbbox()
    if bbox:
        return im.crop(bbox)
    return im


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # HTML은 절대 캐시하지 않는다 — JS/CSS 버전 쿼리만으로는
    # 오래된 HTML이 물려 있을 때 화면이 깨진다.
    return templates.TemplateResponse(
        # base: /pdf-book 처럼 하위 경로에 붙었을 때의 접두어 (단독 실행이면 "")
        request, "index.html", {"request": request, "base": request.scope.get("root_path", "")},
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


@app.post("/login")
async def login(request: Request):
    data = await request.json()
    if PASSWORD and data.get("password") != PASSWORD:
        return JSONResponse({"ok": False, "error": "비밀번호가 틀렸습니다."}, status_code=401)
    token = secrets.token_urlsafe(16)
    return JSONResponse({"ok": True, "token": token})


@app.post("/upload")
def upload(files: list[UploadFile] = File(...), insert_at: int = Form(-1)):
    saved = []
    for f in files:
        name = Path(f.filename or "").name
        if not name or Path(name).suffix.lower() not in IMAGE_EXT:
            continue
        dest = UPLOAD_DIR / name
        with dest.open("wb") as b:
            shutil.copyfileobj(f.file, b)
        _thumb_cache.pop((name, 0), None)
        _view_cache.pop((name, 0), None)
        saved.append(name)

    if saved:
        # 한 번에 올린 파일들은 파일 이름순으로
        saved = sorted(dict.fromkeys(saved), key=name_key)
        order = [p.name for p in ordered_files()]
        if insert_at >= 0:
            # 끌어놓은 위치에 끼워 넣기 (같은 이름이 있으면 그 자리로 옮김)
            pos = min(insert_at, len(order))
            pos -= sum(1 for n in order[:pos] if n in saved)
            order = [n for n in order if n not in saved]
            order[pos:pos] = saved
        else:
            known = set(order)
            order += [n for n in saved if n not in known]
        _save_order(order)

    return JSONResponse({"files": saved})


@app.get("/files")
def list_files():
    return JSONResponse({"files": [p.name for p in ordered_files()]})


@app.get("/thumb/{name}")
def thumb(name: str):
    p = UPLOAD_DIR / Path(name).name
    if not p.exists() or p.suffix.lower() not in IMAGE_EXT:
        raise HTTPException(404, "not found")

    key = (p.name, p.stat().st_mtime)
    cached = _thumb_cache.get(key)
    if cached is None:
        im = Image.open(p)
        im.thumbnail((420, 420))
        if im.mode != "RGB":
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=78, optimize=True)
        cached = buf.getvalue()
        if len(_thumb_cache) > 400:
            _thumb_cache.clear()
        _thumb_cache[key] = cached

    return Response(content=cached, media_type="image/jpeg",
                    headers={"Cache-Control": "max-age=3600"})


@app.get("/view/{name}")
def view(name: str):
    """좌측 미리보기용 큰 이미지 (최대 1400px)."""
    p = UPLOAD_DIR / Path(name).name
    if not p.exists() or p.suffix.lower() not in IMAGE_EXT:
        raise HTTPException(404, "not found")

    key = (p.name, p.stat().st_mtime)
    cached = _view_cache.get(key)
    if cached is None:
        im = Image.open(p)
        im.thumbnail((1400, 1400))
        if im.mode != "RGB":
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=86, optimize=True)
        cached = buf.getvalue()
        if len(_view_cache) > 60:
            _view_cache.clear()
        _view_cache[key] = cached

    return Response(content=cached, media_type="image/jpeg",
                    headers={"Cache-Control": "max-age=3600"})


@app.get("/preview")
def preview_files():
    out = []
    for p in ordered_files():
        try:
            im = Image.open(p)
            im.thumbnail((120, 120))
            if im.mode != "RGB":
                im = im.convert("RGB")
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=70)
            b64 = base64.b64encode(buf.getvalue()).decode()
            out.append({"name": p.name, "thumb": b64})
        except Exception:
            out.append({"name": p.name, "thumb": None})
    return JSONResponse({"items": out})


@app.post("/reorder")
def reorder(order: list[str]):
    existing = {p.name for p in _image_files()}
    clean = [n for n in order if n in existing]
    # 누락된 파일은 뒤에 붙여 유실 방지
    for n in existing:
        if n not in clean:
            clean.append(n)
    _save_order(clean)
    return JSONResponse({"ok": True, "order": clean})


@app.post("/sort-by-name")
def sort_by_name():
    """전체 페이지를 파일 이름순으로 다시 정렬."""
    names = sorted((p.name for p in _image_files()), key=name_key)
    _save_order(names)
    return JSONResponse({"ok": True, "order": names})


@app.delete("/files/{name}")
def delete_file(name: str):
    p = UPLOAD_DIR / Path(name).name
    if p.exists() and p.suffix.lower() in IMAGE_EXT:
        p.unlink()
    _save_order([n for n in _load_order() if n != p.name])
    crops = _load_crops()
    if crops.pop(p.name, None) is not None:
        _save_crops(crops)
    return JSONResponse({"ok": True})


@app.post("/clear")
def clear_files():
    for p in _image_files():
        p.unlink()
    _save_order([])
    _save_crops({})
    _thumb_cache.clear()
    _view_cache.clear()
    return JSONResponse({"ok": True})


@app.get("/crop/{name}")
def get_crop(name: str):
    return JSONResponse(_load_crops().get(Path(name).name, {"l": 0, "t": 0, "r": 0, "b": 0}))


@app.post("/crop/{name}")
async def set_crop(name: str, request: Request):
    """페이지별 상하좌우 픽셀 자르기 저장 (원본 이미지 기준)."""
    name = Path(name).name
    data = await request.json()
    c = {k: max(0, int(data.get(k) or 0)) for k in ("l", "t", "r", "b")}
    crops = _load_crops()
    if any(c.values()):
        crops[name] = c
    else:
        crops.pop(name, None)
    _save_crops(crops)
    return JSONResponse({"ok": True, "crop": c})


class Settings:
    """PDF 설정 — /build 와 /layout 이 같은 값을 같은 방식으로 해석한다."""

    PAGE_SIZES = {"A4": (210, 297), "A5": (148, 210), "Letter": (216, 279), "Legal": (216, 356)}

    def __init__(self, page_size="A4", custom_w=0.0, custom_h=0.0, custom_auto="true",
                 first_page_as_base="true", fit="contain", crop_whitespace="false"):
        self.page_size = page_size
        self.custom_w = float(custom_w or 0)
        self.custom_h = float(custom_h or 0)
        self.custom_auto = custom_auto == "true"
        self.first_page_as_base = first_page_as_base == "true"
        self.fit = fit
        self.crop_whitespace = crop_whitespace == "true"


def page_mm(files: list[Path], s: Settings, crops: dict) -> tuple[float, float]:
    """PDF 페이지 크기(mm). 비율 기준은 첫 이미지(자르기 반영)."""
    def first_size():
        _, _, box = crop_box(files[0], crops.get(files[0].name), s.crop_whitespace)
        return box[2] - box[0], box[3] - box[1]

    base_w, base_h = Settings.PAGE_SIZES.get(s.page_size, (210, 297))
    if s.page_size == "CUSTOM":
        base_w, base_h = s.custom_w, s.custom_h
        if s.custom_auto or base_h <= 0:
            try:
                fw, fh = first_size()
                base_h = round(s.custom_w * fh / fw, 1)
            except Exception:
                base_h = s.custom_h or 297
    elif s.first_page_as_base and files:
        try:
            fw, fh = first_size()
            base_w, base_h = fw * 25.4 / DPI, fh * 25.4 / DPI
        except Exception:
            pass
    return base_w, base_h


def image_mm(box_w: int, box_h: int, page_w: float, page_h: float, fit: str) -> tuple[float, float]:
    """페이지 안에 놓일 이미지 크기(mm). 비율 유지 = 원래 크기(200dpi)로, 넘치면 줄임 / 꽉 채우기 = 덮고 넘치는 부분은 잘림."""
    iw, ih = box_w * 25.4 / DPI, box_h * 25.4 / DPI
    if fit == "cover":
        s = max(page_w / iw, page_h / ih)
    else:
        s = min(1.0, page_w / iw, page_h / ih)
    return iw * s, ih * s


# 용량 줄이기: (페이지에 놓인 크기 기준 dpi, JPEG 품질). none 이면 원본을 그대로 넣는다
COMPRESS = {"normal": (200, 82), "strong": (130, 68)}


def compressed_jpeg(p: Path, box: tuple[int, int, int, int], w_mm: float, h_mm: float, level: str) -> bytes:
    """잘라낸 이미지를 놓일 크기에 맞춰 줄이고 JPEG 로 다시 저장한 바이트."""
    dpi, quality = COMPRESS[level]
    tw = max(1, round(w_mm / 25.4 * dpi))
    th = max(1, round(h_mm / 25.4 * dpi))
    im = Image.open(p)
    ow, oh = im.size
    # JPEG 는 처음부터 1/2·1/4·1/8 크기로 읽을 수 있다 (풀 해상도로 풀지 않아 훨씬 빠름)
    bw, bh = box[2] - box[0], box[3] - box[1]
    im.draft("RGB", (max(1, ow * tw // bw), max(1, oh * th // bh)))
    if im.size != (ow, oh):
        sx, sy = im.width / ow, im.height / oh
        box = (int(box[0] * sx), int(box[1] * sy), max(int(box[0] * sx) + 1, int(box[2] * sx)), max(int(box[1] * sy) + 1, int(box[3] * sy)))
    im = im.crop(box) if box != (0, 0, *im.size) else im
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.getchannel("A"))
        im = bg
    elif im.mode != "RGB":
        im = im.convert("RGB")
    if im.width > tw or im.height > th:
        im = im.resize((tw, th), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


_estimate_cache: dict[tuple, dict] = {}


@app.get("/estimate")
def estimate(page_size: str = "A4", custom_w: float = 0.0, custom_h: float = 0.0,
             custom_auto: str = "true", first_page_as_base: str = "true",
             fit: str = "contain", crop_whitespace: str = "false"):
    """압축 단계별 예상 PDF 용량(바이트). 몇 장만 실제로 줄여 보고 전체로 늘려 계산한다."""
    files = ordered_files()
    if not files:
        return JSONResponse({"count": 0, "none": 0, "normal": 0, "strong": 0})
    crops = _load_crops()
    key = (tuple((p.name, p.stat().st_mtime) for p in files), page_size, custom_w, custom_h, custom_auto,
           first_page_as_base, fit, crop_whitespace, json.dumps(crops, sort_keys=True))
    if key in _estimate_cache:
        return JSONResponse(_estimate_cache[key])

    s = Settings(page_size, custom_w, custom_h, custom_auto, first_page_as_base, fit, crop_whitespace)
    base_w, base_h = page_mm(files, s, crops)

    # 원본: 파일 크기 (직접 자른 만큼은 면적 비율로 줄여 셈)
    def orig_bytes(p: Path) -> float:
        size = p.stat().st_size
        c = crops.get(p.name)
        if c and any(c.values()):
            ow, oh = Image.open(p).size
            keep = max(1, ow - c.get("l", 0) - c.get("r", 0)) * max(1, oh - c.get("t", 0) - c.get("b", 0))
            size *= min(1.0, keep / (ow * oh))
        return size

    total = sum(orig_bytes(p) for p in files)

    # 표본: 고르게 최대 6장
    n = len(files)
    idx = sorted({round(i * (n - 1) / 5) for i in range(6)}) if n > 6 else range(n)
    sample_orig, sample = 0.0, {lvl: 0 for lvl in COMPRESS}
    for i in idx:
        p = files[i]
        _, _, box = crop_box(p, crops.get(p.name), s.crop_whitespace)
        w, h = image_mm(box[2] - box[0], box[3] - box[1], base_w, base_h, s.fit)
        sample_orig += orig_bytes(p)
        for lvl in COMPRESS:
            sample[lvl] += len(compressed_jpeg(p, box, w, h, lvl))

    overhead = 2000 * (n + 1)   # 페이지마다 붙는 PDF 구조 몫 (대략)
    out = {"count": n, "sampled": len(idx), "none": int(total + overhead)}
    for lvl in COMPRESS:
        out[lvl] = int(total * sample[lvl] / sample_orig + overhead) if sample_orig else 0
        out[lvl] = min(out[lvl], out["none"])   # 원본보다 커지지는 않게 (빌드에서도 같은 규칙)
    if len(_estimate_cache) > 20:
        _estimate_cache.clear()
    _estimate_cache[key] = out
    return JSONResponse(out)


@app.get("/layout/{name}")
def layout(name: str, page_size: str = "A4", custom_w: float = 0.0, custom_h: float = 0.0,
                 custom_auto: str = "true", first_page_as_base: str = "true",
                 fit: str = "contain", crop_whitespace: str = "false"):
    """미리보기용: 이 페이지가 PDF에서 어떻게 놓이는지 (mm, 원본 픽셀 기준 자르기 영역)."""
    files = ordered_files()
    p = UPLOAD_DIR / Path(name).name
    if p not in files:
        raise HTTPException(404, "not found")
    s = Settings(page_size, custom_w, custom_h, custom_auto, first_page_as_base, fit, crop_whitespace)
    crops = _load_crops()
    pw, ph = page_mm(files, s, crops)
    ow, oh, box = crop_box(p, crops.get(p.name), s.crop_whitespace)
    iw, ih = image_mm(box[2] - box[0], box[3] - box[1], pw, ph, s.fit)
    return JSONResponse({
        "page_w": pw, "page_h": ph, "img_w": iw, "img_h": ih,
        "orig_w": ow, "orig_h": oh, "box": list(box),
        "crop": crops.get(p.name, {"l": 0, "t": 0, "r": 0, "b": 0}),
    })


@app.post("/build")
def build_pdf(
    title: str = Form(""),
    page_size: str = Form("A4"),
    custom_w: float = Form(0.0),
    custom_h: float = Form(0.0),
    custom_auto: str = Form("true"),
    first_page_as_base: str = Form("true"),
    fit: str = Form("contain"),
    crop_whitespace: str = Form("false"),
    compress: str = Form("none"),
):
    files = ordered_files()
    if not files:
        raise HTTPException(400, "업로드된 이미지가 없습니다.")
    if compress not in COMPRESS:
        compress = "none"

    if page_size == "CUSTOM" and custom_w <= 0:
        raise HTTPException(400, "페이지 가로 크기를 mm 단위로 입력해주세요.")

    s = Settings(page_size, custom_w, custom_h, custom_auto, first_page_as_base, fit, crop_whitespace)
    crops = _load_crops()
    base_w, base_h = page_mm(files, s, crops)

    with tempfile.TemporaryDirectory() as tmp:
        pages_html = ""
        for i, p in enumerate(files):
            ow, oh, box = crop_box(p, crops.get(p.name), s.crop_whitespace)
            src = p
            if box != (0, 0, ow, oh):
                # 잘라낸 이미지는 임시 PNG로 (화질 손실 없음)
                im = Image.open(p)
                if im.mode != "RGB":
                    im = im.convert("RGB")
                src = Path(tmp) / f"{i:05d}.png"
                im.crop(box).save(src, "PNG")
            w, h = image_mm(box[2] - box[0], box[3] - box[1], base_w, base_h, s.fit)
            if compress != "none":
                # 줄인 JPEG 가 더 클 때(이미 작은 파일)는 그대로 둔다
                jpg = compressed_jpeg(p, box, w, h, compress)
                if len(jpg) < src.stat().st_size:
                    src = Path(tmp) / f"{i:05d}.jpg"
                    src.write_bytes(jpg)
            pages_html += f"""
            <div class="page">
              <img src="file://{src.resolve()}" style="width:{w}mm;height:{h}mm;" />
            </div>
            """

        back_html = """
        <div class="page back">
          <p>끝</p>
        </div>
        """

        html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{ size: {base_w}mm {base_h}mm; margin: 0; }}
  body {{ margin: 0; }}
  .page {{ position: relative; width: {base_w}mm; height: {base_h}mm; overflow: hidden; page-break-after: always; }}
  .page img {{ position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); }}
  .back {{ display: flex; align-items: center; justify-content: center; background:#fff; color:#000; }}
</style>
</head>
<body>
{pages_html}
{back_html}
</body>
</html>
"""
        pdf_bytes = HTML(string=html).write_pdf()

    return Response(content=pdf_bytes, media_type="application/pdf", headers={
        "Content-Disposition": "attachment; filename=book.pdf"
    })


@app.get("/health")
def health():
    return {"status": "ok"}
