import gzip
import io
import logging
import random
import ssl
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from fnmatch import fnmatch
from html.parser import HTMLParser
from typing import Iterable, List, Sequence, Set
from urllib.parse import urlparse, urljoin

import requests
from requests.adapters import HTTPAdapter

from .throttle import RequestThrottler
from .utils import extract_article_id


logger = logging.getLogger(__name__)
LEGACY_SSL_HOSTS = {"bnews.vn"}


class _LegacySSLAdapter(HTTPAdapter):
    """HTTP adapter that enables legacy TLS renegotiation support."""

    def __init__(self) -> None:
        self.ssl_context = ssl.create_default_context()
        option = getattr(ssl, "OP_LEGACY_SERVER_CONNECT", None)
        if option:
            self.ssl_context.options |= option
        super().__init__()

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self.ssl_context
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs["ssl_context"] = self.ssl_context
        return super().proxy_manager_for(*args, **kwargs)


@dataclass(frozen=True)
class SitemapEntry:
    url: str
    lastmod: str | None = None
    article_id: str | None = None

    @property
    def dedupe_key(self) -> str:
        return self.article_id or self.url


class SitemapCrawler:
    """Utility to collect article URLs from sitemap and sitemap index files."""

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: int = 20,
        allowed_extensions: Iterable[str] | None = None,
        include_patterns: Sequence[str] | None = None,
        exclude_patterns: Sequence[str] | None = None,
        user_agent: str | None = None,
        throttler: RequestThrottler | None = None,
        url_include_patterns: Sequence[str] | None = None,
        url_exclude_patterns: Sequence[str] | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout
        self.allowed_extensions: Set[str] | None = (
            set(ext.lower() for ext in allowed_extensions)
            if allowed_extensions
            else None
        )
        self.include_patterns = list(include_patterns) if include_patterns else None
        self.exclude_patterns = list(exclude_patterns) if exclude_patterns else None
        self.url_patterns = list(url_include_patterns) if url_include_patterns else None
        self.url_exclude_patterns = list(url_exclude_patterns) if url_exclude_patterns else None
        self.throttler = throttler

        if user_agent:
            self.session.headers["User-Agent"] = user_agent
        self._configure_legacy_ssl_hosts()

    def fetch_urls(self, sitemap_url: str) -> List[SitemapEntry]:
        """Fetch sitemap (or sitemap index) and return structured article entries."""
        try:
            response = self._request_with_retry(sitemap_url)
        except Exception as exc:
            logger.error("Failed to fetch sitemap %s: %s", sitemap_url, exc)
            return []

        raw_content = self._maybe_decompress(response, sitemap_url)
        entries: List[SitemapEntry] = []

        try:
            root = ET.fromstring(raw_content)
        except ET.ParseError as exc:
            fallback_entries = self._parse_non_xml_sitemap(sitemap_url, raw_content)
            if fallback_entries is not None:
                return fallback_entries
            logger.error("Failed to parse sitemap %s: %s", sitemap_url, exc)
            return []

        namespace = self._detect_namespace(root)

        if root.tag.endswith("sitemapindex"):
            child_tag = f"{namespace}loc" if namespace else "loc"
            for sitemap in root.findall(f"{namespace}sitemap" if namespace else "sitemap"):
                loc = sitemap.find(child_tag)
                if loc is not None and loc.text:
                    loc_text = loc.text.strip()
                    if self._allowed_child_sitemap(loc_text):
                        entries.extend(self.fetch_urls(loc_text))
        else:
            for url in root.findall(f"{namespace}url" if namespace else "url"):
                loc = url.find(f"{namespace}loc" if namespace else "loc")
                if loc is None or not loc.text:
                    continue
                loc_text = loc.text.strip()
                if self._looks_like_child_sitemap(sitemap_url, loc_text):
                    if self._allowed_child_sitemap(loc_text):
                        entries.extend(self.fetch_urls(loc_text))
                    continue
                if not self._allowed_url(loc_text):
                    continue
                lastmod_element = url.find(f"{namespace}lastmod" if namespace else "lastmod")
                lastmod_text = lastmod_element.text.strip() if lastmod_element is not None and lastmod_element.text else None
                entries.append(
                    SitemapEntry(
                        url=loc_text,
                        lastmod=lastmod_text,
                        article_id=extract_article_id(loc_text),
                    )
                )
        return entries

    def _configure_legacy_ssl_hosts(self) -> None:
        if not LEGACY_SSL_HOSTS:
            return

        adapter = _LegacySSLAdapter()
        for host in LEGACY_SSL_HOSTS:
            if not host:
                continue
            normalized = host.strip()
            if not normalized:
                continue
            if normalized.startswith("http://") or normalized.startswith("https://"):
                prefix = normalized.rstrip("/") + "/"
            else:
                prefix = f"https://{normalized.rstrip('/')}/"
            self.session.mount(prefix, adapter)

    def _maybe_decompress(
        self, response: requests.Response, source_url: str
    ) -> bytes:
        """Decompress gzip responses if needed."""
        content = response.content
        content_type = response.headers.get("Content-Type", "")
        if (
            content_type.startswith("application/gzip")
            or content_type.startswith("application/x-gzip")
            or source_url.endswith(".gz")
        ):
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(content)) as gz:
                    return gz.read()
            except OSError:
                logger.warning("Failed to decompress gzip for %s; using raw content", source_url)
        return content

    @staticmethod
    def _detect_namespace(root: ET.Element) -> str:
        if root.tag.startswith("{"):
            namespace_uri = root.tag.split("}")[0].strip("{")
            return f"{{{namespace_uri}}}"
        return ""

    def _allowed_url(self, url: str) -> bool:
        if not self.allowed_extensions:
            allowed = True
        else:
            path = urlparse(url).path.lower()
            allowed = any(path.endswith(ext) for ext in self.allowed_extensions)

        if not allowed:
            return False

        if self.url_exclude_patterns and any(fnmatch(url, pattern) for pattern in self.url_exclude_patterns):
            return False

        if not self.url_patterns:
            return True
        return any(fnmatch(url, pattern) for pattern in self.url_patterns)

    def _looks_like_child_sitemap(self, parent_url: str, candidate_url: str) -> bool:
        """Detect sitemap indexes that embed child sitemap URLs inside <urlset> entries."""
        try:
            parent_host = urlparse(parent_url).netloc.lower()
        except Exception:  # pragma: no cover - defensive guard
            parent_host = ""

        parsed = urlparse(candidate_url)
        candidate_host = parsed.netloc.lower()

        if parent_host and candidate_host and parent_host != candidate_host:
            return False

        path = parsed.path.lower()
        if not path:
            return False

        if path.startswith("/sitemaps/") or path.startswith("/sitemap/"):
            return True

        filename = path.rsplit("/", 1)[-1]
        if not filename:
            return False

        if filename.startswith("sitemap") and (
            filename.endswith(".xml") or filename.endswith(".xml.gz") or filename.endswith(".txt")
        ):
            return True
        return False

    def _allowed_child_sitemap(self, url: str) -> bool:
        if self.exclude_patterns and any(fnmatch(url, pattern) for pattern in self.exclude_patterns):
            return False
        if not self.include_patterns:
            return True
        return any(fnmatch(url, pattern) for pattern in self.include_patterns)

    def _request_with_retry(self, url: str, max_attempts: int = 3) -> requests.Response:
        attempt = 0
        last_exc: Exception | None = None
        while attempt < max_attempts:
            try:
                if self.throttler:
                    self.throttler.wait()
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                return response
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                # Retry on transient server errors.
                if status not in {500, 502, 503, 504}:
                    raise
                last_exc = exc
            except requests.RequestException as exc:
                last_exc = exc

            attempt += 1
            sleep_time = min(5.0, 0.5 * (2 ** attempt))  # exponential backoff capped at 5s
            jitter = random.uniform(0, 0.3 * sleep_time)
            time.sleep(sleep_time + jitter)

        if last_exc:
            raise last_exc
        raise RuntimeError(f"Failed to fetch {url} after {max_attempts} attempts")

    def _parse_non_xml_sitemap(self, sitemap_url: str, content: bytes) -> List[SitemapEntry] | None:
        """
        Handle hosts that publish sitemap listings as HTML pages instead of XML (e.g. baophapluat.vn).
        """
        host = urlparse(sitemap_url).netloc.lower()
        if not host.endswith("baophapluat.vn"):
            return None

        parser = _AnchorExtractor()
        try:
            parser.feed(content.decode("utf-8", errors="ignore"))
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to parse HTML sitemap %s: %s", sitemap_url, exc)
            return []
        parser.close()

        entries: List[SitemapEntry] = []
        for href in parser.links:
            article_url = urljoin(sitemap_url, href)
            if not self._allowed_url(article_url):
                continue
            entries.append(
                SitemapEntry(
                    url=article_url,
                    article_id=extract_article_id(article_url),
                )
            )
        return entries


class _AnchorExtractor(HTMLParser):
    """Lightweight link extractor for HTML-based sitemap listings."""

    def __init__(self) -> None:
        super().__init__()
        self.links: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        for attr, value in attrs:
            if attr.lower() == "href" and value:
                self.links.append(value.strip())
                break
