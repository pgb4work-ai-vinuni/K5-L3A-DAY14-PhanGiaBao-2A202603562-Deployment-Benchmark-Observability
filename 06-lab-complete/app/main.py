"""
Production AI Agent — Part 6 Final Project

Đạt 12 tiêu chí trong README.md:
  /health (liveness), /ready (readiness theo Redis), X-API-Key → 401,
  rate limit Redis → 429, cost guard Redis → 402, config từ env,
  log JSON, graceful shutdown qua lifespan của uvicorn.

Kiểm tra: python check_production_ready.py
"""
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


# ── Structured logging: mỗi dòng là 1 JSON object ──────────────────────────
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        payload.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(payload, ensure_ascii=False, default=str)


logger = logging.getLogger("agent")
logger.setLevel(settings.log_level)
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(JsonFormatter())
logger.handlers = [_handler]
logger.propagate = False


def log(event: str, level: int = logging.INFO, **fields):
    logger.log(level, event, extra={"extra_fields": fields})


# ── Lifespan: khởi động + graceful shutdown ────────────────────────────────
# Uvicorn tự bắt SIGTERM: ngừng nhận kết nối mới, chờ request đang chạy xong,
# rồi chạy phần sau `yield` và thoát với exit code 0. Không đăng ký handler
# SIGTERM riêng để khỏi chặn mất handler của uvicorn.
@asynccontextmanager
async def lifespan(app: FastAPI):
    log("startup", environment=settings.environment, port=settings.port,
        redis_ok=redis_healthy(), rate_limit_per_minute=settings.rate_limit_per_minute)
    if not settings.agent_api_key:
        log("agent_api_key_not_set", logging.WARNING)
    yield
    log("shutdown", reason="SIGTERM or server stop — in-flight requests finished")
    try:
        r.close()
    except Exception:
        pass


app = FastAPI(title="Production AI Agent", lifespan=lifespan,
              docs_url=None if settings.environment == "production" else "/docs")


@app.middleware("http")
async def access_log(request: Request, call_next):
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        log("request", method=request.method, path=request.url.path, status=status,
            ms=round((time.perf_counter() - start) * 1000, 1))


# ── Xử lý lỗi: mã lỗi rõ ràng, không lộ stack trace ─────────────────────────
@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    errors = [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "msg": e.get("msg")}
              for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": "Invalid request body", "errors": errors})


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    log("unhandled_error", logging.ERROR, path=request.url.path, error_type=type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=100)


@app.get("/")
def root():
    return {"service": "production-ai-agent", "endpoints": ["/health", "/ready", "POST /ask"]}


@app.get("/health")
def health():
    """Liveness: process còn chạy là 200, không phụ thuộc Redis."""
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """Readiness: chỉ nhận traffic khi Redis kết nối được."""
    if redis_healthy():
        return {"status": "ready", "redis": "ok"}
    return JSONResponse(status_code=503, content={"status": "not ready", "redis": "unreachable"})


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)           # 429 khi vượt giới hạn
    check_budget()                      # 402 khi hết budget
    answer = llm_ask(body.question)
    cost = record_cost(estimate_tokens(body.question), estimate_tokens(answer))
    log("ask", user_id=body.user_id, q_len=len(body.question), cost_usd=round(cost, 8))
    return {"question": body.question, "answer": answer}
