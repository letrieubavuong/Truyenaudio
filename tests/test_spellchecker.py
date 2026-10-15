"""
Unit and integration tests for VietnameseSpellChecker.
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.parser import SourceParser
from core.spellchecker import VietnameseSpellChecker


class TestVietnameseSpellChecker(unittest.TestCase):
    def setUp(self):
        self.checker = VietnameseSpellChecker(
            dictionary_path="resources/default_dictionary.json",
            protected_terms_path="resources/protected_terms.json",
        )

    def test_clean_underscores(self):
        text = '"Anh ngố" _ _ _ _ trợn trừng hai mắt'
        edited, issues = self.checker.check_paragraph(text, paragraph_idx=0)
        self.assertNotIn("_", edited)
        self.assertIn('"Anh ngố" trợn trừng hai mắt', edited)

    def test_clean_wrapped_underscores(self):
        text = 'ban cho hỗn danh _"anh ngố" _ là vì'
        edited, issues = self.checker.check_paragraph(text, paragraph_idx=0)
        self.assertNotIn("_", edited)
        self.assertIn('"anh ngố"', edited)

    def test_clean_star(self):
        text = 'thật nhiều hồng tương quả*, loại quả mà muội muội hắn thích nhất.'
        edited, issues = self.checker.check_paragraph(text, paragraph_idx=0)
        self.assertNotIn("*", edited)
        self.assertIn('hồng tương quả', edited)

    def test_dictionary_replacement(self):
        text = 'nhìn không còn ra hình dạng ban đâu, phảng phất có nguời đi tới.'
        edited, issues = self.checker.check_paragraph(text, paragraph_idx=0)
        self.assertIn('ban đầu', edited)
        self.assertIn('người', edited)

    def test_punctuation_spacing(self):
        text = 'Cách giường chừng nửa trượng ,là một vách tường đất .Từ những vết nứt đó'
        edited, issues = self.checker.check_paragraph(text, paragraph_idx=0)
        self.assertIn('nửa trượng, là', edited)
        self.assertIn('vách tường đất. Từ', edited)

    def test_protected_terms(self):
        text = 'Hàn Lập tham gia Thất Huyền Môn tại Thái Hà Sơn.'
        edited, issues = self.checker.check_paragraph(text, paragraph_idx=0)
        self.assertIn('Hàn Lập', edited)
        self.assertIn('Thất Huyền Môn', edited)
        self.assertIn('Thái Hà Sơn', edited)

    def test_duplicate_sentences(self):
        text = 'Đây là một câu rất quan trọng trong truyện. Đây là một câu rất quan trọng trong truyện. Tiếp theo là đoạn sau.'
        edited, issues = self.checker.check_paragraph(text, paragraph_idx=0)
        # Chỉ còn 1 câu
        count = edited.count('Đây là một câu rất quan trọng trong truyện.')
        self.assertEqual(count, 1)

    def test_real_chapter_1(self):
        html_path = "data/sample_chapters/chuong_1.html"
        if os.path.exists(html_path):
            with open(html_path, "r", encoding="utf-8") as f:
                parsed = SourceParser.parse_chapter_html(f.read())
            edited_paras, issues = self.checker.check_chapter(
                parsed["paragraphs"], chapter_num=1, chapter_title=parsed["chapter_title"]
            )
            self.assertGreater(len(issues), 0)
            self.assertEqual(len(edited_paras), len(parsed["paragraphs"]))
            print(f"\n[Test Real Chapter 1] Total issues detected: {len(issues)}")
            cat_counts = {}
            for iss in issues:
                cat_counts[iss.category] = cat_counts.get(iss.category, 0) + 1
            print(f"[Test Real Chapter 1] Categories: {cat_counts}")


if __name__ == "__main__":
    unittest.main()
