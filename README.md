# CÔNG CỤ THU THẬP, HIỆU ĐÍNH TIẾNG VIỆT & GỘP TẬP TRUYỆN (PNTT)

Hệ thống desktop Python chạy trên Windows hỗ trợ thu thập nội dung truyện được phép sử dụng, tự động sửa lỗi chính tả tiếng Việt (theo quy tắc & AI tùy chọn), gộp mỗi 4 chương thành một tập TXT (xuất chuẩn Windows CRLF UTF-8), kèm báo cáo Markdown và nhật ký kiểm tra JSON.

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
│   ├── models.py           # Dataclass: Chapter, Volume, SpellIssue, StoryInfo
│   ├── parser.py           # Bộ phân tích HTML vivutruyen và tệp văn bản TXT
│   ├── storage.py          # Quản lý CSDL SQLite crawler_state.db, băm SHA256, resume
│   ├── crawler.py          # Bộ tải mạng tuần tự, rate limit, timeout, chống loop/redirect
│   ├── importer.py         # Bộ nạp tệp offline HTML/TXT vào SQLite
│   ├── spellchecker.py     # Bộ chuẩn hóa Unicode NFC, quy tắc, từ điển, tên riêng, câu trùng
│   ├── ai_checker.py       # Bộ sửa lỗi AI với mã định danh chunk và kiểm tra toàn vẹn
│   ├── merger.py           # Bộ gộp 4 chương/tập, Windows CRLF, xử lý bản nháp DRAFT
│   └── reporter.py         # Xuất bundle: RAW TXT, EDITED TXT, REPORT MD, CHANGELOG JSON
├── resources\
│   ├── default_dictionary.json  # Từ điển sửa lỗi chính tả có thể chỉnh sửa
│   ├── protected_terms.json     # Danh từ riêng, tên nhân vật, địa danh được bảo vệ
│   └── styles.qss               # Giao diện nền sáng hiện đại PySide6
├── gui\
│   ├── widgets.py          # Bảng trạng thái chương & Giao diện duyệt lỗi Side-by-Side
│   ├── dialogs.py          # Hộp thoại cài đặt AI, từ điển, thuật ngữ bảo vệ
│   ├── workers.py          # QThread chạy nền không đơ giao diện
│   └── main_window.py      # Cửa sổ chính giao diện PySide6
├── cli.py                  # Giao diện dòng lệnh CLI đầy đủ chức năng
├── app.py                  # Khởi chạy ứng dụng GUI PySide6
├── data\sample_chapters\   # 4 chương mẫu thực tế lấy từ vivutruyen.com
└── tests\                  # Toàn bộ Unit & Integration tests (19/19 PASS 100%)
```

---

## 3. CÀI ĐẶT & MÔI TRƯỜNG

Yêu cầu Python 3.10 trở lên trên Windows / Linux / macOS.

1. **Cài đặt thư viện phụ thuộc:**
```bash
pip install -r requirements.txt
```

2. **Chạy bộ kiểm thử tự động (Unit & Integration Tests):**
```bash
python -m unittest discover -s tests -p "test_*.py"
```

---

## 4. HƯỚNG DẪN SỬ DỤNG

### A. Khởi chạy Giao diện Desktop (PySide6)
Chạy lệnh trong terminal:
```bash
python app.py
```
- **Khu vực 1 - Nguồn dữ liệu:**
  - Nhập URL truyện và URL chương bắt đầu nếu tải mạng.
  - Hoặc bấm nút **"Nạp tệp máy tính (Offline)..."** trỏ đến thư mục chứa các file HTML/TXT (ví dụ: `data/sample_chapters`).
- **Khu vực 2 - Cấu hình:**
  - Chọn chương bắt đầu, chương kết thúc.
  - Chọn số chương mỗi tập (mặc định: 4).
  - Nhập số tập bắt đầu (ví dụ: người dùng nhập chương 1069–1076, số tập bắt đầu 268 -> sinh `Tap_268_Chuong_1069_den_1072.txt` và `Tap_269_Chuong_1073_den_1076.txt`).
  - Chọn thư mục xuất tệp.
  - Bật/tắt các cờ: Sửa lỗi chính tả, Gộp tập, Ghi đè, Xuất nhóm cuối (< 4 chương), Sử dụng AI.
- **Khu vực 3 - Điều khiển:**
  - Bấm **"Bắt đầu"**, có thể **"Tạm dừng"**, **"Tiếp tục"** hoặc **"Hủy bỏ"** bất kỳ lúc nào.
- **Khu vực 4 - Duyệt & Xem trước:**
  - Tab 1: Xem trạng thái từng chương và Log thời gian thực.
  - Tab 2: So sánh trực quan văn bản Bản gốc vs Bản sửa (Side-by-side) và tích chọn/từ chối từng đề xuất sửa.
  - Tab 3: Xem báo cáo thống kê Markdown và mở thư mục xuất.

---

### B. Sử dụng bằng Dòng lệnh (CLI)
CLI dùng chung toàn bộ nghiệp vụ từ `core/`:

1. **Chạy trọn gói (Process):**
```bash
# Nạp từ thư mục offline và xuất tập:
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

