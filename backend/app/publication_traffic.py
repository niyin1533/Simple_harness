"""@input Redis and MySQL admission counts. @output Atomic public rate admission, fail closed.
@position Distributed publication traffic boundary. @doc-sync Update INDEX.md on changes.
"""

from fastapi import HTTPException
from .config import settings
from .publication import keyed

RATE = """
local app = tonumber(redis.call('GET', KEYS[1]) or '0')
local ip = tonumber(redis.call('GET', KEYS[2]) or '0')
if app >= tonumber(ARGV[1]) or (ARGV[2] == 'web' and ip >= 10) then return 0 end
for i=1,2 do
  local count=redis.call('INCR', KEYS[i])
  if count == 1 then redis.call('PEXPIRE', KEYS[i], 60000) end
end
return 1
"""


async def admit(app, channel, ip):
    # MySQL app row lock serializes admissions and counts ALL durable queued/running runs.
    # It remains authoritative across Redis loss/restart; TTL cannot free live concurrency.
    from redis.asyncio import Redis
    try:
        async with Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2) as client:
            allowed = await client.eval(RATE, 2, "agent:publication:rate:" + app.id,
                                        "agent:publication:ip:" + app.id + ":" + keyed(ip), app.rpm,
                                        "web" if channel == "WEB_APP" else "api")
    except Exception as exc:
        raise HTTPException(503, "TRAFFIC_SERVICE_UNAVAILABLE") from exc
    if not allowed:
        raise HTTPException(429, "RATE_LIMIT_EXCEEDED")
