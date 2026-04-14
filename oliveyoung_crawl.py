import os
import io
import time
import json
import base64
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ── 설정 ───────────────────────────────────────────
OLIVEYOUNG_URL = (
    "https://www.oliveyoung.co.kr/store/main/getHotdealList.do"
    "?t_page=%EB%9E%AD%ED%82%B9&t_click=GNB"
    "&t_gnb_type=%EC%98%A4%ED%8A%B9&t_swiping_type=N"
)

# GitHub Actions에서는 환경변수로, 로컬에서는 직접 입력
NOTION_TOKEN   = os.environ.get("NOTION_TOKEN", "여기에_Notion_Token_입력")
NOTION_PAGE_ID = os.environ.get("NOTION_PAGE_ID", "33e90b577e73802d8a76d90412267d4c")
GITHUB_TOKEN   = os.environ.get("GITHUB_TOKEN", "여기에_GitHub_Token_입력")
GITHUB_REPO    = "hyeonggeonim0709/oliveyoung-crawling"
GITHUB_BRANCH  = "main"

GRID_COLS  = 4    # 한 줄에 몇 개씩
THUMB_SIZE = 300  # 썸네일 크기 (px)
# ─────────────────────────────────────────────────

today = datetime.now().strftime("%Y-%m-%d")

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}


# ── 1. Selenium으로 올리브영 크롤링 ─────────────────
def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options,
    )


def crawl_image_urls():
    print(f"[{today}] 올리브영 크롤링 시작...")
    driver = get_driver()
    try:
        driver.get(OLIVEYOUNG_URL)
        time.sleep(3)
        soup = BeautifulSoup(driver.page_source, "html.parser")
    finally:
        driver.quit()

    images = soup.select("img.pic-thumb")
    print(f"총 {len(images)}개 썸네일 발견")

    result = []
    for img in images:
        url = img.get("src", "")
        if url:
            result.append(url)
    return result


# ── 2. 이미지 다운로드 후 그리드로 합치기 ────────────
def make_grid(image_urls):
    print("그리드 이미지 생성 중...")
    thumbnails = []
    headers = {"Referer": "https://www.oliveyoung.co.kr/"}

    for url in image_urls:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
            img = img.resize((THUMB_SIZE, THUMB_SIZE))
            thumbnails.append(img)
        except Exception as e:
            print(f"  ⚠️ 이미지 로드 실패: {e}")

    if not thumbnails:
        return None

    rows = (len(thumbnails) + GRID_COLS - 1) // GRID_COLS
    grid_w = THUMB_SIZE * GRID_COLS
    grid_h = THUMB_SIZE * rows
    grid = Image.new("RGB", (grid_w, grid_h), (255, 255, 255))

    for idx, thumb in enumerate(thumbnails):
        x = (idx % GRID_COLS) * THUMB_SIZE
        y = (idx // GRID_COLS) * THUMB_SIZE
        grid.paste(thumb, (x, y))

    print(f"  ✅ 그리드 완성 ({GRID_COLS}열 × {rows}행)")
    return grid


# ── 3. GitHub에 이미지 업로드 → URL 반환 ─────────────
def upload_to_github(image: Image.Image) -> str:
    print("GitHub에 업로드 중...")
    filename = f"oliveyoung_{today}.jpg"
    path = f"thumbnails/{filename}"

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    encoded = base64.b64encode(buffer.getvalue()).decode()

    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Content-Type": "application/json",
    }

    sha = None
    check = requests.get(api_url, headers=headers)
    if check.status_code == 200:
        sha = check.json().get("sha")

    payload = {
        "message": f"Add oliveyoung thumbnails {today}",
        "content": encoded,
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    resp = requests.put(api_url, headers=headers, data=json.dumps(payload))
    if resp.status_code in (200, 201):
        raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{path}"
        print(f"  ✅ GitHub 업로드 완료: {raw_url}")
        return raw_url
    else:
        raise Exception(f"GitHub 업로드 실패: {resp.status_code} - {resp.text}")


# ── 4. Notion에 날짜 헤딩 + 이미지 블록 삽입 ─────────
def upload_to_notion(image_url: str):
    print("Notion에 업로드 중...")
    blocks = [
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": f"📅 {today}"}}]
            },
        },
        {
            "object": "block",
            "type": "image",
            "image": {
                "type": "external",
                "external": {"url": image_url},
            },
        },
    ]

    resp = requests.patch(
        f"https://api.notion.com/v1/blocks/{NOTION_PAGE_ID}/children",
        headers=NOTION_HEADERS,
        data=json.dumps({"children": blocks}),
    )
    if resp.status_code == 200:
        print("  ✅ Notion 업로드 완료!")
    else:
        print(f"  ❌ Notion 업로드 실패: {resp.status_code} - {resp.text}")


# ── 메인 ─────────────────────────────────────────────
if __name__ == "__main__":
    image_urls = crawl_image_urls()
    if not image_urls:
        print("❌ 이미지를 찾지 못했습니다.")
    else:
        grid = make_grid(image_urls)
        if grid:
            github_url = upload_to_github(grid)
            upload_to_notion(github_url)
            print(f"\n🎉 완료! {len(image_urls)}개 썸네일 → 그리드 → Notion 삽입 성공")
