# Benchmark & Observability Report — Day 14

**Họ tên:** Phan Gia Bao
**Ngày chạy:** 2026-11-25
**Môi trường:**
- Bước 1 (develop): Linux VM Ubuntu 22.04, 2 vCPU / 3 GB RAM, Python 3.10, chạy trên laptop Windows. Agent và `load_test.py` chạy cùng một máy.
- Bước 2 (production): Docker Desktop (Docker 29.9.3, Compose v5.7.1) + WSL2 Ubuntu 24.04 trên cùng laptop.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Mock LLM mất khoảng 120–180 ms/call, retrieval khoảng 20 ms. 500 ms chừa gấp đôi khoảng dư cho mạng và hàng đợi mà người dùng chat vẫn thấy "tức thì". Đặt theo p95 vì average che mất các request chậm (mục 2.2) |
| Error rate `/ask` | < 2 % | Mock có `MOCK_ERROR_RATE=0.01` (1 % lỗi upstream). 2 % cho error budget gấp đôi mức nền, vượt ngưỡng này nghĩa là có sự cố thật chứ không phải nhiễu |
| Accuracy trên golden dataset | ≥ 85 % (CI), 100 % trước khi release | 85 % là ngưỡng CI chặn merge (Exercise 7.3). Bản phát hành phải đạt 23/23 và không regression so với baseline |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

Lệnh: `python load_test.py --url http://localhost:8002 --requests 300 --concurrency <c> --out reports/load_v2_c<c>.json` (agent v2, `MOCK_SLOW_RATE` mặc định 0.03).

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.48 | 188.7 | 219.3 | 1692.7 | 0.33% | ✅ PASS |
| 10 | 35.96 | 191.4 | 220.4 | 1707.9 | 0.33% | ✅ PASS |
| 50 | 106.96 | 196.1 | 260.2 | 1691.8 | 1.00% | ✅ PASS |
| 100 | 50.24 | 435.0 | 4213.0 | 4607.3 | 0.67% | ❌ FAIL |

**Nhận xét:** Từ 1 lên 50, RPS tăng gần tuyến tính (4.48 → 35.96 → 106.96) trong khi p50 gần như không đổi (khoảng 190 ms). Lý do: agent là async, mỗi request chủ yếu *chờ* LLM (`await asyncio.sleep`), nên một process phục vụ được nhiều request chồng lên nhau. Lên 100 thì RPS **giảm** còn 50.24, p50 tăng gấp đôi (435 ms) và p95 lên 4213 ms, vi phạm SLO. Agent (1 process uvicorn) và load generator chạy chung trên VM chỉ có 2 vCPU, nên event loop bị bão hoà: tạo/parse request, ghi log JSON và cập nhật metric cho 100 kết nối cùng lúc tốn CPU, request phải xếp hàng. Điểm bão hoà của cấu hình này nằm trong khoảng 50–100 concurrent. Muốn chịu tải cao hơn phải thêm worker/instance (mục 5).

### 2.2 Tail latency

Lệnh: khởi động lại v2 với `MOCK_SLOW_RATE=<x>`, rồi `--requests 300 --concurrency 20 --out reports/load_v2_slow_<x>.json`.

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 188.7 | 218.5 | 228.3 |
| 0.03 (mặc định) | 248.5 | 225.1 | 1683.0 |
| 0.1 | 295.1 | 1680.2 | 1708.6 |

**Nhận xét:** Đi từ 0 lên 0.1, avg chỉ tăng khoảng 56 % (188.7 → 295.1 ms) nhưng p99 tăng khoảng 7.5 lần (228 → 1709 ms). Khi slow rate lên 10 %, p95 cũng vọt lên 1680 ms. Percentile nhạy nhất là percentile nằm *phía trên* tỉ lệ request chậm: 3 % chậm làm hỏng p99, 10 % chậm làm hỏng cả p95. Average gộp vài request rất chậm với hàng trăm request nhanh nên bị "pha loãng". Avg 295 ms trông vẫn đạt SLO trong khi cứ 10 người thì 1 người phải chờ gần 1.7 s. Vì vậy SLO phải đặt theo p95/p99, là trải nghiệm của những người dùng tệ nhất, chứ không theo average.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 57.5 | 109.3 | 113.8 |
| Tổng cost (USD) | 0.000410 | 0.000764 | 0.000792 |
| Cost / câu đúng (USD) | 0.00040995 | 0.00003639 | 0.00003442 |
| Latency p50 / p95 (ms) | 173.6 / 1493.9 | 183.6 / 216.3 | 188.5 / 219.7 |
| Quality gate | FAIL (ngưỡng 80 %) | PASS (ngưỡng 80 %, 0 regression so với v1) | PASS (ngưỡng 100 %, 0 regression so với v2) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| security-02 ("JWT khác gì API key…") | `token`, `hết hạn`, `chữ ký` | Thêm tài liệu với keyword `["jwt"]` vào `KNOWLEDGE_BASE`: API key là chuỗi cố định không hết hạn; JWT là token có chữ ký số, chứa user và thời điểm hết hạn |
| scaling-03 ("Kubernetes HPA scale dựa trên…") | `cpu`, `memory`, `custom metrics` | Thêm tài liệu với keyword `["hpa", "kubernetes", "autoscal"]`: HPA scale số pod theo CPU, memory hoặc custom metrics (RPS, độ dài hàng đợi) |

