"""Підключення до PostgreSQL: engine і фабрика сесій."""
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from journal.config import database_url

engine = create_engine(database_url(), echo=False)
SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
