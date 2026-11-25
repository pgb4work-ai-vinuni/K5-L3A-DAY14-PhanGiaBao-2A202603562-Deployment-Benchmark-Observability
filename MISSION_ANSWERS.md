# Day 14 Lab — Mission Answers

> Repo: `K5-L3A-DAY14-PhanGiaBao-2A202603562-Deployment-Benchmark-Observability`
> Output trong file này lấy từ lệnh đã chạy thật (2026-11-25). Phần Part 1, 4, 5.1–5.2 chạy trên Linux VM (Python 3.10); phần cần Docker chạy trên Docker Desktop + WSL2.

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`

1. **Hard-code secret** (dòng 17–18): `OPENAI_API_KEY = "sk-hardcoded-..."` và `DATABASE_URL = "postgresql://admin:password123@..."`. Push lên GitHub là lộ key và mật khẩu DB, và secret nằm mãi trong lịch sử git.
2. **Log ra secret và dùng `print()`** (dòng 33–34, 38): `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` in thẳng API key ra log. Log không có cấu trúc (không level, không timestamp, không JSON) nên log aggregator không lọc được.
3. **Không có config management** (dòng 21–22): `DEBUG = True`, `MAX_TOKENS = 500` cố định trong code. Muốn đổi giữa dev/staging/prod phải sửa code và build lại.
4. **Không có health check / readiness** (dòng 42): không có `/health`, `/ready`. Platform không biết agent đã treo hay crash để restart, load balancer không biết lúc nào nên ngừng gửi traffic.
5. **Bind `localhost` và port cố định 8000** (dòng 51–52): trong container, `localhost` chỉ nhận kết nối từ bên trong container. Railway/Render cấp port qua biến `PORT` nên app sẽ không nhận được request.
6. **`reload=True` ở production** (dòng 53): auto-reload tốn tài nguyên, theo dõi file system, không dùng khi chạy thật.
7. **Không xử lý graceful shutdown**: không có lifespan/cleanup, nên khi platform gửi SIGTERM lúc deploy, request đang chạy có thể bị cắt ngang.
8. **Không validate input**: `question: str` lấy từ query, không giới hạn độ dài, không có auth.

### Exercise 1.2: Chạy bản develop

```text
$ curl -X POST "http://localhost:8000/ask?question=Hello"
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
$ curl -i http://localhost:8000/health
HTTP/1.1 404 Not Found
```

Nó chạy, nhưng **không production-ready**: không có `/health` (404), và log server in ra secret:

```text
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
```

### Exercise 1.3: So sánh với bản production

```text
$ curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","model":"gpt-4o-mini"}
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":3.7,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T13:50:29.686081+00:00"}
$ curl http://localhost:8000/ready
{"ready":true}
```

| Feature | Develop | Production | Tại sao quan trọng? |
|---------|---------|------------|---------------------|
| Config | Hard-code trong code (`DEBUG=True`, key, port) | `config.py` đọc env (`os.getenv`), `.env.example`, `validate()` fail-fast nếu thiếu `AGENT_API_KEY` ở production | Cùng một image chạy được ở mọi môi trường; secret không nằm trong git; đổi cấu hình không cần build lại |
| Secrets | `sk-...`, `password123` trong code và bị `print` ra log | Đọc từ env, không log secret (chỉ log `question_length`) | Lộ key là mất tiền, mất dữ liệu; log thường được nhiều người và hệ thống đọc |
| Health check | Không có (`/health` → 404) | `/health` (liveness: uptime, version) + `/ready` (readiness: 503 khi chưa sẵn sàng) | Platform tự restart khi agent chết; load balancer chỉ gửi traffic vào instance đã sẵn sàng |
| Logging | `print()` text tự do | Logging có level, format JSON (`{"event": "agent_request", ...}`) | Parse, lọc, alert được trong Loki/Datadog; gắn được với request/trace |
| Shutdown | Đột ngột, không cleanup | `lifespan`: startup/shutdown, `is_ready=False` khi tắt, handler SIGTERM | Deploy hoặc scale down không cắt ngang request đang chạy |
| Host / Port | `localhost:8000` cố định | `0.0.0.0` + `PORT` từ env | Chạy được trong container và trên cloud (platform inject `PORT`) |
| Reload / Debug | `reload=True` luôn bật | `reload` chỉ khi `DEBUG=true` | Tránh tốn tài nguyên và hành vi khó lường ở production |
| Input | Query param, không validate | JSON body, kiểm tra `question` rỗng → 422 | Lỗi rõ ràng cho client, tránh crash |

---

## Part 2: Docker

### Exercise 2.1: Câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11`, bản Debian đầy đủ (có compiler, header, nhiều tool), khoảng 1 GB.
2. **Working directory:** `/app` (`WORKDIR /app`). Mọi `COPY`/`RUN`/`CMD` sau đó chạy tương đối với thư mục này.
3. **Vì sao `COPY requirements.txt` trước rồi mới copy code:** Docker cache theo layer. `requirements.txt` ít thay đổi, nên layer `pip install` được dùng lại từ cache. Khi chỉ sửa `app.py`, Docker chỉ build lại layer `COPY app.py` (vài giây). Nếu `COPY . .` đứng trước thì mỗi lần sửa code đều phải `pip install` lại từ đầu.
4. **CMD vs ENTRYPOINT:** `ENTRYPOINT` là chương trình chính, cố định của container. `CMD` là lệnh hoặc tham số *mặc định*, bị ghi đè khi chạy `docker run image <lệnh khác>`. Khi dùng cả hai, `CMD` trở thành tham số truyền cho `ENTRYPOINT`. Nên dùng exec form (`["python","app.py"]`) để process là PID 1 và nhận được SIGTERM.

