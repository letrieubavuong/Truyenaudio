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
        # Theo yêu cầu an toàn, dấu sao cuối từ có thể là chú thích nên mặc định pending chờ duyệt
        star_issues = [i for i in issues if i.category == "dau_cau" and "*" in i.original]
        self.assertTrue(len(star_issues) > 0)
        self.assertEqual(star_issues[0].status, "pending")
        # Khi được duyệt (status='applied'), dấu sao được loại bỏ
        star_issues[0].status = "applied"
        approved_edited = self.checker.apply_fixes(text, issues, approved_only=True)
        self.assertNotIn("*", approved_edited)
        self.assertIn('hồng tương quả', approved_edited)

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
        # Mặc định đề xuất ở trạng thái pending để tránh xóa nhầm lời thoại cố ý lặp
        dup_issues = [i for i in issues if i.category == "lap_cau"]
        self.assertTrue(len(dup_issues) > 0)
        self.assertEqual(dup_issues[0].status, "pending")
        # Khi được duyệt (applied), câu trùng lặp được loại bỏ
        dup_issues[0].status = "applied"
        approved_edited = self.checker.apply_fixes(text, issues, approved_only=True)
        count = approved_edited.count('Đây là một câu rất quan trọng trong truyện.')
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
