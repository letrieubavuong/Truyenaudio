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
│   ├── parser.py           # Phân tích HTML vivutruyen và tệp văn bản TXT
│   ├── storage.py          # Quản lý CSDL SQLite, bản gốc bất biến, versioning, lưu quyết định duyệt
│   ├── crawler.py          # Tải mạng tuần tự, rate limit, timeout, chống lặp URL
│   ├── importer.py         # Nạp tệp offline HTML/TXT vào SQLite
│   ├── spellchecker.py     # Chuẩn hóa NFC, dọn gạch dưới, khoảng trắng, bảo vệ từ che c*m v**
│   ├── ai_checker.py       # Trợ lý AI đề xuất (mặc định pending, schema check, ẩn API key)
│   ├── merger.py           # Bộ gộp 4 chương/tập audio, chuẩn hóa \s\n -> \n, xử lý DRAFT
│   └── reporter.py         # Xuất bundle an toàn (file tạm .tmp): RAW, EDITED, REPORT, CHANGELOG
├── resources\
│   ├── default_dictionary.json  # Từ điển lỗi gõ có thể mở rộng (đã lọc các cặp trùng nhau)
│   ├── protected_terms.json     # Danh từ riêng, tên nhân vật, địa danh được bảo vệ
│   └── styles.qss               # Giao diện nền sáng hiện đại PySide6
├── gui\
│   ├── widgets.py          # Bảng chương & Giao diện duyệt Side-by-Side (chuột + phím Space)
│   ├── dialogs.py          # Hộp thoại cấu hình AI, từ điển, thuật ngữ bảo vệ
│   ├── workers.py          # Luồng nền: CrawlWorker, SpellCheckWorker, ExportWorker riêng biệt
│   └── main_window.py      # Cửa sổ chính với nút "Áp dụng và xuất tập..." sau khi duyệt
├── cli.py                  # Giao diện dòng lệnh CLI đầy đủ chức năng
├── app.py                  # Khởi chạy ứng dụng GUI PySide6
├── data\sample_chapters\   # 4 chương mẫu thực tế phục vụ kiểm thử offline
└── tests\                  # Bộ kiểm thử tự động toàn diện (33/33 PASS 100%)
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

---

## 4. HƯỚNG DẪN SỬ DỤNG

### A. Quy trình trên Giao diện Desktop (PySide6)
Chạy lệnh trong terminal:
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

Mỗi tập được xuất thành 4 tệp đồng bộ:
1. `Tap_{vol}_Chuong_{start}_den_{end}_RAW.txt`: Bản gốc bất biến định dạng đọc audio chuẩn:
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
2. `Tap_{vol}_Chuong_{start}_den_{end}_EDITED.txt`: Bản đã sửa lỗi sau khi duyệt/áp dụng theo cùng định dạng đọc audio. Bản này tái tạo chính xác 100% từ bản gốc và nhật ký thay đổi.
3. `Tap_{vol}_Chuong_{start}_den_{end}_REPORT.md`: Báo cáo chi tiết:
   - Thống kê: Tổng số đề xuất, Số đã áp dụng, Số chờ duyệt (pending), Số từ chối (rejected).
   - Phân loại theo các nhóm lỗi (Chính tả, Dấu câu, Khoảng trắng, Gạch dưới thừa, Lặp câu, Tên riêng).
   - Bảng kê chi tiết từng vị trí ký tự, nội dung gốc, nội dung sửa, lý do, nguồn và trạng thái (ký tự đặc biệt như `|` được escape an toàn).
4. `Tap_{vol}_Chuong_{start}_den_{end}_CHANGELOG.json`: Nhật ký kiểm tra (audit log) máy đọc được.

**Quy tắc an toàn dữ liệu:**
- **Bất biến:** Nội dung raw đã nạp vào CSDL không bị ghi đè khi cùng URL trả về nội dung khác; phiên bản mới được lưu vào `chapter_versions`.
- **Ghi đè:** Không ghi đè tệp xuất nếu chưa bật cờ overwrite. Quá trình xuất sử dụng file tạm `.tmp` trước khi atomic replace.
- **Tập nháp (DRAFT):** Nếu thiếu một chương hoặc có lỗi tải, tập được đánh dấu là `is_draft = True`, xuất file có hậu tố `_DRAFT_...` kèm cảnh báo danh sách chương thiếu, không xuất như tập hoàn chỉnh.
- **Nhóm cuối:** Nhóm cuối dưới 4 chương chỉ xuất khi bật cờ `allow_partial_last_volume`.
