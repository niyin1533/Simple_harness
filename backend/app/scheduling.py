"""@input Calendar schedules. @output Durable due-time calculation. @position Scheduler.
@doc-sync Update header and INDEX.md on changes.
"""

from datetime import datetime
from zoneinfo import ZoneInfo
from croniter import croniter


def next_time(config, after_ms):
    zone = ZoneInfo(config.get("timezone", "Asia/Shanghai"))
    current = datetime.fromtimestamp(after_ms / 1000, zone)
    mode = config.get("type", config.get("mode", "daily"))
    if mode not in {"once", "daily", "weekly", "monthly", "cron"}:
        raise ValueError("未知计划周期")
    if mode == "once":
        value = datetime.fromisoformat(config["at"])
        if value.tzinfo is None:
            value = value.replace(tzinfo=zone)
        return int(value.timestamp() * 1000) if value > current else 0
    hour, minute = map(int, config.get("time", "09:00").split(":"))
    if not 0 <= hour < 24 or not 0 <= minute < 60:
        raise ValueError("时间不合法")
    day = "*"
    weekday = "*"
    if mode == "weekly":
        value = int(config.get("weekday", 0))
        if not 0 <= value <= 6:
            raise ValueError("星期需为 0-6")
        weekday = str((value + 1) % 7)
    if mode == "monthly":
        value = int(config.get("day", 1))
        if not 1 <= value <= 31:
            raise ValueError("日期需为 1-31")
        day = str(value)
    expression = (
        config.get("expression", config.get("cron", ""))
        if mode == "cron"
        else f"{minute} {hour} {day} * {weekday}"
    )
    if not croniter.is_valid(expression):
        raise ValueError("Cron 不合法")
    return int(croniter(expression, current).get_next(datetime).timestamp() * 1000)
