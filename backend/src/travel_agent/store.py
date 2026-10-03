"""PostgreSQL repositories; JSONB retains the exact claim and evidence contracts."""
import copy
import os
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class StoredClaim(Base):
    __tablename__ = "claims"
    claim_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class StoredJob(Base):
    __tablename__ = "evaluation_jobs"
    job_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class StoredEvaluation(Base):
    __tablename__ = "evaluations"
    evaluation_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.claim_id"), index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("evaluation_jobs.job_id"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class EvaluationStore(Protocol):
    async def open(self, claims: list[dict]): ...
    async def latest(self) -> dict[str, dict]: ...
    async def jobs(self) -> list[dict]: ...
    async def save_job(self, job: dict): ...
    async def save_evaluation(self, envelope: dict, job: dict | None = None): ...
    async def close(self): ...


class PostgresStore:
    def __init__(self, url: str | None = None):
        url = url or os.environ.get("DATABASE_URL", "postgresql+asyncpg://travel_app:travel_local_only@127.0.0.1:5433/travel_companion")
        if not url.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use postgresql+asyncpg://")
        self.engine = create_async_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def open(self, claims: list[dict]):
        async with self.engine.begin() as connection:
            # Initial prototype schema is idempotent. Future schema changes require a migration.
            await connection.run_sync(Base.metadata.create_all)
        async with self.sessions.begin() as session:
            for claim in claims:
                await session.execute(insert(StoredClaim).values(claim_id=claim["claim_id"], payload=claim)
                                      .on_conflict_do_nothing(index_elements=["claim_id"]))
            existing = (await session.scalars(select(StoredJob))).all()
            for job in existing:
                if job.payload.get("status") in {"queued", "running"}:
                    payload = dict(job.payload)
                    payload.update(status="failed", error="Server restarted before this job completed.", finished_at=datetime.now(timezone.utc).isoformat())
                    job.payload = payload

    async def latest(self) -> dict[str, dict]:
        async with self.sessions() as session:
            records = (await session.scalars(select(StoredEvaluation).distinct(StoredEvaluation.claim_id)
                       .order_by(StoredEvaluation.claim_id, StoredEvaluation.created_at.desc()))).all()
            return {record.claim_id: copy.deepcopy(record.payload) for record in records}

    async def jobs(self) -> list[dict]:
        async with self.sessions() as session:
            query = select(StoredJob).order_by(StoredJob.payload["created_at"].astext.desc()).limit(32)
            return [copy.deepcopy(job.payload) for job in (await session.scalars(query)).all()]

    async def save_job(self, job: dict):
        async with self.sessions.begin() as session:
            await session.execute(insert(StoredJob).values(job_id=job["job_id"], payload=job)
                                  .on_conflict_do_update(index_elements=["job_id"], set_={"payload": job}))

    async def save_evaluation(self, envelope: dict, job: dict | None = None):
        async with self.sessions.begin() as session:
            await session.execute(insert(StoredClaim).values(claim_id=envelope["claim"]["claim_id"], payload=envelope["claim"])
                                  .on_conflict_do_nothing(index_elements=["claim_id"]))
            if job:
                await session.execute(insert(StoredJob).values(job_id=job["job_id"], payload=job)
                                      .on_conflict_do_update(index_elements=["job_id"], set_={"payload": job}))
            session.add(StoredEvaluation(evaluation_id=uuid4().hex, claim_id=envelope["claim"]["claim_id"],
                        job_id=job["job_id"] if job else None, payload=envelope, created_at=datetime.now(timezone.utc)))

    async def close(self):
        await self.engine.dispose()
