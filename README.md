# CÔNG CỤ THU THẬP, HIỆU ĐÍNH TIẾNG VIỆT & GỘP TẬP TRUYỆN (PNTT)

Hệ thống desktop Python chạy trên Windows / đa nền tảng hỗ trợ thu thập nội dung truyện được phép sử dụng, tự động phát hiện lỗi chính tả tiếng Việt (theo quy tắc regex, từ điển tùy chỉnh & AI phân tích đề xuất), giao diện duyệt so sánh trực quan và gộp mỗi 4 chương thành một tập TXT định dạng audio, kèm báo cáo Markdown và nhật ký kiểm tra JSON.

> **Lưu ý về cơ chế hiệu đính:**  
> Ứng dụng kết hợp chuẩn hóa Unicode NFC, các bộ lọc quy tắc regex, từ điển các lỗi gõ chắc chắn và mô hình AI tùy chọn. Đây **không phải** là mô hình hiểu ngữ cảnh tiếng Việt tự nhiên hoàn chỉnh. Mọi thay đổi đều được ghi vết chính xác trong nhật ký thay đổi và yêu cầu người dùng duyệt trước khi xuất bản `EDITED`.

---

## 1. KẾT QUẢ KHẢO SÁT THỰC TẾ NGUỒN `vivutruyen.com`

- **Trang mục lục & truyện:** `https://vivutruyen.com/truyen/pham-nhan-tu-tien`
  - Đọc được tiêu đề truyện, giới thiệu, tổng số chương (2447 chương).
  - Mục lục trên trang web hiển thị theo thứ tự giảm dần (chương mới nhất ở trang 1). Phân trang AJAX có dạng `/94/{page}`.
- **Trang chương mẫu:** `https://vivutruyen.com/truyen/pham-nhan-tu-tien/chuong-1-son-bien-tieu-thon-103484`
  - Biến JavaScript chuẩn xác: `var bname = "Phàm Nhân Tu Tiên"`, `var nextChap = "..."`, `var prevChap = "..."`.
  - Vùng tiêu đề: `h1.current-book span.current-chapter`.
  - Vùng nội dung: `div.truyen` chứa danh sách các thẻ `<p>`.
  - Điều hướng: Thẻ `a.next` dẫn đến chương tiếp theo.
- **Xác minh lỗi HTTP 403 / Timeout từ môi trường nội địa:**
  - `vivutruyen.com` đặt sau Cloudflare CDN (`104.21.3.116`, `172.67.130.169`). Khi gọi trực tiếp bằng các thư viện HTTP thuần không có browser session từ IP máy cá nhân, Cloudflare áp dụng cơ chế Turnstile/Managed Challenge dẫn tới kết nối bị treo hoặc nhận HTTP 403.
  - **Cơ chế an toàn:** Công cụ tự động phát hiện mã 403, 429 hoặc trang thử thách Cloudflare/CAPTCHA, **dừng ngay lập tức** và thông báo rõ ràng cho người dùng, không spam request lặp lại.
  - **Luồng nạp offline (Offline Importer):** Công cụ cung cấp tính năng nạp trực tiếp toàn bộ thư mục tệp `.html` hoặc `.txt` do người dùng lưu sẵn, hoàn thiện trọn vẹn luồng gộp tập và sửa lỗi chính tả.

---

## 2. KIẾN TRÚC HỆ THỐNG

```
c:\Lap trinh Android\PNTT Truyen\
├── core\
│   ├── models.py           # Dataclass: Chapter, Volume, SpellIssue, StoryInfo (băm, version)
│   ├── profiles.py         # Hồ sơ truyện đa nguồn: Phàm Nhân Tu Tiên, Tiên Nghịch, template mở/kết
│   ├── parser.py           # Phân tích HTML vivutruyen.com, webnovel.vn, tamhoan.com và tệp TXT
│   ├── storage.py          # Quản lý CSDL SQLite, bản gốc bất biến, versioning, lưu quyết định duyệt
│   ├── crawler.py          # Tải mạng tuần tự, rate limit, timeout, chống lặp URL
│   ├── importer.py         # Nạp tệp offline HTML/TXT vào SQLite
│   ├── spellchecker.py     # Chuẩn hóa NFC, dọn gạch dưới, khoảng trắng, bảo vệ từ che c*m v**
│   ├── ai_checker.py       # Trợ lý AI đề xuất (mặc định pending, schema check, ẩn API key)
│   ├── merger.py           # Bộ gộp tập audio, chuẩn hóa \s\n -> \n, xử lý DRAFT
│   ├── reporter.py         # Xuất bundle an toàn (file tạm .tmp): RAW, EDITED, REPORT, CHANGELOG
│   ├── video_models.py     # Dataclass hàng đợi Audio/Video và cấu hình xuất video YouTube
│   ├── video_renderer.py   # Bộ dựng khung hình QPainter dùng chung 100% giữa Preview và FFmpeg
│   ├── ffmpeg_utils.py     # Gọi FFmpeg/ffprobe qua subprocess, đọc tiến độ pipe:1, xuất an toàn .tmp
│   ├── tts_models.py       # Dataclass hàng đợi TTS, chunk, cấu hình âm thanh, manifest
│   ├── tts_chunker.py      # Phân đoạn tiếng Việt (<240 ký tự), bảo vệ dấu câu và số thập phân
│   ├── tts_manifest.py     # Quản lý manifest.json và cache WAV, kiểm tra tính toàn vẹn và resumption
│   ├── tts_adapter.py      # Cầu nối tiến trình con chạy độc lập VieNeu-TTS, không xung đột GUI
│   ├── tts_runner.py       # Worker chạy trong Python TTS, nạp model một lần duy nhất, output JSON-lines
│   └── tts_assembler.py    # Ghép PCM WAV, chèn khoảng nghỉ (câu/đoạn/chương), mã hóa MP3 với FFmpeg
├── resources\
│   ├── default_dictionary.json            # Từ điển lỗi gõ có thể mở rộng (đã lọc các cặp trùng nhau)
│   ├── protected_terms.json               # Danh từ riêng, tên nhân vật, địa danh Phàm Nhân Tu Tiên
│   ├── protected_terms_tien_nghich.json   # Thuật ngữ tu tiên, nhân vật, môn phái Tiên Nghịch
│   └── styles.qss                         # Giao diện nền sáng hiện đại PySide6
├── gui\
│   ├── widgets.py          # Bảng chương & Giao diện duyệt Side-by-Side (chuột + phím Space)
│   ├── dialogs.py          # Hộp thoại cấu hình AI, từ điển, thuật ngữ bảo vệ
│   ├── workers.py          # Luồng nền: CrawlWorker, SpellCheckWorker, ExportWorker riêng biệt
│   ├── tts_tab.py          # Tab "Sản Xuất Audio": Cấu hình VieNeu-TTS, hàng đợi, tiếp tục và chuyển video
│   ├── tts_worker.py       # Luồng nền tổng hợp giọng đọc, đo tốc độ chars/s, tính ETA thực tế
│   ├── video_tab.py        # Tab "Sản Xuất Video": Quản lý danh sách, xem trước và xuất video
│   ├── video_worker.py     # Luồng nền xuất video hàng loạt, báo cáo ETA/tiến độ, hỗ trợ hủy
│   └── main_window.py      # Cửa sổ chính: 5 tab nghiệp vụ hoàn chỉnh (Tải -> Sửa -> Gộp -> Audio -> Video)
├── cli.py                  # Giao diện dòng lệnh CLI đầy đủ chức năng (--story, tts)
├── app.py                  # Khởi chạy ứng dụng GUI PySide6
├── setup_tts_env_cpu.bat   # Script tự động tạo môi trường Python TTS cho CPU (ONNX Runtime)
├── setup_tts_env_gpu.bat   # Script tự động tạo môi trường Python TTS cho GPU (PyTorch CUDA 12.x)
├── data\
│   ├── sample_chapters\   # 4 chương mẫu thực tế phục vụ kiểm thử offline PNTT
│   └── fixtures\          # Fixture HTML thực tế webnovel.vn và tamhoan.com
└── tests\                  # Bộ kiểm thử tự động toàn diện (104/104 PASS 100%)
```

