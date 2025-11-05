from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True, slots=True)
class ArticleSiteConfig:
    """Configuration overrides for extracting article details from specific hosts."""

    title_selectors: Tuple[str, ...] = ()
    main_container_selectors: Tuple[str, ...] = ()
    main_container_keywords: Tuple[str, ...] = ()
    category_extractors: Tuple[str, ...] = ()
    tag_extractors: Tuple[str, ...] = ()


ARTICLE_SITE_CONFIG: Dict[str, ArticleSiteConfig] = {
    "mattran.org.vn": ArticleSiteConfig(
        title_selectors=(
            "meta[property='dcterms.title']",
            ".news-title",
            ".detail-title",
            ".content-title",
            ".title-news",
            ".box-detail-title",
            ".post-title",
            ".article-title",
        ),
        main_container_selectors=(
            ".article__body",
            ".article__content",
            ".article-container .article__body",
            "#ContentDetail",
            ".content-detail",
            ".detail-content",
            ".news-detail",
            ".post-detail",
            ".entry-content",
            ".article-detail",
        ),
        main_container_keywords=("content", "detail", "article", "entry", "main"),
    ),
    "genk.vn": ArticleSiteConfig(
        main_container_selectors=("div#ContentDetail",),
        category_extractors=("genk_category",),
    ),
    "kenh14.vn": ArticleSiteConfig(
        category_extractors=("kenh14_category",),
        tag_extractors=("kenh14_tags",),
    ),
    "baocamau.vn": ArticleSiteConfig(
        category_extractors=("baocamau_category",),
    ),
    "baodongkhoi.vn": ArticleSiteConfig(
        category_extractors=("baodongkhoi_category",),
    ),
    "nguoiquansat.vn": ArticleSiteConfig(
        main_container_selectors=(
            "article.entry.entry-no-padding",
            "div.b-maincontent.normal-article-content article.entry",
        ),
        main_container_keywords=("entry", "article"),
    ),
    "giadinh.suckhoedoisong.vn": ArticleSiteConfig(
        main_container_selectors=(
            "div.detail-content.afcbc-body[data-role='content']",
            "div.detail-content[data-role='content']",
            "div.detail__content-page div.detail-content",
        ),
        main_container_keywords=("detail-content", "afcbc-body", "content"),
        category_extractors=("giadinh_suckhoedoisong_category",),
    ),
    "nhandan.vn": ArticleSiteConfig(
        main_container_selectors=(
            "div.article__body",
            "div.article__main",
            "article.article",
            "div.cms-body",
        ),
        main_container_keywords=("article__body", "cms-body", "zce-content-body", "article"),
    ),
    "anninhthudo.vn": ArticleSiteConfig(
        main_container_selectors=(
            "div.article__body",
            "div.cms-body",
        ),
        main_container_keywords=("article__body", "cms-body", "zce-content-body", "article"),
    ),
}


def _matches_domain(domain: str, pattern: str) -> bool:
    if domain == pattern:
        return True
    return domain.endswith(f".{pattern}")


def get_article_site_config(domain: str) -> ArticleSiteConfig | None:
    """Return configuration overrides for the given domain, if any."""
    normalized = domain.lower()
    for pattern, config in ARTICLE_SITE_CONFIG.items():
        if _matches_domain(normalized, pattern):
            return config
    return None
