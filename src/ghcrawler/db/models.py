from datetime import datetime, date
from sqlalchemy import BigInteger, Date, Integer, Text, TIMESTAMP, ForeignKey, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass  # shared metadata lives here

class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name_owner: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    language: Mapped[str | None]
    created_at: Mapped[datetime | None]
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    stars = relationship("RepoStarSnapshot", back_populates="repo", cascade="all, delete")

class RepoStarSnapshot(Base):
    __tablename__ = "repo_star_snapshots"

    repo_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    star_count: Mapped[int] = mapped_column(Integer, nullable=False)

    repo = relationship("Repository", back_populates="stars")