---

## 3. CÀI ĐẶT & MÔI TRƯỜNG

Yêu cầu Python 3.10 trở lên trên Windows / Linux / macOS.

1. **Cài đặt thư viện phụ thuộc:**
```bash
pip install -r requirements.txt
```

2. **Chạy bộ kiểm thử tự động (Unit, Integration & Safety Tests):**
```bash
python -m unittest discover -s tests -p "test_*.py"
```

3. **Đóng gói tệp thực thi Windows (.EXE) độc lập:**
- Cách 1: Chạy file kịch bản tự động `build_exe.bat` (nhấp đúp hoặc chạy trong cmd/powershell):
  ```cmd
  build_exe.bat
  ```
- Cách 2: Sử dụng PyInstaller trực tiếp từ môi trường ảo:
  ```bash
  .venv\Scripts\pyinstaller --clean -y TruyenAudio.spec
  ```
- Kết quả: File thực thi độc lập **`dist\TruyenAudio.exe`** (~56MB) đã đóng gói đầy đủ Python runtime, Qt PySide6 và tài nguyên từ điển/stylesheet, có thể chạy trực tiếp trên bất kỳ máy tính Windows nào mà không cần cài đặt Python.

---

## 4. HƯỚNG DẪN SỬ DỤNG

### A. Chạy ứng dụng
- **Dùng file EXE độc lập:** Nhấp đúp vào `dist\TruyenAudio.exe`.
- **Dùng mã nguồn Python:**
  ```bash
  python app.py
  ```

Quy trình xử lý chia thành các bước rõ ràng:
1. **Bước 1: Nạp hoặc Tải dữ liệu:**
   - Nhập URL truyện hoặc bấm **"📁 Nạp tệp máy tính (Offline)..."** trỏ đến thư mục chứa tệp HTML/TXT (ví dụ: `data/sample_chapters`).
2. **Bước 2: Cấu hình:**
   - Chọn chương bắt đầu, chương kết thúc, số chương mỗi tập (mặc định: 4).
   - Nhập số tập bắt đầu (ví dụ: bắt đầu tập 268).
   - Chọn thư mục xuất tệp và bật/tắt các cờ tùy chọn.
3. **Bước 3: Phân tích và Tạo đề xuất:**
   - Bấm **"▶ Bắt đầu phân tích"**. Hệ thống nạp dữ liệu, kiểm tra quy tắc và AI (nếu bật), sau đó tự động chuyển sang Tab **"🔍 Xem Trước & Duyệt Lỗi"**.
4. **Bước 4: Xem trước & Duyệt lỗi:**
   - Người dùng xem so sánh đối chiếu văn bản Gốc vs Bản sửa.
   - Duyệt bằng chuột (click checkbox) hoặc bàn phím (phím Space / Enter).
   - Có thể dùng nút **"✔ Chấp nhận tất cả"** hoặc **"✖ Từ chối tất cả"**.
   - Mọi thao tác thay đổi lựa chọn sẽ cập nhật ngay lập tức bản xem trước và tự động lưu vào CSDL.
5. **Bước 5: Áp dụng và Xuất tập:**
   - Bấm nút **"💾 Áp dụng và xuất tập..."**.
   - Hệ thống áp dụng chính xác các quyết định đã chốt, gộp tập audio và xuất an toàn qua file tạm `.tmp`.
   - Kết quả hiển thị trực tiếp tại Tab **"📊 Báo Cáo Markdown"**.

---

### B. Sử dụng bằng Dòng lệnh (CLI)
CLI dùng chung toàn bộ nghiệp vụ từ `core/`:

1. **Chạy trọn gói (Process):**
```bash
# Nạp từ thư mục offline và xuất tập (quy tắc an toàn mặc định được áp dụng):
python cli.py process --import-dir data/sample_chapters --start-chap 1 --end-chap 4 --start-vol 268 --out-dir output_volumes --overwrite

# Tải từ web (nếu mạng cho phép):
python cli.py process --start-url https://vivutruyen.com/truyen/pham-nhan-tu-tien/chuong-1-son-bien-tieu-thon-103484 --start-chap 1 --end-chap 4 --start-vol 1
```

2. **Chạy từng bước độc lập:**
```bash
# Bước 1: Nạp tệp offline vào SQLite
python cli.py import --dir data/sample_chapters --title "Phàm Nhân Tu Tiên"

# Bước 2: Gộp tập và sửa lỗi từ CSDL
python cli.py merge --start-chap 1 --end-chap 4 --start-vol 268 --per-vol 4 --out-dir output_volumes --overwrite
```

