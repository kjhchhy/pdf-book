# PDF 책 만들기 (pdf-book)

사진을 모아 **PDF 책 파일**로 만들어 주는 개인용 웹 앱입니다.
FastAPI + Jinja2 + WeasyPrint 로 만들었고, 홈랩 LXC(`192.168.0.208`)의 anime-manager(8090)에
하위 앱으로 붙어 **http://192.168.0.208:8090/pdf-book/** 에서 돌아갑니다 (아래 "서버 배치" 참고).

- 이미지를 끌어다 놓으면 **파일명 번호순**으로 정렬되고, 카드를 끌어 순서를 바꿀 수 있습니다.
- 만들면 **브라우저로 즉시 다운로드**됩니다 (서버에 PDF를 저장하지 않음).
- 모든 처리는 서버 안에서만 이뤄지고, 외부로 나가지 않습니다.

## 화면 구성

```
┌──────────────────────────────────────────────────────────┐
│ 상단: 책 제목 · 페이지 크기 · 이미지 맞춤 · 토글 · 버튼     │
├──────────────────────────────────────────────────────────┤
│ 이미지를 끌어다 놓기 (얇은 바)                             │
├───────────────┬──────────────────────────────────────────┤
│ 페이지 목록    │  고른 페이지 큰 미리보기                  │
│ (세로 한 줄)   │  03 / 258 · ‹ 파일명 ›                    │
└───────────────┴──────────────────────────────────────────┘
```

- **왼쪽**: 페이지 카드가 세로 한 줄로 이어집니다. 누르면 선택됩니다.
- **오른쪽**: 고른 페이지를 크게 보여 줍니다. `‹ ›` 버튼과 키보드 `←` `→` 로 넘길 수 있고,
  마지막에 보던 페이지는 새로고침해도 유지됩니다(`localStorage`).
- 모바일(≤980px)에서는 설정 → (드롭 바) → 목록 → 미리보기 순으로 세로로 쌓이고,
  하단에 `이미지 추가` / `PDF 만들기` 고정 바가 붙습니다.

## 기능

| 항목 | 설명 |
| --- | --- |
| 정렬 | 파일명에서 숫자를 뽑아 번호순 정렬 (`20261022_0213…`) |
| 순서 변경 | 카드 드래그 → `uploads/_order.json` 에 저장 (새로고침해도 유지) |
| 페이지 크기 | A4 / A5 / Letter / Legal / **사용자 지정(mm)** |
| 사용자 지정 | 가로(mm)만 넣으면 **세로는 첫 페이지 비율**로 자동 계산 (`세로 = 가로 × 첫 이미지 세로/가로`) |
| 이미지 맞춤 | `비율 유지`(원본 비율) / `꽉 채우기`(페이지에 맞춰 확대) |
| 첫 이미지 크기 기준 | 모든 페이지를 첫 장 비율에 맞춤 |
| 여백 자르기 | 스캔한 흰 여백을 잘라냄 (`ImageFilter` + bbox) |
| 용량 줄이기 | `원본` / `보통`(200dpi·JPEG 82) / `강하게`(130dpi·JPEG 68). 놓일 크기에 맞춰 줄이고, 더 커지면 원본 유지 |
| 예상 용량 | `/estimate` — 최대 6장을 실제로 줄여 보고 전체로 환산 (시험에서 실제와 1% 안쪽) |
| 표지 / 뒷장 | 책 제목을 넣으면 표지, 항상 마지막에 "끝" 뒷장 |
| 썸네일 | `/thumb/{name}` (420px), 미리보기 `/view/{name}` (1400px) |

## 파일 구조

```
pdf-book/
├── app/
│   ├── main.py                 # 라우트 전부 (업로드·목록·썸네일·미리보기·순서·삭제·빌드)
│   ├── templates/index.html    # 단일 화면 (Jinja2)
│   └── static/
│       ├── style.css           # 편집(編輯) 테마 — paper/card/accent
│       └── app.js              # 로그인·업로드·그리드·미리보기·빌드
├── deploy/pdf-book.service     # systemd 유닛 예시
├── docs/작업일지-20261025.md    # 2026-10-25 디자인 개편·기능 추가 기록
├── requirements.txt
└── .gitignore
```

## 서버 배치 (anime-manager 하위 앱)

LXC `192.168.0.208` 에서는 따로 서비스를 띄우지 않고, anime-manager(8090) 안에 패키지로 넣어 마운트합니다.
netmap(`/netmap`), 회비(`/hoa`)와 같은 방식이고, 8090 첫 화면(홈)에서 들어갑니다.

| 항목 | 위치 |
| --- | --- |
| 코드 | `/opt/anime-manager/app/pdfbook/` (`main.py`, `static/`, `templates/` — 이 저장소의 `app/` 그대로) |
| 업로드 폴더 | `/opt/anime-manager/data/pdf-book/` (`PDFBOOK_UPLOADS`) |
| 마운트 | anime-manager `app/main.py` 의 `app.mount("/pdf-book", pdfbook_main.app)` |
| 접속 제한 | anime-manager 인증을 그대로 따름 (내부망은 바로, 외부는 로그인) |
| 의존성 | anime-manager `.venv` 에 `weasyprint` 설치 (Pango·Noto CJK 는 시스템 패키지) |

하위 경로에서도 돌아가도록 HTML/JS 는 경로 앞에 `base`(= `root_path`, 예: `/pdf-book`)를 붙입니다.
단독 실행이면 `base` 는 빈 문자열이라 그대로 `/` 에서 동작합니다.

## 코드 수정 후 반영

```bash
# 바뀐 파일만 올린다 (data/ 와 .venv 는 건드리지 않는다)
scp -i ~/.ssh/anime_lxc app/static/app.js root@192.168.0.208:/opt/anime-manager/app/pdfbook/static/
ssh -i ~/.ssh/anime_lxc root@192.168.0.208 \
  'cd /opt/anime-manager && .venv/bin/python -m py_compile app/pdfbook/main.py && systemctl restart anime-manager'
```

재시작하면 anime-manager 전체(애니·포토 백업 등)가 같이 다시 뜹니다. 포토 백업·번역이 돌고 있지 않을 때 하세요.
static 만 바꿨다면 재시작 없이 `index.html` 의 `?v=` 만 올려도 됩니다.

## 단독 실행 (로컬 테스트)

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
PDFBOOK_BASE=. .venv/bin/uvicorn app.main:app --port 8092   # 업로드는 ./uploads
```

## 주의사항 (실제로 겪은 것들)

- **CSS/JS를 고치면 `index.html` 의 `?v=` 쿼리를 올려야** 브라우저가 새 파일을 받습니다.
  HTML 자체는 `Cache-Control: no-store` 로 내려갑니다. 웨일(Whale)은 `Ctrl+Shift+R` 필요할 수 있습니다.
- **한글 비밀번호 금지**: IME 조합 때문에 입력이 씹혀 "비밀번호가 틀렸습니다"만 반복됩니다. 숫자·영문만 사용하세요.
- **서비스 재시작은 배치 중에 하지 않기**: PDF 생성 중 재시작하면 요청이 끊깁니다.
- **업로드 폴더를 통째로 지우는 스크립트 금지**: 테스트 파일만 이름으로 걸러 지우세요.
- `uploads/` 와 `.venv/`, `*.bak*` 는 저장소에 올리지 않습니다(`.gitignore`).

## 환경

- Python 3.11+ / FastAPI / uvicorn / Pillow / WeasyPrint / Jinja2
- LXC: Debian 12, 512MB RAM / 2 core — 259장(약 188MB PDF) 생성에 약 27초
