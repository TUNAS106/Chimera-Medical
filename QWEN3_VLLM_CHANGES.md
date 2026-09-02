# Các thay đổi để Chimera dùng Qwen3-VL qua vLLM

Tài liệu này ghi lại các thay đổi dành cho
`Qwen/Qwen3-VL-30B-A3B-Instruct` và cách theo dõi log sinh ra. Cấu hình mặc
định mới dùng một vLLM OpenAI-compatible server thay cho GPT-4o-mini.

## 1. Luồng xử lý sau khi sửa

Chimera có hai kiểu gọi model và cả hai đều trỏ tới cùng endpoint:

1. Các tác vụ sinh JSON/text như hồ sơ công ty, hồ sơ nhân viên, lịch, email,
   tóm tắt và lập lịch tấn công gọi `foundation_model.run_llm()`.
2. Các agent CAMEL/OWL thực thi task, gọi tool, tìm kiếm web và đọc screenshot
   tạo model qua `model_backend.create_camel_model()`.

Tên model gửi trong mọi request là:

```text
Qwen/Qwen3-VL-30B-A3B-Instruct
```

Tên này phải trùng với `--served-model-name` trong notebook Kaggle.

## 2. File đã thay đổi

| File | Nội dung thay đổi |
|------|-------------------|
| `chimera-kaggle-vllm-server-offline.ipynb` | Chạy Qwen3-VL-30B-A3B-Instruct, ưu tiên checkpoint FP8 nếu được attach; bật vision, prefix cache và structured tool calling; dùng CLI Triton MoE trên vLLM mới hoặc tắt FlashInfer MoE bằng legacy environment trên vLLM cũ cho GPU SM120; có ô xem log snapshot thủ công và smoke test text/tool/vision. |
| `src/config.py` | Đọc cấu hình model từ biến môi trường; mặc định `vllm` + Qwen3-VL; thêm endpoint, timeout, max token, top-p, chế độ web và thư mục audit model. |
| `src/model_backend.py` | File mới, tạo backend CAMEL dùng `ModelPlatformType.VLLM`; truyền đúng URL, API key, model name và generation config; ghi `run_metadata.jsonl`. |
| `src/foundation_model.py` | Gọi Qwen qua OpenAI-compatible API; retry/timeout; ghi từng request thành JSONL, kể cả lỗi. |
| `src/task.py` | Tất cả user/assistant/browser/planner agent dùng backend Qwen chung; cấp `FileWriteToolkit`/`TerminalToolkit` bị giới hạn workspace và web tool theo mode; phân loại `success`/`incomplete`/`blocked`/`error`, hash và xác minh đúng required artifact; log toàn bộ round, tool call, token và kết quả vào `task_transcripts.jsonl`. |
| `src/web_search.py`, `src/web_search_preflight.py` | Search/fetch text có giới hạn dung lượng, redirect, timeout và URL public; phát hiện CAPTCHA, không retry/bypass; fail-fast trước capture. |
| `src/model_preflight.py` | Kiểm tra `/models` và một chat completion nhỏ trước khi bắt SCAP/PCAP; log chỉ endpoint đã che signed path. |
| `src/task_supervisor.py` | Xếp hàng activity, mặc định tối đa ba process đồng thời ở `search_only`, timeout cứng và kết thúc cả process group để không rò Playwright/Chromium; chờ kết quả theo task, ghi nhận lỗi/cancel và chỉ retry hữu hạn trạng thái semantic `incomplete`. |
| `src/simulation_workspace.py`, `src/workday_policy.py` | Tạo workspace cô lập với dữ liệu EHR tổng hợp đã khử định danh và hợp đồng artifact bắt buộc; chuẩn hóa cutoff ngày làm việc, mention `@member-id`, phân loại email-only, reply depth và lọc replan nằm trong giờ làm việc. |
| `src/daily_run_preflight.py` | Kiểm tra lịch đúng tuần/ngày trước khi mở capture: đủ profile/lịch, `Time`/`Activity` hợp lệ, task nằm trong 08:00–18:00, mention hợp lệ, không meeting và mỗi nhân viên có ít nhất một activity sinh artifact. |
| `src/sanitize_model_audit.py` | Ghi lại atomically trường `endpoint` trong model audit dưới dạng đã che path/token; giữ nguyên record hỏng JSON và mọi trường audit khác. |
| `src/random_browse.py` | Dùng chung cấu hình task/web-mode và lifecycle cleanup; không còn DuckDuckGo/Google tool riêng hoặc rò browser. |
| `src/meeting_for_weekly_goal_auto.py` | Cuộc họp và từng nhân viên dùng Qwen; search tool tuân theo `CHIMERA_OFFLINE_MODE`; dựng cố định đúng một task cho mỗi cặp nhân viên-tuần và thay file meeting chưa hoàn chỉnh khi retry. |
| `src/company_profile_automation.py` | Gắn nhãn audit `company_profile_generation`; ép đúng tổng số nhân viên/role cấu hình và đưa lỗi validation trước đó vào prompt retry. |
| `src/profile_generation.py` | Gắn nhãn audit `member_profile_generation`. |
| `src/daily_plan_generation_auto.py` | Gắn nhãn audit `daily_plan_generation`; bắt buộc JSON đủ bảy ngày, mỗi ngày có task và mỗi task có `Time`/`Activity`; dùng lỗi validation làm phản hồi cho retry. |
| `src/post_meeting_summary_auto.py` | Gắn nhãn audit `weekly_meeting_summary`; bắt buộc mỗi tuần có đúng toàn bộ ID nhân viên, không trùng/không lạ, đúng số tuần và goal không rỗng. |
| `camel/camel/societies/workforce/workforce.py` | Chuẩn hóa ID worker do coordinator trả về (kể cả dạng `<ID>`), fallback theo ID trong subtask và từ chối post assignee không tồn tại để tránh deadlock ở `TaskChannel`; hỗ trợ decomposition/assignee dựng sẵn cho workflow cần số task chính xác. |
| `camel/camel/societies/workforce/single_agent_worker.py` | Ghi `meeting_response.csv` vào thư mục meeting của scenario hiện hành; mỗi dòng có thêm task ID và metadata nhân viên-tuần để kiểm tra tính đầy đủ. |
| `camel/camel/societies/workforce/worker.py` | Bắt lỗi worker ngoài dự kiến và luôn trả task ở trạng thái `FAILED`, tránh coordinator chờ vô hạn khi listener con chết. |
| `src/meeting_for_weekly_goal_auto.py`, `camel/.../prompts.py` | Tắt search mặc định riêng cho weekly meeting và buộc subtasks mô tả công việc thật thay vì meta-task “assign to worker ID”. |
| `camel/camel/agents/chat_agent.py` | Giới hạn vòng lặp tool nội bộ; khi chạm ngưỡng sẽ yêu cầu final response không có tool thay vì lặp vô hạn sau lỗi/rate-limit. |
| `camel/camel/models/openai_compatible_model.py` | Đồng bộ retry của OpenAI sync/async client với `CHIMERA_FOUNDATION_TRANSIENT_RETRIES`, thay cho số retry hard-code. |
| `camel/camel/toolkits/browser_toolkit.py` | Khởi tạo Chromium lazy, tái sử dụng đúng một browser, kiểm tra phần tử editable trước khi fill, giới hạn browser round, dừng khi CAPTCHA/action lỗi lặp và cleanup page/context/browser/Playwright idempotent. |
| `camel/camel/toolkits/file_write_toolkit.py` | Chặn path thoát khỏi task workspace và thêm alias `write_file` tương thích ổn định với Hermes tool parser. |
| `camel/camel/toolkits/terminal_toolkit.py` | Giới hạn file search/read trong task workspace, regex/glob/output/timeout; thêm `file_read` có giới hạn kích thước và `close()` idempotent. |
| `owl/owl/utils/enhanced_role_playing.py` | Ghi tool calls và chỉ chấp nhận tín hiệu hoàn tất sau cặp write/read thành công trên cùng artifact; nhận diện cả đường dẫn tương đối/tuyệt đối và trường hợp marker hoàn tất xuất hiện ở round cuối. |
| `camel/pyproject.toml` | Đặt `tool.uv.default-groups = []` vì `dev`/`docs` là optional extras chứ không phải `dependency-groups`; sửa lỗi `uv sync` dừng trước cả khi xử lý `--no-default-groups`. |
| `src/member_email.py` | Gắn nhãn riêng cho chọn người nhận, sinh email và trả lời email. |
| `src/daily_plan_update.py` | Gắn nhãn riêng cho cập nhật lịch thường và lịch tấn công. |
| `src/attack_schedule.py` | Dùng Qwen cho chọn ngày tấn công và ghi nhãn audit. |
| `src/daily_attack_schedule.py` | Dùng Qwen cho sinh lịch tấn công và ghi nhãn audit. |
| `src/daily_execution_auto.py` | Dùng supervisor chung, chờ kết quả activity và evidence trước hand-off email; serialize replan vào main loop, giới hạn reply/replan/cutoff, chỉ tạo daily summary sau khi worker drain; ghi lifecycle/model/endpoint và làm logger close/flush idempotent. |
| `src/daily_execution_auto_attack.py` | Áp dụng cùng supervisor, evidence, email/replan, cutoff và summary lifecycle cho attack run; metadata có thêm attacker và attack ID. |
| `.env.example` | Thêm các biến cấu hình Qwen/vLLM, web mode, concurrency, timeout, browser/tool limits và mức độ audit. |
| `scripts/daily_execution.sh` | Điều khiển `chimera2`, model/web preflight trước capture; chỉ preflight Chromium ở mode `browser`; chạy đúng entrypoint và thu sysdig/tcpdump. |
| `scripts/attack_auto.sh` | Mặc định điều khiển `chimera2`, gọi `attack_schedule.py` rồi entrypoint tấn công dưới `src/`, và bắt buộc chọn ID attacker đã sinh qua biến môi trường. |
| `scripts/full_execution.sh` | Chạy tuần tự toàn bộ bước dựng công ty, sinh lịch và normal simulation trong `chimera2`; preflight dependency, đúng 5 nhân viên, API/model availability trước khi tạo dữ liệu. |
| `scripts/prepare_company.sh`, `scripts/prepare_company_in_container.sh`, `src/company_preparation_status.py` | Workflow chuẩn bị resumable cho cả host/container: validate và skip từng phase đã hoàn tất, tạo đủ công ty 5 người, profile, meeting, weekly/daily schedules; meeting phải có đúng mọi cặp nhân viên-tuần, output downstream phải mới hơn input; không chạy hành vi hoặc bắt SCAP/PCAP. |
| `README.md`, quy trình cài `owl/` và `camel/` | Dùng lock gốc của OWL làm nguồn dependency runtime rồi cài Camel patched bằng `--no-deps`; tránh `camel[all]` kéo `transformers==4.12.2`/`tokenizers==0.10.3` và gây lỗi build Rust hoặc hạ dependency. Dependency/`uv.lock` của OWL không bị sửa; OWL chỉ có patch completion/artifact trong `enhanced_role_playing.py`. |
| `.gitignore` | Không commit file `.env` chứa khóa truy cập. |
| `README.md` | Cập nhật backend, cấu hình và bản đồ log mới. |
| `tests/` | Thêm regression test cho logger close/flush, exact required artifact, evidence từ transcript, write/read cùng artifact và policy cutoff/email/replan cho cả normal lẫn attack runner. |