### Exercise 2.2: Build và run bản develop

```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run --rm -p 8000:8000 my-agent:develop
curl -X POST "http://localhost:8000/ask?question=What%20is%20Docker"
```

```text
$ curl -X POST "http://localhost:8000/ask?question=What%20is%20Docker"
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":3.9,"container":true}
```

### Exercise 2.3: Multi-stage build và kích thước image

- **Stage 1 (builder):** `python:3.11-slim` + cài `gcc`, `libpq-dev`, rồi `pip install --user` toàn bộ dependencies. Stage này có build tool nặng và không được deploy.
- **Stage 2 (runtime):** `python:3.11-slim` mới, chỉ `COPY --from=builder /root/.local` (packages đã cài) + source code, tạo user non-root `appuser`, có `HEALTHCHECK`.
- **Vì sao nhỏ hơn:** image cuối không chứa gcc, header, cache apt/pip và các layer trung gian của stage build; base `slim` cũng nhỏ hơn nhiều so với `python:3.11` đầy đủ.

```text
$ docker images | grep my-agent
my-agent:advanced                       7d131cea6a30        240MB         57.4MB        
my-agent:develop                        50914a1fda5a       1.67GB          426MB        

develop  bytes=1667784100
advanced bytes=239815357
```

- Develop (`python:3.11` đầy đủ, single-stage): **1667.8 MB** (1 667 784 100 bytes, `docker images` hiển thị 1.67GB)
- Production (multi-stage, `python:3.11-slim`): **239.8 MB** (239 815 357 bytes, hiển thị 240MB)
- Chênh lệch: **giảm 85.6 %** (= (1667.8 − 239.8) / 1667.8 × 100), image production nhỏ hơn khoảng 7 lần

### Exercise 2.4: Docker Compose stack (`02-docker/production/`)

Các service được start: **agent** (FastAPI, build từ Dockerfile multi-stage), **redis** (`redis:7-alpine`: cache session/rate limit), **qdrant** (vector DB cho RAG), **nginx** (reverse proxy / load balancer, cổng 80 ra ngoài).

```text
           Client (curl)
               │  :80
               ▼
        ┌─────────────┐
        │    nginx    │  rate limit 10 r/s/IP, security headers
        └──────┬──────┘
               │ http://agent:8000  (network "internal")
               ▼
        ┌─────────────┐
        │    agent    │  không publish port ra host
        └───┬─────┬───┘
   redis:6379│     │http://qdrant:6333
            ▼     ▼
      ┌───────┐ ┌────────┐
      │ redis │ │ qdrant │   volumes: redis_data, qdrant_data
      └───────┘ └────────┘
```

Các service giao tiếp qua bridge network `internal` bằng **tên service** (Docker DNS): `agent` gọi `redis://redis:6379` và `http://qdrant:6333`, còn Nginx proxy tới upstream `agent:8000`. Chỉ Nginx publish cổng ra host. `depends_on: condition: service_healthy` đảm bảo redis/qdrant healthy rồi mới start agent.

