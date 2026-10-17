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
│   ├── parser.py           # Phân tích HTML vivutruyen.com, webnovel.vn và tệp văn bản TXT
│   ├── storage.py          # Quản lý CSDL SQLite, bản gốc bất biến, versioning, lưu quyết định duyệt
│   ├── crawler.py          # Tải mạng tuần tự, rate limit, timeout, chống lặp URL
│   ├── importer.py         # Nạp tệp offline HTML/TXT vào SQLite
│   ├── spellchecker.py     # Chuẩn hóa NFC, dọn gạch dưới, khoảng trắng, bảo vệ từ che c*m v**
│   ├── ai_checker.py       # Trợ lý AI đề xuất (mặc định pending, schema check, ẩn API key)
│   ├── merger.py           # Bộ gộp 4 chương/tập audio, chuẩn hóa \s\n -> \n, xử lý DRAFT
│   ├── reporter.py         # Xuất bundle an toàn (file tạm .tmp): RAW, EDITED, REPORT, CHANGELOG
│   ├── video_models.py     # Dataclass hàng đợi Audio/Video và cấu hình xuất video YouTube
│   ├── video_renderer.py   # Bộ dựng khung hình QPainter dùng chung 100% giữa Preview và FFmpeg
│   └── ffmpeg_utils.py     # Gọi FFmpeg/ffprobe qua subprocess, đọc tiến độ pipe:1, xuất an toàn .tmp
├── resources\
│   ├── default_dictionary.json            # Từ điển lỗi gõ có thể mở rộng (đã lọc các cặp trùng nhau)
│   ├── protected_terms.json               # Danh từ riêng, tên nhân vật, địa danh Phàm Nhân Tu Tiên
│   ├── protected_terms_tien_nghich.json   # Thuật ngữ tu tiên, nhân vật, môn phái Tiên Nghịch
│   └── styles.qss                         # Giao diện nền sáng hiện đại PySide6
├── gui\
│   ├── widgets.py          # Bảng chương & Giao diện duyệt Side-by-Side (chuột + phím Space)
│   ├── dialogs.py          # Hộp thoại cấu hình AI, từ điển, thuật ngữ bảo vệ
│   ├── workers.py          # Luồng nền: CrawlWorker, SpellCheckWorker, ExportWorker riêng biệt
│   ├── video_tab.py        # Tab "Sản Xuất Video": Quản lý danh sách, xem trước và xuất video
│   ├── video_worker.py     # Luồng nền xuất video hàng loạt, báo cáo ETA/tiến độ, hỗ trợ hủy
│   └── main_window.py      # Cửa sổ chính: Chọn truyện/nguồn, 4 tab nghiệp vụ hoàn chỉnh
├── cli.py                  # Giao diện dòng lệnh CLI đầy đủ chức năng (--story)
├── app.py                  # Khởi chạy ứng dụng GUI PySide6
├── data\
│   ├── sample_chapters\   # 4 chương mẫu thực tế phục vụ kiểm thử offline PNTT
│   └── fixtures\          # Fixture HTML thực tế webnovel.vn (mục lục và chương Tiên Nghịch)
└── tests\                  # Bộ kiểm thử tự động toàn diện (69/69 PASS 100%)
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
2. **Tiên Nghịch** – Nguồn `webnovel.vn` (Tác giả: Nhĩ Căn, URL: `https://webnovel.vn/tien-nghich`)

### A. Khảo sát & Phân tích Nguồn `webnovel.vn`:
- **Mục lục:** Cấu trúc `<ol class="chapter-list" id="chapterList">` chứa trực tiếp các thẻ `<a class="chapter-item__link">` với chỉ số `<span class="chapter-item__index">` và tên chương `<span class="chapter-item__title">`.
- **Nội dung chương:**
  - Tiêu đề chương: `<p class="reader__chapter">`.
  - Đoạn văn nội dung: Nằm trong `<div id="chapter-c">` thuộc `<article class="reader__content">`.
  - **Làm sạch rác & quảng cáo:** Loại bỏ hoàn toàn khối `<div class="bastorypush">` (quảng cáo đề cử nội bộ), dọn sạch các thẻ nút chia sẻ và menu điều hướng.
  - **Điều hướng chương:** Trích xuất liên kết "Chương sau" và "Chương trước" từ cụm `<div class="reader__actions">`.
- **Bảo vệ và cách ly dữ liệu:**
  - Dữ liệu chương lưu trong CSDL riêng biệt hoặc tách theo `story_id`.
  - Thư mục xuất riêng: `output_volumes/tien_nghich/` (tránh xung đột số tập với Phàm Nhân Tu Tiên).
  - Từ điển thuật ngữ bảo vệ riêng: `resources/protected_terms_tien_nghich.json` bảo vệ tên nhân vật (Vương Lâm, Lý Mộ Uyển, Tư Đồ Nam,...), môn phái (Hằng Nhạc Phái, Thi Ma Tông,...) và cảnh giới tu luyện.

### B. Mẫu Mở Đầu & Kết Thúc Tập Tiên Nghịch:
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

