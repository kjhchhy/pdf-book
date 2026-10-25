# PDF 책 만들기 (pdf-book)

사진을 모아 **PDF 책 파일**로 만들어 주는 개인용 웹 앱입니다.
홈랩 LXC(`192.168.0.208`, 포트 `8092`)에서 FastAPI + Jinja2 + WeasyPrint 로 돌아갑니다.

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

## 서버 설치 (Debian 계열 LXC)

```bash
# 1) 코드와 가상환경
sudo mkdir -p /opt/pdf-book && cd /opt/pdf-book
sudo cp -r <이 폴더>/app <이 폴더>/requirements.txt .
sudo python3 -m venv .venv
sudo .venv/bin/pip install -U pip
sudo .venv/bin/pip install -r requirements.txt

# 2) 업로드 폴더
sudo mkdir -p /opt/pdf-book/uploads

# 3) 서비스 등록 (deploy/pdf-book.service 참고, 비밀번호는 본인 값으로)
sudo cp deploy/pdf-book.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pdf-book

# 4) 확인
systemctl is-active pdf-book
#   http://<서버IP>:8092
```

접속: `http://192.168.0.208:8092` — 비밀번호는 `PDFBOOK_PASSWORD` 환경변수 값입니다.

## 코드 수정 후 반영

```bash
# 파일 한 개만 올릴 때 (전체 rsync 금지 — .venv/data/uploads 는 그대로 둔다)
scp -i ~/.ssh/anime_lxc_hermes app/static/app.js root@192.168.0.208:/opt/pdf-book/app/static/
ssh -i ~/.ssh/anime_lxc_hermes root@192.168.0.208 \
  'cd /opt/pdf-book && .venv/bin/python -m py_compile app/main.py && node --check app/static/app.js && systemctl restart pdf-book'
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
