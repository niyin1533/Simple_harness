"""@input SQLAlchemy and persistence base. @output Publication, identity and audit tables.
@position Additive publication schema. @doc-sync Update header and INDEX.md on changes.
"""

from sqlalchemy import String, Integer, Boolean, BigInteger, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, Text, uid, now


class PublishedApp(Base):
    __tablename__ = "published_apps"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    agent_id: Mapped[str] = mapped_column(String(128), unique=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    site_code: Mapped[str] = mapped_column(String(64), unique=True)
    current_version: Mapped[str | None] = mapped_column(String(36), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    web_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    api_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    rpm: Mapped[int] = mapped_column(Integer, default=30)
    concurrency: Mapped[int] = mapped_column(Integer, default=5)
    created: Mapped[int] = mapped_column(BigInteger, default=now)


class PublishedVersion(Base):
    __tablename__ = "published_versions"
    __table_args__ = (UniqueConstraint("app_id", "number"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    app_id: Mapped[str] = mapped_column(String(36), index=True)
    number: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    dependencies: Mapped[list] = mapped_column(JSON)
    grants: Mapped[dict] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str] = mapped_column(Text, default="")
    created: Mapped[int] = mapped_column(BigInteger, default=now)


class AppKey(Base):
    __tablename__ = "app_api_keys"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    app_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(100))
    digest: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(16))
    last_four: Mapped[str] = mapped_column(String(4))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_used: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, default=now)


class EndUser(Base):
    __tablename__ = "app_end_users"
    __table_args__ = (UniqueConstraint("app_id", "channel", "external_digest"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    app_id: Mapped[str] = mapped_column(String(36), index=True)
    channel: Mapped[str] = mapped_column(String(16))
    external_digest: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created: Mapped[int] = mapped_column(BigInteger, default=now)


class AppSession(Base):
    __tablename__ = "app_sessions"
    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    app_id: Mapped[str] = mapped_column(String(36), index=True)
    version_id: Mapped[str] = mapped_column(String(36))
    end_user_id: Mapped[str] = mapped_column(String(36), index=True)
    channel: Mapped[str] = mapped_column(String(16))


class Invocation(Base):
    __tablename__ = "app_invocations"
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    app_id: Mapped[str] = mapped_column(String(36), index=True)
    version_id: Mapped[str] = mapped_column(String(36))
    end_user_id: Mapped[str] = mapped_column(String(36), index=True)
    channel: Mapped[str] = mapped_column(String(16))
    key_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    public_seq: Mapped[int] = mapped_column(Integer, default=0)


class Idempotency(Base):
    __tablename__ = "app_idempotency"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[str] = mapped_column(String(36))
    expires: Mapped[int] = mapped_column(BigInteger)


class PublicEvent(Base):
    __tablename__ = "app_events"
    __table_args__ = (UniqueConstraint("run_id", "seq"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict] = mapped_column(JSON)


class PublicationAudit(Base):
    __tablename__ = "publication_audit"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    app_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created: Mapped[int] = mapped_column(BigInteger, default=now)
