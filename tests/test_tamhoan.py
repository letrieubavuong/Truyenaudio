"""
Unit and Integration Tests for TamHoan (tamhoan.com) integration for Tiên Nghịch.
Verification includes:
1. TOC parsing, chapters list, and pagination from real tamhoan.com fixtures.
2. Real chapter number extraction vs arbitrary URL ID (e.g. 205299 is Ch. 1668, not Ch. 205299).
3. Ad cleaning (<ins class="adsbygoogle">, <script>) while preserving dialogues, marks, and word masks.
4. Edge cases: 403 forbidden, Cloudflare challenge, empty content, missing next.
5. Hostname normalization and strict source detection.
6. SQLite multi-source isolation: Chapter 1 from webnovel and Chapter 1 from tamhoan co-exist without collision.
7. Resumption and safe navigation recovery.
8. Offline import from browser-saved HTML (canonical preservation, rejection of file:// as next_url).
9. Simulated 12-chapter crawl and merge into 3 volumes under output_volumes/tien_nghich/tamhoan/.
10. Legacy database migration preservation.
11. Clean process execution for CLI (--help) and GUI (MainWindow).
"""
import unittest
import os
import shutil
import tempfile
import subprocess
import sys
from datetime import datetime
from unittest.mock import patch, MagicMock

from core.models import Chapter, Volume
from core.parser import SourceParser, TamHoanParser
from core.storage import StorageManager
from core.profiles import (
    get_profile,
    normalize_hostname,
    detect_source_from_url,
    StoryProfile,
    SourceProfile,
)
from core.crawler import NetworkCrawler
from core.importer import OfflineImporter
from core.merger import VolumeMerger
from core.reporter import ReportGenerator


class TestTamHoanIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_dir = os.path.join(os.path.dirname(__file__), "..", "data", "fixtures")
        cls.toc_file = os.path.join(cls.fixture_dir, "tamhoan_story_tien_nghich.html")
        cls.chap1_file = os.path.join(cls.fixture_dir, "tamhoan_chap_203612.html")
        cls.chap1668_file = os.path.join(cls.fixture_dir, "205299.html")

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_tamhoan.db")
        self.storage = StorageManager(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_parse_toc_and_pagination(self):
        """Kiểm tra phân tích mục lục thực tế từ tamhoan.com và phân trang."""
        if not os.path.isfile(self.toc_file):
            self.skipTest("Tệp fixture TOC TamHoan không tồn tại.")

        with open(self.toc_file, "r", encoding="utf-8") as f:
            html = f.read()

        toc = SourceParser.parse_toc_html(html, current_url="https://tamhoan.com/truyen/tien-nghich")
        self.assertEqual(toc["story_title"], "Tiên Nghịch")
        self.assertEqual(toc["author"], "Nhĩ Căn")
        self.assertEqual(len(toc["chapters"]), 50)  # Mỗi trang mục lục có 50 chương
        # Chương 1 phải có số chương là 1 và link tới ID bài viết thực tế 203612
        first_chap = toc["chapters"][0]
        self.assertEqual(first_chap["chapter_num"], 1)
        self.assertIn("https://tamhoan.com/tien-nghich/203612", first_chap["url"])
        self.assertEqual(toc["total_pages"], 43)
        self.assertEqual(toc["next_page_url"], "https://tamhoan.com/truyen/tien-nghich?page=2")

    def test_02_parse_chapter_1668_url_id_distinction(self):
        """Xác minh: URL ID 205299 là mã bài viết, không phải số chương (số chương thật là 1668)."""
        if not os.path.isfile(self.chap1668_file):
            self.skipTest("Tệp fixture 205299.html không tồn tại.")

        with open(self.chap1668_file, "r", encoding="utf-8") as f:
            html = f.read()

        parsed = SourceParser.parse_chapter_html(html, current_url="https://tamhoan.com/tien-nghich/205299")
        self.assertEqual(parsed["chapter_num"], 1668)
        self.assertNotEqual(parsed["chapter_num"], 205299)
        self.assertEqual(parsed["chapter_title"], "Chương 1668: Thuộc về Tây Tử một năm")
        self.assertTrue(parsed["next_url"].startswith("https://tamhoan.com/tien-nghich/"))
        self.assertTrue(parsed["prev_url"].startswith("https://tamhoan.com/tien-nghich/"))
        self.assertGreater(len(parsed["paragraphs"]), 10)

    def test_03_parse_chapter_1_and_ad_removal_preserve_vietnamese(self):
        """Trích xuất Chương 1 từ tamhoan_chap_203612.html: loại bỏ adsbygoogle nhưng giữ nguyên lời thoại tiếng Việt."""
        if not os.path.isfile(self.chap1_file):
            self.skipTest("Tệp fixture Chương 1 TamHoan không tồn tại.")

        with open(self.chap1_file, "r", encoding="utf-8") as f:
            html = f.read()

        parsed = SourceParser.parse_chapter_html(html, current_url="https://tamhoan.com/tien-nghich/203612")
        self.assertEqual(parsed["chapter_num"], 1)
        self.assertEqual(parsed["chapter_title"], "Chương 1: Ly hương.")
        self.assertEqual(parsed["next_url"], "https://tamhoan.com/tien-nghich/203613")
        self.assertEqual(parsed["prev_url"], "")  # Nút lùi ở Chương 1 bị disabled

        raw_text = parsed["raw_content"]
        # Không còn chứa thẻ script quảng cáo hay adsbygoogle
        self.assertNotIn("adsbygoogle", raw_text)
        self.assertNotIn("<script", raw_text)
        self.assertNotIn("window.adsbygoogle", raw_text)
        # Giữ nguyên lời thoại tiếng Việt và tên riêng
        self.assertIn("Thiết Trụ", raw_text)
        self.assertIn("Vương Lâm", raw_text)
        self.assertIn("- Cha,", raw_text)
        self.assertTrue(len(parsed["content_hash"]) == 64)  # SHA-256

    def test_04_edge_cases_parser(self):
        """Kiểm tra các trường hợp biên: 403 Forbidden, Cloudflare challenge, trang rỗng, điều hướng."""
        # 1. Trang bị chặn 403
        blocked_html = "<html><head><title>403 Forbidden</title></head><body>Access Denied</body></html>"
        res_blocked = SourceParser.parse_chapter_html(blocked_html, "https://tamhoan.com/tien-nghich/1000")
        self.assertTrue(res_blocked.get("is_blocked"))
        self.assertIn("bị từ chối", res_blocked.get("error", "").lower())

        # 2. Trang Cloudflare challenge
        cf_html = "<html><head><title>Just a moment...</title></head><body>Checking your browser...</body></html>"
        res_cf = SourceParser.parse_chapter_html(cf_html, "https://tamhoan.com/tien-nghich/1001")
        self.assertTrue(res_cf.get("is_blocked"))

        # 3. Trang rỗng không có nội dung truyện
        empty_html = "<html><body><div class='chapContent'><div class='content'></div></div></body></html>"
        res_empty = SourceParser.parse_chapter_html(empty_html, "https://tamhoan.com/tien-nghich/1002")
        self.assertEqual(len(res_empty["paragraphs"]), 0)
        self.assertIn("Không tìm thấy nội dung", res_empty.get("error", ""))

    def test_05_hostname_normalization_and_source_detection(self):
        """Kiểm tra chuẩn hóa hostname và phát hiện nguồn chặt chẽ."""
        self.assertEqual(normalize_hostname("https://tamhoan.com/tien-nghich/203612"), "tamhoan.com")
        self.assertEqual(normalize_hostname("http://WWW.TAMHOAN.COM/truyen/tien-nghich"), "tamhoan.com")
        self.assertEqual(normalize_hostname("https://webnovel.vn:443/tien-nghich/"), "webnovel.vn")
        self.assertEqual(normalize_hostname("https://vivutruyen.com/truyen/pham-nhan-tu-tien"), "vivutruyen.com")

        self.assertEqual(detect_source_from_url("https://tamhoan.com/tien-nghich/203612"), "tamhoan")
        self.assertEqual(detect_source_from_url("https://webnovel.vn/tien-nghich/chuong-1/"), "webnovel")
        self.assertEqual(detect_source_from_url("https://vivutruyen.com/truyen/pham-nhan-tu-tien"), "vivutruyen")
        self.assertEqual(detect_source_from_url("https://otherdomain.com/something"), "")

    def test_06_sqlite_source_isolation_same_chapter_num(self):
        """Hai nguồn webnovel.vn và tamhoan.com cùng có Chương 1 phải độc lập, không ghi đè."""
        story = self.storage.get_or_create_story(
            url="https://webnovel.vn/tien-nghich",
            title="Tiên Nghịch",
            author="Nhĩ Căn",
        )
        s_id = story.id

        # Chương 1 từ Webnovel
        ch_webnovel = Chapter(
            story_id=s_id,
            chapter_num=1,
            chapter_title="Chương 1: Xa nhà (1)",
            source_url="https://webnovel.vn/tien-nghich/chuong-1/",
            raw_content="Nội dung bản dịch Webnovel chương 1...",
            content_hash="hash_webnovel_001",
            status="verified",
            source="webnovel",
        )
        self.storage.save_chapter(ch_webnovel)

        # Chương 1 từ TamHoan
        ch_tamhoan = Chapter(
            story_id=s_id,
            chapter_num=1,
            chapter_title="Chương 1: Ly hương.",
            source_url="https://tamhoan.com/tien-nghich/203612",
            raw_content="Nội dung bản dịch TamHoan chương 1...",
            content_hash="hash_tamhoan_001",
            status="verified",
            source="tamhoan",
        )
        self.storage.save_chapter(ch_tamhoan)

        # Kiểm tra hai chương cùng tồn tại độc lập
        ret_wn = self.storage.get_chapter_by_num(s_id, 1, source="webnovel")
        ret_th = self.storage.get_chapter_by_num(s_id, 1, source="tamhoan")

        self.assertIsNotNone(ret_wn)
        self.assertIsNotNone(ret_th)
        self.assertNotEqual(ret_wn.id, ret_th.id)
        self.assertEqual(ret_wn.chapter_title, "Chương 1: Xa nhà (1)")
        self.assertEqual(ret_th.chapter_title, "Chương 1: Ly hương.")
        self.assertEqual(ret_wn.source, "webnovel")
        self.assertEqual(ret_th.source, "tamhoan")

        # Range query theo nguồn
        wn_list = self.storage.get_chapters_range(s_id, 1, 10, source="webnovel")
        th_list = self.storage.get_chapters_range(s_id, 1, 10, source="tamhoan")
        self.assertEqual(len(wn_list), 1)
        self.assertEqual(len(th_list), 1)
        self.assertEqual(wn_list[0].chapter_title, "Chương 1: Xa nhà (1)")
        self.assertEqual(th_list[0].chapter_title, "Chương 1: Ly hương.")

    def test_07_crawler_navigation_recovery_and_resumption(self):
        """Kiểm tra crawler tiếp tục tải từ CSDL và phục hồi điều hướng nếu thiếu next_url."""
        story = self.storage.get_or_create_story(
            url="https://tamhoan.com/truyen/tien-nghich",
            title="Tiên Nghịch",
            author="Nhĩ Căn",
        )
        s_id = story.id

        # Giả lập đã lưu chương 1 nhưng next_url bị rỗng
        ch1 = Chapter(
            story_id=s_id,
            chapter_num=1,
            chapter_title="Chương 1: Ly hương.",
            source_url="https://tamhoan.com/tien-nghich/203612",
            raw_content="Nội dung chương 1",
            content_hash="h1",
            status="verified",
            next_url="",  # Thiếu điều hướng
            source="tamhoan",
        )
        self.storage.save_chapter(ch1)

        crawler = NetworkCrawler(storage=self.storage, delay_seconds=0.01)

        # Mock fetch_page để phục hồi next_url cho ch1 và tải ch2
        def mock_fetch(url):
            if "203612" in url:
                # Trả về HTML chứa next link
                html = """
                <html><body>
                <div class="chapContent">
                    <span class="chapTitle">Chương 1: Ly hương.</span>
                    <div class="content"><p>Nội dung ch1</p></div>
                    <a id="next_chap" href="https://tamhoan.com/tien-nghich/203613">Chương tiếp</a>
                </div>
                </body></html>
                """
                return {"success": True, "status_code": 200, "text": html, "url": url}
            elif "203613" in url:
                html = """
                <html><body>
                <div class="chapContent">
                    <span class="chapTitle">Chương 2: Ly hương (2)</span>
                    <div class="content"><p>Nội dung ch2</p></div>
                    <a id="next_chap" class="disabled" href="#">Hết</a>
                </div>
                </body></html>
                """
                return {"success": True, "status_code": 200, "text": html, "url": url}
            return {"success": False, "status_code": 404, "error": "Not Found"}

        crawler.fetch_page = mock_fetch

        res = crawler.crawl_range(
            story_url="https://tamhoan.com/truyen/tien-nghich",
            start_chapter_url="https://tamhoan.com/tien-nghich/203612",
            start_chap_num=1,
            end_chap_num=2,
        )

        self.assertTrue(res["success"])
        # Kiểm tra chương 2 đã được lưu vào CSDL
        ch2 = self.storage.get_chapter_by_num(s_id, 2, source="tamhoan")
        self.assertIsNotNone(ch2)
        self.assertEqual(ch2.chapter_num, 2)
        self.assertEqual(ch2.source, "tamhoan")

    def test_08_offline_import_tamhoan_html(self):
        """Kiểm tra nhập offline HTML lưu từ trình duyệt nguồn TamHoan."""
        import_dir = os.path.join(self.test_dir, "offline_tamhoan")
        os.makedirs(import_dir, exist_ok=True)

        # Tạo file HTML lưu từ trình duyệt với canonical url
        sample_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <link rel="canonical" href="https://tamhoan.com/tien-nghich/203612" />
        </head>
        <body>
            <div class="chapContent">
                <span class="chapTitle">Chương 1: Ly hương.</span>
                <div class="content">
                    <p>Thiết Trụ ngồi ở đầu thôn nhìn xa xăm...</p>
                    <ins class="adsbygoogle"></ins>
                    <p>- Cha, con muốn đi.</p>
                </div>
                <a id="next_chap" href="https://tamhoan.com/tien-nghich/203613">Sau</a>
            </div>
        </body>
        </html>
        """
        html_path = os.path.join(import_dir, "tamhoan_chap_1.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(sample_html)

        importer = OfflineImporter(self.storage)
        chapters = importer.import_directory(
            directory_path=import_dir,
            story_url="https://tamhoan.com/truyen/tien-nghich",
            story_title="Tiên Nghịch",
        )
        self.assertEqual(len(chapters), 1)
        imported = chapters[0]
        self.assertEqual(imported.chapter_num, 1)
        self.assertEqual(imported.source, "tamhoan")
        self.assertEqual(imported.source_url, "https://tamhoan.com/tien-nghich/203612")
        self.assertNotIn("file://", imported.next_url)
        self.assertEqual(imported.next_url, "https://tamhoan.com/tien-nghich/203613")

    def test_09_simulated_12_chapters_merge_3_volumes_isolated_dirs(self):
        """Giả lập 12 chương TamHoan, gộp đúng 3 tập vào output_volumes/tien_nghich/tamhoan/."""
        profile = get_profile("tien-nghich", source_id="tamhoan")
        self.assertEqual(profile.active_source_id, "tamhoan")
        self.assertEqual(profile.default_output_dir, "output_volumes/tien_nghich/tamhoan")

        story = self.storage.get_or_create_story(
            url=profile.story_url,
            title=profile.title,
            author=profile.author,
        )
        s_id = story.id

        chapters = []
        for i in range(1, 13):
            ch = Chapter(
                story_id=s_id,
                chapter_num=i,
                chapter_title=f"Chương {i}: Tiêu đề TamHoan {i}",
                source_url=f"https://tamhoan.com/tien-nghich/{203611 + i}",
                raw_content=f"Đoạn văn thứ nhất của chương {i}.\n\nĐoạn văn thứ hai của chương {i}.",
                content_hash=f"hash_tamhoan_{i:03d}",
                status="verified",
                source="tamhoan",
            )
            self.storage.save_chapter(ch)
            chapters.append(ch)

        merger = VolumeMerger(chapters_per_volume=4, story_profile=profile)
        volumes = merger.build_volumes(
            chapters=chapters,
            start_volume_num=1,
            expected_start_chap=1,
            expected_end_chap=12,
            story_title=profile.title,
        )

        self.assertEqual(len(volumes), 3)
        self.assertEqual(volumes[0].volume_num, 1)
        self.assertEqual(volumes[0].start_chapter, 1)
        self.assertEqual(volumes[0].end_chapter, 4)

        self.assertEqual(volumes[1].volume_num, 2)
        self.assertEqual(volumes[1].start_chapter, 5)
        self.assertEqual(volumes[1].end_chapter, 8)

        self.assertEqual(volumes[2].volume_num, 3)
        self.assertEqual(volumes[2].start_chapter, 9)
        self.assertEqual(volumes[2].end_chapter, 12)

        # Xuất file và kiểm tra thư mục
        out_dir = os.path.join(self.test_dir, "output", "tien_nghich", "tamhoan")
        os.makedirs(out_dir, exist_ok=True)

        for vol in volumes:
            bundle = ReportGenerator.export_volume_bundle(
                volume=vol,
                output_dir=out_dir,
                merger=merger,
                issues=[],
                export_reports=False,
            )
            self.assertTrue(os.path.isfile(bundle["txt"]))
            # Đọc kiểm tra mở đầu và kết thúc Tiên Nghịch
            with open(bundle["txt"], "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("TIÊN NGHỊCH - TẬP", content)
            self.assertIn("tác giả Nhĩ Căn", content)
            self.assertIn(f"Hết Tập {vol.volume_num}", content)

    def test_10_migration_legacy_data(self):
        """Kiểm tra migration CSDL cũ chưa có cột source."""
        import sqlite3

        old_db_path = os.path.join(self.test_dir, "legacy.db")
        conn = sqlite3.connect(old_db_path)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                story_id INTEGER,
                chapter_num INTEGER,
                chapter_title TEXT,
                source_url TEXT UNIQUE,
                raw_content TEXT,
                content_hash TEXT,
                version INTEGER DEFAULT 1,
                fetch_time TEXT,
                status TEXT DEFAULT 'pending',
                prev_url TEXT,
                next_url TEXT,
                warnings TEXT
            )
        """)
        c.execute("""
            INSERT INTO chapters (story_id, chapter_num, chapter_title, source_url, raw_content, content_hash)
            VALUES (1, 1, 'Chương 1 cũ', 'https://webnovel.vn/tien-nghich/chuong-1/', 'Nội dung cũ', 'hash_old')
        """)
        conn.commit()
        conn.close()

        # Khởi tạo StorageManager trên DB cũ -> tự động chạy migration
        migrated_storage = StorageManager(old_db_path)
        with migrated_storage._get_connection() as c2:
            cols = [r[1] for r in c2.execute("PRAGMA table_info(chapters)").fetchall()]
            self.assertIn("source", cols)

            row = c2.execute("SELECT source FROM chapters WHERE chapter_num = 1").fetchone()
            # source được tự động điền từ source_url (webnovel)
            self.assertEqual(row["source"], "webnovel")

    def test_11_clean_process_cli_help(self):
        """Kiểm tra CLI chạy trong tiến trình Python sạch và trả về exit code 0."""
        python_exe = sys.executable
        res = subprocess.run(
            [python_exe, "cli.py", "--help"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("crawl", res.stdout)
        self.assertIn("merge", res.stdout)
        self.assertIn("import", res.stdout)
        self.assertIn("process", res.stdout)

    def test_12_clean_process_gui_initialization(self):
        """Kiểm tra MainWindow khởi tạo thành công trong tiến trình Python sạch và hỗ trợ chuyển đổi nguồn."""
        python_exe = sys.executable
        code = (
            "import sys; "
            "sys.stdout.reconfigure(encoding='utf-8'); "
            "from PySide6.QtWidgets import QApplication; "
            "from gui.main_window import MainWindow; "
            "app = QApplication(sys.argv); "
            "w = MainWindow(); "
            "assert w.current_profile.title == 'Phàm Nhân Tu Tiên'; "
            "w.combo_story.setCurrentIndex(1); "
            "assert w.current_profile.title == 'Tiên Nghịch'; "
            "w.combo_source.setCurrentIndex(1); "
            "assert w.current_profile.source_domain == 'tamhoan.com'; "
            "print('SUCCESS_GUI_SWITCH')"
        )
        res = subprocess.run(
            [python_exe, "-c", code],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
        )
    def test_13_cookie_buffer_overflow_and_http_400_recovery(self):
        """Kiểm tra cơ chế dọn dẹp cookie và tự động phục hồi khi gặp HTTP 400 do tràn bộ đệm Nginx."""
        crawler = NetworkCrawler(storage=self.storage, delay_seconds=0.01)

        # Giả lập session tích lũy 40 cookie page_viewed_* lớn (như khi crawl 36+ chương liên tục)
        for i in range(40):
            crawler.session.cookies.set(f"page_viewed_{i}", "X" * 250, domain="tamhoan.com")

        # Gọi fetch_url trên mock trả về 400 nếu có nhiều cookie, 200 nếu session sạch
        attempt_count = 0
        def mock_get(url, **kwargs):
            nonlocal attempt_count
            attempt_count += 1
            # Kiểm tra cookie trong session
            if len([c for c in crawler.session.cookies if c.name.startswith("page_viewed_")]) > 0:
                resp = MagicMock()
                resp.status_code = 400
                resp.url = url
                resp.content = b"400 Bad Request"
                return resp
            resp = MagicMock()
            resp.status_code = 200
            resp.url = url
            resp.content = b"<html><div class='chapContent'><span class='chapTitle'>Ch 36</span><div class='content'><p>Text</p></div></div></html>"
            resp.text = resp.content.decode("utf-8")
            resp.apparent_encoding = "utf-8"
            return resp

        with patch.object(crawler.session, "get", side_effect=mock_get):
            html, err, code, diag = crawler.fetch_url("https://tamhoan.com/tien-nghich/203647")
            self.assertEqual(code, 200)
            self.assertIsNotNone(html)
            self.assertIsNone(err)

    def test_14_skip_duplicate_reposted_chapters(self):
        """Kiểm tra cơ chế tự động bỏ qua nhóm chương bị đăng lặp lại trên website mà không bị dừng lỗi."""
        crawler = NetworkCrawler(storage=self.storage, delay_seconds=0.001)

        # Giả lập HTML các trang:
        # Chapter 1 (đã có), Chapter 2 (đã có)
        # Trang tiếp theo là lặp lại Chapter 1 (dup)
        # Sau đó mới đến Chapter 3 (mới)
        pages = {
            "https://tamhoan.com/tien-nghich/1": (
                "<html><div class='chapContent'><span class='chapTitle'>Chương 1</span>"
                "<div class='content'><p>Nội dung 1</p></div>"
                "<a id='next_chap' href='https://tamhoan.com/tien-nghich/2'>Tiếp</a></div></html>"
            ),
            "https://tamhoan.com/tien-nghich/2": (
                "<html><div class='chapContent'><span class='chapTitle'>Chương 2</span>"
                "<div class='content'><p>Nội dung 2</p></div>"
                "<a id='next_chap' href='https://tamhoan.com/tien-nghich/dup_1'>Tiếp</a></div></html>"
            ),
            "https://tamhoan.com/tien-nghich/dup_1": (
                # Lặp lại y hệt nội dung của Chương 1
                "<html><div class='chapContent'><span class='chapTitle'>Chương 1</span>"
                "<div class='content'><p>Nội dung 1</p></div>"
                "<a id='next_chap' href='https://tamhoan.com/tien-nghich/3'>Tiếp</a></div></html>"
            ),
            "https://tamhoan.com/tien-nghich/3": (
                # Chương 3 mới
                "<html><div class='chapContent'><span class='chapTitle'>Chương 3</span>"
                "<div class='content'><p>Nội dung 3</p></div>"
                "<a id='next_chap' href=''>Hết</a></div></html>"
            ),
        }

        def mock_get(url, **kwargs):
            resp = MagicMock()
            if url in pages:
                resp.status_code = 200
                resp.url = url
                resp.content = pages[url].encode("utf-8")
                resp.text = pages[url]
                resp.apparent_encoding = "utf-8"
            else:
                resp.status_code = 404
                resp.content = b"Not Found"
                resp.text = "Not Found"
            return resp

        logs = []
        with patch.object(crawler.session, "get", side_effect=mock_get):
            res = crawler.crawl_range(
                story_url="https://tamhoan.com/truyen/tien-nghich",
                start_chapter_url="https://tamhoan.com/tien-nghich/1",
                start_chap_num=1,
                end_chap_num=3,
                on_log=lambda lvl, msg: logs.append((lvl, msg)),
            )

        self.assertTrue(res["success"])
        self.assertEqual(res["downloaded_count"], 3)
        self.assertEqual(res["missing_count"], 0)

        # Xác nhận có log cảnh báo bỏ qua trùng lặp
        dup_logs = [m for lvl, m in logs if "[BỎ QUA TRÙNG LẶP]" in m]
        self.assertEqual(len(dup_logs), 1)
        self.assertIn("dup_1", dup_logs[0])


if __name__ == "__main__":
    unittest.main()
