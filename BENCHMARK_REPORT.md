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

> ⏳ **Đang hoàn thiện (CP8 làm sau giờ lab).** Lần chạy đầu tiên agent trong stack bị crash-loop (`Restarting (1)`, `up{job="agent"}=0`, Locust nhận 100% lỗi 502/504) do lỗi trong `production/Dockerfile` của đề: `useradd -d /app` làm `HOME=/app` nên Python không thấy packages ở `/home/agent/.local`. Đã sửa bằng `ENV PYTHONUSERBASE=/home/agent/.local`. Số liệu, screenshot và CSV của lần chạy đó **không dùng**; mục 4–5 sẽ được điền từ lần chạy lại.

### 4.1 Screenshot

- [ ] Dashboard Grafana khi đang có tải: `screenshots/grafana-dashboard.png`
- [ ] Một trace chậm trong Jaeger: `screenshots/jaeger-slow-trace.png`
- [ ] Một trace lỗi trong Jaeger (có event `exception`): `screenshots/jaeger-error-trace.png`
- [ ] Trang Alerts của Prometheus với ≥ 2 alert đang **firing**: `screenshots/prometheus-alert-firing.png`

**Exercise 7.4:**
1. p95 = ___ ms, avg = ___ ms. Khoảng cách lớn nghĩa là phân bố latency có đuôi dài: phần lớn request nhanh, một số ít (slow LLM call) rất chậm.
2. Requests/s theo instance: ___ (Nginx round-robin nên mỗi instance nhận khoảng 1/N traffic).
3. Input tokens/s > output tokens/s vì v2 nhét tài liệu retrieval vào prompt: input = câu hỏi + context, output chỉ là câu trả lời ngắn.
4. `curl http://localhost:8080/metrics` trả về **404**, vì `production/nginx/nginx.conf` có `location = /metrics { return 404; }`. Metric nội bộ (tên model, cost, số request) không được lộ ra ngoài qua cổng public; Prometheus scrape thẳng từng agent `agent:8000/metrics` trong mạng nội bộ `obs_net` (qua DNS service discovery). _(dán output `curl -i` khi chạy CP8)_

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | | | |
| B | `MOCK_SLOW_RATE=0.3` | | | |
| C | `LLM_MODEL=mock-llm-large` | | | |
| D | `docker pause` 1 instance | | | |
| E | `AGENT_VERSION=v1` | Không có | — | Retrieval hit ratio, tokens/s |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Lỗi chất lượng không làm metric hạ tầng (latency, error rate, up) đổi màu: agent vẫn trả 200 nhanh, chỉ là trả lời sai. Cách phát hiện:
1. **Eval làm quality gate trong CI/CD**: chạy golden dataset trước mỗi deploy và chặn nếu accuracy giảm hoặc có regression (mục 3).
2. **Eval định kỳ trên production** (synthetic check), ví dụ mỗi giờ gọi một tập golden nhỏ vào URL thật và đẩy accuracy thành metric để alert.
3. **Proxy metric chất lượng**: alert khi `retrieval hit ratio` giảm đột ngột, hoặc khi `agent_info{version}` đổi mà không có deploy được duyệt.
4. **Tín hiệu từ người dùng** (thumbs-down, tỉ lệ hỏi lại).

### 4.3 Debug bằng trace

- `trace_id`: ...
- Tổng thời gian: ... ms
- Span chiếm nhiều thời gian nhất: ... (... ms, ...%)
- Dòng log tương ứng (grep theo `trace_id`):

```json

```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

> ⏳ Chờ chạy lại sau khi sửa Dockerfile (xem ghi chú mục 4). `benchmark-results/` sẽ được bổ sung cùng lúc.

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | | | | | |
| 3 | | | | | |

**Giải thích kết quả:** ...

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
