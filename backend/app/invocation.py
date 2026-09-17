"""@input Trusted invocation context. @output Principal-isolated memory queries and inserts.
@position Identity boundary shared by console and published runtime.
@doc-sync Update header and INDEX.md on changes.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from sqlalchemy import event
from sqlalchemy.orm import Session as OrmSession, with_loader_criteria
from .db import Memory
from types import SimpleNamespace

principal = ContextVar("agent_principal", default=("PLATFORM_USER", ""))
memory_policy = ContextVar("published_memory_policy", default=None)


@contextmanager
def acting_as(end_user_id=None, policy=None):
    token = principal.set(("APP_END_USER", end_user_id) if end_user_id else ("PLATFORM_USER", ""))
    policy_token = memory_policy.set(policy if end_user_id else None)
    try:
        yield
    finally:
        principal.reset(token)
        memory_policy.reset(policy_token)


async def preferences(db, owner):
    from .db import Preference
    live = await db.get(Preference, owner)
    frozen = memory_policy.get()
    return SimpleNamespace(config=frozen, secret=live.secret if live else None) if frozen is not None else live


@event.listens_for(OrmSession, "do_orm_execute")
def scope_memories(state):
    if state.is_select or state.is_update or state.is_delete:
        kind, identity = principal.get()
        criterion = Memory.subject_type == kind
        if kind == "APP_END_USER":
            criterion = criterion & (Memory.subject_id == identity)
        state.statement = state.statement.options(with_loader_criteria(
            Memory, criterion,
            include_aliases=True,
        ))


@event.listens_for(OrmSession, "before_flush")
def assign_memory_subject(session, context, instances):
    kind, identity = principal.get()
    for row in session.new:
        if isinstance(row, Memory):
            row.subject_type = kind
            row.subject_id = identity if kind == "APP_END_USER" else row.user_id