---

## 5. QUY ƯỚC ĐẾM VÀ ĐỊNH DẠNG XUẤT AUDIO

Định dạng xuất file audio:
- **Mặc định:** Chỉ xuất duy nhất 1 file TXT hoàn chỉnh: `Tap_{vol}_Chuong_{start}_den_{end}.txt` (không sinh thêm các file rác `.md` hay `.json`).
- **Tùy chọn Audit (`--export-reports` trên CLI hoặc checkbox trên GUI):** Khi cần đối chiếu, có thể xuất thêm bộ 4 tệp:
  1. `Tap_{vol}_Chuong_{start}_den_{end}_RAW.txt`: Bản gốc bất biến.
  2. `Tap_{vol}_Chuong_{start}_den_{end}_EDITED.txt`: Bản đã sửa lỗi sau khi duyệt/áp dụng.
  3. `Tap_{vol}_Chuong_{start}_den_{end}_REPORT.md`: Báo cáo chi tiết thống kê và bảng kê các lỗi.
  4. `Tap_{vol}_Chuong_{start}_den_{end}_CHANGELOG.json`: Nhật ký kiểm tra (audit log) máy đọc được.

**Quy chuẩn nội dung file TXT:**
- **Phần mở đầu tiêu chuẩn:**
  ```
  PHÀM NHÂN TU TIÊN - TẬP {so_tap}
  Chào mừng các bạn đang theo dõi bộ truyện tiên hiệp Phàm Nhân Tu Tiên, tác giả Vong Ngữ.
  Đây là Tập {so_tap}, phát từ Chương {chuong_dau} đến Chương {chuong_cuoi}.
  Chúc các bạn có những giây phút thư giãn và trải nghiệm tuyệt vời.
  ```
- Không xuất tiêu đề từng chương, không xuất nhãn đánh số chương và đường phân cách.
- Các chương nối tiếp nhau bằng một dòng trống.
- **Kết thúc tập bằng đúng một dòng:**
  ```
  Hết Tập {so_tap}: Cảm ơn quý thính giả đã chú ý lắng nghe. Hẹn gặp lại các bạn trong Tập {so_tap_tiep_theo} tiếp theo!
  ```
- **Chuẩn hóa xuống dòng:** Văn bản được ghi bằng mã hóa UTF-8 với kiểu xuống dòng LF (`\n`) sau khi áp dụng quy tắc chuẩn hóa khoảng trắng cuối dòng: chuyển đổi `\r\n` / `\r` thành `\n`, sau đó áp dụng regex `\s\n` → `\n` đúng một lượt.

**Quy tắc an toàn dữ liệu:**
- **Bất biến:** Nội dung raw đã nạp vào CSDL không bị ghi đè khi cùng URL trả về nội dung khác; phiên bản mới được lưu vào `chapter_versions`.
- **Ghi đè:** Không ghi đè tệp xuất nếu chưa bật cờ overwrite. Quá trình xuất sử dụng file tạm `.tmp` trước khi atomic replace.
- **Tập nháp (DRAFT):** Nếu thiếu một chương hoặc có lỗi tải, tập được đánh dấu là `is_draft = True`, xuất file có hậu tố `_DRAFT.txt` kèm cảnh báo danh sách chương thiếu, không xuất như tập hoàn chỉnh.
- **Nhóm cuối:** Nhóm cuối dưới 4 chương chỉ xuất khi bật cờ `allow_partial_last_volume`.

---

## 6. CHẨN ĐOÁN CRAWLER & TÁCH BIỆT THAM SỐ TẢI / GỘP

### A. Tách biệt hai tham số:
1. **Khoảng tải (`start_chap` → `end_chap`):**
   - Xác định chính xác phạm vi chương cần thu thập từ nguồn (ví dụ: Chương 1 đến 12).
   - Crawler sẽ tuần tự tải đủ tất cả các chương trong khoảng này theo liên kết chương tiếp (`nextChap`), không dừng lại sau khi đủ một tập.
2. **Số chương mỗi tập (`chapters_per_volume`, mặc định: 4):**
   - Chỉ phục vụ bước gộp file TXT sau khi đã có dữ liệu. Ví dụ tải 1–12 sẽ gộp thành 3 tập hoàn chỉnh (Tập 1: 1–4, Tập 2: 5–8, Tập 3: 9–12).

### B. Cơ chế trích xuất liên kết và khôi phục tiến độ (Resume):
- **Trích xuất liên kết chương kế tiếp:** Ưu tiên biến JavaScript `nextChap`. Nếu không có, quét các thẻ điều hướng HTML kiểm tra `rel="next"`, văn bản "chương tiếp", và xử lý triệt để bẫy của website khi cả thẻ "Chương trước" lẫn "Chương tiếp" đều mang `class='next'`.
- **Khôi phục điều hướng khi bản lưu thiếu liên kết:** Khi khôi phục các chương đã có sẵn trong CSDL mà chương cuối cùng thiếu `next_url` (ví dụ Chương 4 lưu trong cache thiếu link kế tiếp), Crawler sẽ thực hiện tải lại trang web của Chương 4 để phân tích và khôi phục `next_url` mà **không ghi đè nội dung gốc** đã lưu trong CSDL (tuân thủ tính bất biến và versioning). Sau đó, tiếp tục tải bình thường từ Chương 5 đến 12.
- **Không tự đoán mò URL:** Nếu không tìm thấy liên kết tiếp theo đáng tin cậy, Crawler dừng lại và trả về trạng thái `incomplete` kèm lý do cụ thể, tuyệt đối không đoán mò URL.

### C. Phân loại trạng thái tác vụ & Thống kê minh bạch:
Crawler và giao diện Worker phân biệt rõ 6 nhóm trạng thái:
1. `completed`: Hoàn tất thu thập đủ 100% số chương yêu cầu.
2. `incomplete`: Chưa hoàn tất do thiếu liên kết hoặc thiếu chương.
3. `blocked`: Bị chặn truy cập bởi máy chủ (HTTP 403, HTTP 429 hoặc Cloudflare Turnstile/CAPTCHA). Tự động dừng ngay, không cố vượt cơ chế bảo vệ.
4. `network_error`: Lỗi kết nối mạng, DNS hoặc timeout.
5. `parse_error`: Trang rỗng, cấu trúc HTML không hợp lệ hoặc thiếu vùng nội dung. Các trang này được lưu với trạng thái `failed`, tuyệt đối **không đánh dấu `verified`**.
6. `stopped_by_user`: Người dùng chủ động tạm dừng hoặc hủy tác vụ.

