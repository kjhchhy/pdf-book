from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
import shutil, secrets, re, os, base64, io, json

from PIL import Image, ImageFilter
from weasyprint import HTML, CSS

app = FastAPI()

BASE = Path("/opt/pdf-book")
UPLOAD_DIR = BASE / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ORDER_FILE = UPLOAD_DIR / "_order.json"

app.mount("/static", StaticFiles(directory=str(BASE / "app/static")), name="static")
templates = Jinja2Templates(directory=str(BASE / "app/templates"))

PASSWORD = os.getenv("PDFBOOK_PASSWORD", "")

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}

# 썸네일 메모리 캐시 (파일명 + mtime 기준)
_thumb_cache: dict[tuple[str, float], bytes] = {}
_view_cache: dict[tuple[str, float], bytes] = {}


def sort_key(path: Path):
    m = re.search(r"(\d+)", path.name)
    return int(m.group(1)) if m else path.name


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
        request, "index.html", {"request": request},
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
async def upload(files: list[UploadFile] = File(...)):
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
        order = _load_order()
        known = set(order)
        for n in saved:
            if n not in known:
                order.append(n)
        _save_order(order)

    return JSONResponse({"files": saved})


@app.get("/files")
async def list_files():
    return JSONResponse({"files": [p.name for p in ordered_files()]})


@app.get("/thumb/{name}")
async def thumb(name: str):
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
async def view(name: str):
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
async def preview_files():
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
async def reorder(order: list[str]):
    existing = {p.name for p in _image_files()}
    clean = [n for n in order if n in existing]
    # 누락된 파일은 뒤에 붙여 유실 방지
    for n in existing:
        if n not in clean:
            clean.append(n)
    _save_order(clean)
    return JSONResponse({"ok": True, "order": clean})


@app.delete("/files/{name}")
async def delete_file(name: str):
    p = UPLOAD_DIR / Path(name).name
    if p.exists() and p.suffix.lower() in IMAGE_EXT:
        p.unlink()
    _save_order([n for n in _load_order() if n != p.name])
    return JSONResponse({"ok": True})


@app.post("/clear")
async def clear_files():
    for p in _image_files():
        p.unlink()
    _save_order([])
    _thumb_cache.clear()
    _view_cache.clear()
    return JSONResponse({"ok": True})


@app.post("/build")
async def build_pdf(
    title: str = Form(""),
    page_size: str = Form("A4"),
    custom_w: float = Form(0.0),
    custom_h: float = Form(0.0),
    custom_auto: str = Form("true"),
    first_page_as_base: str = Form("true"),
    fit: str = Form("contain"),
    crop_whitespace: str = Form("false"),
):
    files = ordered_files()
    if not files:
        raise HTTPException(400, "업로드된 이미지가 없습니다.")

    if page_size == "CUSTOM" and custom_w <= 0:
        raise HTTPException(400, "페이지 가로 크기를 mm 단위로 입력해주세요.")

    page_sizes = {
        "A4": (210, 297),
        "A5": (148, 210),
        "Letter": (216, 279),
        "Legal": (216, 356),
    }
    base_w, base_h = page_sizes.get(page_size, (210, 297))
    if page_size == "CUSTOM":
        base_w = custom_w
        base_h = custom_h
        if custom_auto == "true" or base_h <= 0:
            # 비율은 첫 페이지(첫 이미지)를 기준으로: 세로 = 가로 × (첫 이미지 세로/가로)
            try:
                first_img = crop_whitespace_impl(files[0]) if crop_whitespace == "true" else Image.open(files[0])
                fw, fh = first_img.size
                base_h = round(custom_w * fh / fw, 1)
            except Exception:
                base_h = custom_h or 297
    elif first_page_as_base == "true" and files:
        try:
            first_img = crop_whitespace_impl(files[0]) if crop_whitespace == "true" else Image.open(files[0])
            if first_img.mode != "RGB":
                first_img = first_img.convert("RGB")
            w, h = first_img.size
            base_w, base_h = w * 25.4 / 200, h * 25.4 / 200
        except Exception:
            pass

    def page_for(p: Path):
        if crop_whitespace == "true":
            im = crop_whitespace_impl(p)
        else:
            im = Image.open(p)
        if im.mode != "RGB":
            im = im.convert("RGB")
        w, h = im.size
        img_mm_w = w * 25.4 / 200
        img_mm_h = h * 25.4 / 200
        if fit == "contain":
            return img_mm_w, img_mm_h
        scale = max(base_w / img_mm_w, base_h / img_mm_h)
        return img_mm_w * scale, img_mm_h * scale

    pages_html = ""
    for p in files:
        w, h = page_for(p)
        pages_html += f"""
        <div class="page">
          <img src="file://{p.resolve()}" style="width:{w}mm;height:{h}mm;" />
        </div>
        """

    cover_html = f"""
    <div class="page cover">
      <h1>{title or '이미지 책'}</h1>
    </div>
    """ if title else ""

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
  .page {{ page-break-after: always; display:flex; align-items:center; justify-content:center; }}
  .page img {{ max-width:100%; max-height:100%; object-fit:contain; }}
  .cover {{ background:#fff; color:#000; font-size:32px; }}
  .back {{ background:#fff; color:#000; }}
</style>
</head>
<body>
{cover_html}
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
async def health():
    return {"status": "ok"}
