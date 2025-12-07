# VNExpress News Crawler

A Python-based web crawler for collecting news articles from VNExpress, one of Vietnam's leading online newspapers. The crawler supports article content, images, videos, and comments collection with PostgreSQL storage.

## Features

- Crawls articles from multiple categories
- Downloads and stores article images locally
- Collects video references
- Stores article comments
- Supports date range-based crawling
- PostgreSQL database integration
- Configurable crawling parameters

## Prerequisites

- Python 3.x
- PostgreSQL database
- Required Python packages (install via `requirements.txt`)

## Installation

1. Clone the repository
2. Install the required dependencies:
```bash
pip install -r requirements.txt
```

3. Set up PostgreSQL database and ensure it's running
4. Configure environment variables (optional):
   - `DATABASE_URL`: PostgreSQL connection string (default: "postgresql://crawl:crawl@localhost:5432/vnexpress_news")
   - `IMAGE_STORAGE_DIR`: Directory for storing downloaded images

## Usage

Basic usage:
```bash
python main.py
```

### Command Line Arguments

- `--start-date`: ISO formatted start date (default: 7 days before end-date)
- `--end-date`: ISO formatted end date (default: current time)
- `--interval-days`: Size of the crawl window in days (default: 7)
- `--max-pages`: Maximum pages per date window (default: 10)
- `--workers`: Number of concurrent workers fetching article details (default: 4)
- `--request-delay`: Delay between listing requests in seconds to avoid throttling (default: 0.25)
- `--skip-comments`: Skip Selenium-based comment crawling for faster runs
- `--categories`: Optional list of category slugs to crawl (e.g., thoi-su the-gioi)
- `--database-url`: PostgreSQL connection string
- `--urls-file`: Path to store/load crawled article URLs (default: `resume_url.txt`)
- `--only-crawl-urls`: Only crawl article URLs, save them, and exit
- `--use-url-file`: Skip category crawling and load article URLs from the specified file

### Examples

Crawl articles from specific categories for the last 7 days:
```bash
python main.py --categories thoi-su the-gioi
```

Crawl articles for a specific date range:
```bash
python main.py --start-date 2020-07-01 --end-date 2025-11-20
```

Crawl with custom database connection:
```bash
python main.py --database-url "postgresql://crawl:crawl@localhost:5432/vnexpress"
```

Step 1: only crawl and save URLs:
```bash
python main.py --only-crawl-urls --urls-file resume_url.txt
```

Step 2: resume detail crawling from the saved list of URLs:
```bash
python main.py --use-url-file --urls-file resume_url.txt
```

Speed up a crawl while avoiding comment scraping:
```bash
python main.py --workers 8 --request-delay 0.1 --skip-comments
```

## Data Storage

### Database Schema

The crawler uses SQLAlchemy ORM with the following main tables:
- `articles`: Stores article metadata and content
- `article_images`: Stores downloaded image information
- `article_videos`: Stores video references

### Image Storage

Images are downloaded and stored in the configured `IMAGE_STORAGE_DIR` with a naming pattern of:
`{article_id}_img_{sequence}{extension}`

## Contributing

Feel free to open issues or submit pull requests for improvements or bug fixes.

## License

[Insert your chosen license here]


Usage:

Crawl URLs only: python main.py --only-crawl-urls --urls-file resume_url.txt
Resume detail crawl from saved URLs: python main.py --use-url-file --urls-file resume_url.txt