"""
Utilities for crawling Tuoi Tre Online articles by consuming the monthly sitemaps.

The crawler fetches sitemap indices between two month-year boundaries,
downloads individual article pages, extracts structured information that
matches the data model defined in ``models.py`` and can optionally persist
the result via SQLAlchemy.
"""

from __future__ import annotations

import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Union

import requests
from bs4 import BeautifulSoup
from requests import Response

LOGGER = logging.getLogger(__name__)


@dataclass
class ArticleMedia:
    """Lightweight representation for image/video assets found in an article."""

    url: str
    sequence_number: int


@dataclass
class ArticleData:
    """Structured payload for article information understood by ``models.Article``."""

    title: str
    description: Optional[str]
    content: Optional[str]
    category_id: Optional[str]
    category_name: Optional[str]
    comments: Dict[str, Union[int, Sequence[Dict[str, Union[str, int]]]]]
    tags: List[str]
    url: str
    publish_date: Optional[datetime]
    images: List[ArticleMedia] = field(default_factory=list)
    videos: List[ArticleMedia] = field(default_factory=list)

    def tags_as_string(self) -> Optional[str]:
        """Return a comma separated representation that fits the DB schema."""
        if not self.tags:
            return None
        unique_tags: List[str] = []
        seen = set()
        for tag in self.tags:
            cleaned = tag.strip()
            lowered = cleaned.lower()
            if cleaned and lowered not in seen:
                unique_tags.append(cleaned)
                seen.add(lowered)
        concatenated = ", ".join(unique_tags)
        # Truncate to 500 chars to respect the Article.tags column constraint.
        return concatenated[:500]