```text
$ docker compose -p k5-day14-docker ps
NAME                       IMAGE                   COMMAND                  SERVICE   CREATED          STATUS                    PORTS
k5-day14-docker-agent-1    k5-day14-docker-agent   "uvicorn main:app --…"   agent     25 seconds ago   Up 15 seconds (healthy)   8000/tcp
k5-day14-docker-nginx-1    nginx:alpine            "/docker-entrypoint.…"   nginx     25 seconds ago   Up 15 seconds             0.0.0.0:80->80/tcp, [::]:80->80/tcp, 0.0.0.0:443->443/tcp, [::]:443->443/tcp
k5-day14-docker-qdrant-1   qdrant/qdrant:v1.9.0    "./entrypoint.sh"        qdrant    25 seconds ago   Up 24 seconds (healthy)   6333-6334/tcp
k5-day14-docker-redis-1    redis:7-alpine          "docker-entrypoint.s…"   redis     25 seconds ago   Up 24 seconds (healthy)   6379/tcp

$ curl http://localhost/health
{"status":"ok","uptime_seconds":14.3,"version":"2.0.0","timestamp":"2026-11-25T15:22:46.403343"}
$ curl -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question":"What is Docker?"}'
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

Cả 4 container đều `Up`; agent, redis, qdrant `healthy`. Chỉ Nginx publish cổng ra host (`0.0.0.0:80`); agent chỉ có `8000/tcp` nội bộ. Request vào `localhost:80` đi qua Nginx tới agent.

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deploy agent Part 6

- Nền tảng chính: **Railway** (Docker build từ `06-lab-complete/Dockerfile`, Redis là service riêng trong cùng project)
- URL: **https://day14-agent-production-f8c3da1f.up.railway.app**
- Kết quả 4 lệnh tự kiểm CP6: `/health` 200 · `/ready` 200 · `/ask` không key 401 · `/ask` có key 200; vòng lặp 12 request → 10 × `200` rồi `429`; `check_production_ready.py --public-url` → ✅ Public URL.
- Chi tiết, biến môi trường và lệnh test: [DEPLOYMENT.md](DEPLOYMENT.md). Ảnh chụp: `screenshots/dashboard.png`, `running.png`, `test.png`.

### So sánh `railway.toml` với `render.yaml`

| Khía cạnh | `railway.toml` | `render.yaml` |
|---|---|---|
| Phạm vi | Cấu hình **một service** (build + deploy) | **Blueprint** (Infrastructure as Code) cho cả hệ thống: nhiều service + database/Redis trong một file |
| Build | `[build] builder = "DOCKERFILE"` (hoặc NIXPACKS/RAILPACK tự detect) | `runtime: docker` + `dockerfilePath`/`dockerContext` (hoặc `runtime: python` + `buildCommand`) |
| Start / Port | Dùng `CMD` của Dockerfile hoặc `startCommand`; Railway inject `PORT` | Dùng `CMD` của Dockerfile hoặc `startCommand`; Render inject `PORT` |
| Health check | `healthcheckPath = "/health"`, `healthcheckTimeout` | `healthCheckPath: /health` |
| Restart | `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries` | Render tự quản lý, không cấu hình trong file |
| Biến môi trường / secret | **Không khai báo trong file**: đặt bằng dashboard hoặc `railway variables set` | Khai báo trong `envVars`: giá trị thường dùng `value`, secret dùng `sync: false` (điền tay) hoặc `generateValue: true` (Render tự sinh) |
| Redis / DB | Tạo service Redis riêng trong project rồi tham chiếu `REDIS_URL` bằng biến | Khai báo ngay trong file (`type: keyvalue`/`redis`), nối bằng `fromService ... property: connectionString` |
| Region / plan | Chọn trên dashboard | `region: singapore`, `plan: free` ngay trong file |

**Vì sao khác:** Railway thiên về "deploy nhanh từ CLI": file chỉ mô tả cách build/chạy một service, còn hạ tầng và secret quản lý ngoài file. Render coi `render.yaml` là nguồn sự thật cho toàn bộ hạ tầng (GitOps): commit file là Render tạo hoặc đồng bộ đủ service, Redis, biến môi trường. Vì file nằm trong git, Render phải có cơ chế `sync: false`/`generateValue` để không ghi secret vào file.

### Exercise 3.3: Pipeline CI/CD trên Cloud Run (`cloudbuild.yaml` + `service.yaml`)

Mỗi lần push, Cloud Build chạy 4 bước nối tiếp nhau bằng `waitFor`:
1. **test**: `pip install` + `pytest` trong `python:3.11-slim`; test fail thì dừng pipeline.
2. **build**: `docker build` gắn tag `:$COMMIT_SHA` và `:latest`, dùng `--cache-from` image `latest` để tận dụng layer cache.
3. **push**: đẩy cả hai tag lên Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **deploy**: `gcloud run deploy` image theo đúng commit SHA lên `asia-southeast1` (min 1 / max 10 instance, 512Mi, 1 CPU, timeout 60s). Secret lấy từ **Secret Manager** (`--set-secrets`), không nằm trong code.

`service.yaml` mô tả cùng service theo dạng khai báo (Knative): autoscale 1–10 instance với `containerConcurrency: 80`, giới hạn CPU/RAM, secret qua `secretKeyRef`, `livenessProbe` vào `/health` và `startupProbe` vào `/ready`.

---

## Part 4: API Security

### Exercise 4.1: API Key authentication (`04-api-gateway/develop`)

- **Key được check ở đâu?** Trong dependency `verify_api_key()`: `APIKeyHeader(name="X-API-Key")` đọc header, so với `API_KEY = os.getenv("AGENT_API_KEY")`. Endpoint `/ask` khai báo `Depends(verify_api_key)` nên request bị chặn trước khi vào logic.
- **Sai key thì sao?** Thiếu key trả **401**. Key sai trả **403** "Invalid API key" (bản Part 6 của mình trả 401 cho cả hai trường hợp, theo hợp đồng).
- **Rotate key thế nào?** Đổi biến `AGENT_API_KEY` trên platform rồi restart/redeploy, không cần sửa code. Để không gián đoạn: cho phép tạm thời **hai key** (cũ + mới, ví dụ `AGENT_API_KEYS=old,new`), chuyển client sang key mới, rồi gỡ key cũ.

Bật bằng `AGENT_API_KEY=secret-key-123 python app.py`:

```text
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'   # không có key
HTTP/1.1 401 Unauthorized
content-length: 67
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: wrong-key" ...   # sai key
HTTP/1.1 403 Forbidden
content-length: 29
content-type: application/json

