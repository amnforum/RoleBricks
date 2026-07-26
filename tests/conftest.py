from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./data/test_emotionos.db")
os.environ.setdefault("USE_MOCK_TTS", "true")
os.environ.setdefault("SCENE_COMPILER_PROVIDER", "rules")
os.environ.setdefault("SCENE_RESEARCH_PROVIDER", "none")
os.environ.setdefault("SCENE_RETRIEVAL_PROVIDER", "database")
os.environ.setdefault("AUDIO_DATA_DIR", "./data/test_audio")
Path("data").mkdir(exist_ok=True)

from emotionos.app.core.config import get_settings
from emotionos.app.db.base import Base
from emotionos.app.db.session import make_engine

get_settings.cache_clear()


@pytest.fixture
def db_session(tmp_path):
    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from emotionos.app.db.session import engine
    from emotionos.app.main import app

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(engine)