Hệ thống luôn phân định rõ và hiển thị 3 chỉ số số lượng:
- **`cached_count`**: Số chương khôi phục từ CSDL.
- **`downloaded_count`**: Số chương tải mới thành công qua mạng.
- **`missing_count`**: Số chương còn thiếu trong khoảng yêu cầu.

### D. Đồng bộ áp dụng sửa đổi và Báo cáo (Audit Trail):
- **Tách biệt quyết định duyệt và kết quả áp dụng:**
  - `user_decision`: Quyết định của người dùng (`approved`, `pending`, `rejected`).
  - `applied_status`: Kết quả thực tế khi áp dụng vào văn bản (`applied`, `skipped_conflict`, `skipped_mismatch`, `skipped_pending`, `skipped_rejected`).
  - `applied_reason`: Giải thích chi tiết nguyên nhân khi một đề xuất bị bỏ qua.
- **Phân xử xung đột đề xuất chồng lấn:** Ưu tiên theo thứ tự độ tin cậy: `Từ điển (dictionary)` > `Quy tắc (rule)` > `AI phân tích (ai)`. Các đề xuất bị trùng vùng ký tự sẽ được gắn cờ `skipped_conflict` kèm thông tin đề xuất ưu tiên hơn, không tính vào số lỗi đã sửa.
- **Kiểm tra lát cắt và băm nội dung:** Trước khi thay thế, hệ thống kiểm tra `original_hash` và lát cắt ký tự thực tế `[char_start:char_end]`. Bất kỳ sự sai lệch nào đều được đánh dấu `skipped_mismatch` và bỏ qua an toàn.
- **Xử lý chuẩn hóa Unicode NFC / NFD:** Chuẩn hóa nhất quán NFC trên cả bản gốc và đề xuất sửa đổi, đảm bảo các ký tự tiếng Việt có dấu không bị lệch chỉ số.
- **Thống kê chính xác tuyệt đối:** Chỉ tiêu "Số thay đổi đã áp dụng" trên Báo cáo Markdown, JSON Changelog và file EDITED TXT hoàn toàn đồng nhất và chỉ tính các thay đổi thực tế.

### E. Cách ly Quyết định duyệt Đa truyện & Migration CSDL:
- **Định danh duy nhất đa truyện:** Bảng `review_decisions` được định danh theo `UNIQUE(story_id, content_hash, issue_id, original, replacement)`. Hai tác phẩm khác nhau có cùng số chương, đoạn và vị trí lỗi sẽ hoàn toàn không bị ghi đè quyết định của nhau.
- **Bảo toàn khi nội dung thay đổi:** Khi nội dung chương thay đổi sinh ra `content_hash` mới, hệ thống không tự động khôi phục quyết định cũ nếu chưa được xác thực lại.
- **Migration tự động:** Tự động di chuyển CSDL phiên bản cũ sang cấu trúc mới, đánh dấu dữ liệu lịch sử là `legacy_unverified` để tránh tự ý áp dụng sai lệch.

### F. Định dạng File Audio Chuẩn & Loại bỏ Tiêu đề Chương:
- Mỗi tập gồm 4 chương theo thứ tự liên tiếp (Tập cuối có thể ít hơn nếu hết phạm vi truyện).
- Không âm thầm gộp bù chương khi thiếu chương ở giữa; tập thiếu được gắn cảnh báo `DRAFT`.
- Mẫu mở đầu và kết thúc hỗ trợ các biến `{tap}` / `{so_tap}`, `{chuong_dau}`, `{chuong_cuoi}`, `{tap_tiep_theo}` / `{so_tap_tiep_theo}`.
- Tự động nhận diện và loại bỏ:
  - Các đường phân cách như `------------------------------------------------------------` hoặc `==============================`.
  - Các dòng tiêu đề chương do công cụ chèn như `=== CHƯƠNG 4: LUYỆN CỐT NHAI ===`.
  - Dòng tiêu đề chương trùng với metadata chương.
  - Tuyệt đối **không xóa** các câu văn bình thường trong truyện dù có chứa từ "chương" (ví dụ: *"Chương này là bí mật lớn nhất..."*, *"Họ Chương..."*).
- Chuẩn hóa khoảng trắng cuối dòng bằng regex `\s\n` → `\n` đúng một lượt trên bản xuất audio sau khi chuẩn hóa CRLF/CR thành LF. Bản gốc luôn được giữ nguyên.

---

## 8. HỖ TRỢ ĐA TRUYỆN: TIÊN NGHỊCH (WEBNOVEL.VN)

Hệ thống hỗ trợ cơ chế hồ sơ truyện đa nguồn (`core/profiles.py`), cho phép chuyển đổi linh hoạt giữa:
1. **Phàm Nhân Tu Tiên** – Nguồn `vivutruyen.com` (Tác giả: Vong Ngữ)
2. **Tiên Nghịch** – Đa nguồn cung cấp (Tác giả: Nhĩ Căn):
   - Nguồn 1: `webnovel.vn` (URL: `https://webnovel.vn/tien-nghich`)
   - Nguồn 2: `tamhoan.com` (URL chuẩn: `https://tamhoan.com/truyen/tien-nghich`)

---

### A. Khảo sát Thực tế & Phân tích Nguồn `tamhoan.com`:
- **Đường dẫn chuẩn của trang truyện:**
  - URL gốc `https://tamhoan.com/truyen/tien-nghich` (trả về HTTP 200).
  - *Lưu ý quan trọng:* URL `https://tamhoan.com/tien-nghich` trả về **HTTP 404**; crawler và hệ thống tự động chuẩn hóa sang `/truyen/tien-nghich` nếu người dùng nhập thiếu.
- **Mục lục và phân trang:**
  - Mục lục nằm trong `<div class="storyListHolder">`, mỗi trang chứa đúng **50 chương** được sắp xếp theo thứ tự tăng dần.
  - Phân trang mục lục có **43 trang** (`total_pages = 43`), liên kết trang kế tiếp có dạng `?page=2` (thuộc `<div class="storyPagination">`).
