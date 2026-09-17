"""@input Existing platform schema. @output Additive publication tables and memory subjects.
@position Idempotent single-agent publication migration. @doc-sync Update INDEX.md on changes.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGTEXT

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def tables():
    """Frozen definitions: future application models must not change migration history."""
    metadata = sa.MetaData()
    def col(name, type_, **kwargs):
        return sa.Column(name, type_, nullable=kwargs.pop("nullable", False), **kwargs)
    def idcol(name="id"):
        return col(name, sa.String(36), primary_key=True)
    def ref(name, indexed=False, nullable=False):
        return col(name, sa.String(36), index=indexed, nullable=nullable)
    def integer(name):
        return col(name, sa.Integer())
    def stamp(name="created", nullable=False):
        return col(name, sa.BigInteger(), nullable=nullable)
    def boolean(name):
        return col(name, sa.Boolean())
    def jsoncol(name):
        return col(name, sa.JSON())
    sa.Table("published_apps", metadata, idcol(), col("agent_id", sa.String(128), unique=True),
             ref("user_id", True), col("site_code", sa.String(64), unique=True), ref("current_version", nullable=True),
             boolean("enabled"), boolean("web_enabled"), boolean("api_enabled"), integer("rpm"), integer("concurrency"), stamp())
    sa.Table("published_versions", metadata, idcol(), ref("app_id", True), integer("number"), jsoncol("snapshot"),
             jsoncol("dependencies"), jsoncol("grants"), col("checksum", sa.String(64)), col("notes", LONGTEXT()), stamp(),
             sa.UniqueConstraint("app_id", "number"))
    sa.Table("app_api_keys", metadata, idcol(), ref("app_id", True), col("name", sa.String(100)),
             col("digest", sa.String(64), unique=True), col("prefix", sa.String(16)), col("last_four", sa.String(4)),
             boolean("active"), stamp("expires", True), stamp("last_used", True), stamp())
    sa.Table("app_end_users", metadata, idcol(), ref("app_id", True), col("channel", sa.String(16)),
             col("external_digest", sa.String(64)), boolean("active"), stamp(), sa.UniqueConstraint("app_id", "channel", "external_digest"))
    sa.Table("app_sessions", metadata, idcol("session_id"), ref("app_id", True), ref("version_id"),
             ref("end_user_id", True), col("channel", sa.String(16)))
    sa.Table("app_invocations", metadata, idcol("run_id"), ref("app_id", True), ref("version_id"),
             ref("end_user_id", True), col("channel", sa.String(16)), ref("key_id", nullable=True), integer("public_seq"))
    sa.Table("app_idempotency", metadata, col("id", sa.String(64), primary_key=True), col("request_hash", sa.String(64)), ref("run_id"), stamp("expires"))
    sa.Table("app_events", metadata, col("id", sa.BigInteger(), primary_key=True, autoincrement=True),
             ref("run_id", True), integer("seq"), col("name", sa.String(32)), jsoncol("data"), sa.UniqueConstraint("run_id", "seq"))
    sa.Table("publication_audit", metadata, idcol(), ref("app_id", True), ref("actor_id"),
             col("action", sa.String(64)), jsoncol("details"), stamp())
    return metadata


def upgrade():
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("memories")}
    if "subject_type" not in columns:
        op.add_column("memories", sa.Column("subject_type", sa.String(24), nullable=False, server_default="PLATFORM_USER"))
        op.create_index("ix_memories_subject_type", "memories", ["subject_type"])
    if "subject_id" not in columns:
        op.add_column("memories", sa.Column("subject_id", sa.String(36), nullable=False, server_default=""))
        op.create_index("ix_memories_subject_id", "memories", ["subject_id"])
    tables().create_all(bind, checkfirst=True)
    op.execute("UPDATE memories SET subject_id = user_id WHERE subject_type = 'PLATFORM_USER' AND subject_id = ''")


def downgrade():
    raise RuntimeError("Publication history must be retained; restore a verified backup instead.")
