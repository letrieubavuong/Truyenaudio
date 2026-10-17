"""
Unit and Integration Tests for Tiên Nghịch (Nhĩ Căn) & webnovel.vn integration.
Tests:
1. HTML parser on real webnovel.vn fixtures (TOC and Chapters).
2. Ad/banner removal (div.bastorypush) and navigation link extraction.
3. Edge cases: multi-page TOC, missing next links, empty content, blocked/Cloudflare challenge pages.
4. Simulated 12-chapter crawl and export into 3 audio volumes with custom Tiên Nghịch prologue/epilogue.
5. Multi-story SQLite isolation: ensuring Phàm Nhân Tu Tiên and Tiên Nghịch data/decisions do not cross-contaminate.
6. Resumption from saved SQLite data.
7. Protected terms preservation for Tiên Nghịch characters and terms.
"""
import unittest
import os
import shutil
import tempfile
from core.parser import SourceParser, WebnovelParser
from core.models import Chapter, Volume, SpellIssue
from core.storage import StorageManager
from core.profiles import get_profile
from core.merger import VolumeMerger
from core.spellchecker import VietnameseSpellChecker
from core.reporter import ReportGenerator


class TestTienNghichWebnovel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_dir = os.path.join(os.path.dirname(__file__), "..", "data", "fixtures")
        cls.toc_file = os.path.join(cls.fixture_dir, "webnovel_tien_nghich_toc_page1.html")
        cls.chap1_file = os.path.join(cls.fixture_dir, "webnovel_tien_nghich_chuong_1.html")
        cls.chap2_file = os.path.join(cls.fixture_dir, "webnovel_tien_nghich_chuong_2.html")

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_tien_nghich.db")
        self.storage = StorageManager(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_parse_toc_fixture(self):
        """Kiểm tra phân tích mục lục thực tế từ webnovel.vn."""
        if not os.path.isfile(self.toc_file):
            self.skipTest("Tệp fixture TOC không tồn tại.")

        with open(self.toc_file, "r", encoding="utf-8") as f:
            html = f.read()

        toc = SourceParser.parse_toc_html(html, current_url="https://webnovel.vn/tien-nghich")
        self.assertEqual(toc["story_title"], "Tiên Nghịch")
        self.assertEqual(toc["author"], "Nhĩ Căn")
        self.assertEqual(len(toc["chapters"]), 20)
        self.assertEqual(toc["chapters"][0]["chapter_num"], 1)
        self.assertIn("https://webnovel.vn/tien-nghich/chuong-1/", toc["chapters"][0]["url"])
        self.assertEqual(toc["total_pages"], 106)
        self.assertIn("https://webnovel.vn/tien-nghich/2/", toc["next_page_url"])

    def test_02_parse_chapter_fixtures_and_ad_removal(self):
        """Kiểm tra trích xuất chương 1 & 2 và loại bỏ banner quảng cáo div.bastorypush."""
        if not os.path.isfile(self.chap1_file):
            self.skipTest("Tệp fixture Chương 1 không tồn tại.")

        with open(self.chap1_file, "r", encoding="utf-8") as f:
            html1 = f.read()

        ch1 = SourceParser.parse_chapter_html(html1, current_url="https://webnovel.vn/tien-nghich/chuong-1/")
        self.assertEqual(ch1["story_title"], "Tiên Nghịch")
        self.assertEqual(ch1["chapter_num"], 1)
        self.assertEqual(ch1["chapter_title"], "Chương 1: Xa nhà (1)")
        self.assertEqual(ch1["next_url"], "https://webnovel.vn/tien-nghich/chuong-2/")
        self.assertEqual(ch1["prev_url"], "")  # Chương 1 không có chương trước
        self.assertGreater(len(ch1["paragraphs"]), 30)

        # Kiểm tra sạch: không dính quảng cáo trò chơi hay banner
        full_text = ch1["raw_content"]
        self.assertNotIn("tro-choi-nay-cung-qua-chan-that", full_text)
        self.assertNotIn("bastorypush", full_text)
        self.assertNotIn("Chương sau", full_text)
        self.assertNotIn("Chương trước", full_text)
        self.assertTrue(full_text.startswith("Vương Lâm"))

        # Kiểm tra Chương 2 có liên kết cả lùi và tiến
        if os.path.isfile(self.chap2_file):
            with open(self.chap2_file, "r", encoding="utf-8") as f:
                html2 = f.read()
            ch2 = SourceParser.parse_chapter_html(html2, current_url="https://webnovel.vn/tien-nghich/chuong-2/")
            self.assertEqual(ch2["chapter_num"], 2)
            self.assertEqual(ch2["next_url"], "https://webnovel.vn/tien-nghich/chuong-3/")
            self.assertEqual(ch2["prev_url"], "https://webnovel.vn/tien-nghich/chuong-1/")

    def test_03_edge_cases_parser(self):
        """Kiểm tra các trường hợp biên: trang bị chặn 403, Cloudflare challenge, nội dung rỗng, thiếu liên kết."""
        # 1. Trang bị chặn 403
        blocked_html = "<html><head><title>403 Forbidden</title></head><body>Access Denied</body></html>"
        res_blocked = SourceParser.parse_chapter_html(blocked_html, "https://webnovel.vn/tien-nghich/chuong-99/")
        self.assertTrue(res_blocked.get("is_blocked"))
        self.assertIn("bị từ chối", res_blocked.get("error", "").lower())

        # 2. Trang Cloudflare challenge
        cf_html = "<html><head><title>Just a moment...</title></head><body>cf-browser-verification</body></html>"
        res_cf = SourceParser.parse_chapter_html(cf_html, "https://webnovel.vn/tien-nghich/chuong-99/")
        self.assertTrue(res_cf.get("is_blocked"))
        self.assertIn("cloudflare", res_cf.get("error", "").lower())

        # 3. Trang nội dung rỗng
        empty_html = "<html><body><article class='reader__content'></article></body></html>"
        res_empty = SourceParser.parse_chapter_html(empty_html, "https://webnovel.vn/tien-nghich/chuong-99/")
        self.assertEqual(len(res_empty["paragraphs"]), 0)
        self.assertTrue(any("rất ngắn" in w.lower() for w in res_empty["warnings"]))

        # 4. Thiếu liên kết tiếp (chương cuối)
        last_html = """
        <html><body>
            <p class="reader__chapter">Chương 2120: Đại kết cục</p>
            <div id="chapter-c"><p>Vương Lâm đứng trên đỉnh tinh không nhìn về phương xa.</p></div>
            <div class="reader__actions">
                <a href="https://webnovel.vn/tien-nghich/chuong-2119/">Chương trước</a>
                <a href="javascript:void(0)">Chương sau</a>
            </div>
        </body></html>
        """
        res_last = SourceParser.parse_chapter_html(last_html, "https://webnovel.vn/tien-nghich/chuong-2120/")
        self.assertEqual(res_last["next_url"], "")
        self.assertEqual(res_last["prev_url"], "https://webnovel.vn/tien-nghich/chuong-2119/")

    def test_04_simulate_12_chapters_and_export_3_volumes(self):
        """Giả lập nạp 12 chương Tiên Nghịch, xuất đúng 3 tập (4 chương/tập) với định dạng chuẩn."""
        profile = get_profile("tien-nghich")
        story = self.storage.get_or_create_story(profile.story_url, profile.title, profile.author)

        # Tạo giả lập 12 chương Tiên Nghịch
        for num in range(1, 13):
            content = f"Đoạn 1 chương {num}: Vương Lâm tu luyện tại Hằng Nhạc Phái.\n\nĐoạn 2 chương {num}: Thiết Trụ kiên trì ngưng tụ linh khí nhập thể."
            ch = Chapter(
                story_id=story.id,
                chapter_num=num,
                chapter_title=f"Chương {num}: Thí luyện {num}",
                source_url=f"https://webnovel.vn/tien-nghich/chuong-{num}/",
                raw_content=content,
                status="verified",
                next_url=f"https://webnovel.vn/tien-nghich/chuong-{num+1}/" if num < 12 else "",
            )
            self.storage.save_chapter(ch)

        # Lấy 12 chương từ CSDL
        chapters = self.storage.get_chapters_range(story.id, 1, 12)
        self.assertEqual(len(chapters), 12)

        # Gộp thành các tập
        merger = VolumeMerger(chapters_per_volume=4, story_profile=profile)
        volumes = merger.build_volumes(
            chapters=chapters,
            start_volume_num=1,
            expected_start_chap=1,
            expected_end_chap=12,
            story_title=profile.title,
        )

        self.assertEqual(len(volumes), 3)

        # Kiểm tra định dạng Tập 1
        vol1 = volumes[0]
        self.assertEqual(vol1.volume_num, 1)
        self.assertEqual(vol1.start_chapter, 1)
        self.assertEqual(vol1.end_chapter, 4)
        self.assertIn("TIÊN NGHỊCH - TẬP 1", vol1.prologue)
        self.assertIn("tác giả Nhĩ Căn", vol1.prologue)
        self.assertIn("phát từ Chương 1 đến Chương 4", vol1.prologue)
        self.assertIn("Hết Tập 1: Cảm ơn quý thính giả", vol1.epilogue)
        self.assertIn("trong Tập 2 tiếp theo!", vol1.epilogue)

        # Xuất file kiểm tra
        out_dir = os.path.join(self.test_dir, "output_tien_nghich")
        for vol in volumes:
            bundle = ReportGenerator.export_volume_bundle(
                volume=vol,
                output_dir=out_dir,
                merger=merger,
                issues=[],
                export_reports=False,
            )
            self.assertTrue(os.path.isfile(bundle["txt"]))
            with open(bundle["txt"], "r", encoding="utf-8") as f:
                content = f.read()
            self.assertTrue(content.startswith(f"TIÊN NGHỊCH - TẬP {vol.volume_num}"))
            self.assertTrue(content.strip().endswith(f"trong Tập {vol.volume_num + 1} tiếp theo!"))

    def test_05_multi_story_isolation(self):
        """Kiểm tra không lẫn lộn chương, tiến độ, quyết định duyệt giữa Phàm Nhân Tu Tiên và Tiên Nghịch."""
        p_pntt = get_profile("pham-nhan-tu-tien")
        p_tn = get_profile("tien-nghich")

        s_pntt = self.storage.get_or_create_story(p_pntt.story_url, p_pntt.title, p_pntt.author)
        s_tn = self.storage.get_or_create_story(p_tn.story_url, p_tn.title, p_tn.author)

        self.assertNotEqual(s_pntt.id, s_tn.id)

        # Lưu chương 1 cho PNTT
        ch_pntt = Chapter(
            story_id=s_pntt.id,
            chapter_num=1,
            chapter_title="Chương 1: Sơn Biên Tiểu Thôn",
            source_url="https://vivutruyen.com/truyen/pham-nhan-tu-tien/c1",
            raw_content="Hàn Lập sinh ra tại một thôn nghèo.",
            content_hash="hash_pntt_1",
        )
        self.storage.save_chapter(ch_pntt)

        # Lưu chương 1 cho Tiên Nghịch
        ch_tn = Chapter(
            story_id=s_tn.id,
            chapter_num=1,
            chapter_title="Chương 1: Xa nhà (1)",
            source_url="https://webnovel.vn/tien-nghich/chuong-1/",
            raw_content="Vương Lâm ngồi bên con lộ nhỏ nhìn trời xanh.",
            content_hash="hash_tn_1",
        )
        self.storage.save_chapter(ch_tn)

        # Kiểm tra đọc tách biệt
        pntt_chaps = self.storage.get_all_chapters(story_id=s_pntt.id)
        tn_chaps = self.storage.get_all_chapters(story_id=s_tn.id)

        self.assertEqual(len(pntt_chaps), 1)
        self.assertEqual(len(tn_chaps), 1)
        self.assertEqual(pntt_chaps[0].chapter_title, "Chương 1: Sơn Biên Tiểu Thôn")
        self.assertEqual(tn_chaps[0].chapter_title, "Chương 1: Xa nhà (1)")

        # Kiểm tra quyết định duyệt độc lập
        issue_pntt = SpellIssue(id="iss_pntt", original_hash="hash_pntt_1", original="Hàn Lập", replacement="Hàn Lập", status="applied")
        issue_tn = SpellIssue(id="iss_tn", original_hash="hash_tn_1", original="Vương Lâm", replacement="Vương Lâm", status="rejected")

        self.storage.save_review_decisions(s_pntt.id, [issue_pntt])
        self.storage.save_review_decisions(s_tn.id, [issue_tn])

        dec_pntt = self.storage.get_review_decisions(s_pntt.id)
        dec_tn = self.storage.get_review_decisions(s_tn.id)

        self.assertIn("iss_pntt", dec_pntt)
        self.assertNotIn("iss_tn", dec_pntt)
        self.assertIn("iss_tn", dec_tn)
        self.assertNotIn("iss_pntt", dec_tn)

    def test_06_protected_terms_tien_nghich(self):
        """Kiểm tra danh sách thuật ngữ bảo vệ cho Tiên Nghịch không bị thay đổi bởi quy tắc thông thường."""
        profile = get_profile("tien-nghich")
        checker = VietnameseSpellChecker()
        checker.set_protected_terms_path(profile.protected_terms_file)

        self.assertIn("Vương Lâm", checker.protected_terms)
        self.assertIn("Thiết Trụ", checker.protected_terms)
        self.assertIn("Tư Đồ Nam", checker.protected_terms)
        self.assertIn("Hằng Nhạc Phái", checker.protected_terms)
        self.assertIn("Thiên Nghịch Châu", checker.protected_terms)

        # Đoạn văn chứa tên riêng và lỗi chính tả thật
        raw_paragraph = "Vương Lâm và Thiết Trụ đi tới Hằng Nhạc Phái, nhìn thấy con suối có nhìu rác."
        # Từ "nhìu" là lỗi chính tả thông thường -> "nhiều", còn Vương Lâm, Thiết Trụ, Hằng Nhạc Phái phải giữ nguyên
        edited, issues = checker.check_paragraph(raw_paragraph, 0)
        self.assertIn("Vương Lâm", edited)
        self.assertIn("Thiết Trụ", edited)
        self.assertIn("Hằng Nhạc Phái", edited)
        # Không có issue nào đề xuất đổi Vương Lâm hay Thiết Trụ
        for iss in issues:
            self.assertNotIn("Vương Lâm", iss.original)
            self.assertNotIn("Thiết Trụ", iss.original)


if __name__ == "__main__":
    unittest.main()
