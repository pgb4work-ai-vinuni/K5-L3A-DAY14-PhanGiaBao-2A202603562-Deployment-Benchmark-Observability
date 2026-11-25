# Deployment Information

## Public URL
https://day14-agent-production-f8c3da1f.up.railway.app

## Platform
**Railway**: project `day14-phangiabao-agent`, environment `production`, service `day14-agent`. Deploy thư mục `06-lab-complete/` bằng `railway up`; Railway build từ Dockerfile multi-stage theo `06-lab-complete/railway.toml` (builder `DOCKERFILE`, `healthcheckPath = "/health"`).
Redis: service `Redis` (có volume `redis-volume`) trong cùng project, nối với agent qua biến tham chiếu `REDIS_URL=${{Redis.REDIS_URL}}`. Log khởi động của agent có `redis_ok: true`.

> Ghi chú: chạy `railway up` trực tiếp từ thư mục trên ổ Windows mount vào WSL (`/mnt/d/...`) luôn lỗi `header key "exclude-patterns" contains value with non-printable ASCII characters`. Cách khắc phục: copy `06-lab-complete/` sang ổ Linux của WSL (`~/day14-deploy`), chạy `railway link`, rồi `railway up` từ đó.

## Test Commands

Đặt biến trước (không ghi key thật vào file này):

```bash
export BASE=https://day14-agent-production-f8c3da1f.up.railway.app
export AGENT_API_KEY=<key đã đặt trên platform>
```

### 4 lệnh tự kiểm (CP6) — chỉ in mã HTTP

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả (ngày 2026-11-25, ảnh: `screenshots/test.png`):

```text
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
200
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
200
$ curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'
401
$ curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'
200
$ for i in $(seq 1 12); do curl -s -o /dev/null -w '%{http_code} ' -X POST "$BASE/ask" -H "X-API-Key: $AGENT_API_KEY" -H 'Content-Type: application/json' -d '{"question":"test"}'; done; echo
200 200 200 200 200 200 200 200 200 200 429 429
$ python 06-lab-complete/check_production_ready.py --public-url "$BASE" --static-only | grep "Public URL"
✅ 12. Public URL ready (Railway / Render config)
     ✅ Public URL: GET https://day14-agent-production-f8c3da1f.up.railway.app/health → 200
```

Deploy log trên Railway (`screenshots/running.png`) xác nhận: uvicorn chạy 2 worker, log JSON `event: startup environment: production redis_ok: true rate_limit_per_minute: 10`; request `/ask` không key → `401`, có key → `200`.

### Health Check
```bash
curl $BASE/health
# Expected: {"status":"ok"}
```

### API Test (with authentication)
```bash
curl -X POST $BASE/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "What is deployment?"}'
```

### Rate limit (10 req/phút) → 429
```bash
for i in $(seq 1 12); do
  curl -s -o /dev/null -w '%{http_code} ' -X POST $BASE/ask \
    -H "X-API-Key: $AGENT_API_KEY" -H 'Content-Type: application/json' -d '{"question":"test"}'
done; echo
# Expected: 200 ×10 rồi 429
```

### Script chấm với URL public
```bash
cd 06-lab-complete && python check_production_ready.py --public-url $BASE
```

## Environment Variables Set
Đặt trên dashboard / CLI của platform, **không** ghi trong code:

| Biến | Giá trị |
|---|---|
| `AGENT_API_KEY` | secret (chuỗi ngẫu nhiên dài, chỉ đặt trên platform) |
| `REDIS_URL` | tham chiếu tới Redis của platform (vd `${{Redis.REDIS_URL}}` trên Railway) |
| `ENVIRONMENT` | `production` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `MONTHLY_BUDGET_USD` | `10.0` |
| `LOG_LEVEL` | `INFO` |
| `PORT` | do platform tự cấp (Dockerfile lắng nghe `${PORT:-8000}`) |

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