Trước khi thêm, đã kiểm tra golden dataset không có câu nào khác chứa `jwt`, `hpa`, `kubernetes`, `autoscal`, nên tài liệu mới không "cướp" retrieval của câu khác. Kết quả eval cuối xác nhận 0 regression. Sửa ở cả `develop/utils/mock_llm.py` và `production/utils/mock_llm.py`. Không sửa `golden_dataset.jsonl`.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

v2 thêm bước retrieval (RAG) nên prompt dài hơn: avg tokens tăng khoảng 1.9 lần (57.5 → 109.3) và tổng cost tăng khoảng 1.86 lần. Đổi lại accuracy tăng từ 4.3 % lên 91.3 %. Vì vậy **cost / câu đúng giảm khoảng 11 lần** (0.00041 → 0.0000364 USD). Nếu chỉ nhìn "cost / câu" thì v1 rẻ hơn, nhưng v1 gần như không trả lời đúng, nên tiền bỏ ra là phí. "Cost / câu đúng" mới phản ánh giá trị thật. Về latency, retrieval chỉ thêm khoảng 10–20 ms ở p50. p95 của v1 cao (1493.9 ms) là do vài request trúng `MOCK_SLOW_RATE` trong một mẫu nhỏ (23 câu), không phải do v1 chậm hơn về bản chất. Sau khi sửa KB, cost chỉ tăng thêm 0.000028 USD cho +8.7 điểm % accuracy.

**Chặn merge bằng exit code (job CI):** `run_eval.py` trả exit code 1 khi accuracy < `--min-accuracy` hoặc có regression so với `--baseline`. Job `.github/workflows/eval.yml` (đã thêm vào repo) chạy agent v2 với `MOCK_ERROR_RATE=0` rồi chạy `run_eval.py --min-accuracy 0.85` trên mỗi pull request. Exit code ≠ 0 làm step fail, nên job đỏ. Đặt job này là *required status check* trong branch protection thì PR không merge được.

---

## 4. Observability stack (production)

