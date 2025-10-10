from sqlalchemy import Column, Text, String, DateTime, ForeignKey, Integer, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
from datetime import datetime
import uuid_utils
import uuid


def generate_uuid7():
    """Generate UUIDv7 and convert to standard Python UUID"""
    uuid7_obj = uuid_utils.uuid7()
    return uuid.UUID(str(uuid7_obj))

Base = declarative_base()


class Article(Base):
    __tablename__ = 'articles'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid7)
    title = Column(String(500), nullable=False, index=True)
    description = Column(Text)
    content = Column(Text)
    category_id = Column(String(100), index=True)
    category_name = Column(String(200), index=True)
    comments = Column(JSONB)
    tags = Column(String(500), index=True)
    url = Column(String(2000), unique=True, nullable=False)
    publish_date = Column(DateTime, index=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    images = relationship(
        "ArticleImage",
        back_populates="article",
        cascade="all, delete-orphan",
        order_by="ArticleImage.sequence_number"
    )
    videos = relationship(
        "ArticleVideo",
        back_populates="article",
        cascade="all, delete-orphan",
        order_by="ArticleVideo.sequence_number"
    )
    
    def __repr__(self):
        return f"<Article(id={self.id}, title='{self.title[:30]}...', url='{self.url}')>"


class ArticleImage(Base):
    __tablename__ = 'article_images'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid7)
    article_id = Column(UUID(as_uuid=True), ForeignKey('articles.id', ondelete='CASCADE'), nullable=False)
    image_path = Column(String(500), nullable=False)
    sequence_number = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    # Relationship
    article = relationship("Article", back_populates="images")
    
    # Composite index for efficient queries
    __table_args__ = (
        Index('ix_article_images_article_id_seq', 'article_id', 'sequence_number'),
    )
    
    def __repr__(self):
        return f"<ArticleImage(id={self.id}, article_id={self.article_id}, path='{self.image_path}')>"


class ArticleVideo(Base):
    __tablename__ = 'article_videos'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid7)
    article_id = Column(UUID(as_uuid=True), ForeignKey('articles.id', ondelete='CASCADE'), nullable=False)
    video_path = Column(String(500), nullable=False)
    sequence_number = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    # Relationship
    article = relationship("Article", back_populates="videos")
    
    # Composite index for efficient queries
    __table_args__ = (
        Index('ix_article_videos_article_id_seq', 'article_id', 'sequence_number'),
    )
    
    def __repr__(self):
        return f"<ArticleVideo(id={self.id}, article_id={self.article_id}, path='{self.video_path}')>"


# Helper functions for generating file paths
def generate_image_path(article_id: uuid.UUID, sequence_number: int, extension: str = "jpg") -> str:
    """Generate image path following the naming convention"""
    return f"{article_id}_img_{sequence_number}.{extension}"


def generate_video_path(article_id: uuid.UUID, sequence_number: int, extension: str = "mp4") -> str:
    """Generate video path following the naming convention"""
    return f"{article_id}_video_{sequence_number}.{extension}"


# Example usage:
if __name__ == "__main__":
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    
    # Create engine (replace with your actual database URL)
    engine = create_engine('postgresql://user:password@localhost:5432/crawl_db')
    
    # Create all tables
    Base.metadata.create_all(engine)
    
    # Create session
    Session = sessionmaker(bind=engine)
    session = Session()
    
    # Example: Create an article with images and videos
    article = Article(
        title="Sample Article with UUIDv7",
        description="This is a sample article using UUIDv7 for IDs",
        content="Full content here...",
        category_id="tech",
        category_name="Technology",
        tags="python,database,crawling,uuid",
        url="https://example.com/article/sample-uuid",
        publish_date=datetime.now(),
        comments={"count": 10, "list": [{"user": "john", "text": "Great article!"}]}
    )
    
    # Add to session to generate ID
    session.add(article)
    session.flush()  # Generates the UUID
    
    # Add images
    article.images.append(ArticleImage(
        image_path=generate_image_path(article.id, 1),
        sequence_number=1
    ))
    article.images.append(ArticleImage(
        image_path=generate_image_path(article.id, 2),
        sequence_number=2
    ))
    
    # Add videos
    article.videos.append(ArticleVideo(
        video_path=generate_video_path(article.id, 1),
        sequence_number=1
    ))
    
    session.commit()
    
    print(f"Created article with ID: {article.id}")
    print(f"Article: {article}")
    print(f"Images: {article.images}")
    print(f"Videos: {article.videos}")
    
    # Example query by UUID
    fetched_article = session.query(Article).filter(Article.id == article.id).first()
    print(f"\nFetched article: {fetched_article}")
    print(f"Title: {fetched_article.title}")
    print(f"Number of images: {len(fetched_article.images)}")
    print(f"Number of videos: {len(fetched_article.videos)}")