class TuoitreCrawler:
    """Crawler for https://tuoitre.vn/ content based on historical sitemaps."""

    BASE_SITEMAP_URL = "https://tuoitre.vn/StaticSitemaps/sitemaps-{year:04d}-{month}.xml"
    SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        delay_seconds: float = 0.2,
        request_timeout: int = 30,
    ) -> None:
        """
        Parameters
        ----------
        session:
            Optional ``requests.Session`` for HTTP pooling/tuning. A default session
            is created when not provided.
        delay_seconds:
            Politeness delay inserted after each article fetch.
        request_timeout:
            Timeout applied to HTTP requests, in seconds.
        """

        self.session = session or requests.Session()
        self.delay_seconds = delay_seconds
        self.request_timeout = request_timeout

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #
    def crawl(
        self,
        start_year: int = 2010,
        start_month: int = 1,
        end_year: int = 2015,
        end_month: int = 10,
        limit_per_month: Optional[int] = None,
    ) -> Iterator[ArticleData]:
        """
        Iterate through all article data between the provided month ranges.

        Parameters
        ----------
        start_year, start_month:
            Inclusive lower bound for sitemap retrieval.
        end_year, end_month:
            Inclusive upper bound for sitemap retrieval.
        limit_per_month:
            Optional cap on the number of articles processed per sitemap month.

        Yields
        ------
        ArticleData
            Structured representation for each crawled article.
        """

        for year, month in self._iter_months(start_year, start_month, end_year, end_month):
            sitemap_url = self.BASE_SITEMAP_URL.format(year=year, month=month)
            try:
                entries = self._fetch_sitemap_entries(sitemap_url)
            except Exception as exc:  # pylint: disable=broad-except
                LOGGER.warning("Failed to fetch sitemap %s: %s", sitemap_url, exc)
                continue

            LOGGER.info("Found %d urls in sitemap %s", len(entries), sitemap_url)
            processed = 0
            for loc_url in entries:
                try:
                    article_data = self._fetch_article(loc_url)
                except Exception as exc:  # pylint: disable=broad-except
                    LOGGER.warning("Failed to process article %s: %s", loc_url, exc)
                    continue

                if article_data:
                    yield article_data
                processed += 1
                if limit_per_month is not None and processed >= limit_per_month:
                    LOGGER.info(
                        "Reached monthly limit (%s) for %04d-%02d",
                        limit_per_month,
                        year,
                        month,
                    )
                    break

                if self.delay_seconds:
                    time.sleep(self.delay_seconds)

    def persist_article(
        self,
        session,
        article_data: ArticleData,
        commit: bool = False,
    ):
        """
        Insert the article (and related media) into the database if not present.

        Parameters
        ----------
        session:
            SQLAlchemy session.
        article_data:
            Extracted article payload.
        commit:
            Whether to commit immediately after persisting. When ``False`` the caller
            is responsible for committing.

        Returns
        -------
        Tuple[Article, bool]
            Persisted ``Article`` instance and a flag that is ``True`` when the row was
            newly created, ``False`` when it already existed.
        """

        try:
            from .models import Article, ArticleImage, ArticleVideo  # pylint: disable=cyclic-import
        except ImportError:  # pragma: no cover
            from models import Article, ArticleImage, ArticleVideo  # type: ignore

        existing = session.query(Article).filter(Article.url == article_data.url).first()
        if existing:
            LOGGER.debug("Article already exists, skipping %s", article_data.url)
            return existing, False

        article = Article(
            title=article_data.title,
            description=article_data.description,
            content=article_data.content,
            category_id=article_data.category_id,
            category_name=article_data.category_name,
            comments=article_data.comments,
            tags=article_data.tags_as_string(),
            url=article_data.url,
            publish_date=article_data.publish_date,
        )

        for media in article_data.images:
            article.images.append(
                ArticleImage(image_path=media.url, sequence_number=media.sequence_number)
            )
        for media in article_data.videos:
            article.videos.append(
                ArticleVideo(video_path=media.url, sequence_number=media.sequence_number)
            )

        session.add(article)
        if commit:
            session.commit()
        return article, True

    # --------------------------------------------------------------------- #
    # Sitemap utilities
    # --------------------------------------------------------------------- #
    def _fetch_sitemap_entries(self, sitemap_url: str) -> List[str]:
        response = self._get(sitemap_url)
        if response.status_code != 200:
            raise RuntimeError(f"Unexpected status {response.status_code} for {sitemap_url}")

        root = ET.fromstring(response.content)
        locs: List[str] = []
        for url_node in root.findall("sm:url", namespaces=self.SITEMAP_NS):
            loc = url_node.findtext("sm:loc", namespaces=self.SITEMAP_NS)
            if loc:
                locs.append(loc.strip())
        if not locs:
            # Fallback for XMLs without namespace declarations.
            for url_node in root.findall("url"):
                loc = url_node.findtext("loc")
                if loc:
                    locs.append(loc.strip())
        return locs

    # --------------------------------------------------------------------- #
    # Article parsing helpers
    # --------------------------------------------------------------------- #
    def _fetch_article(self, article_url: str) -> Optional[ArticleData]:
        response = self._get(article_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        self._sanitize_document(soup)

        ld_json = self._extract_ld_json(soup)
        title = self._extract_title(soup, ld_json)
        if not title:
            LOGGER.debug("Missing title for %s, skipping", article_url)
            return None

        description = self._extract_description(soup, ld_json)
        publish_date = self._extract_publish_date(soup, ld_json)
        category_name = self._extract_category_name(soup, ld_json)
        category_id = self._slugify(category_name) if category_name else None
        content = self._extract_content(soup, ld_json)
        tags = self._extract_tags(soup, ld_json)
        images = self._extract_images(soup, ld_json)
        videos = self._extract_videos(soup)

        article = ArticleData(
            title=title,
            description=description,
            content=content,
            category_id=category_id,
            category_name=category_name,
            comments={"count": 0, "list": []},
            tags=tags,
            url=article_url,
            publish_date=publish_date,
            images=images,
            videos=videos,
        )
        return article

    # --------------------------------------------------------------------- #
    # HTTP utilities
    # --------------------------------------------------------------------- #
    def _get(self, url: str) -> Response:
        LOGGER.debug("GET %s", url)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
            )
        }
        return self.session.get(url, headers=headers, timeout=self.request_timeout)

    # --------------------------------------------------------------------- #
    # Extraction helpers
    # --------------------------------------------------------------------- #
    @staticmethod
    def _sanitize_document(soup: BeautifulSoup) -> None:
        for element in soup(["script", "style", "noscript"]):
            element.decompose()

    @staticmethod
    def _extract_ld_json(soup: BeautifulSoup) -> Optional[Dict]:
        payloads: List[Dict] = []
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                payloads.append(data)
            elif isinstance(data, list):
                payloads.extend([item for item in data if isinstance(item, dict)])
        # Prefer entries describing a NewsArticle.
        for data in payloads:
            if data.get("@type") in {"NewsArticle", "Article"}:
                return data
        return payloads[0] if payloads else None

    @staticmethod
    def _extract_title(soup: BeautifulSoup, ld_json: Optional[Dict]) -> Optional[str]:
        if ld_json:
            title = ld_json.get("headline")
            if title:
                return title.strip()
        meta = soup.find("meta", attrs={"property": "og:title"})
        if meta and meta.get("content"):
            return meta["content"].strip()
        if soup.title and soup.title.string:
            return soup.title.string.strip()
        heading = soup.find(["h1", "h2"])
        return heading.get_text(strip=True) if heading else None

    @staticmethod
    def _extract_description(soup: BeautifulSoup, ld_json: Optional[Dict]) -> Optional[str]:
        if ld_json:
            description = ld_json.get("description")
            if isinstance(description, str) and description.strip():
                return description.strip()
        meta_names = ["description", "og:description"]
        for name in meta_names:
            meta = soup.find("meta", attrs={"name": name}) or soup.find(
                "meta", attrs={"property": name}
            )
            if meta and meta.get("content"):
                return meta["content"].strip()
        return None

    @staticmethod
    def _extract_publish_date(soup: BeautifulSoup, ld_json: Optional[Dict]) -> Optional[datetime]:
        if ld_json:
            for key in ("datePublished", "dateCreated"):
                value = ld_json.get(key)
                parsed = TuoitreCrawler._parse_datetime(value)
                if parsed:
                    return parsed
        meta_keys = [
            ("property", "article:published_time"),
            ("name", "pubdate"),
            ("name", "publishdate"),
            ("name", "date"),
        ]
        for attr, value in meta_keys:
            meta = soup.find("meta", attrs={attr: value})
            if meta and meta.get("content"):
                parsed = TuoitreCrawler._parse_datetime(meta["content"])
                if parsed:
                    return parsed
        # Some pages embed publication date inside elements with these classes.
        date_selectors = [
            ".detail-time",
            ".article__meta",
            ".date-time",
            ".main-content .time",
        ]
        for selector in date_selectors:
            node = soup.select_one(selector)
            if node:
                parsed = TuoitreCrawler._parse_datetime(node.get_text(" ", strip=True))
                if parsed:
                    return parsed
        return None

    @staticmethod
    def _extract_category_name(soup: BeautifulSoup, ld_json: Optional[Dict]) -> Optional[str]:
        if ld_json:
            section = ld_json.get("articleSection") or ld_json.get("section")
            if isinstance(section, str):
                return section.strip()
            if isinstance(section, list) and section:
                return str(section[0]).strip()
        meta = soup.find("meta", attrs={"property": "article:section"})
        if meta and meta.get("content"):
            return meta["content"].strip()
        breadcrumb = soup.select_one(".breadcrumb a")
        if breadcrumb:
            return breadcrumb.get_text(strip=True)
        return None

    @staticmethod
    def _extract_content(soup: BeautifulSoup, ld_json: Optional[Dict]) -> Optional[str]:
        if ld_json and isinstance(ld_json.get("articleBody"), str):
            text = ld_json["articleBody"].strip()
            if text:
                return text

        selectors = [
            "div.detail-content",
            "div#main-detail",
            "div.article-content",
            "div.content",
            "article",
        ]
        for selector in selectors:
            node = soup.select_one(selector)
            if not node:
                continue
            paragraphs = []
            for child in node.find_all(["p", "li", "h2", "h3"]):
                text = child.get_text(" ", strip=True)
                if text:
                    paragraphs.append(text)
            if paragraphs:
                return "\n".join(paragraphs)
        main_article = soup.find("article")
        if main_article:
            text = main_article.get_text(" ", strip=True)
            if text:
                return text
        return None

    @staticmethod
    def _extract_tags(soup: BeautifulSoup, ld_json: Optional[Dict]) -> List[str]:
        tags: List[str] = []
        if ld_json:
            keywords = ld_json.get("keywords")
            if isinstance(keywords, list):
                tags.extend(str(item) for item in keywords)
            elif isinstance(keywords, str):
                tags.extend(re.split(r"[;,]", keywords))
        meta = soup.find("meta", attrs={"name": "news_keywords"})
        if meta and meta.get("content"):
            tags.extend(re.split(r"[;,]", meta["content"]))
        tag_links = soup.select("a[rel='tag'], .tags a, .tag a")
        for link in tag_links:
            text = link.get_text(strip=True)
            if text:
                tags.append(text)

        cleaned_tags: List[str] = []
        seen = set()
        for tag in tags:
            normalized = tag.strip()
            lowered = normalized.lower()
            if normalized and lowered not in seen:
                cleaned_tags.append(normalized)
                seen.add(lowered)
        return cleaned_tags

    @staticmethod
    def _extract_images(soup: BeautifulSoup, ld_json: Optional[Dict]) -> List[ArticleMedia]:
        images: List[str] = []
        if ld_json:
            image_value = ld_json.get("image")
            if isinstance(image_value, dict):
                url = image_value.get("url")
                if url:
                    images.append(url)
            elif isinstance(image_value, list):
                images.extend(str(item) for item in image_value)
            elif isinstance(image_value, str):
                images.append(image_value)

        content_node = soup.select_one("div.detail-content") or soup.select_one("article")
        if content_node:
            for img in content_node.find_all("img"):
                src = img.get("data-src") or img.get("data-original") or img.get("src")
                if src:
                    images.append(src)

        unique: List[str] = []
        for url in images:
            cleaned = url.strip()
            if cleaned and cleaned not in unique:
                unique.append(cleaned)

        return [ArticleMedia(url=img_url, sequence_number=index + 1) for index, img_url in enumerate(unique)]

    @staticmethod
    def _extract_videos(soup: BeautifulSoup) -> List[ArticleMedia]:
        videos: List[str] = []
        for video_tag in soup.find_all("video"):
            if video_tag.get("src"):
                videos.append(video_tag["src"])
            for source in video_tag.find_all("source"):
                if source.get("src"):
                    videos.append(source["src"])
        for iframe in soup.find_all("iframe"):
            src = iframe.get("src")
            if src and "youtube.com" in src:
                videos.append(src)

        unique: List[str] = []
        for url in videos:
            cleaned = url.strip()
            if cleaned and cleaned not in unique:
                unique.append(cleaned)
        return [ArticleMedia(url=vid_url, sequence_number=index + 1) for index, vid_url in enumerate(unique)]

    # --------------------------------------------------------------------- #
    # Generic helpers
    # --------------------------------------------------------------------- #
    @staticmethod
    def _iter_months(
        start_year: int,
        start_month: int,
        end_year: int,
        end_month: int,
    ) -> Iterator[Tuple[int, int]]:
        current_year, current_month = start_year, start_month
        while (current_year, current_month) <= (end_year, end_month):
            yield current_year, current_month
            if current_month == 12:
                current_year += 1
                current_month = 1
            else:
                current_month += 1

    @staticmethod
    def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        value = value.strip()
        if not value:
            return None
        known_formats = [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%d/%m/%Y %H:%M",
            "%d-%m-%Y %H:%M",
        ]
        for fmt in known_formats:
            try:
                parsed = datetime.strptime(value, fmt)
                return parsed
            except ValueError:
                continue
        # Handle ISO strings with timezone offsets lacking colon (e.g. +0700)
        iso_match = re.match(
            r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})([+-]\d{2})(\d{2})", value
        )
        if iso_match:
            normalized = f"{iso_match.group(1)}{iso_match.group(2)}:{iso_match.group(3)}"
            try:
                return datetime.fromisoformat(normalized)
            except ValueError:
                pass
        # Fallback to fromisoformat for other variations.
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _slugify(value: str) -> Optional[str]:
        if not value:
            return None
        value = value.strip().lower()
        value = re.sub(r"[^a-z0-9]+", "-", value)
        value = re.sub(r"-{2,}", "-", value).strip("-")
        return value or None