Lưu ý cho CLI vLLM mới: notebook dò `--moe-backend` bằng
`vllm serve --help=moe-backend`/`--help=all`. Lệnh `vllm serve --help` mặc định
chỉ hiện các nhóm cấu hình và có thể làm phép kiểm tra cũ kết luận nhầm rằng
option này không tồn tại. Ô log cũng phân biệt process zombie (`Z`) với server
đang chạy và báo `FAILED` khi EngineCore khởi tạo thất bại.

Các helper nội bộ có hậu tố `_with_gpt` trong ba file lập/cập nhật lịch cũng đã
được đổi thành `_with_llm` để tên hàm không còn gắn với một nhà cung cấp cụ thể.

### 2.1. Kiểm kê các thay đổi bổ sung so với source ban đầu

Baseline dùng để đối chiếu là commit Git
`76ac1d38c0afb6f4cf8a9fdf96566b164017dde1` (source ban đầu ngày 2026-08-11)
và hai archive `zips/camel.zip`, `zips/owl.zip`. Kiểm kê lại trực tiếp bằng
`diff` ngày 2026-09-01 cho thấy CAMEL vendored khác archive gốc ở đúng mười
file:

```text
camel/camel/agents/chat_agent.py
camel/camel/models/openai_compatible_model.py
camel/camel/societies/workforce/prompts.py
camel/camel/societies/workforce/single_agent_worker.py
camel/camel/societies/workforce/worker.py
camel/camel/societies/workforce/workforce.py
camel/camel/toolkits/browser_toolkit.py
camel/camel/toolkits/file_write_toolkit.py
camel/camel/toolkits/terminal_toolkit.py
camel/pyproject.toml
```