{"detail":"Invalid API key."}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: secret-key-123" ...   # đúng key
HTTP/1.1 200 OK
content-length: 114
content-type: application/json

{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

### Exercise 4.2 + 4.3: JWT và rate limiting (`04-api-gateway/production`)

Luồng JWT: `POST /auth/token` với `student`/`demo123` → server ký token HS256 chứa `sub`, `role`, `exp` (60 phút) → client gửi `Authorization: Bearer <token>` → `verify_token` kiểm chữ ký và hạn, không cần tra DB.

- **Limit:** user thường 10 request/60 s (`rate_limiter_user`), admin 100 request/60 s (`rate_limiter_admin`). Thuật toán: sliding window, mỗi user có một `deque` timestamp.
- **Bypass cho admin:** endpoint chọn limiter theo `role` trong JWT (`rate_limiter_admin if role == "admin"`), nên tài khoản role admin (`teacher`) có hạn mức cao hơn. Muốn bỏ hẳn giới hạn thì bỏ qua `limiter.check()` khi `role == "admin"`.

Output (token đã che):

```text
$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
HTTP/1.1 200 OK
content-length: 307
content-type: application/json

{"access_token":"<TOKEN_REDACTED>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer <TOKEN_REDACTED>"}


$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"what is docker?"}'   # không có token
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
content-length: 76
content-type: application/json

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}


$ for i in $(seq 1 12); do curl -s -o /dev/null -w "%{http_code} " -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"question\":\"test $i\"}"; done
200 200 200 200 200 200 200 200 200 200 429 429 

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer <TOKEN_REDACTED>" ...   # request thứ 13
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795614725
retry-after: 59
content-length: 98
content-type: application/json

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}


$ curl -s http://localhost:8000/me/usage -H "Authorization: Bearer <TOKEN_REDACTED>"
{"user_id":"student","date":"2026-11-25","requests":10,"input_tokens":40,"output_tokens":308,"cost_usd":0.000191,"budget_usd":1.0,"budget_remaining_usd":0.999809,"budget_used_pct":0.0}
```

10 request đầu trả 200, từ request thứ 11 trả **429** kèm `Retry-After` và `X-RateLimit-*`.

### Exercise 4.4: Cost guard

Bản mẫu `04-api-gateway/production/cost_guard.py` đếm token in-memory theo user/ngày: vượt $1/ngày/user trả **402**, vượt $10/ngày toàn hệ thống trả 503, cảnh báo ở 80 %.

Cách mình làm trong Part 6 (`06-lab-complete/app/cost_guard.py`):
- **Trước khi gọi LLM**, `check_budget()` đọc tổng chi phí từ Redis bằng một lệnh `MGET` hai key `cost:daily:YYYY-MM-DD` và `cost:monthly:YYYY-MM` (UTC). Nếu `>= DAILY_BUDGET_USD` hoặc `>= MONTHLY_BUDGET_USD` thì trả **402 Payment Required**.
- **Sau khi gọi LLM**, `record_cost()` ước lượng token (~4 ký tự/token), tính tiền theo giá gpt-4o-mini ($0.15/1M input, $0.60/1M output) rồi `INCRBYFLOAT` vào cả hai key trong một pipeline, kèm `EXPIRE` (2 ngày / 32 ngày) để key tự dọn và tự reset khi sang ngày/tháng mới.
- State nằm trong **Redis** nên mọi worker/instance cộng dồn chung và không mất khi restart. Redis lỗi khi kiểm budget thì trả 503 (fail-closed), không cho gọi LLM "miễn phí".
- Ngân sách đọc từ env (mặc định $1/ngày, $10/tháng).
- **Vì sao cần cả rate limit lẫn cost guard:** rate limit bảo vệ *tốc độ* (chống spam, DoS trên mỗi key); cost guard bảo vệ *tiền*. Nhiều key, hoặc request hợp lệ nhưng prompt rất dài, vẫn có thể đốt ngân sách dù không vượt rate limit.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks

`/health` (liveness) trả 200 kèm uptime và trạng thái memory khi process còn sống; platform restart container nếu endpoint này fail. `/ready` (readiness) trả 503 khi đang khởi động hoặc đang tắt (`_is_ready=False`), hoặc khi dependency (Redis/DB) chưa kết nối; load balancer chỉ gửi traffic vào instance trả 200. Phân biệt: **mất Redis thì instance vẫn sống** (không nên bị restart vô ích), chỉ tạm thời không nhận traffic. Vì vậy trong Part 6, `/health` luôn 200 còn `/ready` 503.

### Exercise 5.2: Graceful shutdown

```text
$ curl -s http://localhost:8000/health
{"status":"ok","uptime_seconds":3.5,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T13:51:26.795325+00:00","checks":{"memory":{"status":"ok","used_percent":9.7}}}
$ curl -s http://localhost:8000/ready
{"ready":true,"in_flight_requests":1}

$ curl -X POST "http://localhost:8000/ask?question=Long%20task" &   # gửi request
$ kill -TERM $PID                                                  # ngay lập tức
Kết quả request đang chạy: {"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."} [HTTP 200]
Process còn sống sau SIGTERM? không — đã tự thoát
```

Log server:

```text
INFO:     Shutting down
INFO:     127.0.0.1:42890 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
2026-11-25 13:51:29,959 INFO 🔄 Graceful shutdown initiated...
2026-11-25 13:51:29,959 INFO ✅ Shutdown complete
INFO:     Finished server process [8]
2026-11-25 13:51:29,959 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

Khi nhận SIGTERM, uvicorn ngừng nhận kết nối mới ("Shutting down"), **chờ request `/ask` đang chạy trả 200**, rồi mới chạy phần shutdown của `lifespan` và thoát. Request không bị cắt ngang.

### Exercise 5.3: Stateless design

Nếu lưu `conversation_history = {}` trong RAM, mỗi instance có dict riêng: request 1 vào instance A, request 2 vào instance B thì B không thấy history. Restart hoặc scale down cũng làm mất toàn bộ state. Bản production lưu session vào Redis (`session:<id>`, `SETEX` TTL 1h), nên mọi instance đọc cùng một nguồn và instance nào cũng phục vụ được bất kỳ request nào. Part 6 áp dụng cùng nguyên tắc: rate limit và cost đều nằm trong Redis.

### Exercise 5.4: Load balancing (`05-scaling-reliability/production`, cổng 8080, `POST /chat`)

```bash
touch .env.local
docker compose -p k5-day14-scaling up -d --build --scale agent=3
```

```text
$ docker compose -p k5-day14-scaling ps
NAME                       IMAGE                    COMMAND                  SERVICE   CREATED          STATUS                    PORTS
k5-day14-scaling-agent-1   k5-day14-scaling-agent   "python -m uvicorn a…"   agent     25 seconds ago   Up 15 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-2   k5-day14-scaling-agent   "python -m uvicorn a…"   agent     25 seconds ago   Up 15 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-3   k5-day14-scaling-agent   "python -m uvicorn a…"   agent     25 seconds ago   Up 15 seconds (healthy)   8000/tcp
k5-day14-scaling-nginx-1   nginx:alpine             "/docker-entrypoint.…"   nginx     24 seconds ago   Up 15 seconds             0.0.0.0:8080->80/tcp, [::]:8080->80/tcp
k5-day14-scaling-redis-1   redis:7-alpine           "docker-entrypoint.s…"   redis     25 seconds ago   Up 24 seconds (healthy)   6379/tcp

$ for i in 1..10: curl -X POST http://localhost:8080/chat ...  (in served_by)
req 1 -> instance-01cbde
req 2 -> instance-1f5c1c
req 3 -> instance-5a56e2
req 4 -> instance-01cbde
req 5 -> instance-1f5c1c
req 6 -> instance-5a56e2
req 7 -> instance-01cbde
req 8 -> instance-1f5c1c
req 9 -> instance-5a56e2
req 10 -> instance-01cbde

$ docker compose -p k5-day14-scaling logs agent | grep -c POST (theo instance)
      5 agent-1
      5 agent-2
      5 agent-3
```

Có 3 agent `healthy`. 10 request được chia **round-robin** tuần tự `01cbde → 1f5c1c → 5a56e2 → 01cbde…`, và log cho thấy mỗi instance xử lý đúng 5 request `/chat` (tính cả 5 request của `test_stateless.py`).

Nginx resolve `agent` qua Docker DNS (`resolver 127.0.0.11`), round-robin giữa 3 container, và `proxy_next_upstream error timeout http_503` chuyển sang instance khác khi một instance lỗi.

### Exercise 5.5: Test stateless

```text
$ python test_stateless.py
============================================================
Stateless Scaling Demo
============================================================

Session ID: 240812a6-0a80-4548-90e5-3cb55dedd8b0

Request 1: [instance-1f5c1c]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-5a56e2]
  Q: Why do we need containers?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

