"""
Rate limiting (tiêu chí 7).

  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây (sliding window)
  • Vượt giới hạn → HTTP 429 kèm header Retry-After
  • State lưu trong Redis (sorted set) → mọi worker / instance dùng chung, còn sau khi restart
"""
import hashlib
import math
import time
import uuid

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def _bucket(key: str) -> str:
    # Không lưu API key thô trong Redis — chỉ lưu hash
    return "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:24]


def check_rate_limit(key: str) -> None:
    limit = settings.rate_limit_per_minute
    bucket = _bucket(key)
    now = time.time()
    member = f"{now:.6f}-{uuid.uuid4().hex[:8]}"
    try:
        pipe = r.pipeline()
        pipe.zremrangebyscore(bucket, 0, now - WINDOW_SECONDS)   # bỏ request ngoài cửa sổ
        pipe.zadd(bucket, {member: now})                         # ghi request hiện tại
        pipe.zcard(bucket)                                       # đếm trong cửa sổ 60s
        pipe.expire(bucket, WINDOW_SECONDS + 1)
        _, _, count, _ = pipe.execute()
        if count > limit:
            r.zrem(bucket, member)                               # request bị chặn không tính
            oldest = r.zrange(bucket, 0, 0, withscores=True)
            retry_after = WINDOW_SECONDS
            if oldest:
                retry_after = max(1, math.ceil(WINDOW_SECONDS - (now - oldest[0][1])))
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {limit} requests per minute",
                headers={"Retry-After": str(retry_after)},
            )
    except redis.RedisError:
        # Không có Redis thì không đảm bảo được giới hạn → từ chối an toàn (fail closed)
        raise HTTPException(status_code=503, detail="Rate limiter unavailable")