- **Cấu trúc URL chương và phân biệt số chương thực tế:**
  - URL chương mẫu: `https://tamhoan.com/tien-nghich/203612` (Chương 1) và `https://tamhoan.com/tien-nghich/205299` (Chương 1668).
  - **Khẳng định khảo sát thực tế:** Số `205299` trên URL là **ID bài viết trong CSDL** của website, **không phải là số chương**. Chương tại `205299` có tiêu đề thực tế là *"Chương 1668: Thuộc về Tây Tử một năm"*.
  - Hệ thống **tuyệt đối không tự tăng ID URL** và trích xuất đúng số chương (1668) từ tiêu đề văn bản thông qua regex chuẩn `Chương\s+(\d+)`.
- **Trích xuất nội dung và dọn dẹp quảng cáo:**
  - Nội dung chương nằm trong `<div class="content">` bên trong `<div class="chapContent">`.
  - **Dọn dẹp quảng cáo Google Ads:** Thư viện BeautifulSoup tự động phân rã (decompose) các thẻ `<ins class="adsbygoogle">`, `<script>`, `<iframe>`, `<style>` mà không làm mất câu chuyện.
  - **Bảo toàn ngữ nghĩa:** Giữ nguyên vẹn dấu tiếng Việt, lời thoại có gạch đầu dòng (`- Cha, ...`), dấu câu, và các từ viết tắt/che dấu (`c*m`, `v**`).
- **Liên kết điều hướng:**
  - Nút chuyển chương: `<a id="next_chap">` và `<a id="prev_chap">`.
  - Nút bị vô hiệu hóa (như lùi ở Chương 1 hoặc tiến ở chương cuối) có class `disabled` và `href="#"`. Parser nhận diện chính xác để không sinh link lặp.

---

### B. Khảo sát & Phân tích Nguồn `webnovel.vn`:
- **Mục lục:** Cấu trúc `<ol class="chapter-list" id="chapterList">` chứa trực tiếp các thẻ `<a class="chapter-item__link">` với chỉ số `<span class="chapter-item__index">` và tên chương `<span class="chapter-item__title">`.
- **Nội dung chương:**
  - Tiêu đề chương: `<p class="reader__chapter">`.
  - Đoạn văn nội dung: Nằm trong `<div id="chapter-c">` thuộc `<article class="reader__content">`.
  - **Làm sạch rác & quảng cáo:** Loại bỏ hoàn toàn khối `<div class="bastorypush">` (quảng cáo đề cử nội bộ), dọn sạch các thẻ nút chia sẻ và menu điều hướng.
  - **Điều hướng chương:** Trích xuất liên kết "Chương sau" và "Chương trước" từ cụm `<div class="reader__actions">`.

---

### C. Kiến Trúc Tách Rời "Bộ Truyện" Khỏi "Nguồn Cung Cấp" & Cách Ly Dữ Liệu:
- **Mô hình hóa:** Khái niệm `StoryProfile` đại diện cho tác phẩm ("Tiên Nghịch", "Phàm Nhân Tu Tiên"), quản lý một tập hợp các `SourceProfile` ("webnovel.vn", "tamhoan.com", "vivutruyen.com").
- **Giao diện người dùng độc lập:**
  - Hộp chọn **Bộ truyện**: Cho phép chọn *Tiên Nghịch* hoặc *Phàm Nhân Tu Tiên*.
  - Hộp chọn **Nguồn cung cấp**: Tự động cập nhật danh sách nguồn theo bộ truyện đang chọn (chọn Tiên Nghịch -> nguồn `webnovel.vn` hoặc `tamhoan.com`; chọn Phàm Nhân Tu Tiên -> nguồn `vivutruyen.com`).
- **Cách ly CSDL SQLite:**
  - Bảng `chapters` được bổ sung cột `source` với index `idx_chap_source_num(story_id, source, chapter_num)`.
  - Hai nguồn cùng có Chương 1 (ví dụ: Chương 1 của Webnovel và Chương 1 của TamHoan) được lưu trữ độc lập, không ghi đè, không lẫn tiến độ.
  - Tự động di chuyển (migration) dữ liệu cũ, bảo toàn 100% các chương đã lưu từ trước.
- **Thư mục xuất riêng biệt theo nguồn:**
  - Nguồn TamHoan: `output_volumes/tien_nghich/tamhoan/`
  - Nguồn Webnovel: `output_volumes/tien_nghich/webnovel/`
  - Nguồn Vivutruyen: `output_volumes/pham_nhan_tu_tien/`
  - Đảm bảo khi xuất tập hoàn chỉnh không bao giờ ghi đè lên file của nguồn khác.

---

### D. Nhập Offline HTML từ Trình Duyệt:
- Hỗ trợ nạp các tệp `.html` chương TamHoan được lưu trực tiếp từ trình duyệt web.
- **Bảo toàn nguồn gốc:** Tự động phát hiện `<link rel="canonical">` hoặc `<meta property="og:url">` để giữ URL gốc và xác định nguồn `tamhoan`.
- **An toàn điều hướng:** Tuyệt đối không dùng đường dẫn `file://` làm `next_url` để crawler tải mạng.
- **Chính xác số chương:** Nếu tệp không chứa số chương rõ ràng, hệ thống ghi cảnh báo yêu cầu người dùng đặt lại tên tệp (ví dụ: `chuong_1.html`), tuyệt đối không tự đoán số chương.

---

### E. Mẫu Mở Đầu & Kết Thúc Tập Tiên Nghịch:
- **Đầu file:**
  ```
  TIÊN NGHỊCH - TẬP {tap}
  Chào mừng các bạn đang theo dõi bộ truyện tiên hiệp Tiên Nghịch, tác giả Nhĩ Căn.
  Đây là Tập {tap}, phát từ Chương {chuong_dau} đến Chương {chuong_cuoi}.
  Chúc các bạn có những giây phút thư giãn và trải nghiệm tuyệt vời.
  ```
- **Cuối file:**
  ```
  Hết Tập {tap}: Cảm ơn quý thính giả đã chú ý lắng nghe. Hẹn gặp lại các bạn trong Tập {tap_tiep_theo} tiếp theo!
  ```

---

