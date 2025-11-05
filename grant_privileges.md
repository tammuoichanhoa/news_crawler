-- Chuyển quyền sở hữu database cho crawl
ALTER DATABASE vietnamese_news_db OWNER TO crawl;

-- Kết nối vào database đó
\c vietnamese_news_db;

-- Gán quyền cho schema public
GRANT ALL PRIVILEGES ON SCHEMA public TO crawl;
ALTER SCHEMA public OWNER TO crawl;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO crawl;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO crawl;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO crawl;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO crawl;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO crawl;
