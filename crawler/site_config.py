from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True, slots=True)
class ArticleSiteConfig:
    """Configuration overrides for extracting article details from specific hosts."""

    title_selectors: Tuple[str, ...] = ()
    description_selectors: Tuple[str, ...] = ()
    main_container_selectors: Tuple[str, ...] = ()
    main_container_keywords: Tuple[str, ...] = ()
    excluded_section_selectors: Tuple[str, ...] = ()
    inline_image_container_selectors: Tuple[str, ...] = ()
    category_extractors: Tuple[str, ...] = ()
    tag_extractors: Tuple[str, ...] = ()
    inline_media_only: bool = False


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
    "cafebiz.vn": ArticleSiteConfig(
        main_container_selectors=(
            "div.detail-content[data-role='content']",
        ),
        main_container_keywords=("detail-content", "content"),
        category_extractors=("cafebiz_category",),
    ),
    "cafef.vn": ArticleSiteConfig(
        main_container_selectors=(
            "div#mainContent.detail-cmain",
            "div.detail-cmain.ss#mainContent",
            "div.detail-cmain.ss",
        ),
        main_container_keywords=("detail-cmain", "maincontent", "detail"),
        category_extractors=("cafef_category",),
    ),
    "vtv.vn": ArticleSiteConfig(
        category_extractors=("vtv_category",),
    ),
    "vietnamnet.vn": ArticleSiteConfig(
        category_extractors=("vietnamnet_category",),
        tag_extractors=("vietnamnet_tags",),
    ),
    "vietnamplus.vn": ArticleSiteConfig(
        main_container_selectors=(
            "div.article__body.zce-content-body.cms-body[itemprop='articleBody']",
            "div.article__body.zce-content-body.cms-body",
            "div.article__body",
        ),
        main_container_keywords=("article__body", "cms-body"),
    ),
    "dantri.com.vn": ArticleSiteConfig(
        title_selectors=(
            "h1",
            "meta[name='title']",
            "meta[property='og:title']",
        ),
        description_selectors=(
            ".singular-sapo",
            ".singular-sapo h2",
            "meta[name='description']",
        ),
        main_container_selectors=(
            ".singular-content",
            "div.singular-content",
        ),
        category_extractors=("dantri_category",),
    ),
    "congly.vn": ArticleSiteConfig(
        main_container_selectors=(
            "div.b-maincontent",
            ".b-maincontent",
        ),
        main_container_keywords=("b-maincontent", "maincontent"),
    ),
    "baocamau.vn": ArticleSiteConfig(
        category_extractors=("baocamau_category",),
    ),
    "baodongkhoi.vn": ArticleSiteConfig(
        category_extractors=("baodongkhoi_category",),
    ),
    "baodongnai.com.vn": ArticleSiteConfig(
        description_selectors=(
            "div#content.content-detail .td-post-content > p",
            "div#content.content-detail p",
        ),
        main_container_selectors=(
            "div#content.content-detail",
            "div#content.content-detail .td-post-content",
            "div.content-detail .td-post-content",
        ),
        main_container_keywords=("content-detail", "td-post-content", "content"),
        category_extractors=("baodongnai_category",),
        inline_media_only=True,
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
    "soha.vn": ArticleSiteConfig(
        main_container_selectors=(
            "div.detail-content.afcbc-body[data-role='content']",
            "div.detail-content[data-role='content']",
            "div.detail__content-page div.detail-content",
        ),
        main_container_keywords=("detail-content", "afcbc-body", "content"),
        category_extractors=("giadinh_suckhoedoisong_category", "soha_category"),
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
    "baolaocai.vn": ArticleSiteConfig(
        main_container_selectors=(
            "div[data-field='body']",
            "div.article__body.zce-content-body.cms-body[itemprop='articleBody']",
            "div.article__body.zce-content-body.cms-body",
            "div.article__body.cms-body",
            "div.article__body",
        ),
        main_container_keywords=("article__body", "cms-body", "zce-content-body", "article"),
        tag_extractors=("vneconomy_tags",),
    ),
    "baodautu.vn": ArticleSiteConfig(
        title_selectors=(
            "meta[property='dcterms.title']",
            "meta[name='dcterms.title']",
            "meta[property='og:title']",
            "meta[name='og:title']",
            "meta[name='title']",
            "h1.detail__title",
            ".detail__title",
            ".article__title",
            ".title-detail",
            ".title-article",
            ".detail-title",
        ),
        main_container_selectors=(
            "#content_detail_news",
            "div#content_detail_news",
            "div.detail__content",
            "div.detail__content.cms-body",
            "div.detail__content.content",
            "div.detail__content.detail-content",
            "div.detail__content article",
            "div.article__main",
            "div.article__body",
            "article.article__detail",
            "article.article-detail",
            "article.detail__body",
            "div.article__body",
            "div.article-content",
            "div.detail-content",
            "div.cms-body",
            "section.detail__body",
            "section.article__body",
            "article[itemprop='articleBody']",
        ),
        main_container_keywords=(
            "detail__content",
            "detail-content",
            "article__body",
            "article__main",
            "cms-body",
            "content",
            "detail",
        ),
        category_extractors=("baodautu_category",),
    ),
    "bnews.vn": ArticleSiteConfig(
        main_container_selectors=(
            "div.article__body div.article__content",
            "div.article__content",
            "div.article-detail__content",
            "div.article-content",
            "div.detail-content",
            "div.article__body",
            "section.article__body",
            "div[itemprop='articleBody']",
            "article[itemprop='articleBody']",
        ),
        main_container_keywords=("article__body", "article__content", "article-content", "detail-content"),
        excluded_section_selectors=(
            ".article__related",
            ".article__box--related",
            ".article-related",
            ".article__other",
            ".article__list--related",
            "[class*='tin-lien']",
            "[class*='tin_lien']",
            "[class*='tinlienquan']",
        ),
        inline_image_container_selectors=(
            ".post-mid-entry",
        ),
        inline_media_only=True,
    ),
    "baophapluat.vn": ArticleSiteConfig(
        category_extractors=("baophapluat_category",),
    ),
    "baoxaydung.vn": ArticleSiteConfig(
        category_extractors=("baoxaydung_category",),
    ),
    "vneconomy.vn": ArticleSiteConfig(
        description_selectors=(
            "div.news-sapo",
            "[data-field='sapo']",
            "div.news-sapo[data-field='sapo'] p",
            "div.news-sapo p",
            "[data-field='sapo'] p",
            "div.news-sapo[data-field='sapo'] p b",
        ),
        main_container_selectors=(
            "div[data-field='body']",
            "div.article__body",
            "div[itemprop='articleBody']",
        ),
        main_container_keywords=("article__body", "article", "body"),
        tag_extractors=("vneconomy_tags",),
    ),
    "nongnghiepmoitruong.vn": ArticleSiteConfig(
        description_selectors=("h2.main-intro.detail-intro",),
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