Request 3: [instance-01cbde]
  Q: What is Kubernetes?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

Request 4: [instance-1f5c1c]
  Q: How does load balancing work?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 5: [instance-5a56e2]
  Q: What is Redis used for?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-1f5c1c', 'instance-01cbde', 'instance-5a56e2'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...
  [user]: What is Kubernetes?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...
  [user]: How does load balancing work?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: What is Redis used for?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...

✅ Session history preserved across all instances via Redis!
```

**Giải thích:** 5 câu trong *cùng một session* lần lượt đi vào cả 3 instance (`1f5c1c → 5a56e2 → 01cbde → 1f5c1c → 5a56e2`). Mỗi instance đọc history cũ từ Redis (`session:<id>`), thêm lượt mới rồi ghi lại, nên `/chat/<session>/history` có đủ **10 message** (5 user + 5 assistant) theo đúng thứ tự. Nếu history nằm trong RAM, instance thứ 2 sẽ không thấy câu 1, và history chỉ còn các lượt mà instance trả lời request đọc history từng xử lý. Script không tự tắt instance nào. Nhưng vì không instance nào giữ state riêng, tắt một instance thì Nginx chuyển sang instance còn lại và session vẫn còn nguyên.

---

## Part 6: Final Project — `check_production_ready.py`

Chạy trong `06-lab-complete/` (WSL2, có Docker, bản đầy đủ):

```text
$ python check_production_ready.py      # bản đầy đủ, WSL2 Ubuntu 24.04, Docker 29.9.3
...
     ✅ Docker: build image thành công — 14s
     ✅ Docker: image < 500 MB — 238 MB
     ✅ Docker: container chạy được, GET /health → 200