OWL vendored khác archive gốc ở một file:

```text
owl/owl/utils/enhanced_role_playing.py
```

Hai file `camel/camel/toolkits/function_tool.py` và
`camel/camel/types/enums.py` khác commit nằm trong Git lồng của CAMEL nhưng
không khác `zips/camel.zip`, vì vậy không phải patch mới của Chimera. Tương tự,
việc đổi tên PDF trong Git lồng của OWL không phải thay đổi source Python và
không khác nội dung archive dùng làm baseline. Các thư mục scenario đã sinh,
`.env`, cache, `.venv`, log, `.scap`, `.pcap` và hai ZIP gốc là dữ liệu
runtime/tham chiếu, không được tính là thay đổi source.

#### Cấu hình và backend model

- [x] Chuyển backend mặc định từ GPT-4o-mini sang Qwen3-VL self-host qua vLLM
  OpenAI-compatible API.
- [x] Đưa model, endpoint, API key, timeout, max tokens, top-p, số nhân viên,
  số tuần, scenario, container và chế độ web/search ra biến môi trường.
- [x] Dùng chung một factory model cho direct LLM calls và toàn bộ agent
  CAMEL/OWL, tránh model/provider hard-code rải rác.
- [x] Thêm retry có giới hạn, timeout và audit JSONL cho cả request thành công
  lẫn request lỗi.

