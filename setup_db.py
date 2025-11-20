import os
from sqlalchemy import create_engine
from models import Base

# Default database connection URL
DEFAULT_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://crawl:crawl@localhost:5432/vnexpress_news"
)

def setup_database(database_url=DEFAULT_DATABASE_URL):
    """Create database tables if they don't exist."""
    engine = create_engine(database_url)
    
    # Create all tables
    print(f"Creating database tables on {database_url}...")
    Base.metadata.create_all(engine)
    print("Database tables created successfully!")

if __name__ == "__main__":
    setup_database()