## 5. QUY ƯỚC ĐẾM VÀ ĐỊNH DẠNG XUẤT

Mỗi tập được xuất thành 4 tệp đồng bộ:
1. `Tap_{vol}_Chuong_{start}_den_{end}_RAW.txt`: Bản gốc bất biến định dạng đọc audio chuẩn:
   - Phần mở đầu tiêu chuẩn:
     ```
     PHÀM NHÂN TU TIÊN - TẬP {so_tap}
     Chào mừng các bạn đang theo dõi bộ truyện tiên hiệp Phàm Nhân Tu Tiên, tác giả Vong Ngữ.
     Đây là Tập {so_tap}, phát từ Chương {chuong_dau} đến Chương {chuong_cuoi}.
     Chúc các bạn có những giây phút thư giãn và trải nghiệm tuyệt vời.
     ```
   - Không xuất tiêu đề từng chương, không xuất nhãn đánh số chương và đường phân cách.
   - Các chương nối tiếp nhau bằng một dòng trống.
   - Kết thúc tập bằng một dòng:
     ```
     Hết Tập {so_tap}: Cảm ơn quý thính giả đã chú ý lắng nghe. Hẹn gặp lại các bạn trong Tập {so_tap_tiep_theo} tiếp theo!
     ```
   - Xuống dòng Windows CRLF (`\r\n`), mã hóa UTF-8.
2. `Tap_{vol}_Chuong_{start}_den_{end}_EDITED.txt`: Bản đã sửa lỗi sau khi duyệt/áp dụng theo cùng định dạng đọc audio.
3. `Tap_{vol}_Chuong_{start}_den_{end}_REPORT.md`: Báo cáo chi tiết:
   - Thống kê: Tổng số đề xuất, Số đã áp dụng, Số chờ duyệt (pending), Số từ chối (rejected).
   - Phân loại 5 nhóm: Chính tả/từ vựng, Dấu câu, Khoảng trắng, Gạch dưới thừa/rác ký tự, Lặp câu, Tên riêng.
   - Bảng kê chi tiết từng vị trí ký tự, nội dung gốc, nội dung sửa, lý do, nguồn đề xuất.
4. `Tap_{vol}_Chuong_{start}_den_{end}_CHANGELOG.json`: Nhật ký kiểm tra (audit log) máy đọc được.

**Quy tắc an toàn:**
- Không ghi đè nếu người dùng chưa bật cờ overwrite.
- Nếu thiếu một chương hoặc có lỗi tải: Tập được đánh dấu là `is_draft = True`, xuất file có hậu tố `_DRAFT_...` kèm danh sách chương thiếu, không xuất như tập hoàn chỉnh.
- Nhóm cuối dưới 4 chương chỉ xuất khi bật cờ `allow_partial_last_volume`.