#### Dựng công ty trước khi sinh log hoạt động

- [x] Ép cấu trúc công ty có đúng `CHIMERA_EMPLOYEE_NUMBER`; với cấu hình hiện
  tại là năm role, mỗi role có `count=1`, tổng đúng năm nhân viên.
- [x] Kiểm tra profile khớp ID/role trong cấu trúc công ty, có đủ trường bắt
  buộc, có tool/application và không trùng ID, IP hoặc email.
- [x] Tách workflow chuẩn bị khỏi workflow chạy hành vi. Hai script
  `prepare_company*.sh` chỉ sinh company, profile, meeting, weekly schedule và
  daily schedule; không chạy employee task và không bắt SCAP/PCAP.
- [x] Thêm `--status-only` để kiểm tra năm phase mà không gọi model; phase hợp
  lệ được skip để có thể tiếp tục sau lỗi thay vì chạy lại từ đầu.
- [x] Thêm preflight `uv pip check`, in cấu hình employee/week và xác nhận model
  cấu hình thật sự xuất hiện tại endpoint `/models`.

#### Meeting và chống deadlock

- [x] Không còn để model tự chọn số lượng subtask meeting. Script dựng ma trận
  cố định `employee_number × period`; cấu hình năm người/hai tuần luôn tạo đúng
  mười task.
- [x] Mỗi task được bind trực tiếp tới worker tương ứng bằng
  `workforce_assignee_id`; coordinator không thể chọn một worker hợp lệ nhưng
  sai nhân viên.
- [x] `meeting_response.csv` có thêm `task_id` và JSON `assignment` chứa ID,
  tên, role, tuần và worker; lần retry thay file meeting dở thay vì append vào
  dữ liệu cũ.
- [x] Validator kiểm tra đủ và duy nhất mọi cặp nhân viên-tuần, đúng người xử
  lý, content không rỗng và event meeting mới nhất phải là `completed`.
- [x] Chuẩn hóa worker ID có/không có dấu `<...>`, từ chối assignee không tồn
  tại và trả task `FAILED` khi listener worker ném exception, loại bỏ các điểm
  chờ vô hạn đã gặp trong `TaskChannel`.
- [x] Giới hạn tối đa năm vòng tool/model trong `ChatAgent`; sau lỗi tool hoặc
  rate-limit, agent được yêu cầu trả final response không dùng tool.
- [x] Search trong weekly meeting tắt mặc định, tránh gọi DuckDuckGo cho tác vụ
  nội bộ kiểu “assign worker” và bị rate-limit 202.

#### Kiểm tra dữ liệu lịch

- [x] Weekly schedule phải là JSON array có đúng số nhân viên, đúng tập ID,
  không ID trùng/lạ, đúng `week` và `detailed_goals` không rỗng.
- [x] Daily schedule phải là JSON object đủ Monday–Sunday; mỗi ngày có ít nhất
  một activity và mỗi activity có cả `Time` lẫn `Activity`.
- [x] Với năm nhân viên, hai tuần và bảy ngày, validator yêu cầu đủ 70 file lịch
  ngày trước khi coi bước chuẩn bị hoàn tất.
- [x] Kiểm tra mtime buộc weekly schedule mới hơn meeting hiện tại và daily
  schedule mới hơn weekly schedule hiện tại, tránh tái sử dụng output cũ sau
  khi upstream được sinh lại.

#### Chạy container, simulation và thu thập log

- [x] Chuẩn hóa container mặc định thành `chimera2`, repository mount tại
  `/data/Chimera`, entrypoint Python nằm dưới `src/`.
