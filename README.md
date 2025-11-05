# Local News Crawler

This project crawls news sitemaps and persists article details to the PostgreSQL schema defined in `db/models.py`.

## Setup

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Provide a PostgreSQL database URL via the `DATABASE_URL` environment variable, or pass it through `--database-url`. Example:

   ```bash
   export DATABASE_URL=postgresql://user:password@localhost:5432/crawl_db
   ```

You can also place this value in a local `.env` file (loaded automatically via `python-dotenv`):

```bash
echo "DATABASE_URL=postgresql://user:password@localhost:5432/crawl_db" > .env
```

## Usage

Use the `main.py` entrypoint to run the workflow:

```bash
python main.py \
  --sitemaps-file sitemaps.txt \
  --stored-urls-dir stored_urls
```

The command performs two steps:

1. Fetch sitemap URLs and append new article links to `stored_urls/<slug>_urls.txt`.
2. Sequentially crawl those URLs and insert articles (plus related images/videos) into the database.

### Common Options

- `--skip-url-collection`: Reuse cached URLs without re-downloading sitemaps.
- `--skip-article-ingest`: Only collect URLs, skip database writes.
- `--slug example_com`: Process a single sitemap slug (slug is derived from the sitemap domain).
- `--max-urls-per-site 100`: Limit the number of article URLs processed per slug in a single run.
- `--max-total-urls 200`: Stop after crawling the specified number of URLs across all sites.
- `--allowed-extension .html`: Only cache URLs whose paths end with the given extensions (can be repeated).
- `--sitemap-include '*sitemap-article*'`: Restrict child sitemap traversal to matching glob patterns (useful when a sitemap index mixes article/image feeds).
- `--direct-crawl`: Skip URL caching and crawl articles directly from the provided sitemaps in one pass.
- `--verbose`: Enable debug logging.

The pipeline is idempotent: stored URL files prevent duplicate sitemap work and the `articles.url` unique constraint avoids inserting the same article twice. Re-running after a failure will resume the crawl from the last successfully stored article.

When ingesting from `stored_urls`, progress is tracked in `stored_urls/<slug>_cursor.txt`, so subsequent runs continue from the next URL without repeating work. Delete or edit the cursor file to restart from the beginning.

### Direct Crawl Mode

To fetch sitemap URLs and immediately ingest articles (without writing `stored_urls/<slug>_urls.txt`), use:

```bash
python main.py --direct-crawl --sitemaps-file sitemaps.txt --max-urls-per-site 10
```

Optional filters like `--slug` and `--sitemap-include` still apply in direct mode.
Combine with `--max-total-urls` to cap overall work, e.g. `--max-total-urls 20`.

## Verify Crawled Data

Use the inspection helper to review what has been stored:

```bash
python inspect_data.py --host baohaiphong.vn --limit 3
```

The script prints totals for articles/images/videos and displays the selected entries (filterable by hostname, ordered by publish date or created time). Include `--show-content 300` to preview the first 300 characters of each article.

Generate a simple quality report (missing tags, short content) with:

```bash
python quality_check.py --host baohaiphong.vn --content-threshold 400
```

> The requirements include `psycopg2-binary` for convenience. If you prefer a compiled driver in production, install `psycopg2` with the necessary PostgreSQL build headers instead.
