"""
Unit tests for SourceParser.
"""
import unittest
import os
from core.parser import SourceParser


class TestSourceParser(unittest.TestCase):
    def test_parse_sample_html(self):
        sample_path = "data/sample_chapters/chuong_1.html"
        self.assertTrue(os.path.exists(sample_path))
        with open(sample_path, "r", encoding="utf-8") as f:
            html = f.read()

        parsed = SourceParser.parse_chapter_html(
            html, "https://vivutruyen.com/truyen/pham-nhan-tu-tien/chuong-1-son-bien-tieu-thon-103484"
        )
        self.assertEqual(parsed["story_title"], "Phàm Nhân Tu Tiên")
        self.assertEqual(parsed["chapter_num"], 1)
        self.assertIn("Sơn Biên Tiểu Thôn", parsed["chapter_title"])
        self.assertEqual(len(parsed["paragraphs"]), 37)
        self.assertIn("chuong-2", parsed["next_url"])
        self.assertTrue(len(parsed["content_hash"]) == 64)

    def test_parse_raw_text_file(self):
        sample_txt = (
            "Chương 1069: Đại Chiến Bắt Đầu\n\n"
            "Đoạn văn thứ nhất của chương truyện...\n\n"
            "Đoạn văn thứ hai của chương truyện."
        )
        parsed = SourceParser.parse_raw_text_file(sample_txt, "chuong_1069.txt")
        self.assertEqual(parsed["chapter_num"], 1069)
        self.assertEqual(parsed["chapter_title"], "Chương 1069: Đại Chiến Bắt Đầu")
        self.assertEqual(len(parsed["paragraphs"]), 2)
        self.assertTrue(len(parsed["content_hash"]) == 64)

    def test_blocked_detection(self):
        blocked_html = "<html><head><title>Just a moment...</title></head><body>cf-browser-verification</body></html>"
        parsed = SourceParser.parse_chapter_html(blocked_html)
        self.assertTrue(parsed.get("is_blocked"))


if __name__ == "__main__":
    unittest.main()