- [x] `daily_execution.sh` chạy đủ số tuần và bảy ngày theo cấu hình, cho phép
  giới hạn bằng `CHIMERA_WEEKS`/`CHIMERA_DATES`, dùng tmux session riêng và có
  cleanup cho sysdig/tcpdump.
- [x] Trên kernel `7.0.0-30-generic`, cả normal/attack runner dùng bản
  `sysdig-chimera` modern-BPF đã vá thay vì `/usr/bin/sysdig` bị crash/verifier
  reject; runner nạp container plugin, chờ SCAP/PCAP sẵn sàng và đọc lại file
  sau mỗi ngày. Hai syscall
  `sendmmsg`/`recvmmsg` bị loại khỏi SCAP do giới hạn verifier, nhưng traffic
  tương ứng vẫn có trong PCAP.
- [x] `attack_auto.sh` bỏ attacker hard-code, bắt buộc truyền attacker ID qua
  môi trường (người chạy chọn một ID trong profile đã sinh), gọi bước chèn
  attack schedule trước khi chạy và thu SCAP/PCAP theo từng attack.
- [x] `full_execution.sh` nối workflow chuẩn bị resumable với normal daily
  simulation; không tự động chạy attack simulation.
- [x] Ghi model/endpoint và lifecycle `started`/`completed`/`failed` vào run
  metadata; ghi task transcript có file lock để nhiều process append an toàn.
- [x] Detailed task log chuyển sang DEBUG và append, giữ lại lịch sử khi cùng
  một simulated task được chạy lại; prompt/response có thể tắt bằng
  `CHIMERA_LOG_MODEL_CONTENT=false`.

## 3. Cấu hình local Chimera

Tạo `.env` ở thư mục gốc repository:

```dotenv
CHIMERA_FOUNDATION_CORP=vllm
CHIMERA_FOUNDATION_MODEL=Qwen/Qwen3-VL-30B-A3B-Instruct
CHIMERA_FOUNDATION_BASE_URL=http://127.0.0.1:8000/v1
CHIMERA_FOUNDATION_API_KEY=chimera-local-change-me
CHIMERA_FOUNDATION_TIMEOUT=600
CHIMERA_FOUNDATION_MAX_RETRIES=0
CHIMERA_FOUNDATION_TRANSIENT_RETRIES=2
CHIMERA_FOUNDATION_RETRY_BASE_SECONDS=1
CHIMERA_FOUNDATION_MAX_TOKENS=8192
CHIMERA_FOUNDATION_TOP_P=0.9
CHIMERA_OFFLINE_MODE=false
CHIMERA_WEB_MODE=search_only
CHIMERA_WEB_SEARCH_MAX_ATTEMPTS=4
CHIMERA_MAX_CONCURRENT_TASKS=3
CHIMERA_MAX_AUX_MODEL_CALLS=1
CHIMERA_VLLM_MAX_NUM_SEQS=4
CHIMERA_TASK_TIMEOUT_SECONDS=900
CHIMERA_TASK_TERMINATE_GRACE_SECONDS=10
CHIMERA_WORKDAY_START=08:00:00
CHIMERA_WORKDAY_END=18:00:00
CHIMERA_MAX_EMAIL_REPLY_DEPTH=1
CHIMERA_MAX_DAILY_EMAIL_REPLIES=12
CHIMERA_MAX_DAILY_REPLANS=12
CHIMERA_ACTIVITY_MAX_TOOL_ITERATIONS=8
CHIMERA_ACTIVITY_SEMANTIC_RETRIES=1
CHIMERA_BROWSER_ROUND_LIMIT=6
CHIMERA_MAX_TOOL_ARGUMENT_CHARS=4096
CHIMERA_TERMINAL_FILE_READ_MAX_CHARS=12000
CHIMERA_LOG_MODEL_CONTENT=true

# Dùng khi source/data không nằm tại /data/Chimera
CHIMERA_BASE_DIR=/data/Chimera
CHIMERA_SCENARIO_NAME=chimera_scenario_1
```

`CHIMERA_WEB_MODE=search_only` cho phép `search_web`/`fetch_url` nhưng không mở
Chromium, phù hợp host 16 GB. `llm_only` chỉ dùng kiến thức model; `browser` mới
bật Playwright cho tác vụ cần tương tác hình ảnh. `CHIMERA_OFFLINE_MODE=true`
luôn ép về `llm_only` và không liên quan tới cách Kaggle tải weight offline.