### F. Sử Dụng Qua CLI (Đa Nguồn):
```bash
# 1. Tải truyện Tiên Nghịch từ nguồn tamhoan.com (chương 1 đến 12):
python cli.py crawl --story tien-nghich --source tamhoan --start-chap 1 --end-chap 12

# 2. Gộp 12 chương TamHoan thành 3 tập (4 chương/tập) xuất vào output_volumes/tien_nghich/tamhoan:
python cli.py merge --story tien-nghich --source tamhoan --start-chap 1 --end-chap 12 --start-vol 1

# 3. Nạp offline các tệp HTML TamHoan lưu từ trình duyệt:
python cli.py import --story tien-nghich --source tamhoan --dir data/offline_tamhoan

# 4. Pipeline trọn gói từ tải mạng tới xuất tập:
python cli.py process --story tien-nghich --source tamhoan --start-chap 1 --end-chap 12 --start-vol 1

# 5. Tải từ webnovel.vn:
python cli.py crawl --story tien-nghich --source webnovel --start-chap 1 --end-chap 12
```

---

## 9. TAB "SẢN XUẤT VIDEO" (YOUTUBE READY MP4)

Tab **"🎬 Sản Xuất Video"** tích hợp trực tiếp trên giao diện PySide6, cho phép ghép các file âm thanh MP3 thành video MP4 chất lượng cao 1080p hoặc 720p để đăng tải YouTube.

### A. Tính Năng Nổi Bật:
1. **Danh sách hàng đợi & Đọc Metadata bằng Worker nền:**
   - Đọc thời lượng và kiểm tra luồng audio trong luồng nền `AudioMetadataWorker(QThread)`, không gây đơ giao diện khi thêm nhiều tệp.
   - Hộp thoại tiến độ nạp tệp âm thanh có thể hủy bất kỳ lúc nào.
   - Tự động phát hiện và loại bỏ các tệp trùng lặp khi nạp nhiều đợt.
   - Kiểm tra tệp hỏng, tệp không có luồng audio hoặc thời lượng bằng 0: cảnh báo lý do rõ ràng và không thêm vào danh sách như tệp hợp lệ.
   - Tự động nhận diện thông minh metadata từ tên tệp (Tên truyện, Tác giả, Số tập, Khoảng chương).
   - Sắp xếp tự nhiên theo số tập (Tập 2 luôn đứng trước Tập 10).
   - Cho phép chỉnh sửa metadata từng mục trực quan qua hộp thoại riêng mà không bị kết quả quét ngầm ghi đè.
2. **Ảnh nền & Hiển thị thông minh:**
   - Hỗ trợ ảnh JPG, JPEG, PNG với cơ chế chọn ảnh chung cho cả dự án hoặc ảnh riêng cho từng tập.
   - **2 chế độ hiển thị:**
     + *Cắt đầy khung (Crop & Fill):* Giữ nguyên tỉ lệ, phóng to phủ kín khung hình 16:9, không biến dạng méo hình.
     + *Hiển thị toàn ảnh (Fit & Letterbox):* Giữ nguyên tỉ lệ ảnh gốc, tự động chèn viền nền tối hai bên hoặc trên dưới.
3. **Typography & Thiết lập Chữ Tiếng Việt:**
   - Tùy biến bật/tắt từng thành phần: Tên truyện, Tác giả, Số tập, Khoảng chương.
   - Hỗ trợ chọn Font hệ thống tiếng Việt (Segoe UI, Arial, Calibri, Tahoma,...), kích thước, màu chữ, viền chữ (stroke outline), và bóng đổ (drop shadow).
   - Tự động xuống dòng khi tiêu đề dài, giữ khoảng cách an toàn với mép khung hình (Safe margin padding).
4. **Bộ dựng chung (Shared Renderer) & Xem trước chính xác 100%:**
   - Dùng chung bộ kết xuất `render_frame()` bằng PySide6 QPainter cho cả khung hình xem trước (Live Preview / Phóng to) và khung hình đưa vào FFmpeg mã hóa video. Đảm bảo chữ tiếng Việt sắc nét và hình ảnh xem trước hoàn toàn khớp với video thành phẩm.
5. **Mã hóa FFmpeg, Bảo vệ File khi Ghi đè & Đồng bộ Hàng đợi:**
   - Thiết lập chuẩn YouTube: Container MP4, Video H.264 (yuv420p), Audio AAC 192kbps, cờ `+faststart`.
   - **Bảo vệ file hoàn chỉnh cũ khi ghi đè:** Xuất qua tệp tạm độc nhất `.tmp_[base]_[pid]_[time].mp4` trong cùng thư mục đích. Chỉ thay thế nguyên tử qua `os.replace` sau khi FFmpeg thành công và `ffprobe` xác minh tính hợp lệ của video/audio. Tuyệt đối không xóa file cũ trước khi thay thế; nếu file đích bị khóa (đang mở trong trình phát) hoặc thay thế thất bại, file cũ vẫn còn nguyên 100%.
   - **Hỗ trợ đủ 3 chế độ xử lý tệp tồn tại:**
     + *Tự đổi tên (Rename):* Đổi tên thêm hậu tố (ví dụ: `_1.mp4`).
     + *Bỏ qua (Skip):* Không xuất lại tệp đã có; đánh dấu trạng thái `skipped` và không tính là video xuất mới.
     + *Ghi đè an toàn (Overwrite):* Thay thế an toàn file cũ với bảo vệ nguyên vẹn.
   - **Hủy tác vụ và đóng ứng dụng an toàn:**
     + Đọc tiến độ qua hàng đợi nền (non-blocking polling 100ms), không chặn vòng kiểm tra hủy ngay cả khi FFmpeg không phát thêm dòng stdout.
     + Luồng nền thu gom toàn bộ stderr tránh pipe deadlock.
     + Quy trình dừng tiến trình có bảo đảm: `terminate()` -> chờ giới hạn -> `kill()` -> `wait()` xác nhận thoát hoàn toàn.
     + File tạm chỉ được dọn sau khi tiến trình đã giải phóng handle.
     + Khi đóng ứng dụng: Hộp thoại xác nhận cho phép tiếp tục làm việc hoặc hủy tác vụ rồi đóng; luồng GUI duy trì phản hồi qua `QCoreApplication.processEvents()` và không hủy QThread khi thread còn chạy.
   - **Đồng bộ trạng thái hàng đợi và Xuất lại:**
     + Phân biệt rõ các trạng thái mục: `waiting`, `processing`, `completed`, `skipped`, `cancelled`, `error`.
     + Phân biệt kết quả toàn hàng đợi: `hoàn tất`, `hoàn tất có lỗi`, `đã hủy`.
     + Khi hủy, tiến độ giữ đúng giá trị thực tế đã làm, không ép thành 100%. Các mục chưa chạy được gán trạng thái `cancelled` nhất quán.
     + Nút **"🔄 Xuất lại mục lỗi/hủy"** cho phép chọn và chạy lại nhanh các mục chưa hoàn tất.

