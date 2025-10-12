import asyncio
import time
import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


async def fetch_comments_with_playwright(article_url: str):
    """
    Fallback: render the full page with Playwright when the AJAX API is blocked.
    """
    print("⚙️ Falling back to Playwright rendering...")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(article_url, timeout=60000)
        # wait for comment list to render
        await page.wait_for_selector("li.item-comment", timeout=20000)
        html = await page.content()
        await browser.close()

    soup = BeautifulSoup(html, "html.parser")
    comment_items = soup.select("li.item-comment")
    comments = []
    for el in comment_items:
        comments.append({
            "username": el.select_one(".name") and el.select_one(".name").get_text(strip=True),
            "content": el.select_one(".contentcomment") and el.select_one(".contentcomment").get_text(" ", strip=True),
            "time": el.select_one(".timeago") and (
                el.select_one(".timeago").get("title") or el.select_one(".timeago").get_text(strip=True)
            ),
            "comment_id": el.get("data-cmid"),
            "parent_id": el.get("data-parentid"),
        })

    print(f"✅ Extracted {len(comments)} comments via Playwright")
    return comments


def fetch_comments_via_api(article_url: str):
    """
    Primary method: use Tuổi Trẻ's AJAX endpoint directly.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "vi,en-US;q=0.9,en;q=0.8",
        "Referer": article_url,
    }
    s = requests.Session()
    r = s.get(article_url, headers=headers, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    cmt_section = soup.select_one("section.comment-wrapper[data-objectid]")
    if not cmt_section:
        print("❌ No comment section found")
        return []

    objectid = cmt_section["data-objectid"]
    objecttype = cmt_section.get("data-objecttype", "1")

    comments = []
    page = 1

    while True:
        api_url = (
            f"https://tuoitre.vn/ajax/comment-list.htm?"
            f"objectid={objectid}&objecttype={objecttype}&sort=1&page={page}"
        )
        resp = s.get(api_url, headers=headers)
        print(f"Fetching page {page}: {resp.status_code}, len={len(resp.text)}")

        if resp.status_code != 200 or not resp.text.strip():
            break

        frag = BeautifulSoup(resp.text, "html.parser")
        items = frag.select("li.item-comment")
        if not items:
            break

        for el in items:
            comments.append({
                "username": el.select_one(".name") and el.select_one(".name").get_text(strip=True),
                "content": el.select_one(".contentcomment") and el.select_one(".contentcomment").get_text(" ", strip=True),
                "time": el.select_one(".timeago") and (
                    el.select_one(".timeago").get("title") or el.select_one(".timeago").get_text(strip=True)
                ),
                "comment_id": el.get("data-cmid"),
                "parent_id": el.get("data-parentid"),
            })

        page += 1
        time.sleep(1.5)

    print(f"✅ Extracted {len(comments)} comments via API")
    return comments


def crawl_tuoitre_comments(article_url: str):
    """
    Try API first, then fallback to Playwright if needed.
    """
    comments = fetch_comments_via_api(article_url)
    if not comments:
        comments = asyncio.run(fetch_comments_with_playwright(article_url))
    return comments


if __name__ == "__main__":
    url = "https://tuoitre.vn/4-kich-ban-cua-cuoc-dung-do-kinh-te-my-trung-20251011234722858.htm"
    comments = crawl_tuoitre_comments(url)
    print("\n=== Final results ===")
    for c in comments:
        print(c)
    print(f"\nTotal comments: {len(comments)}")