Search preflight hiện kiểm tra hai truy vấn y tế theo nội dung liên quan và
fetch một kết quả thật. Bing HTML được retry tối đa
`CHIMERA_WEB_SEARCH_MAX_ATTEMPTS` lần bằng các query reorder hữu hạn; kết quả
phải khớp nhiều từ khóa. Nếu Bing vẫn không có kết quả liên quan, search dùng
MediaWiki API làm fallback text-only có giới hạn. HTTP 4xx/5xx từ `fetch_url`
được trả thành lỗi.
Activity chỉ được ghi `success` khi completion marker và artifact hợp lệ được
nhận diện nhất quán: thông thường reviewer phát `TASK_DONE`; nếu executor phát
`CHIMERA_TASK_COMPLETE` đúng ở round cuối thì vẫn được chấp nhận khi đã có cặp
tool write/read thành công trên đúng artifact bắt buộc. Hết round, agent dừng
sớm hoặc chỉ có marker chữ mà thiếu artifact được ghi `incomplete`; CAPTCHA là
`blocked`, còn exception/tool/model failure thật là `error`.

Activity runner dùng system prompt riêng thay cho prompt AI-society mặc định
của CAMEL (prompt mặc định luôn nối `Next request`, nên trước đây các task hữu
hạn thường hết round). Mỗi nhân viên được cấp workspace mô phỏng cục bộ với dữ
liệu EHR tổng hợp đã khử định danh, inbox/configuration/access/backup/health giả
lập. Agent không được yêu cầu credential hay truy cập EHR thật. Task chỉ thành
công sau khi executor phát `CHIMERA_TASK_COMPLETE`, completion được reviewer
hoặc nhánh round-cuối xác nhận, và runner xác nhận đúng artifact bắt buộc ngoài
seed file đã được tạo/thay đổi, không rỗng và được đọc lại sau lần ghi cuối.

Activity toolkit cung cấp trực tiếp `file_read` và `write_file`, đều bị giới
hạn trong workspace của task. Prompt yêu cầu dùng hai tool này khi đã biết
đường dẫn thay vì lặp `file_find_*`. Số vòng tool nội bộ mặc định là 8 qua
`CHIMERA_ACTIVITY_MAX_TOOL_ITERATIONS`; nội dung đọc file được giới hạn bởi
`CHIMERA_TERMINAL_FILE_READ_MAX_CHARS` (mặc định 12.000 ký tự).

Direct auxiliary model calls giữ SDK `max_retries=0` nhưng có retry minh bạch
cho lỗi kết nối/timeout, HTTP 408/409/429 và 5xx. Mặc định retry hai lần với
backoff 1 giây rồi 2 giây; mỗi lần được ghi trong model audit. HTTP 404 và lỗi
cấu hình không được retry. Nếu replan sau email vẫn hết retry, runner giữ lịch
hiện tại và tiếp tục thay vì làm chết employee thread.
CAMEL activity client cũng dùng cùng
`CHIMERA_FOUNDATION_TRANSIENT_RETRIES` cho OpenAI-compatible sync/async calls,
để một lần DNS chập chờn không làm task process thoát ngay.

Khi chạy lại cùng week/day, `scripts/daily_execution.sh` tự chuyển bốn output
capture hiện có (`scap`, `pcap`, `sysdig.log`, `tcpdump.log`) vào thư mục
`previous_week_<n>_<day>.*` dưới capture directory trước khi mở writer mới. Vì
vậy capture cũ không bị trộn hoặc ghi đè âm thầm.
Nếu terminal host nhận `Ctrl+C`, runner đọc PID đã được ghi riêng cho lần chạy,
xác minh command line rồi dừng đúng process group simulation trong container;
Python/resource-tracker không còn tiếp tục chạy sau khi capture runner thoát.

## 4. Kết nối Kaggle với máy local

Notebook mở vLLM tại `0.0.0.0:8000` bên trong Kaggle. Địa chỉ
`http://127.0.0.1:8000/v1` chỉ dùng được trong chính Kaggle runtime. Khi Chimera
chạy trên máy local hoặc trong Docker local, cần forward cổng 8000 của Kaggle
qua Jupyter server/tunnel đang dùng.

Sau khi forward, đặt `CHIMERA_FOUNDATION_BASE_URL` thành endpoint nhìn từ tiến
trình Chimera:

- Chimera chạy trực tiếp trên host và forward về cổng 8000:
  `http://127.0.0.1:8000/v1`.
- Chimera chạy trong Docker với `--network host` trên Linux: dùng cùng URL.
- Chimera chạy trong Docker bridge: dùng hostname/IP của host và cổng đã
  forward, không dùng localhost của container.

Notebook không tự tạo public tunnel. Không nên mở endpoint công khai nếu chưa
đổi `CHIMERA_FOUNDATION_API_KEY` và giới hạn truy cập mạng.