### C. Sử dụng qua CLI cho Tiên Nghịch:
```bash
# Nạp và xử lý truyện Tiên Nghịch từ thư mục offline:
python cli.py process --story tien-nghich --import-dir data/sample_tien_nghich --start-chap 1 --end-chap 12 --start-vol 1 --overwrite

# Tải từ webnovel.vn (hoặc kiểm tra fixture offline):
python cli.py crawl --story tien-nghich --url https://webnovel.vn/tien-nghich/chuong-1 --start-chap 1 --end-chap 4
```

---

## 9. TAB "SẢN XUẤT VIDEO" (YOUTUBE READY MP4)

Tab **"🎬 Sản Xuất Video"** tích hợp trực tiếp trên giao diện PySide6, cho phép ghép các file âm thanh MP3 thành video MP4 chất lượng cao 1080p hoặc 720p để đăng tải YouTube.

### A. Tính Năng Nổi Bật:
1. **Danh sách hàng đợi Audio:**
   - Hỗ trợ thêm từng file MP3 hoặc quét toàn bộ file MP3 trong thư mục.
   - Hỗ trợ đầy đủ đường dẫn tiếng Việt có dấu và dấu cách trên Windows.
   - Tự động nhận diện thông minh metadata từ tên tệp (Tên truyện, Tác giả, Số tập, Khoảng chương) hoặc liên kết dữ liệu từ các tập truyện đã có trong ứng dụng.
   - Sắp xếp tự nhiên theo số tập (Tập 2 luôn đứng trước Tập 10).
   - Chặn thêm trùng file; cho phép chỉnh sửa metadata từng mục trực quan.
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
5. **Mã hóa FFmpeg & An toàn tệp tin:**
   - Thiết lập chuẩn YouTube: Container MP4, Video H.264 (yuv420p), Audio AAC 192kbps, cờ `+faststart`.
   - Xuất qua tệp tạm `.tmp.mp4`, chỉ đổi tên chính thức sau khi `ffprobe` kiểm tra có đầy đủ luồng video, luồng audio và thời lượng trùng khớp với file MP3.
   - Không lo deadlock: Đọc tiến độ bằng cờ machine-readable `-progress pipe:1` và luồng nền hút sạch `stderr`.
   - Hỗ trợ hủy tác vụ an toàn (dừng tiến trình FFmpeg và dọn dẹp file tạm).
   - Chính sách ghi đè rõ ràng: *Ghi đè (Overwrite)*, *Bỏ qua (Skip)*, hoặc *Tự đổi tên thêm hậu tố (Rename)*.

### B. Cấu hình FFmpeg trên Windows:
- Công cụ tự động quét FFmpeg và ffprobe trong `PATH` hệ thống hoặc thư mục mặc định `C:\ffmpeg\bin\`.
- Cho phép người dùng duyệt chọn file thực thi thủ công trên giao diện.
- Nút **"Kiểm tra FFmpeg"** xác minh phiên bản và khả năng hoạt động ngay trên màn hình.
- **Hướng dẫn cài đặt nhanh FFmpeg trên Windows:**
  1. Tải bản build đầy đủ từ [gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/) (tệp `ffmpeg-release-essentials.zip`).
  2. Giải nén vào `C:\ffmpeg` sao cho có đường dẫn `C:\ffmpeg\bin\ffmpeg.exe`.
  3. Thêm `C:\ffmpeg\bin` vào biến môi trường `PATH` của Windows (hoặc duyệt chọn file trực tiếp trên giao diện ứng dụng).

---

## 10. KẾT QUẢ KIỂM THỬ TOÀN DIỆN

Bộ kiểm thử tự động gồm **69 test case** bao phủ 100% các chức năng cốt lõi:
- Khởi động CLI (`cli.py --help`) và GUI (PySide6 offscreen).
- Tải giả lập 12 chương và xuất 3 tập hoàn chỉnh.
- Cache chương 1–4, phục hồi liên kết điều hướng và tiếp tục thu thập.
- Phát hiện và phân loại lỗi HTTP 403, 429, timeout, trang rỗng, URL lặp.
- Cách ly hoàn toàn CSDL, hồ sơ và quyết định duyệt giữa Phàm Nhân Tu Tiên và Tiên Nghịch.
- Phân tích mục lục, trích xuất nội dung và làm sạch quảng cáo `bastorypush` nguồn `webnovel.vn`.
- Đọc metadata audio bằng ffprobe, sắp xếp tập tự nhiên theo số.
- Xử lý đường dẫn tiếng Việt có dấu, khoảng trắng và ký tự đặc biệt.
- Dựng ảnh khung hình đúng kích thước, giữ đúng tỉ lệ ở cả 2 chế độ (`crop_fill` và `fit_letterbox`).
- Chống tràn khung chữ dài, xử lý font tiếng Việt, đổ bóng viền chữ.
- Mã hóa video MP4 thật bằng FFmpeg, kiểm tra stream video/audio và thời lượng chuẩn xác.
- Hủy tác vụ xuất video an toàn, dọn tệp tạm, chịu lỗi từng mục trong hàng đợi và bảo vệ chống ghi đè mất tệp.

Chạy toàn bộ kiểm thử:
```bash
python -m unittest discover -s tests -p "test_*.py"
```
*Kết quả:* **69/69 test đạt (OK) 100%.**

