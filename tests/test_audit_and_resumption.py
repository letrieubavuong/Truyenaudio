"""
Comprehensive tests for audit trail synchronization, crawler resumption,
error classifications, multi-story review isolation, database migration,
and audio volume format compliance.
"""
import os
import sys
import sqlite3
import tempfile
import shutil
import unittest
import unicodedata
import subprocess
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.models import Chapter, Volume, SpellIssue
from core.storage import StorageManager
from core.crawler import NetworkCrawler, SourceParser
from core.spellchecker import VietnameseSpellChecker
from core.merger import VolumeMerger, normalize_trailing_spaces, is_separator_or_inserted_title
from core.reporter import ReportGenerator


class TestAuditAndResumption(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_state.db")
        self.storage = StorageManager(self.db_path)
        self.checker = VietnameseSpellChecker()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # =========================================================================
    # 1. KIỂM TRA KHỞI ĐỘNG (CLI & GUI)
    # =========================================================================
    def test_startup_imports_and_cli_help(self):
        """1. Kiểm tra import core.crawler thành công và cli.py --help chạy exit code 0."""
        # Import core.crawler
        import core.crawler
        self.assertTrue(hasattr(core.crawler, "NetworkCrawler"))
        self.assertTrue(hasattr(core.crawler, "SourceParser"))

        # python cli.py --help
        res = subprocess.run(
            [sys.executable, "cli.py", "--help"],
            cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(res.returncode, 0, f"cli.py --help failed: {res.stderr}")
        self.assertIn("usage:", res.stdout.lower())

    def test_startup_pyside6_gui_instantiation(self):
        """1b. Kiểm tra GUI khởi động được trong môi trường có PySide6 (offscreen)."""
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtWidgets import QApplication
        from gui.main_window import MainWindow

        app = QApplication.instance()
        if not app:
            app = QApplication(sys.argv)

        window = MainWindow()
        self.assertIsNotNone(window)
        self.assertIn("Phàm Nhân Tu Tiên", window.windowTitle())
        window.close()

    # =========================================================================
    # 2. TẢI ĐỦ 12 CHƯƠNG GIẢ LẬP, GỘP THÀNH 3 TẬP
    # =========================================================================
    def test_mock_12_chapters_merged_into_3_volumes(self):
        """2. Tải đủ 12 chương giả lập qua crawler và gộp thành đúng 3 tập (4 chương/tập)."""
        story = self.storage.get_or_create_story("https://test.com/truyen", "Truyện Test")

        def mock_fetch(url, *args, **kwargs):
            chap_num = int(url.split("c-")[-1])
            next_link = f"https://test.com/c-{chap_num + 1}" if chap_num < 12 else ""
            html = f"""
            <html>
                <span class="current-chapter">Chương {chap_num}: Tiêu đề {chap_num}</span>
                <div class="truyen">
                    <p>Đoạn 1 chương {chap_num}.</p>
                    <p>Đoạn 2 chương {chap_num}.</p>
                </div>
                <script>var nextChap = "{next_link}";</script>
            </html>
            """
            return html, None, 200, {"final_url": url, "redirected": False}

        crawler = NetworkCrawler(storage=self.storage, delay_seconds=0.0)
        with patch.object(crawler, "fetch_url", side_effect=mock_fetch):
            res = crawler.crawl_range(
                story_url="https://test.com/truyen",
                start_chapter_url="https://test.com/c-1",
                start_chap_num=1,
                end_chap_num=12,
            )

        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["fetched_count"], 12)
        self.assertEqual(res["downloaded_count"], 12)
        self.assertEqual(res["missing_count"], 0)

        # Gộp thành các tập Volume
        chapters = self.storage.get_chapters_range(story.id, 1, 12)
        merger = VolumeMerger(chapters_per_volume=4)
        volumes = merger.build_volumes(chapters, start_volume_num=1, expected_start_chap=1, expected_end_chap=12)

        self.assertEqual(len(volumes), 3)
        self.assertEqual((volumes[0].start_chapter, volumes[0].end_chapter), (1, 4))
        self.assertEqual((volumes[1].start_chapter, volumes[1].end_chapter), (5, 8))
        self.assertEqual((volumes[2].start_chapter, volumes[2].end_chapter), (9, 12))
        for v in volumes:
            self.assertFalse(v.is_draft)

    # =========================================================================
    # 3. RESUMPTION KHI CHƯƠNG 4 THIẾU NEXT_URL -> TẢI LẠI TRANG TIẾP TỤC ĐẾN 12
    # =========================================================================
    def test_resume_when_cached_chapter_lacks_next_url(self):
        """3. Cache chương 1-4, chương 4 thiếu next_url: tải lại trang lấy điều hướng rồi tiếp tục đến 12."""
        story = self.storage.get_or_create_story("https://test.com/truyen", "Truyện Test")

        # Lưu sẵn chương 1-3 có next_url
        for n in range(1, 4):
            self.storage.save_chapter(
                Chapter(
                    story_id=story.id,
                    chapter_num=n,
                    chapter_title=f"Chương {n}",
                    source_url=f"https://test.com/c-{n}",
                    raw_content=f"Nội dung chương {n}",
                    content_hash=f"hash_{n}",
                    next_url=f"https://test.com/c-{n+1}",
                    status="verified",
                )
            )

        # Chương 4 trong CSDL THIẾU next_url
        chap4 = Chapter(
            story_id=story.id,
            chapter_num=4,
            chapter_title="Chương 4",
            source_url="https://test.com/c-4",
            raw_content="Nội dung gốc bất biến của chương 4",
            content_hash="hash_4_orig",
            next_url="",  # Thiếu liên kết tiếp
            status="verified",
        )
        self.storage.save_chapter(chap4)

        # Mock tải lại trang chương 4 trả về next_url = https://test.com/c-5, và các chương 5-12
        def mock_fetch(url, *args, **kwargs):
            chap_num = int(url.split("c-")[-1])
            next_link = f"https://test.com/c-{chap_num + 1}" if chap_num < 12 else ""
            html = f"""
            <html>
                <span class="current-chapter">Chương {chap_num}</span>
                <div class="truyen"><p>Nội dung tải mới chương {chap_num}</p></div>
                <script>var nextChap = "{next_link}";</script>
            </html>
            """
            return html, None, 200, {"final_url": url, "redirected": False}

        crawler = NetworkCrawler(storage=self.storage, delay_seconds=0.0)
        with patch.object(crawler, "fetch_url", side_effect=mock_fetch):
            res = crawler.crawl_range(
                story_url="https://test.com/truyen",
                start_chapter_url="https://test.com/c-1",
                start_chap_num=1,
                end_chap_num=12,
            )

        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["cached_count"], 4)
        self.assertEqual(res["downloaded_count"], 8)
        self.assertEqual(res["missing_count"], 0)

        # Bản gốc chương 4 vẫn được giữ nguyên
        saved_c4 = self.storage.get_chapter_by_num(story.id, 4)
        self.assertEqual(saved_c4.raw_content, "Nội dung gốc bất biến của chương 4")
        # Nhưng next_url đã được khôi phục thành công
        self.assertEqual(saved_c4.next_url, "https://test.com/c-5")

        # Toàn bộ 12 chương đã có trong CSDL
        all_chaps = self.storage.get_chapters_range(story.id, 1, 12)
        self.assertEqual(len(all_chaps), 12)

    # =========================================================================
    # 4. KHÔNG TÌM THẤY CHƯƠNG TIẾP: TRẢ VỀ TRẠNG THÁI CHƯA HOÀN THÀNH
    # =========================================================================
    def test_missing_next_url_returns_incomplete_status(self):
        """4. Không tìm thấy chương kế tiếp -> dừng và trả về status='incomplete' kèm lý do."""
        story = self.storage.get_or_create_story("https://test.com/truyen", "Truyện Test")

        # Lưu chương 1-4, chương 4 thiếu next_url
        for n in range(1, 4):
            self.storage.save_chapter(
                Chapter(
                    story_id=story.id,
                    chapter_num=n,
                    source_url=f"https://test.com/c-{n}",
                    raw_content=f"C{n}",
                    next_url=f"https://test.com/c-{n+1}",
                    status="verified",
                )
            )
        self.storage.save_chapter(
            Chapter(
                story_id=story.id,
                chapter_num=4,
                source_url="https://test.com/c-4",
                raw_content="C4",
                next_url="",
                status="verified",
            )
        )

        # Mock tải lại trang chương 4 nhưng trang web không có link chương tiếp
        def mock_fetch(url, *args, **kwargs):
            html = "<html><div class='truyen'><p>C4</p></div><!-- Không có next link --></html>"
            return html, None, 200, {"final_url": url, "redirected": False}

        crawler = NetworkCrawler(storage=self.storage, delay_seconds=0.0)
        with patch.object(crawler, "fetch_url", side_effect=mock_fetch):
            res = crawler.crawl_range(
                story_url="https://test.com/truyen",
                start_chapter_url="https://test.com/c-1",
                start_chap_num=1,
                end_chap_num=12,
            )

        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "incomplete")
        self.assertEqual(res["fetched_count"], 4)
        self.assertEqual(res["missing_count"], 8)
        self.assertIn("Không tìm thấy liên kết chương tiếp theo", res["stop_reason"])

    # =========================================================================
    # 5. XỬ LÝ LỖI MẠNG, 403, 429, TIMEOUT, TRANG RỖNG, VÀ URL LẶP
    # =========================================================================
    def test_crawler_error_conditions(self):
        """5. Kiểm tra phân loại chính xác các lỗi: 403, 429, timeout, trang rỗng, URL lặp."""
        # 5a. HTTP 403 Bị chặn
        crawler = NetworkCrawler(storage=self.storage, delay_seconds=0.0)
        with patch.object(crawler, "fetch_url", return_value=(None, "Forbidden", 403, {"final_url": "https://test.com/c-1"})):
            res_403 = crawler.crawl_range("https://test.com", "https://test.com/c-1", 1, 5)
            self.assertFalse(res_403["success"])
            self.assertEqual(res_403["status"], "blocked")
            self.assertIn("403", res_403["stop_reason"])

        # 5b. HTTP 429 Giới hạn tần suất
        with patch.object(crawler, "fetch_url", return_value=(None, "Too Many Requests", 429, {"final_url": "https://test.com/c-1"})):
            res_429 = crawler.crawl_range("https://test.com", "https://test.com/c-1", 1, 5)
            self.assertFalse(res_429["success"])
            self.assertEqual(res_429["status"], "blocked")
            self.assertIn("429", res_429["stop_reason"])

        # 5c. Timeout / Network error
        with patch.object(crawler, "fetch_url", return_value=(None, "Connection timed out", 0, {})):
            res_timeout = crawler.crawl_range("https://test.com", "https://test.com/c-1", 1, 5)
            self.assertFalse(res_timeout["success"])
            self.assertEqual(res_timeout["status"], "network_error")
            self.assertIn("kết nối mạng", res_timeout["stop_reason"].lower())

        # 5d. Trang rỗng không được đánh dấu verified
        empty_html = "<html><body><div>Không có nội dung chương nào</div></body></html>"
        with patch.object(crawler, "fetch_url", return_value=(empty_html, None, 200, {"final_url": "https://test.com/c-1"})):
            res_empty = crawler.crawl_range("https://test.com", "https://test.com/c-1", 1, 5)
            self.assertFalse(res_empty["success"])
            self.assertEqual(res_empty["status"], "parse_error")
            chaps = self.storage.get_all_chapters()
            if chaps:
                self.assertNotEqual(chaps[0].status, "verified")

        # 5e. URL lặp (vòng lặp điều hướng)
        loop_html = "<html><div class='truyen'><p>Nội dung</p></div><script>var nextChap = 'https://test.com/c-1';</script></html>"
        with patch.object(crawler, "fetch_url", return_value=(loop_html, None, 200, {"final_url": "https://test.com/c-1"})):
            res_loop = crawler.crawl_range("https://test.com", "https://test.com/c-1", 1, 5)
            self.assertFalse(res_loop["success"])
            self.assertIn("vòng lặp", res_loop["stop_reason"].lower())

    # =========================================================================
    # 6. ĐỀ XUẤT CHỒNG LẤN: SỐ ĐÃ SỬA KHỚP THAY ĐỔI THỰC TẾ
    # =========================================================================
    def test_overlapping_proposals_audit_accuracy(self):
        """6. Hai đề xuất chồng lấn: giải quyết xung đột, số đã sửa khớp chính xác thay đổi thực tế."""
        raw_text = "Hắn nhìn thấy nguời kia."
        norm_text = unicodedata.normalize("NFC", raw_text)
        import hashlib
        para_hash = hashlib.sha256(norm_text.encode("utf-8")).hexdigest()[:16]

        s1 = norm_text.find("nguời")
        e1 = s1 + len("nguời")

        s2 = norm_text.find("thấy nguời kia")
        e2 = s2 + len("thấy nguời kia")

        # Đề xuất 1: Dictionary sửa "nguời" -> "người" (priority 3)
        dict_iss = SpellIssue(
            id="iss_dict_1",
            original_hash=para_hash,
            paragraph_idx=0,
            char_start=s1,
            char_end=e1,
            original="nguời",
            replacement="người",
            category="chinh_ta",
            source="dictionary",
            status="applied",
        )

        # Đề xuất 2: Rule sửa cụm "thấy nguời kia" -> "thấy người đó" (priority 2, chồng lấn)
        rule_iss = SpellIssue(
            id="iss_rule_1",
            original_hash=para_hash,
            paragraph_idx=0,
            char_start=s2,
            char_end=e2,
            original="thấy nguời kia",
            replacement="thấy người đó",
            category="chinh_ta",
            source="rule",
            status="applied",
        )

        edited_text, resolved = VietnameseSpellChecker.apply_fixes_with_audit(
            raw_text, [dict_iss, rule_iss], approved_only=True
        )

        # Kiểm tra văn bản chỉ áp dụng đề xuất từ điển ưu tiên hơn
        self.assertEqual(edited_text, "Hắn nhìn thấy người kia.")

        # Đề xuất từ điển: applied
        self.assertEqual(dict_iss.applied_status, "applied")
        self.assertEqual(dict_iss.status, "applied")

        # Đề xuất rule: skipped_conflict
        self.assertEqual(rule_iss.applied_status, "skipped_conflict")
        self.assertEqual(rule_iss.status, "skipped_conflict")
        self.assertIn("Xung đột", rule_iss.applied_reason)

        # Kiểm tra tính toán thống kê
        stats = ReportGenerator.calculate_statistics([dict_iss, rule_iss])
        self.assertEqual(stats["total_suggestions"], 2)
        self.assertEqual(stats["applied"], 1)  # Chỉ đúng 1 thay đổi được áp dụng!
        self.assertEqual(stats["skipped"], 1)

    # =========================================================================
    # 7. ĐỀ XUẤT KHÔNG KHỚP VĂN BẢN/HASH: KHÔNG ÁP DỤNG VÀ BÁO RÕ
    # =========================================================================
    def test_mismatch_hash_and_slice_skipped(self):
        """7. Đề xuất sai lệch hash hoặc sai lệch văn bản lát cắt: bỏ qua an toàn và gán skipped_mismatch."""
        raw_text = "Văn bản hiện tại đã được chỉnh sửa khác bản gốc."

        # Issue 1: Hash không khớp
        iss_bad_hash = SpellIssue(
            id="iss_bad_h",
            original_hash="hash_khac_hoan_toan",
            char_start=0,
            char_end=8,
            original="Văn bản",
            replacement="Bài viết",
            status="applied",
        )

        # Issue 2: Lát cắt không khớp nội dung
        iss_bad_slice = SpellIssue(
            id="iss_bad_s",
            char_start=0,
            char_end=7,
            original="Đoạn văn",  # Thực tế tại [0:7] là "Văn bản"
            replacement="Đoạn trích",
            status="applied",
        )

        edited, resolved = VietnameseSpellChecker.apply_fixes_with_audit(
            raw_text, [iss_bad_hash, iss_bad_slice], approved_only=True
        )

        # Văn bản không bị thay đổi
        self.assertEqual(edited, raw_text)

        self.assertEqual(iss_bad_hash.applied_status, "skipped_mismatch")
        self.assertIn("Hash nội dung không khớp", iss_bad_hash.applied_reason)

        self.assertEqual(iss_bad_slice.applied_status, "skipped_mismatch")
        self.assertIn("không khớp với", iss_bad_slice.applied_reason)

        stats = ReportGenerator.calculate_statistics([iss_bad_hash, iss_bad_slice])
        self.assertEqual(stats["applied"], 0)
        self.assertEqual(stats["skipped"], 2)

    # =========================================================================
    # 8. XỬ LÝ NHẤT QUÁN UNICODE NFC VÀ NFD
    # =========================================================================
    def test_unicode_nfc_and_nfd_handling(self):
        """8. Kiểm tra văn bản tiếng Việt tổ hợp (NFD) và dựng sẵn (NFC) không bị lệch chỉ số."""
        # Chuỗi gốc viết dạng NFD (tổ hợp ký tự dấu)
        nfd_raw = unicodedata.normalize("NFD", "Hắn là một nguời tốt.")
        self.assertNotEqual(nfd_raw, unicodedata.normalize("NFC", nfd_raw))

        # Phân tích bằng spellchecker
        edited, issues = self.checker.check_paragraph(nfd_raw, paragraph_idx=0)

        # Kết quả trả về phải là NFC
        self.assertEqual(edited, unicodedata.normalize("NFC", edited))
        self.assertIn("người", edited)

        # Thử áp dụng đề xuất trên chuỗi NFD
        nguoi_issues = [i for i in issues if "nguời" in i.original]
        self.assertTrue(len(nguoi_issues) > 0)
        re_applied = VietnameseSpellChecker.apply_fixes(nfd_raw, nguoi_issues, approved_only=True)
        self.assertIn("người", re_applied)

    # =========================================================================
    # 9. QUYẾT ĐỊNH DUYỆT KHÔNG LẪN GIỮA HAI TRUYỆN HOẶC HAI PHIÊN BẢN
    # =========================================================================
    def test_multi_story_and_version_review_decisions_isolation(self):
        """9. Hai truyện có cùng chương, đoạn, vị trí lỗi: quyết định duyệt không bị ghi đè hoặc lẫn lộn."""
        story_a = self.storage.get_or_create_story("https://test.com/truyen-a", "Truyện A")
        story_b = self.storage.get_or_create_story("https://test.com/truyen-b", "Truyện B")

        # Cả 2 truyện đều có issue id giống nhau ở chương 1 đoạn 0
        iss_a = SpellIssue(
            id="iss_c1_p0_0_5_dup",
            original_hash="hash_story_a",
            chapter_num=1,
            paragraph_idx=0,
            char_start=0,
            char_end=5,
            original="từ A",
            replacement="từ A sửa",
            status="applied",
            user_decision="approved",
        )

        iss_b = SpellIssue(
            id="iss_c1_p0_0_5_dup",
            original_hash="hash_story_b",
            chapter_num=1,
            paragraph_idx=0,
            char_start=0,
            char_end=5,
            original="từ B",
            replacement="từ B sửa",
            status="rejected",
            user_decision="rejected",
        )

        # Lưu quyết định cho từng truyện
        self.storage.save_review_decisions(story_id=story_a.id, issues=[iss_a])
        self.storage.save_review_decisions(story_id=story_b.id, issues=[iss_b])

        # Nạp lại quyết định của truyện A
        loaded_a = self.storage.get_review_decisions(story_id=story_a.id, content_hash="hash_story_a")
        self.assertEqual(loaded_a.get(iss_a.id), "applied")

        # Nạp lại quyết định của truyện B
        loaded_b = self.storage.get_review_decisions(story_id=story_b.id, content_hash="hash_story_b")
        self.assertEqual(loaded_b.get(iss_b.id), "rejected")

        # Hash khác không tải được quyết định cũ
        loaded_diff = self.storage.get_review_decisions(story_id=story_a.id, content_hash="hash_version_moi")
        self.assertEqual(len(loaded_diff), 0)

    # =========================================================================
    # 10. MIGRATION CSDL CŨ BẢO TOÀN DỮ LIỆU
    # =========================================================================
    def test_database_migration_from_legacy_schema(self):
        """10. Viết migration cho CSDL cũ, bảo toàn dữ liệu và đánh dấu legacy_unverified thận trọng."""
        legacy_db_path = os.path.join(self.temp_dir, "legacy.db")
        conn = sqlite3.connect(legacy_db_path)
        c = conn.cursor()
        # Tạo bảng CSDL cũ thiếu content_hash và có issue_id UNIQUE toàn cục
        c.execute("""
            CREATE TABLE review_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id TEXT UNIQUE,
                chapter_num INTEGER,
                paragraph_idx INTEGER,
                char_start INTEGER,
                char_end INTEGER,
                original TEXT,
                replacement TEXT,
                status TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            INSERT INTO review_decisions (issue_id, chapter_num, paragraph_idx, char_start, char_end, original, replacement, status)
            VALUES ('old_iss_1', 1, 0, 0, 5, 'cũ', 'mới', 'applied')
        """)
        conn.commit()
        conn.close()

        # Mở bằng StorageManager để kích hoạt migration
        migrated_storage = StorageManager(legacy_db_path)
        with migrated_storage._get_connection() as m_conn:
            m_c = m_conn.cursor()
            m_c.execute("PRAGMA table_info(review_decisions)")
            cols = [col["name"] for col in m_c.fetchall()]
            self.assertIn("content_hash", cols)
            self.assertIn("story_id", cols)

            m_c.execute("SELECT * FROM review_decisions WHERE issue_id = 'old_iss_1'")
            row = m_c.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["content_hash"], "legacy_unverified")
            self.assertEqual(row["status"], "applied")

        # Dữ liệu legacy_unverified không bị tự ý áp dụng khi truy vấn thông thường
        decisions = migrated_storage.get_review_decisions(story_id=1)
        self.assertNotIn("old_iss_1", decisions)

    # =========================================================================
    # 11. ĐỊNH DẠNG ĐẦU/CUỐI TẬP VÀ LOẠI BỎ TIÊU ĐỀ CHƯƠNG
    # =========================================================================
    def test_audio_format_and_title_separator_removal(self):
        """11. Kiểm tra định dạng đầu/cuối tập, loại bỏ đường phân cách và tiêu đề chương mà không xóa câu truyện."""
        # 11a. Helper kiểm tra tiêu đề và phân cách
        self.assertTrue(is_separator_or_inserted_title("------------------------------------------------------------"))
        self.assertTrue(is_separator_or_inserted_title("=============================="))
        self.assertTrue(is_separator_or_inserted_title("=== CHƯƠNG 4: LUYỆN CỐT NHAI ==="))
        self.assertTrue(is_separator_or_inserted_title("Chương 4: Luyện Cốt Nhai", chapter_num=4, chapter_title="Chương 4: Luyện Cốt Nhai"))
        self.assertTrue(is_separator_or_inserted_title("Chương 4", chapter_num=4))

        # Không xóa câu văn bình thường trong truyện dù có chứa từ "chương"
        self.assertFalse(is_separator_or_inserted_title("Chương này là bí mật lớn nhất của Thất Huyền Môn."))
        self.assertFalse(is_separator_or_inserted_title("Chương gia trang cách đây không xa."))
        self.assertFalse(is_separator_or_inserted_title("Hắn đọc đến chương 4 của quyển sách thì dừng lại."))

        # 11b. Render volume text
        chap = Chapter(
            chapter_num=4,
            chapter_title="Chương 4: Luyện Cốt Nhai",
            raw_content=(
                "------------------------------------------------------------\n"
                "=== CHƯƠNG 4: LUYỆN CỐT NHAI ===\n"
                "Chương này là bí mật lớn nhất của Thất Huyền Môn.\n"
                "Hắn tiếp tục tu luyện tại Luyện Cốt Nhai.\n"
                "------------------------------------------------------------"
            ),
            status="verified",
        )

        merger = VolumeMerger(chapters_per_volume=1, include_prologue=True, include_epilogue=True)
        vols = merger.build_volumes([chap], start_volume_num=1, expected_start_chap=4, expected_end_chap=4)
        rendered = merger.render_volume_text(vols[0])

        # Tiêu đề và phân cách chèn bị xóa
        self.assertNotIn("------------------------------------------------------------", rendered)
        self.assertNotIn("=== CHƯƠNG 4: LUYỆN CỐT NHAI ===", rendered)

        # Câu truyện chứa từ 'chương' vẫn được giữ nguyên vẹn
        self.assertIn("Chương này là bí mật lớn nhất của Thất Huyền Môn.", rendered)
        self.assertIn("Hắn tiếp tục tu luyện tại Luyện Cốt Nhai.", rendered)

        # Mẫu đầu file và cuối file
        self.assertIn("PHÀM NHÂN TU TIÊN - TẬP 1", rendered)
        self.assertIn("Đây là Tập 1, phát từ Chương 4 đến Chương 4.", rendered)
        self.assertIn("Hết Tập 1: Cảm ơn quý thính giả đã chú ý lắng nghe. Hẹn gặp lại các bạn trong Tập 2 tiếp theo!", rendered)

        # 11c. Chuẩn hóa khoảng trắng cuối dòng
        text_spaces = "Dòng 1   \r\nDòng 2 \rDòng 3\n\nDòng 4  \n"
        norm_spaces = normalize_trailing_spaces(text_spaces)
        self.assertNotIn("\r", norm_spaces)
        # Thực hiện đúng một lượt thay thế r"\s\n" -> "\n"
        self.assertIn("Dòng 2\n", norm_spaces)
        self.assertIn("Dòng 4 \n", norm_spaces)  # Ban đầu có 2 dấu cách, bớt 1 dấu cách còn 1 dấu cách


if __name__ == "__main__":
    unittest.main()