...
     ✅ Khi chạy: SIGTERM lúc đang có request → request vẫn 200, process tự thoát — exit code 0
     ✅ Docker: `docker stop` tắt êm (exit code 0, < 10s) — exit code 0, 0.7s
...
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Tóm tắt cách làm: `config.py` đọc mọi biến từ env; `auth.py` dùng `APIKeyHeader` + `hmac.compare_digest` (401); `rate_limiter.py` dùng sliding window bằng Redis sorted set (`ZREMRANGEBYSCORE` → `ZADD` → `ZCARD` → `EXPIRE` trong một pipeline, 429 + `Retry-After`); `cost_guard.py` dùng `INCRBYFLOAT` theo ngày/tháng (402); `main.py` có `/health`, `/ready` (ping Redis), log JSON cho mọi request, exception handler không lộ stack trace, graceful shutdown qua lifespan của uvicorn. Dockerfile multi-stage `python:3.11-slim`, user non-root, `HEALTHCHECK`, `CMD sh -c "exec uvicorn ... --port ${PORT:-8000}"` để uvicorn là PID 1.

---

## AI log

| # | Hỏi AI gì | Nhận được gì | Tự sửa / tự kiểm tra thế nào |
|---|---|---|---|
| 1 | Nhờ Claude (Anthropic) đọc toàn bộ file .md của repo và tóm tắt các bước cần làm | Danh sách việc theo CP0–CP8 và yêu cầu nộp bài | Đối chiếu lại với `CHECKPOINTS.md`, `SUBMISSION.md`, `RUBRIC.md` |
| 2 | Nhờ Claude viết code các TODO Part 6 (`app/*.py`, Dockerfile, compose, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`) dựa trên hợp đồng trong `06-lab-complete/README.md` và nội dung `check_production_ready.py` | Code hoàn chỉnh cho 12 tiêu chí | Chạy script test riêng mô phỏng đúng các kịch bản của script chấm (401/200/429 + Retry-After, restart vẫn 429, `/ready` 503 khi mất Redis, 402, SIGTERM giữa request vẫn 200, log JSON). Sau đó chạy `python check_production_ready.py` bản đầy đủ trên WSL2 + Docker. Không sửa script chấm |
| 3 | Nhờ Claude chạy các ví dụ Part 1, 4, 5 và Part 7 Bước 1 (load test, eval) rồi ghi output | Output thật của các lệnh và các file JSON trong `reports/` | Số trong `BENCHMARK_REPORT.md` được trích trực tiếp từ JSON, không ước lượng |
| 4 | Nhờ Claude tìm 2 câu v2 sai và sửa `KNOWLEDGE_BASE` | Thêm 2 tài liệu (HPA, JWT), kiểm tra golden dataset không có câu khác dùng các keyword mới | Chạy lại eval với `--min-accuracy 1.0 --baseline reports/eval_v2.json`: 23/23, 0 regression. Không sửa `golden_dataset.jsonl` |
| 5 | Nhờ Claude viết câu trả lời Part 1–5 và so sánh railway/render | Bản nháp câu trả lời | Đọc lại từng file code được trích (số dòng, tên hàm) để xác nhận đúng |
| 6 | Hỏi Claude vì sao `railway up` lỗi `header key "exclude-patterns" contains value with non-printable ASCII characters` | Đã đổi comment trong các `.dockerignore`/`.gitignore` sang ASCII nhưng lỗi vẫn còn. Nguyên nhân thật (theo một thread trên Railway Station có cùng lỗi): chạy Railway CLI bản Linux trên thư mục Windows mount vào (`/mnt/d`) | Copy `06-lab-complete/` sang ổ Linux của WSL (`~/day14-deploy`), `railway link`, `railway up` → build thành công; kiểm tra bằng 4 lệnh curl + `--public-url` |
| 7 | Hỏi Claude vì sao Grafana không có số liệu p50/p95 ở stack observability | Container agent bị `Restarting (1)`, `up{job="agent"} = 0`. Lỗi trong `production/Dockerfile` của đề: `useradd -d /app` làm `HOME=/app` nên Python không thấy packages đã copy vào `/home/agent/.local` → sửa bằng `ENV PYTHONUSERBASE=/home/agent/.local` | Build lại stack, kiểm tra agent `Up (healthy)`, target `agent` UP trong Prometheus, Locust không còn 502/504 |