Kiểm tra từ đúng môi trường chạy Chimera:

```bash
curl -sS \
  -H "Authorization: Bearer ${CHIMERA_FOUNDATION_API_KEY}" \
  "${CHIMERA_FOUNDATION_BASE_URL}/models"
```

Kết quả phải chứa đúng model
`Qwen/Qwen3-VL-30B-A3B-Instruct` trước khi chạy simulation.

## 5. Các nguồn log sau khi sửa

Giả sử `CHIMERA_BASE_DIR=/data/Chimera` và scenario là
`chimera_scenario_1`.

| Nguồn | Đường dẫn | Giá trị audit/SOC |
|-------|-----------|-------------------|
| Direct model audit | `chimera_scenario_1/model_logs/model_calls.jsonl` | Một dòng cho mỗi lần sinh hồ sơ/lịch/email/tóm tắt: operation, thời gian UTC, duration, provider, model, endpoint, token usage, prompt, response hoặc lỗi. |
| Task transcript | `chimera_scenario_1/execution_logs/task_transcripts.jsonl` hoặc thư mục của attack run dưới `attack_logs/` | Toàn bộ các round CAMEL/OWL, structured tool calls, câu trả lời, token, member, tuần/ngày và event index. |
| Run metadata | `chimera_scenario_1/execution_logs/run_metadata.jsonl` hoặc thư mục của attack run dưới `attack_logs/` | Liên kết sự kiện `started`/`completed` của lần chạy với model, endpoint, workflow, week/date và PID. Attack run có thêm attack ID và attacker ID. |
| Detailed task log | `chimera_scenario_1/execution_logs/<member>_week_..._task_<index>.log` | DEBUG trace của agent, browser, planning và tool trong từng task; append khi chạy lại. |
| OWL solution log | `chimera_scenario_1/execution_logs/<member>_week_..._solution_<index>.log` | Hội thoại solution do bản OWL đã patch sinh ra. |
| Daemon log | `chimera_scenario_1/execution_logs/daemon_logs/*.log` | stdout/stderr, lifecycle, lỗi, model và endpoint của ngày giả lập. |
| User logon | `chimera_scenario_1/execution_logs/logon.csv` | Login/logout theo real time và simulated time. |
| User schedule/activity | `chimera_scenario_1/execution_logs/final_schedule.csv` | User, container, activity và thời điểm thực/giả lập. Đây là log hoạt động mức nghiệp vụ, không phải telemetry hệ điều hành. |
| Email | `chimera_scenario_1/execution_logs/email.csv` | From/to/cc/subject/content và timestamp. |
| Meeting audit | `chimera_scenario_1/meeting_logs/meeting_detailed_actions.log`, `meeting_result.log`, `run_metadata.jsonl` | Thảo luận, kết quả meeting và model dùng cho lần chạy. |
| Syscall | `.scap` do `scripts/daily_execution.sh`/sysdig thu thập | File/process/network/system call thật từ container; phù hợp hơn để tạo telemetry endpoint cho SOC. |
| Network | `.pcap` do tcpdump thu thập | Kết nối mạng thật của browser/tool/container. |

`task_transcripts.jsonl` và `model_calls.jsonl` là application/tool audit để
giải thích vì sao agent thực hiện hành vi. Để giả lập SOC có chiều sâu, nên kết
hợp chúng với `logon.csv`, `email.csv`, `.scap`, `.pcap` và log dịch vụ đích;
không nên coi transcript LLM là log endpoint thật.

## 6. Quyền riêng tư và dung lượng

Mặc định `CHIMERA_LOG_MODEL_CONTENT=true` để phục vụ yêu cầu audit đầy đủ. File
JSONL sẽ chứa prompt, email, nội dung phản hồi và chi tiết attack scenario. Nếu
chỉ cần thống kê vận hành, đặt:

```dotenv
CHIMERA_LOG_MODEL_CONTENT=false
```

Khi đó hệ thống vẫn ghi request ID, operation, thời gian, model, endpoint, token
usage, trạng thái và lỗi nhưng bỏ prompt/response/chat history. Nên giới hạn
quyền đọc thư mục scenario và thiết lập rotation/retention cho lần chạy dài.

## 7. Thứ tự chạy đề xuất

1. Attach checkpoint Qwen3-VL và wheelhouse vLLM vào Kaggle.
2. Chạy notebook từ đầu tới cuối; cả tool-calling test và vision/OCR test phải
   báo `OK`.
