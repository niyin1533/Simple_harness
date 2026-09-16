"""@input User messages, existing private memories and governance model.
@output Validated stable-slot operations shared by explicit and asynchronous memory paths.
@position Memory governance service. @doc-sync Update INDEX.md on changes.
"""

import json
import re
import unicodedata
from sqlalchemy import select
from .db import Memory, Preference, Resource, User, public, now
from .providers import structured, embedding
from .security import sanitize

TYPES = {
    "fact": 0.70,
    "preference": 0.85,
    "rule": 0.95,
    "experience": 0.75,
    "error": 0.80,
    "context": 0.55,
}


def canonical(value):
    return "".join(
        c for c in unicodedata.normalize("NFKC", value).lower() if c.isalnum()
    )


def slot(meta):
    return (canonical(meta.get("entity", "")), canonical(meta.get("attribute", "")))


def validate_operations(value, rows, explicit):
    if not isinstance(value, dict) or not isinstance(value.get("operations"), list):
        raise ValueError("缺少 operations 数组")
    if len(value["operations"]) > 30:
        raise ValueError("治理操作过多")
    visible = {r.id: r for r in rows}
    for op in value["operations"]:
        if not isinstance(op, dict) or op.get("action") not in {
            "create",
            "update",
            "delete",
            "ignore",
        }:
            raise ValueError("治理操作无效")
        action = op["action"]
        if action == "ignore":
            continue
        target = op.get("targetMemoryId")
        if (target and target not in visible) or (
            action in {"update", "delete"} and not target
        ):
            raise ValueError("治理目标不存在或不可见")
        if action == "delete":
            if not explicit:
                raise ValueError("普通对话不能自动删除记忆")
            continue
        if op.get("scope") not in {"user", "agent"} or op.get("type") not in TYPES:
            raise ValueError("记忆范围或分类无效")
        if target and (visible[target].agent_id is None) != (op["scope"] == "user"):
            raise ValueError("更新不能改变记忆范围")
        for key in ("content", "entity", "attribute"):
            if (
                not isinstance(op.get(key), str)
                or not op[key].strip()
                or len(op[key]) > 500
            ):
                raise ValueError("治理字段缺失或过长")
        confidence = op.get("confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0.7 <= confidence <= 1
        ):
            raise ValueError("长期记忆置信度须为 0.70 至 1")
        if sanitize({"content": op["content"]})["content"] != op["content"]:
            raise ValueError("记忆包含凭据")


