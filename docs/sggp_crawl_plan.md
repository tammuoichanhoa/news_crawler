# SGGP.org.vn News Crawl Plan

## Sitemap Structure
- Root index `https://www.sggp.org.vn/sitemap.xml` lists monthly news sitemaps (`.../sitemaps/news-YYYY-M.xml`) plus auxiliary category/topic maps.
- Monthly news sitemaps are gzip-compressed; request with `Accept-Encoding: gzip` or `--compressed`, then parse `<urlset>` entries.
- News URLs follow the pattern `https://www.sggp.org.vn/<slug>-post<ID>.html`, accompanied by `<lastmod>` timestamps for freshness metadata.

## Crawl Workflow
1. **Compliance & Throttling**: Read `robots.txt`, honor disallow rules, and cap requests to ~1 rps with jitter. Persist crawl state (timestamps, processed article IDs) for resumable runs.
2. **Index Harvest**: Fetch the root sitemap, extract monthly news sitemap URLs within the desired date window, enqueue them for processing.
3. **Monthly Sitemap Parse**: Download each news sitemap, collect `<loc>`/`<lastmod>` pairs, and filter URLs by the `-post` suffix. Deduplicate entries by article ID.
4. **Fetch Articles**: Issue HTTPS GET requests using a desktop user-agent. Retry transient failures (429/5xx) with exponential backoff; log permanent errors.
5. **Content Extraction**:
   - Title: `<h1 class="article__title">` or `meta[property="og:title"]`
   - Deck/Sapo: `<div class="article__sapo cms-desc">`
   - Body: `<div class="article__body cms-body">`, capturing paragraphs, blockquotes, embedded media; resolve lazy images via `data-src`.
   - Metadata: publication/updated times (`meta[property="article:published_time"]`, `article:modified_time`), author (`div.article__author`), categories (`meta[property="article:section"]`), tags (`div.article__tag a`).
   - Related links & media captions can be stored separately for enrichment.
6. **Output Schema**: Normalize per-article JSON (or JSONL) with fields: `id`, `url`, `crawl_time`, `lastmod`, `published_at`, `title`, `sapo`, `body_html`, `body_text`, `author`, `categories`, `tags`, `media[]`, plus optional `raw_html`.
7. **Incremental Updates**: Use `lastmod` to detect new/changed articles, maintain a processed-ID ledger, and rerun scheduled sitemap checks (e.g., hourly for current month, daily for older months).

## Operational Notes
- Respect cookies and redirects enforced by the site; the desktop version keeps content under the same HTML structure.
- Monitor for structural changes (class names, lazy-load conventions) and adjust selectors accordingly.
- Consider storing screenshots or snapshots for QA on initial runs.
- Add health metrics (processed count, failure rate) and alerts for sustained HTTP errors or DOM mismatches.