> Ghi chú: lần chạy stack đầu tiên agent bị crash-loop (`Restarting (1)`, log `ModuleNotFoundError: No module named 'uvicorn'`) do `production/Dockerfile` của đề dùng `useradd -d /app` (nên `HOME=/app`) trong khi packages nằm ở `/home/agent/.local`. Đã sửa bằng `ENV PYTHONUSERBASE=/home/agent/.local`. Mọi số liệu, ảnh và CSV dưới đây lấy từ lần chạy lại sau khi sửa (2026-11-25, 23:42–00:00). Số Prometheus được đọc bằng API `/api/v1/query` với đúng các biểu thức của dashboard.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải: [`screenshots/grafana-dashboard.png`](screenshots/grafana-dashboard.png). Thấy 2 đợt tải của Locust headless (scale 1 rồi scale 3) khoảng 23:43–23:47, p99 khoảng 1.7 s, cost burn rate đỉnh khoảng $6/giờ
- [x] Một trace chậm trong Jaeger: [`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (có event `exception`): [`screenshots/jaeger-error-trace.png`](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với 2 alert đang **firing** (`LLMCostBurnRateHigh`, `AgentHighErrorRate`): [`screenshots/prometheus-alert-firing.png`](screenshots/prometheus-alert-firing.png)

**Exercise 7.4:**
Đo lúc 23:53:30 khi có tải nền 30 user (đọc từ Prometheus API bằng đúng các biểu thức của dashboard; ảnh Grafana chụp lúc tải vừa bắt đầu hiện p95 = 288.77 ms):

1. **p95 = 292.6 ms, avg = 229.5 ms** (p50 = 174.3 ms, p99 = 1819.7 ms). p95 chỉ cao hơn avg khoảng 63 ms, nhưng p99 gấp gần 8 lần avg. Phân bố có **đuôi dài**: khoảng 97 % request tập trung quanh 170–290 ms, còn khoảng 3 % trúng `MOCK_SLOW_RATE` (+1500 ms) bị đẩy lên khoảng 1.8 s. Avg bị pha loãng nên che mất nhóm chậm này; p99 lộ ra rõ.
2. **Requests/s theo instance: 9.87 và 9.91 req/s** (2 instance, tổng 19.8 req/s). Nginx chia **gần như đều tuyệt đối** (chênh lệch dưới 0.5 %) vì upstream `agent` được resolve ra cả 2 IP và cân bằng round-robin.
3. **Input 1518 tokens/s > output 795 tokens/s** (gần gấp đôi). Agent v2 (RAG) nhét tài liệu tìm được vào prompt: input = system prompt + context retrieval + câu hỏi, còn output chỉ là câu trả lời ngắn. Đây cũng là lý do v2 tốn token hơn v1 (mục 3).
4. `curl http://localhost:8080/metrics` trả về **404**, vì `production/nginx/nginx.conf` có `location = /metrics { return 404; }`. Metric nội bộ (tên model, cost, số request) không được lộ ra ngoài qua cổng public; Prometheus scrape thẳng từng agent `agent:8000/metrics` trong mạng nội bộ `obs_net` (qua DNS service discovery). Output thật:

   ```text
   $ curl -i http://localhost:8080/metrics
   HTTP/1.1 404 Not Found
   Server: nginx/1.28.3
   Date: Wed, 25 Nov 2026 16:46:57 GMT
   Content-Type: text/html
   Content-Length: 153
   Connection: keep-alive
   
   <html>
   ```

### 4.2 Thí nghiệm "phá hệ thống"

Unit test alert rules trước khi chạy thí nghiệm:

```text
$ docker run --rm -v "$PWD/prometheus:/p" --entrypoint promtool prom/prometheus:v3.16.0 test rules /p/alert_rules_test.yml
Processing test file: /p/alert_rules_test.yml
  SUCCESS
```

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (critical) | **93 s** (pending ở +31 s, firing ở +93 s) | Error rate (Golden Signals), Requests/s theo status code (đường 503 tăng) |
| B | `MOCK_SLOW_RATE=0.3` | _không làm_ | — | — |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (warning) | Đã ở trạng thái **firing ngay lần kiểm tra đầu tiên (+3 s)**, xem ghi chú bên dưới | Cost burn rate (USD/giờ), LLM latency p95 theo model, bảng phiên bản |
| D | `docker pause` 1 instance | _không làm_ | — | — |
| E | `AGENT_VERSION=v1` | _không làm_ (xem câu hỏi bên dưới) | — | Retrieval hit ratio, tokens/s |

A và C chạy **cùng lúc** (một lần `docker compose up -d --scale agent=3` với `.env` đổi 2 biến, lúc 23:57:58). Tải nền là Locust 30 user. Thời gian đo bằng cách poll `GET /api/v1/alerts` mỗi 5 giây:

```text
LLM_MODEL=mock-llm-large
MOCK_ERROR_RATE=0.2
Doi cau hinh luc: 2026-11-25 23:57:58
Bat dau theo doi alert (doi cau hinh luc 23:57:58)
  [23:58:00] +    3s  LLMCostBurnRateHigh -> firing
  [23:58:09] +   11s  AgentInstanceDown -> pending
  [23:58:29] +   31s  AgentHighErrorRate -> pending
  [23:59:30] +   93s  AgentHighErrorRate -> firing

>>> 2 alert dang FIRING: LLMCostBurnRateHigh, AgentHighErrorRate
Tom tat (giay tinh tu luc doi cau hinh): {"LLMCostBurnRateHigh": {"firing": 3}, "AgentInstanceDown": {"pending": 11}, "AgentHighErrorRate": {"pending": 31, "firing": 93}}
```

Số liệu Prometheus **trước** (23:53:30) và **sau** khi đổi (23:59:30):

| Chỉ số | Trước | Sau (A + C) |
|---|---|---|
| Error rate `/ask` | 0.98 % | **21.3 %** (vượt ngưỡng 5 % của alert) |
| p50 / p95 / p99 | 174 / 293 / 1820 ms | 384 / 696 / 1884 ms |
| avg | 229 ms | 442 ms |
| LLM p95 theo model | small: 198 ms | large: **497 ms** (khoảng 2.5 lần) |
| Cost burn rate | $0.93/giờ | **$9.60/giờ** (vượt ngưỡng $2/giờ) |
| RPS `/ask` | 19.8 | 16.8 (user Locust phải chờ response lâu hơn nên gửi chậm lại) |
| Instances up | 2 | 3 |

**Phân tích:**
- **A (lỗi):** error rate nhảy lên 21 %, gần đúng 20 % đã cấu hình. Alert chuyển *pending* sau 31 s, vì cửa sổ `rate(...[1m])` cần vài lần scrape mới vượt 5 %. Sau đó phải giữ đúng điều kiện liên tục `for: 1m` mới *firing*: 31 + 60 ≈ 93 s, khớp với cấu hình. `for` giúp tránh báo động giả khi chỉ có một spike ngắn.
- **C (model đắt):** cost burn rate tăng khoảng 10 lần (0.93 → 9.60 $/giờ) và LLM latency p95 tăng khoảng 2.5 lần (198 → 497 ms), đúng hệ số của `mock-llm-large`. Riêng thời gian tới firing của `LLMCostBurnRateHigh` **không đo được chính xác**: alert đã ở trạng thái firing ngay lần poll đầu (+3 s), trong khi rule có `for: 2m`, nên alert đã firing từ trước lúc đổi cấu hình. Panel Cost burn rate trên Grafana cho thấy chi phí đã vượt $2/giờ (đỉnh khoảng $6/giờ) trong lúc chạy benchmark scale 100 user. Con số đáng tin là giá trị sau khi đổi model: $9.60/giờ, vượt ngưỡng gần 5 lần, nên alert chắc chắn tiếp tục firing. Muốn đo sạch phải chờ alert về *inactive* rồi mới đổi model; với cửa sổ `rate[5m]` + `for: 2m`, dự kiến mất khoảng 2–3 phút.
- `AgentInstanceDown` chỉ lên *pending* ở +11 s (lúc Compose tạo lại container) rồi tự hết, vì container mới lên trong chưa tới `for: 30s`. Đây là ví dụ tốt cho việc `for` lọc nhiễu khi rolling restart.
- `AgentHighLatencyP95` **không** firing dù latency tăng: p95 = 696 ms vẫn dưới ngưỡng 1 s.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Lỗi chất lượng không làm metric hạ tầng (latency, error rate, up) đổi màu: agent vẫn trả 200 nhanh, chỉ là trả lời sai. Cách phát hiện:
1. **Eval làm quality gate trong CI/CD**: chạy golden dataset trước mỗi deploy và chặn nếu accuracy giảm hoặc có regression (mục 3).
2. **Eval định kỳ trên production** (synthetic check), ví dụ mỗi giờ gọi một tập golden nhỏ vào URL thật và đẩy accuracy thành metric để alert.
3. **Proxy metric chất lượng**: alert khi `retrieval hit ratio` giảm đột ngột, hoặc khi `agent_info{version}` đổi mà không có deploy được duyệt.
4. **Tín hiệu từ người dùng** (thumbs-down, tỉ lệ hỏi lại).

### 4.3 Debug bằng trace

**Trace chậm** ([`jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png), Longest First, lúc 23:52:55):
- `trace_id`: `b4bc7ba…` (Jaeger hiển thị 7 ký tự đầu)
- Tổng thời gian: **194 ms**, gồm 4 span, độ sâu 3
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small` = 169 ms (khoảng 87 %)**. `agent.retrieve_context` = 22.6 ms (khoảng 12 %), phần còn lại (FastAPI, serialize) dưới 3 ms.
- Kết luận: thời gian của request gần như nằm hết ở lời gọi LLM. Muốn giảm latency phải tối ưu phía LLM (model nhanh hơn, cache, streaming), tối ưu code agent hay retrieval gần như không có tác dụng.

**Trace lỗi** ([`jaeger-error-trace.png`](screenshots/jaeger-error-trace.png)), dùng để đối chiếu log ↔ trace:
- `trace_id`: **`71c7136f5a681e5fb976f27a093dac86`**, root span `POST /ask`, `http.status_code = 503`, tổng 98.9 ms
- Span `agent.run` (96.1 ms) có **event `exception`** ở 97.19 ms: `exception.type = utils.mock_llm.LLMError`, `exception.message = Upstream LLM error: 503 Service Unavailable (mock)`. Span `chat mock-llm-small` (69.7 ms) được đánh dấu lỗi ❗.
- Dòng log tương ứng (`docker compose logs agent | grep llm_error`). `trace_id` khớp trace trên, `span_id = 129749e83dd4eb25` khớp đúng SpanID của root span `POST /ask` trong ảnh:

```json
{"ts": "2026-11-25T16:42:53.546388+00:00", "level": "INFO", "service": "observable-agent", "instance": "6bfc4edfa622", "event": "llm_error", "trace_id": "71c7136f5a681e5fb976f27a093dac86", "span_id": "129749e83dd4eb25", "request_id": "635d5373aa89", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Lệnh: `docker compose -p k5-day14-observability run --rm locust ... --headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_<n>`. Số liệu lấy từ hàng `POST /ask` trong `benchmark-results/scale_1_stats.csv` và `scale_3_stats.csv`. Mỗi container agent bị giới hạn 0.5 CPU / 256 MB.

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 63.48 | 190 | 230 | 1700 | 74 / 7112 (1.04 %), toàn bộ là 503 |
| 3 | 63.01 | 190 | 220 | 1700 | 49 / 7168 (0.68 %), toàn bộ là 503 |

**Giải thích kết quả:** Scale từ 1 lên 3 instance **gần như không đổi gì**: RPS giữ khoảng 63 req/s, p50 190 ms, p95 chỉ giảm 230 → 220 ms, p99 vẫn 1700 ms.
- **RPS bị giới hạn bởi phía tạo tải, không bởi agent.** Locust là tải "vòng kín": 100 user, mỗi user chờ `between(0.5, 2)` giây giữa hai request (trung bình 1.25 s) cộng khoảng 0.24 s chờ response. Như vậy mỗi user gửi tối đa khoảng 0.67 req/s, tức 100 user chỉ tạo được khoảng 67 req/s. Đo được 63 req/s, sát mức trần này. Một instance (async, 0.5 CPU) chưa bão hoà nên thêm instance không tăng được throughput.
- **Latency do LLM quyết định, không do số instance.** Mỗi request phải chờ mock LLM khoảng 120–180 ms cộng retrieval khoảng 20 ms, nên p50 giữ khoảng 190 ms bất kể có bao nhiêu instance. p99 khoảng 1700 ms đến từ 3 % call chậm (`MOCK_SLOW_RATE=0.03`, +1500 ms). Đây là độ chậm của upstream LLM, scale ngang không sửa được.
- **Lỗi khoảng 1 % là 503** do `MOCK_ERROR_RATE=0.01` (lỗi upstream giả lập), không phải do quá tải. Hai lần chạy cùng mức lỗi nền.
- **Nút thắt là LLM call** (panel "LLM latency p95 theo model"). Scale ngang chỉ có ích khi agent bão hoà CPU/hàng đợi, ví dụ tăng lên vài trăm user, hoặc ở bài load test develop với concurrency 100 (mục 2.1, p95 vọt lên 4213 ms). Muốn giảm latency phải xử lý phía LLM: model nhanh hơn, cache câu trả lời, timeout + retry cho call chậm, hoặc streaming.

---

## 6. Kết luận

- 3 điều học được về benchmark & observability:
  1. **Average nói dối, percentile thì không.** 10 % request chậm chỉ làm avg tăng khoảng 56 % nhưng làm p95 tăng gần 8 lần (mục 2.2). SLO và alert latency phải dựa trên p95/p99.
  2. **Đo chất lượng và đo hiệu năng là hai việc khác nhau.** v1 nhanh và rẻ nhưng gần như không đúng. Chỉ eval trên golden dataset (và "cost / câu đúng") mới cho thấy v2 tốt hơn khoảng 11 lần về hiệu quả chi phí. Metric hạ tầng không bắt được lỗi chất lượng (thí nghiệm E).
  3. **Một máy có điểm bão hoà.** Throughput tăng tuyến tính tới khoảng 50 concurrent rồi sụp ở 100 (RPS giảm, p95 > 4 s). Load test phải tìm được điểm gãy này để biết khi nào cần scale ngang.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?
  - Metric ở tầng Nginx/load balancer (tỉ lệ 5xx/504 của upstream) và synthetic check từ bên ngoài, vì lỗi 504 do instance treo không hiện trong metric của agent.
  - Accuracy từ eval định kỳ trên production, kèm alert khi giảm dưới 85 %.
  - Alert theo **error budget burn rate** (đốt ngân sách lỗi nhanh trong 1 h và 6 h) thay vì ngưỡng tĩnh.
  - Số request bị 429/402 theo thời gian (phát hiện bị lạm dụng hoặc sắp hết budget), và saturation (CPU, độ dài hàng đợi, Redis latency).