async def govern(db, user_id, agent_id, request, explicit=False):
    # Cross-worker serialization: model sees the latest committed memory state.
    await db.get(User, user_id, with_for_update=True)
    pref = await db.get(Preference, user_id)
    model = (
        await db.get(Resource, (pref.config if pref else {}).get("governance_model_id"))
        if pref
        else None
    )
    if not model or not model.enabled:
        raise ValueError("请先配置可用的记忆治理模型")
    rows = list(
        (
            await db.scalars(
                select(Memory)
                .where(
                    Memory.user_id == user_id,
                    Memory.enabled == True,
                    (Memory.agent_id.is_(None) | (Memory.agent_id == agent_id)),
                )
                .order_by(Memory.updated.desc())
                .limit(200)
            )
        ).all()
    )
    prompt = (
        "你是长期记忆治理模型，只依据用户原始消息，不把助手回答当事实。"
        "重复内容必须 ignore。entity+attribute 是稳定槽，同一槽的新值或补充 update 已有记录，保留未改变的信息。"
        "旧记录没有槽也要按语义判断是否重复，必要时 update 补充分类和槽，不能另建重复项。"
        "已有完整记忆覆盖的信息不可再拆成同义新条目。更新只改变用户明确要求改变的属性：例如只改称呼时，旧记录中的姓名等其他事实必须逐项保留。"
        "仅保留长期信息，confidence>=0.70。事实偏好普通规则 scope=user，明确限当前智能体才 scope=agent。"
        "只有用户明确要求忘记时才 delete；普通对话忽略一次性任务及寒暄。"
        '返回 JSON {"operations":[{"action":"create|update|delete|ignore","targetMemoryId":"已有ID或空",'
        '"scope":"user|agent","type":"fact|preference|rule|experience|error|context",'
        '"entity":"稳定实体","attribute":"稳定属性","value":"当前值","content":"完整当前状态",'
        '"confidence":0.9,"reason":"理由"}]}。无新信息返回 {"operations":[]}。'
    )
    context = [
        {
            "memoryId": r.id,
            "scope": "agent" if r.agent_id else "user",
            "content": r.content,
            **(r.meta or {}),
        }
        for r in rows
    ]
    try:
        value = await structured(
            {**public(model), "secret": model.secret},
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"explicit": explicit, "request": request, "existing": context},
                        ensure_ascii=False,
                    ),
                },
            ],
            lambda v: validate_operations(v, rows, explicit),
        )
    except ValueError as exc:
        # Never claim a failed governance request was saved as an active fact.
        safe = sanitize({"content": request[:500]})["content"]
        pending = next(
            (
                r
                for r in rows
                if r.content == safe
                and (r.meta or {}).get("source") == "governance_failure"
            ),
            None,
        )
        if not pending:
            db.add(
                Memory(
                    user_id=user_id,
                    agent_id=agent_id,
                    content=safe,
                    confirmed=False,
                    meta={
                        "type": "context",
                        "source": "governance_failure",
                        "review_reason": str(exc)[:200],
                    },
                )
            )
        return {
            "status": "pending_review",
            "message": "治理连续两次未通过校验，已留待审核，尚未形成有效记忆",
        }
    result = {
        "status": "success",
        "created": 0,
        "updated": 0,
        "deleted": 0,
        "ignored": 0,
        "pending": 0,
    }
    for op in value["operations"]:
        if op["action"] == "ignore":
            result["ignored"] += 1
            continue
        target = next((r for r in rows if r.id == op.get("targetMemoryId")), None)
        if op["action"] == "delete":
            target.enabled = False
            result["deleted"] += 1
            continue
        scope = agent_id if op["scope"] == "agent" else None
        metadata = {
            k: op.get(k, "")
            for k in ("type", "entity", "attribute", "value", "confidence")
        }
        metadata.update(
            importance=TYPES[op["type"]], source="explicit_tool" if explicit else "chat"
        )
        exact = next(
            (
                r
                for r in rows
                if r.agent_id == scope
                and canonical(r.content) == canonical(op["content"])
            ),
            None,
        )
        if exact:
            exact.meta = metadata
            result["ignored"] += 1
            continue
        if target is None:
            target = next(
                (
                    r
                    for r in rows
                    if r.agent_id == scope and slot(r.meta or {}) == slot(metadata)
                ),
                None,
            )
        if target is None:
            target = Memory(user_id=user_id, agent_id=scope, content=op["content"])
            db.add(target)
            rows.append(target)
            result["created"] += 1
        else:
            result["updated"] += 1
        target.content = op["content"]
        target.meta = metadata
        target.confirmed = not bool(
            re.search(
                r"\b\d{17}[\dXx]\b|\b1[3-9]\d{9}\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
                target.content,
            )
        )
        if not target.confirmed:
            result["pending"] += 1
            target.meta = {
                **metadata,
                "review_reason": "含个人联系方式或身份信息，请人工确认",
            }
        target.updated = now()
        target.vector = (
            await embedding(pref.config, target.content, pref.secret)
            if target.confirmed
            else None
        )
        await db.flush()
    if result["pending"]:
        result["status"] = "pending_review"
    return result


async def review(db, user_id):
    pref = await db.get(Preference, user_id)
    model = (
        await db.get(Resource, pref.config.get("governance_model_id")) if pref else None
    )
    if not model or not model.enabled:
        raise ValueError("请先配置治理模型")
    rows = list(
        (
            await db.scalars(
                select(Memory).where(Memory.user_id == user_id, Memory.enabled == True)
            )
        ).all()
    )
    if not rows:
        return {"suggestions": []}
    visible = {r.id: r for r in rows}

    def validate(value):
        if not isinstance(value, dict) or not isinstance(
            value.get("suggestions"), list
        ):
            raise ValueError("缺少 suggestions")
        for s in value["suggestions"]:
            if (
                not isinstance(s, dict)
                or s.get("id") not in visible
                or s.get("action") not in {"update", "disable"}
            ):
                raise ValueError("建议目标或操作无效")
            if s["action"] == "update" and (
                not isinstance(s.get("content"), str)
                or not s["content"].strip()
                or s.get("type") not in TYPES
            ):
                raise ValueError("建议内容或分类无效")

    return await structured(
        {**public(model), "secret": model.secret},
        [
            {
                "role": "system",
                "content": '审查记忆重复冲突及分类，仅给建议，不执行修改。不同 agent 范围不能合并。重复项保留信息最全的一条，其余建议 disable；冲突不能猜测新事实。返回 JSON {"suggestions":[{"id":"原ID","action":"update|disable","content":"完整内容","type":"fact|preference|rule|experience|error|context","reason":"理由"}]}。没有则空数组。',
            },
            {
                "role": "user",
                "content": json.dumps(
                    [
                        {
                            "id": r.id,
                            "agent_id": r.agent_id,
                            "content": r.content,
                            "meta": r.meta,
                        }
                        for r in rows
                    ],
                    ensure_ascii=False,
                ),
            },
        ],
        validate,
    )
