import requests
from bs4 import BeautifulSoup
import time
import json
from datetime import datetime, timedelta, timezone
import csv
from urllib.parse import urljoin
from typing import Any, Dict, List, Optional
import threading
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from bs4 import BeautifulSoup
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker
import sys
from pathlib import Path
import atexit

FILE = Path(__file__).resolve()
ROOT = FILE.parents[1]  # root directory
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))  # add ROOT to PATH


from contextlib import contextmanager

_thread_local_driver = threading.local()
_shared_drivers = set()
_shared_driver_lock = threading.Lock()

def _build_shared_chrome_options():
    options = ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1920,1080")
    options.page_load_strategy = "eager"
    return options

def _create_shared_driver():
    driver = webdriver.Chrome(options=_build_shared_chrome_options())
    driver.set_page_load_timeout(30)
    return driver

def _cleanup_shared_drivers():
    with _shared_driver_lock:
        drivers = list(_shared_drivers) 
        _shared_drivers.clear()

    for driver in drivers:
        try:
            driver.quit()
        except Exception:
            continue

atexit.register(_cleanup_shared_drivers)

@contextmanager
def shared_driver():
    driver = getattr(_thread_local_driver, "driver", None)
    if driver is None:
        driver = _create_shared_driver()
        _thread_local_driver.driver = driver
        with _shared_driver_lock:
            _shared_drivers.add(driver)

    try:
        yield driver
    except WebDriverException:
        with _shared_driver_lock:
            _shared_drivers.discard(driver)
        _thread_local_driver.driver = None
        try:
            driver.quit()
        except Exception:
            pass
        raise
    finally:
        try:
            driver.switch_to.default_content()
        except WebDriverException:
            pass
        
def collect_comments_selenium(
    url: str,
    selenium_wait_timeout: int = 10,
    selenium_max_load_more: int = 3,
    selenium_comment_tab_selector: str = "",
    selenium_load_more_selector: str = "",
):
    """Thu thập comment từ 1 URL bài viết bằng Selenium (độc lập, không cần class)."""

    try:
        with shared_driver() as driver:
            try:
                driver.set_page_load_timeout(max(int(selenium_wait_timeout), 10))
            except (ValueError, WebDriverException):
                # fallback to driver defaults if timeout cannot be applied
                pass

            driver.get(url)
            wait = WebDriverWait(driver, selenium_wait_timeout)

            # === 2. Click vào tab bình luận nếu có selector ===
            if selenium_comment_tab_selector:
                tab_selectors = [
                    selector.strip()
                    for selector in selenium_comment_tab_selector.split(",")
                    if selector.strip()
                ]
                tab = None
                for selector in tab_selectors:
                    try:
                        tab = wait.until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                        )
                        break
                    except TimeoutException:
                        continue
                    except WebDriverException:
                        continue
                if tab:
                    driver.execute_script("arguments[0].click();", tab)
                    WebDriverWait(driver, 2).until(lambda d: d.execute_script("return document.readyState") == "complete")
                else:
                    print("[DEBUG] Không tìm thấy comment tab selector")

            # === 3. Cuộn trang xuống để load comment ===
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            WebDriverWait(driver, 2).until(lambda d: d.execute_script("return document.readyState") == "complete")

            # === 4. Chờ phần tử comment xuất hiện ===
            try:
                wait.until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "article.comment_item, li.comment_item, div.comment_item")
                    )
                )
            except TimeoutException:
                print("[INFO] Không có comment nào.")
                return {"count": 0, "list": []}

            # === 5. Nhấn nút "Xem thêm" vài lần nếu có ===
            load_more_selectors = [
                selector.strip()
                for selector in (selenium_load_more_selector or "").split(",")
                if selector.strip()
            ]
            if load_more_selectors:
                for _ in range(selenium_max_load_more):
                    button = None
                    for selector in load_more_selectors:
                        try:
                            button = WebDriverWait(driver, 5).until(
                                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                            )
                            break
                        except TimeoutException:
                            continue
                        except WebDriverException:
                            continue
                    if button is None:
                        break
                    try:
                        driver.execute_script("arguments[0].click();", button)
                    except WebDriverException:
                        try:
                            button.click()
                        except WebDriverException:
                            break
                    WebDriverWait(driver, 2).until(lambda d: d.execute_script("return document.readyState") == "complete")

            # === 6. Thu thập danh sách comment ===
            comment_elements = driver.find_elements(
                By.CSS_SELECTOR, "article.comment_item, li.comment_item, div.comment_item"
            )
            print(f"[INFO] Tìm thấy {len(comment_elements)} comment elements")

            comments = []
            for element in comment_elements:
                def extract_first_text(selectors):
                    for sel in selectors:
                        try:
                            el = element.find_element(By.CSS_SELECTOR, sel)
                            txt = el.text.strip()
                            if txt:
                                return txt
                        except:
                            continue
                    return ""

                author = extract_first_text([".nickname", ".name", ".name_user", ".txt_name", "header .autor"])
                timestamp = extract_first_text(["time", ".time", ".txt_time", ".comment_time", ".time-com"])
                likes = extract_first_text([".number_like", ".like_count", ".txt_like", "a.number"])
                content = extract_first_text([".content", ".txt_comment", "p", "div.comment_content"])

                if not content:
                    continue
                comments.append({
                    "author": author,
                    "content": content,
                    "time": timestamp,
                    "likes": likes,
                })

            return {"count": len(comments), "list": comments}

    except (TimeoutException, WebDriverException) as exc:
        print(f"[WARN] Selenium lỗi khi crawl '{url}': {exc}")
        return None
    except Exception as exc:
        print(f"[WARN] Selenium exception khi crawl '{url}': {exc}")
        return None