### B. Cấu hình FFmpeg trên Windows:
- Công cụ tự động quét FFmpeg và ffprobe trong `PATH` hệ thống hoặc thư mục mặc định `C:\ffmpeg\bin\`.
- Cho phép người dùng duyệt chọn file thực thi thủ công trên giao diện.
- Nút **"Kiểm tra FFmpeg"** xác minh phiên bản và khả năng hoạt động ngay trên màn hình.
- **Hướng dẫn cài đặt nhanh FFmpeg trên Windows:**
  1. Tải bản build đầy đủ từ [gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/) (tệp `ffmpeg-release-essentials.zip`).
  2. Giải nén vào `C:\ffmpeg` sao cho có đường dẫn `C:\ffmpeg\bin\ffmpeg.exe`.
  3. Thêm `C:\ffmpeg\bin` vào biến môi trường `PATH` của Windows (hoặc duyệt chọn file trực tiếp trên giao diện ứng dụng).

---

## 10. TÍCH HỢP VIENEU-TTS ĐỂ SẢN XUẤT AUDIO MP3

Thẻ **"🎙️ Sản Xuất Audio"** tích hợp trực tiếp công nghệ tổng hợp giọng nói tiếng Việt tự nhiên [VieNeu-TTS](https://github.com/pnnbao97/VieNeu-TTS) vào quy trình khép kín:
$$\text{Nội dung đã duyệt} \longrightarrow \text{Gộp tập TXT} \longrightarrow \text{Tạo MP3} \longrightarrow \text{Ghép ảnh xuất MP4}$$

### A. Xác minh SDK & Phiên bản Ghim
- **Phiên bản SDK đã kiểm thử:** `vieneu==3.8.3`.
- **Mô hình hỗ trợ:**
  + `v3_turbo` (Mặc định): Độ phân giải 48 kHz, tốc độ nhanh, chất lượng tự nhiên cao.
  + `v3nano`: Độ phân giải 24 kHz, kích thước siêu nhẹ cho máy tính cấu hình yếu.
- **Tuân thủ API SDK chính thức:**
  + Khởi tạo: `Vieneu(mode="v3_turbo", backend="onnx"|"pytorch", precision="fp32"|"int8")`.
  + Suy luận: `tts.infer(text, voice=voice_id)`.
  + Lưu audio: `tts.save(audio, wav_path)`.
  + Lấy danh sách giọng: `tts.list_preset_voices()`.
  + Tuyệt đối **không** tự động hóa Gradio UI.
  + Không truyền tham số `style` lỗi thời (v3 Turbo đã bỏ qua `style` theo tài liệu chính thức).
  + Không đổi đuôi WAV thành MP3: Sử dụng FFmpeg mã hóa chuẩn `libmp3lame` với bitrate 192 kbps.

### B. Kiến trúc Tiến Trình Độc Lập (Subprocess Isolation)
Nhằm tránh xung đột thư viện C++ (ONNX Runtime, PyTorch, Sea-G2P) với giao diện PySide6 và bản đóng gói EXE:
1. **Không import nặng lúc khởi động:** Giao diện GUI khởi động tức thì, các tab Thu thập, Hiệu đính và Video luôn hoạt động bình thường ngay cả khi máy chưa cài đặt VieNeu-TTS.
2. **Môi trường Python TTS riêng (`venv_tts`):**
   - Không sử dụng `sys.executable` của ứng dụng đã đóng gói.
   - Cho phép chỉ định đường dẫn Python tùy ý trên giao diện hoặc tự động nhận diện `venv_tts\Scripts\python.exe`.
3. **Nạp model một lần (Single Model Load):** Tiến trình runner nạp model vào RAM/VRAM một lần duy nhất cho toàn bộ hàng đợi, không nạp lại cho từng đoạn.
4. **Giao tiếp có cấu trúc:** Giao tiếp tiến độ bằng JSON-lines qua stdout với mã hóa UTF-8, cách ly hoàn toàn với stderr của thư viện C++.

### C. Phân Đoạn Tiếng Việt (Text Chunker) & Khoảng Nghỉ
- Chia nhỏ văn bản dài thành các đoạn an toàn ($\le 240$ ký tự) theo ranh giới đoạn văn, dấu câu (`.!?…`) và mệnh đề liên từ (`nhưng`, `mà`, `bởi vì`...).
- Bảo vệ số thập phân (`1.5 vạn dặm`), dấu câu và từ ngữ, bảo đảm **100% độ bao phủ văn bản** không mất, lặp hay đảo câu.
- Tự động nhận diện tiêu đề chương (`Chương \d+:`) để áp dụng khoảng nghỉ dài hơn.
- Cấu hình khoảng nghỉ chuẩn xác:
  + Nghỉ giữa các câu: mặc định `250 ms`.
  + Nghỉ giữa các đoạn văn: mặc định `500 ms`.
  + Nghỉ giữa các chương: mặc định `1500 ms`.
- Ghép PCM trực tiếp không dùng crossfade làm biến dạng lời đọc đầu/cuối câu.

### D. Cơ Chế Manifest, Cache & Phục Hồi (Resume)
- Manifest nội bộ lưu tại: `output_volumes/<Tên_Truyện>/<Nguồn>/.tts_cache/Tap_<SốTập>_<ConfigHash>/manifest.json`.
- Ghi vết băm văn bản snapshot, thuật toán chia đoạn (`v1`), thông số model, giọng đọc và trạng thái từng file WAV.
- Tự động phục hồi các đoạn đã tạo thành công trước đó khi bị ngắt quãng hoặc dừng tác vụ.
- Vô hiệu hóa cache an toàn khi văn bản hoặc cấu hình âm thanh thay đổi.
- Nút **"🔄 Tạo lại đoạn lỗi"** cho phép xử lý lại riêng các đoạn thất bại mà không cần chạy lại từ đầu.

### E. Xuất Bản MP3 Chuẩn & Luân Chuyển Sang Video
- Mã hóa MP3 một lần duy nhất ở bước cuối bằng FFmpeg (`-codec:a libmp3lame -b:a 192k`).
- Đặt tên tệp chuẩn: `{ten_truyen}_Tap_{tap:03d}_Chuong_{dau}_den_{cuoi}.mp3`.
- Ghi đè an toàn qua tệp tạm `.tmp.mp3` và xác thực stream/thời lượng qua `ffprobe` trước khi thay thế nguyên tử (`os.replace`).
- Nút **"🎬 Chuyển sang sản xuất video"** tự động chuyển danh sách MP3 kèm trọn vẹn metadata sang Tab Video để xuất bản MP4 YouTube chỉ với 1 cú nhấp chuột.

### F. Hướng Dẫn Thiết Lập Môi Trường TTS Trên Windows
Dự án cung cấp sẵn 2 kịch bản thiết lập tự động:
1. **Chế độ CPU (ONNX Runtime - Nhẹ, tương thích cao):**
   ```cmd
   setup_tts_env_cpu.bat
   ```
2. **Chế độ GPU (PyTorch CUDA 12.x - Tốc độ cao):**
   ```cmd
   setup_tts_env_gpu.bat
   ```
*Yêu cầu nền tảng:* Cần có Python 3.10, 3.11 hoặc 3.12 64-bit trên máy để các gói pre-built wheel của `kaldi-native-fbank` và `onnxruntime` có thể cài đặt trực tiếp mà không cần trình biên dịch Cmake.

### G. Bản Quyền & Điều Kiện Sử Dụng
- Mã nguồn VieNeu-TTS được phát hành theo giấy phép mã nguồn mở.
- Trọng số mô hình và các giọng đọc preset cộng đồng cần được kiểm tra điều kiện cấp phép riêng trên HuggingFace trước khi sử dụng cho các mục đích thương mại.

---

## 11. KẾT QUẢ KIỂM THỬ TOÀN DIỆN

Bộ kiểm thử tự động gồm **104 test case** bao phủ 100% các chức năng cốt lõi và các tình huống ngoại lệ:
- Khởi động CLI (`cli.py --help`, `cli.py tts --help`) và GUI (PySide6 offscreen) trong tiến trình sạch hoàn toàn.
- Phân tích mục lục, số chương và 43 trang phân trang thực tế từ `tamhoan.com` và `webnovel.vn`.
- Trích xuất đúng số chương (ví dụ: Chương 1668 từ URL `205299`), không nhầm lẫn giữa URL ID và số chương.
- Dọn sạch quảng cáo Google Ads (`adsbygoogle`, script) và bảo toàn 100% lời thoại, dấu câu, từ bị che.
- Xử lý các tình huống biên: HTTP 403, Cloudflare challenge, trang rỗng, điều hướng disabled.
- Chuẩn hóa hostname và nhận diện nguồn chặt chẽ bằng hostname phân tích từ URL.
- Cách ly CSDL: Hai nguồn cùng có Chương 1 độc lập 100%, truy vấn đúng theo nguồn.
- Phục hồi điều hướng an toàn khi chương đã lưu thiếu `next_url`.
- Nhập offline HTML TamHoan giữ canonical URL, không lấy `file://` làm link tải mạng.
- Tải giả lập 12 chương TamHoan, gộp đúng 3 tập vào thư mục cách ly `output_volumes/tien_nghich/tamhoan/`.
- Tự động migration CSDL cũ chưa có cột `source`, bảo toàn toàn bộ dữ liệu hiện có.
- Đổi nguồn trên GUI cập nhật chính xác danh sách chương, thư mục xuất và hồ sơ truyện.
- **Kiểm thử Thuật toán Chia đoạn (Text Chunker):** Bảo toàn 100% từ ngữ khi tái dựng, tách câu dài theo mệnh đề an toàn, bảo vệ số thập phân (`1.5 vạn dặm`), đánh dấu ranh giới chương.
- **Kiểm thử Manifest & Cache:** Kiểm tra tính hợp lệ của WAV header RIFF, lưu trữ snapshot bất biến, phục hồi tiếp tục các đoạn chưa xong, vô hiệu hóa cache khi đổi text hoặc đổi giọng đọc.
- **Kiểm thử Ghép nối & Mã hóa MP3:** Từ chối tạo MP3 nếu thiếu bất kỳ chunk nào, ghép nối chính xác các khoảng lặng (câu, đoạn, chương), mã hóa MP3 với FFmpeg và kiểm tra stream bằng ffprobe.
- **Kiểm thử An toàn Ghi đè MP3:** Bảo toàn file MP3 cũ nếu quá trình ghép thất bại, xử lý các chế độ overwrite, skip, rename.
- **Kiểm thử Tiến trình con (Runner & Adapter):** Kiểm tra môi trường graceful khi chưa có vieneu, chạy batch worker ở chế độ mock phát đúng sự kiện JSON-lines, hủy tác vụ dọn sạch tiến trình con.
- **Kiểm thử Tích hợp GUI & Luân chuyển Video:** Khởi tạo Tab Sản Xuất Audio không phụ thuộc thư viện nặng, nạp tập từ dự án hoặc file TXT, luân chuyển trọn vẹn metadata (tên truyện, số tập, khoảng chương, thời lượng thực tế) sang Tab Sản Xuất Video.
- Đọc metadata audio bằng ffprobe trong worker nền, bỏ qua file hỏng/không có audio, ngăn trùng lặp.
- Sắp xếp tập tự nhiên theo số, xử lý đường dẫn tiếng Việt có dấu, khoảng trắng và ký tự đặc biệt.
- Dựng ảnh khung hình đúng kích thước, giữ đúng tỉ lệ ở cả 2 chế độ (`crop_fill` và `fit_letterbox`).
- Chống tràn khung chữ dài, xử lý font tiếng Việt, đổ bóng viền chữ.
- Mã hóa video MP4 thật bằng FFmpeg, kiểm tra stream video/audio và thời lượng chuẩn xác qua ffprobe.
- Hủy khi FFmpeg đang mã hóa và khi FFmpeg bị treo không phát stdout (dưới 100ms).
- Xử lý tiến trình không chịu terminate bằng cơ chế kill và wait xác thực.
- Đóng cửa sổ ứng dụng an toàn khi worker đang chạy, không còn thread/process mồ côi.

Chạy toàn bộ kiểm thử:
```bash
python -m unittest discover -s tests -p "test_*.py"
```
*Kết quả:* **104/104 test đạt (OK) 100%, 0 thất bại, 0 lỗi, 0 bỏ qua.**

