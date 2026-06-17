from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, Text, Boolean
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session


DB_PATH = "data/pipeline.db"


class Base(DeclarativeBase):
    pass


class ArchiveItem(Base):
    __tablename__ = "archive_items"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    url = Column(String, nullable=False)
    duration = Column(Integer, nullable=True)        # 초 단위
    broadcast_date = Column(String, nullable=True)
    downloaded = Column(Boolean, default=False)
    local_path = Column(String, nullable=True)
    downloaded_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    archive_item_id = Column(String, nullable=False)
    start_time = Column(Float, nullable=False)       # 초 단위
    end_time = Column(Float, nullable=False)         # 초 단위
    transcript = Column(Text, nullable=True)
    interest_score = Column(Float, nullable=False)
    reason = Column(Text, nullable=True)
    analyzed_at = Column(DateTime, default=datetime.utcnow)


class ShortsItem(Base):
    __tablename__ = "shorts_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_result_id = Column(Integer, nullable=False)
    archive_item_id = Column(String, nullable=False)
    local_path = Column(String, nullable=False)
    title = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    tags = Column(String, nullable=True)
    uploaded = Column(Boolean, default=False)
    youtube_video_id = Column(String, nullable=True)
    uploaded_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


def get_engine():
    Path("data").mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
    Base.metadata.create_all(engine)
    return engine


def get_session() -> Session:
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()