class VNExpressScraper:
    def __init__(
        self,
        selenium_wait_timeout: int = 10,
        selenium_max_load_more: int = 3,
        selenium_comment_tab_selector: str = "",
        selenium_load_more_selector: str = "",
        crawl_comments: bool = False,
    ):
        self.base_url = "https://vnexpress.net"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        self.articles = []
        self.selenium_wait_timeout = selenium_wait_timeout
        self.selenium_max_load_more = selenium_max_load_more
        self.selenium_comment_tab_selector = selenium_comment_tab_selector
        self.selenium_load_more_selector = selenium_load_more_selector
        self.crawl_comments = crawl_comments
        
        # Main categories with their IDs
        self.categories = {
            'thoi-su': '1001005',
            'goc-nhin': '1003450',
            'the-gioi': '1001002',
            'kinh-doanh': '1003159',
            'giai-tri': '1002691',
            'the-thao': '1002565',
            'phap-luat': '1001007',
            'giao-duc': '1003497',
            'suc-khoe': '1003750',
            'doi-song': '1002966',
            'du-lich': '1003231',
            'khoa-hoc': '1001009',
            'so-hoa': '1002592',
            'xe': '1001006',
            'y-kien': '1001012',
            'tam-su': '1001014'
        }
    
    def get_page(self, url):
        """Fetch a page with error handling"""
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            print(f"Error fetching {url}: {e}")
            return None
    
    def date_to_timestamp(self, date_obj):
        """Convert datetime to Unix timestamp"""
        return int(date_obj.timestamp())
    
    def generate_date_ranges(self, start_date, end_date, interval_days=30):
        """Generate date ranges for crawling"""
        ranges = []
        current = start_date
        if interval_days <= 0:
            interval_days = 1
        
        while current <= end_date:
            range_end = min(current + timedelta(days=interval_days - 1), end_date)
            ranges.append((current, range_end))
            current = range_end + timedelta(days=1)
        
        return ranges
    
    def build_category_url(self, category_id, from_timestamp, to_timestamp, page=1):
        """Build VNExpress category URL with date range"""
        url = (f"{self.base_url}/category/day/"
               f"cateid/{category_id}/"
               f"fromdate/{from_timestamp}/"
               f"todate/{to_timestamp}/"
               f"allcate/{category_id}/"
               f"page/{page}")
        return url
    
    def parse_article_list(self, html):
        """Parse article links from a page"""
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        
        # Find all article items
        article_items = soup.find_all('article', class_='item-news')
        
        for article in article_items:
            try:
                link_tag = article.find('a', href=True)
                if not link_tag:
                    continue
                
                url = link_tag['href']
                if not url.startswith('http'):
                    url = urljoin(self.base_url, url)
                
                # Title
                title_tag = article.find(['h3', 'h2', 'h4'])
                title = title_tag.get_text(strip=True) if title_tag else ""
                
                # Description
                description_tag = article.find('p', class_='description')
                description = description_tag.get_text(strip=True) if description_tag else ""
                
                # Thumbnail
                thumb_tag = article.find('img')
                thumbnail = thumb_tag.get('data-src') or thumb_tag.get('src') if thumb_tag else ""
                
                # Date
                date_tag = article.find('span', class_='time-count')
                if not date_tag:
                    date_tag = article.find('span', class_='time')
                date_str = date_tag.get_text(strip=True) if date_tag else ""
                
                articles.append({
                    'url': url,
                    'title': title,
                    'description': description,
                    'thumbnail': thumbnail,
                    'date': date_str
                })
            except Exception as e:
                print(f"Error parsing article: {e}")
                continue
        
        return articles
    
    def _parse_iso_datetime(self, value: Optional[str]) -> Optional[datetime]:
        """Convert ISO-like string to naive UTC datetime"""
        if not value:
            return None
        cleaned = value.strip()
        try:
            if cleaned.endswith('Z'):
                cleaned = cleaned[:-1] + '+00:00'
            dt = datetime.fromisoformat(cleaned)
        except ValueError:
            return None
        if dt.tzinfo:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    
    def _collect_images(self, content_tag: Optional[BeautifulSoup]) -> List[Dict[str, Any]]:
        """Extract all image URLs within the content area"""
        images: List[Dict[str, Any]] = []
        if not content_tag:
            return images
        
        sequence = 1
        for img in content_tag.find_all('img'):
            src = img.get('data-src') or img.get('data-original') or img.get('src')
            if not src:
                continue
            images.append({
                'image_path': src,
                'sequence_number': sequence,
                'caption': img.get('alt') or ""
            })
            sequence += 1
        return images
    
    def _collect_videos(self, content_tag: Optional[BeautifulSoup]) -> List[Dict[str, Any]]:
        """Extract embedded video sources within the content area"""
        videos: List[Dict[str, Any]] = []
        if not content_tag:
            return videos
        
        sequence = 1
        for video in content_tag.find_all('video'):
            src = video.get('data-src') or video.get('src')
            if not src:
                source = video.find('source')
                src = source.get('src') if source else None
            if not src:
                continue
            videos.append({
                'video_path': src,
                'sequence_number': sequence
            })
            sequence += 1
        
        for iframe in content_tag.find_all('iframe'):
            src = iframe.get('data-src') or iframe.get('src')
            if not src:
                continue
            videos.append({
                'video_path': src,
                'sequence_number': sequence
            })
            sequence += 1
        
        return videos
    
    def _extract_tags(self, soup: BeautifulSoup) -> str:
        """Collect article tags from VNExpress detail pages."""
        containers = soup.select(
            "div.tags, div.list-tag, ul.list-tag, ul.tag, section.wrap-tag, div.box-keyword"
        )
        tags: List[str] = []
        seen = set()
        
        for container in containers:
            for anchor in container.find_all("a"):
                text = anchor.get_text(strip=True)
                if not text:
                    continue
                key = text.lower()
                if key in seen:
                    continue
                seen.add(key)
                tags.append(text)
        
        if not tags:
            for anchor in soup.select("a[rel='tag']"):
                text = anchor.get_text(strip=True)
                if not text:
                    continue
                key = text.lower()
                if key in seen:
                    continue
                seen.add(key)
                tags.append(text)
        
        if not tags:
            for meta_name in ("news_keywords", "keywords"):
                meta_tag = soup.find("meta", attrs={"name": meta_name})
                if not meta_tag or not meta_tag.get("content"):
                    continue
                for token in meta_tag["content"].split(","):
                    text = token.strip()
                    if not text:
                        continue
                    key = text.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    tags.append(text)
                if tags:
                    break
        
        return ",".join(tags)

    def parse_article_detail(self, url, summary: Optional[Dict[str, Any]] = None):
        """Parse individual article content"""
        html = self.get_page(url)
        if not html:
            return None
        
        soup = BeautifulSoup(html, 'html.parser')
        article_data: Dict[str, Any] = summary.copy() if summary else {}
        article_data['url'] = url
        
        try:
            # Title
            title_tag = soup.find('h1', class_='title-detail')
            article_data['title'] = title_tag.get_text(strip=True) if title_tag else ""
            
            if not article_data.get('category_name'):
                breadcrumb = soup.find('ul', class_='breadcrumb')
                if breadcrumb:
                    tokens = [
                        li.get_text(strip=True)
                        for li in breadcrumb.find_all('li')
                        if li.get_text(strip=True)
                    ]
                    if tokens:
                        article_data['category_name'] = tokens[-1]
            
            # Description/Lead
            description_tag = soup.find('p', class_='description')
            article_data['description'] = description_tag.get_text(strip=True) if description_tag else ""
            
            # Content
            content_tag = soup.find('article', class_='fck_detail')
            if content_tag:
                paragraphs = content_tag.find_all('p', class_='Normal')
                article_data['content'] = '\n'.join(
                    [p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)]
                )
            else:
                article_data['content'] = ""
            
            # Date
            publish_meta = (
                soup.find('meta', attrs={'itemprop': 'datePublished'}) or
                soup.find('meta', property='article:published_time')
            )
            publish_value = publish_meta.get('content') if publish_meta else None
            article_data['publish_date'] = self._parse_iso_datetime(publish_value)
            
            date_tag = soup.find('span', class_='date')
            article_data['date_text'] = date_tag.get_text(strip=True) if date_tag else ""
            
            # Category
            category_tag = soup.find('ul', class_='breadcrumb')
            if category_tag:
                categories = [li.get_text(strip=True) for li in category_tag.find_all('li')]
                article_data['category'] = ' > '.join(categories)
            else:
                article_data['category'] = ""
            
            # Author
            author_tag = soup.find('p', class_='author_mail')
            article_data['author'] = author_tag.get_text(strip=True) if author_tag else ""
            
            # Thumbnail
            thumb_tag = soup.find('meta', property='og:image')
            article_data['thumbnail'] = thumb_tag.get('content') if thumb_tag else ""
            
            # Tags
            article_data['tags'] = self._extract_tags(soup)
            
            # Comments placeholder (requires API to fetch – keep structure)
            if 'comments' not in article_data:
                article_data['comments'] = {'count': 0, 'list': []}

            if self.crawl_comments:
                selenium_comments = collect_comments_selenium(
                    url,
                    selenium_wait_timeout=self.selenium_wait_timeout,
                    selenium_max_load_more=self.selenium_max_load_more,
                    selenium_comment_tab_selector=self.selenium_comment_tab_selector or "",
                    selenium_load_more_selector=self.selenium_load_more_selector or "",
                )
                if selenium_comments is not None:
                    article_data['comments'] = selenium_comments
            
            # Media extraction
            article_data['images'] = self._collect_images(content_tag)
            article_data['videos'] = self._collect_videos(content_tag)
            
        except Exception as e:
            print(f"Error parsing article detail: {e}")
            return None
        
        return article_data
    
    def crawl_date_range(self, category_id, from_date, to_date, max_pages=50):
        """Crawl articles for a specific date range"""
        from_ts = self.date_to_timestamp(from_date)
        to_ts = self.date_to_timestamp(
            to_date + timedelta(days=1) - timedelta(seconds=1)
        )
        
        articles = []
        page = 1
        
        while page <= max_pages:
            url = self.build_category_url(category_id, from_ts, to_ts, page)
            print(f"  Page {page}: {url}")
            
            html = self.get_page(url)
            if not html:
                break
            
            page_articles = self.parse_article_list(html)
            
            if not page_articles:
                print(f"  No more articles at page {page}")
                break
            
            articles.extend(page_articles)
            print(f"  Found {len(page_articles)} articles")
            
            page += 1
            time.sleep(1)  # Be respectful
        
        return articles
    
    def crawl_category_by_date(self, category_name, category_id, start_date, end_date, 
                                interval_days=30, max_pages_per_range=50):
        """Crawl entire category by date ranges"""
        print(f"\n{'='*60}")
        print(f"Crawling category: {category_name} (ID: {category_id})")
        print(f"Date range: {start_date.date()} to {end_date.date()}")
        print(f"{'='*60}\n")
        
        date_ranges = self.generate_date_ranges(start_date, end_date, interval_days)
        all_articles = []
        
        for i, (from_date, to_date) in enumerate(date_ranges, 1):
            print(f"Range {i}/{len(date_ranges)}: {from_date.date()} to {to_date.date()}")
            
            articles = self.crawl_date_range(category_id, from_date, to_date, max_pages_per_range)
            all_articles.extend(articles)
            
            print(f"Total articles in this range: {len(articles)}")
            time.sleep(2)  # Delay between date ranges
        
        # Remove duplicates
        unique_articles = {article['url']: article for article in all_articles}
        unique_articles = list(unique_articles.values())
        
        print(f"\nTotal unique articles for {category_name}: {len(unique_articles)}")
        return unique_articles
    
    def crawl_all_categories(self, start_date, end_date, interval_days=30, 
                            max_pages_per_range=50, get_full_content=False):
        """Crawl all categories from start_date to end_date"""
        all_articles = []
        
        for category_name, category_id in self.categories.items():
            try:
                articles = self.crawl_category_by_date(
                    category_name, 
                    category_id,
                    start_date, 
                    end_date, 
                    interval_days,
                    max_pages_per_range
                )
                
                # Add category info
                for article in articles:
                    article['category_name'] = category_name
                    article['category_id'] = category_id
                
                all_articles.extend(articles)
                
                # Save progress after each category
                # self.save_to_json(all_articles, f'vnexpress_progress_{category_name}.json')
                
            except Exception as e:
                print(f"Error crawling category {category_name}: {e}")
                continue
        
        # Remove duplicates across categories
        unique_articles = {article['url']: article for article in all_articles}
        all_articles = list(unique_articles.values())
        
        print(f"\n{'='*60}")
        print(f"TOTAL UNIQUE ARTICLES CRAWLED: {len(all_articles)}")
        print(f"{'='*60}\n")
        
        # Optionally get full content
        if get_full_content:
            print("Fetching full content for articles...")
            detailed_articles = []
            for i, article in enumerate(all_articles, 1):
                print(f"Fetching {i}/{len(all_articles)}: {article['title'][:50]}...")
                detailed = self.parse_article_detail(
                    article['url'],
                    summary=article
                )
                if detailed:
                    detailed_articles.append(detailed)
                time.sleep(1)
                
                # Save progress every 100 articles
                if i % 100 == 0:
                    self.save_to_json(detailed_articles, f'vnexpress_detailed_progress.json')
            
            return detailed_articles
        
        return all_articles
    
    def save_to_json(self, data, filename='vnexpress_articles.json'):
        """Save articles to JSON file"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=self._serialize_for_json)
        print(f"✓ Saved {len(data)} articles to {filename}")
    
    @staticmethod
    def _serialize_for_json(value: Any):
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)
    
    def save_to_csv(self, data, filename='vnexpress_articles.csv'):
        """Save articles to CSV file"""
        if not data:
            return
        
        keys = data[0].keys()
        with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(data)
        print(f"✓ Saved {len(data)} articles to {filename}")


# Example usage
if __name__ == "__main__":
    scraper = VNExpressScraper()
    
    # Define date range: May 2020 to October 2025
    start_date = datetime(2025, 10, 1)
    end_date = datetime(2025, 10, 14)
    
    # Option 1: Crawl all categories (recommended - links only, faster)
    print("Starting comprehensive crawl from May 2020 to October 2025...")
    articles = scraper.crawl_all_categories(
        start_date=start_date,
        end_date=end_date,
        interval_days=30,  # 30-day chunks
        max_pages_per_range=50,  # Max pages per date range
        get_full_content=False
    )
    scraper.save_to_json(articles, 'vnexpress_all_2020_2025.json')
    scraper.save_to_csv(articles, 'vnexpress_all_2020_2025.csv')
    
    # Option 2: Crawl single category with full content
    # articles = scraper.crawl_category_by_date(
    #     'phap-luat',
    #     '1001007',
    #     start_date,
    #     end_date,
    #     interval_days=30,
    #     max_pages_per_range=50
    # )
    # scraper.save_to_json(articles, 'vnexpress_phapluat.json')
    
    # Option 3: Crawl specific date range
    # articles = scraper.crawl_date_range(
    #     '1001007',  # phap-luat category
    #     datetime(2024, 1, 1),
    #     datetime(2024, 12, 31),
    #     max_pages=100
    # )
    # scraper.save_to_json(articles, 'vnexpress_2024.json')