3. Forward endpoint Kaggle tới môi trường local.
4. Kiểm tra `/v1/models` từ máy/container chạy Chimera.
5. Tạo `.env`, sau đó chạy tuần tự các phase trong `README.md`.
6. Kiểm tra `run_metadata.jsonl`, `model_calls.jsonl` và
   `task_transcripts.jsonl` sau một ngày thử nghiệm ngắn trước khi chạy toàn bộ.

## 8. Giới hạn còn lại

- GPU 96 GB đủ thuận lợi cho checkpoint FP8; bản BF16 có thể dùng nhiều VRAM
  hơn và giảm số request song song. Notebook tự ưu tiên checkpoint FP8 nếu tìm
  thấy nhưng vẫn giữ served model name ổn định.
- `max_num_seqs=4` trong notebook giới hạn concurrency phía vLLM. Với
  `search_only`, Chimera chạy tối đa ba activity process và một auxiliary model
  call; tổng bốn request khớp giới hạn vLLM. `browser` vẫn bắt buộc hạ activity
  worker về hai trên host 16 GiB. Mỗi activity quá 900 giây bị dừng cả process
  group.
- Runner yêu cầu host còn ít nhất 2 GiB `MemAvailable` trước khi mở capture
  (`CHIMERA_HOST_MIN_AVAILABLE_MB=2048`). Giới hạn Docker 8 GiB là trần an
  toàn, không phải lượng RAM được cấp trước; container dùng ít RAM khi model
  chạy từ xa là hành vi bình thường.
- Khả năng đọc ảnh được dùng khi BrowserToolkit gửi screenshot vào model. Tool
  search tự nó thường trả text; model vision hỗ trợ bước quan sát trang web,
  không thay thế kết nối Internet hay search engine.
- Bản CAMEL/OWL đã patch của Chimera vẫn là dependency bắt buộc vì nó cung cấp
  structured task/tool logging mà source chính sử dụng.

## 9. Guardrail cho lần chạy daily mới

- `daily_run_preflight.py` kiểm tra đúng tuần/ngày trước khi mở SCAP/PCAP: đủ
  năm lịch, giờ trong 08:00–18:00, ID email hợp lệ, không `@PEOPLE`, không tự
  gửi, không schedule meeting và mỗi nhân viên có ít nhất một activity tạo
  artifact.
- Activity có `@id` không còn mặc nhiên bị coi là email-only. Với task kép,
  worker phải tạo artifact thành công trước; email hand-off chỉ được gửi sau
  khi transcript và file không rỗng đã được kiểm chứng.
- Email và reply chỉ được phép mô tả kết quả có trong artifact cục bộ đã xác
  minh. Không có evidence thì nội dung phải được viết dưới dạng yêu cầu/kế
  hoạch, không được tuyên bố đã thay đổi EHR hay hệ thống bệnh viện thật.
- Web fetch chỉ nhận URL chính xác do `search_web` trả về trong cùng task và
  dừng sau hai fetch lỗi. Điều này loại vòng lặp đoán URL gây nhiều lỗi 404.
- Runner tự làm sạch signed path cũ trong trường `endpoint` của model audit
  trước preflight; dữ liệu audit khác được giữ nguyên.
- Nếu một activity lỗi, daily run dừng các worker còn lại ngay. `SIGINT` và
  `SIGTERM` được ghi thành sự kiện `interrupted`; chỉ run mà mọi worker thành
  công và mọi nhân viên có artifact mới được ghi `completed`.
- Mỗi event hiện có tên artifact bắt buộc riêng theo member/week/day/event và
  attempt. OWL chỉ xác nhận hoàn tất sau khi thấy một file-write thành công rồi
  `file_read` lại cùng artifact; marker `CHIMERA_TASK_COMPLETE` ở round cuối
  cũng được nhận diện nếu cặp tool này đã hợp lệ. Post-run gate và evidence
  hand-off bắt buộc chính xác file event này; một backup hay artifact phụ không
  còn đủ để task được ghi `success`. Trạng thái `incomplete` được sửa thử đúng
  một lần (`CHIMERA_ACTIVITY_SEMANTIC_RETRIES=1`); timeout, CAPTCHA, lỗi kết nối
  và lỗi tool thật không bị retry mù quáng.
- Bước đọc lại SCAP/PCAP có hard timeout và stdin tách khỏi terminal, nên capture
  reader bị treo hoặc suspend không thể giữ host runner vô hạn. Logger daily và
  attack có thể bị flush lại an toàn sau `close()`, tránh Python đổi một run đã
  ghi metadata `completed` thành exit code 120 lúc interpreter kết thúc.
