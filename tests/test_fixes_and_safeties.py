"""
Comprehensive Regression Tests for Verified Fixes, Safety Constraints, and Invariants.
Validates:
1. Masked words with asterisks (c*m v** bụng) remain completely intact.
2. Correct text (Hắn chần chừ rồi giấu giếm chuyện ấy) produces 0 spurious dictionary errors.
3. Changelog is the single source of truth: 100% exact reconstruction of EDITED from RAW + changelog.
4. Rejection restores original raw text 100%.
5. AI proposals default to pending and only alter EDITED text when explicitly approved.
6. Repeated words in paragraph have precise char offsets without ambiguous .find().
7. Re-importing same URL with new content preserves immutable original and saves versioning.
8. Multi-story isolation: multiple stories in database never mix chapters.
9. Punctuation spacing (Cách giường ,là một vách tường) records all changes with exact positions.
10. Multi-meaning words: 'Bổng nhiên hắn phát hiện một cổ khí thế' proposes 'Bỗng nhiên' without corrupting 'cổ'.
11. Volume 268 format: chapters 1069-1072 with next volume 269.
12. Atomic bundle export with temporary files and overwrite protection.
13. Markdown table escaping: pipes and special characters do not break table structure.
14. Review decisions persistence across app restarts.
"""
import unittest
import os
import shutil
import tempfile
from core.models import Chapter, Volume, SpellIssue
from core.spellchecker import VietnameseSpellChecker
from core.ai_checker import AIChecker
from core.storage import StorageManager
from core.merger import VolumeMerger
from core.reporter import ReportGenerator, escape_md


class TestFixesAndSafeties(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_safeties.db")
        self.storage = StorageManager(self.db_path)
        self.checker = VietnameseSpellChecker(
            dictionary_path="resources/default_dictionary.json",
            protected_terms_path="resources/protected_terms.json",
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_masked_words_with_stars_preserved(self):
        """1. Từ bị che bằng dấu sao không bị hỏng: c*m v** bụng -> không tự thay đổi."""
        text = "Hắn liền thụ một c*m v** bụng đối phương, đau đớn lùi lại."
        edited, issues = self.checker.check_paragraph(text, paragraph_idx=0)
        self.assertIn("c*m v** bụng", edited)
        self.assertNotIn("cm", edited)
        # Không có bất kỳ issue nào sửa vào c*m hay v**
        star_modifications = [
            i for i in issues if "c*m" in i.original or "v**" in i.original
        ]
        self.assertEqual(len(star_modifications), 0)

    def test_correct_text_no_spurious_errors(self):
        """2. Văn bản đúng không sinh lỗi thay thế vô nghĩa: Hắn chần chừ rồi giấu giếm chuyện ấy."""
        text = "Hắn chần chừ rồi giấu giếm chuyện ấy."
        edited, issues = self.checker.check_paragraph(text, paragraph_idx=0)
        self.assertEqual(edited, text)
        self.assertEqual(len(issues), 0)
        # Kiểm tra không có issue nào có original == replacement
        for iss in issues:
            self.assertNotEqual(iss.original.strip().lower(), iss.replacement.strip().lower())

    def test_changelog_exact_reconstruction_of_edited(self):
        """3. Nhật ký tái tạo đúng 100% bản EDITED từ RAW text."""
        raw_text = 'ban đâu _"anh ngố" _ ,nói : nhìn không ra nguời nữa .'
        edited, issues = self.checker.check_paragraph(raw_text, paragraph_idx=0)

        # Tái tạo lại độc lập bằng apply_fixes
        reconstructed = self.checker.apply_fixes(raw_text, issues, approved_only=True)
        self.assertEqual(edited, reconstructed)

    def test_rejection_restores_raw_original(self):
        """4. Từ chối đề xuất làm kết quả trở lại bản gốc bất biến."""
        raw_text = "Cách giường chừng nửa trượng ,là một vách tường đất ."
        edited, issues = self.checker.check_paragraph(raw_text, paragraph_idx=0)
        self.assertNotEqual(edited, raw_text)

        # Người dùng từ chối toàn bộ đề xuất (status='rejected')
        for iss in issues:
            iss.status = "rejected"

        restored = self.checker.apply_fixes(raw_text, issues, approved_only=True)
        self.assertEqual(restored, raw_text)

    def test_ai_suggestions_pending_by_default(self):
        """5. AI đề xuất mặc định ở trạng thái pending, chỉ xuất hiện trong TXT khi được duyệt."""
        ai = AIChecker(
            provider="openai_compatible",
            api_key="mock_key",
            protected_terms=self.checker.protected_terms,
        )
        chunk = {
            "chunk_id": "chunk_1",
            "items": [{"p_idx": 0, "text": "Hắn phát hiện một bóng nguời lạ."}],
        }
        mock_raw_response = """
        [
            {
                "p_idx": 0,
                "original": "nguời",
                "replacement": "người",
                "category": "chinh_ta",
                "reason": "Lỗi gõ phím",
                "confidence": 0.99
            }
        ]
        """
        issues = ai._parse_and_verify_response(mock_raw_response, chunk, 1, "Tiêu đề")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].status, "pending")

        # Khi pending, apply_fixes không làm thay đổi bản gốc
        raw_para = chunk["items"][0]["text"]
        unapproved = VietnameseSpellChecker.apply_fixes(raw_para, issues, approved_only=True)
        self.assertEqual(unapproved, raw_para)

        # Khi duyệt, áp dụng thay đổi thành công
        issues[0].status = "applied"
        approved = VietnameseSpellChecker.apply_fixes(raw_para, issues, approved_only=True)
        self.assertEqual(approved, "Hắn phát hiện một bóng người lạ.")

    def test_multiple_occurrences_exact_offsets(self):
        """6. Cụm từ lặp nhiều lần trong cùng đoạn được gán đúng vị trí, không dùng .find() mù quáng."""
        raw_text = "Hắn thấy nguời này rất giống một nguời bạn cũ."
        edited, issues = self.checker.check_paragraph(raw_text, paragraph_idx=0)
        nguoi_issues = [i for i in issues if i.original == "nguời"]
        self.assertEqual(len(nguoi_issues), 2)
        # Vị trí bắt đầu không được trùng nhau
        self.assertNotEqual(nguoi_issues[0].char_start, nguoi_issues[1].char_start)
        # Kiểm tra lát cắt ký tự
        for iss in nguoi_issues:
            self.assertEqual(raw_text[iss.char_start:iss.char_end], "nguời")

    def test_storage_immutable_raw_content_and_versioning(self):
        """7. Nạp lại cùng URL với nội dung mới không xóa bản gốc mà lưu vào chapter_versions."""
        story = self.storage.get_or_create_story("http://example.com/truyen", "Truyện Thử Nghiệm")
        chap1_v1 = Chapter(
            story_id=story.id,
            chapter_num=1,
            chapter_title="Chương 1",
            source_url="http://example.com/chuong-1",
            raw_content="Nội dung gốc ban đầu v1",
            content_hash="hash_v1",
        )
        self.storage.save_chapter(chap1_v1)

        # Nạp lại cùng URL nhưng nội dung đã bị thay đổi (hash khác)
        chap1_v2 = Chapter(
            story_id=story.id,
            chapter_num=1,
            chapter_title="Chương 1 Mới",
            source_url="http://example.com/chuong-1",
            raw_content="Nội dung đã sửa đổi trên web v2",
            content_hash="hash_v2",
        )
        self.storage.save_chapter(chap1_v2)

        # Kiểm tra: bản gốc trong bảng chapters vẫn được giữ bất biến
        saved_chap = self.storage.get_chapter_by_url("http://example.com/chuong-1")
        self.assertEqual(saved_chap.raw_content, "Nội dung gốc ban đầu v1")
        self.assertEqual(saved_chap.version, 2)

        # Kiểm tra: phiên bản mới được lưu vào bảng chapter_versions
        with self.storage._get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM chapter_versions WHERE chapter_id = ?", (saved_chap.id,))
            ver_row = c.fetchone()
            self.assertIsNotNone(ver_row)
            self.assertEqual(ver_row["raw_content"], "Nội dung đã sửa đổi trên web v2")
            self.assertEqual(ver_row["version"], 2)

    def test_multi_story_isolation(self):
        """8. Nhiều truyện trong database không bị lẫn chương."""
        s1 = self.storage.get_or_create_story("http://example.com/s1", "Truyện A")
        s2 = self.storage.get_or_create_story("http://example.com/s2", "Truyện B")

        ch1_s1 = Chapter(story_id=s1.id, chapter_num=1, source_url="http://s1/c1", raw_content="S1 C1")
        ch1_s2 = Chapter(story_id=s2.id, chapter_num=1, source_url="http://s2/c1", raw_content="S2 C1")
        self.storage.save_chapter(ch1_s1)
        self.storage.save_chapter(ch1_s2)

        s1_chaps = self.storage.get_all_chapters(story_id=s1.id)
        s2_chaps = self.storage.get_all_chapters(story_id=s2.id)
        self.assertEqual(len(s1_chaps), 1)
        self.assertEqual(len(s2_chaps), 1)
        self.assertEqual(s1_chaps[0].raw_content, "S1 C1")
        self.assertEqual(s2_chaps[0].raw_content, "S2 C1")

    def test_punctuation_spacing_exact_reporting(self):
        """9. Sửa khoảng trắng trước & sau dấu câu (Cách giường ,là một vách tường.) được ghi đầy đủ."""
        text = "Cách giường ,là một vách tường."
        edited, issues = self.checker.check_paragraph(text, paragraph_idx=0)
        self.assertEqual(edited, "Cách giường, là một vách tường.")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].original, " ,")
        self.assertEqual(issues[0].replacement, ", ")
        self.assertEqual(text[issues[0].char_start:issues[0].char_end], " ,")

    def test_contextual_multi_meaning_bỗng_nhiên_vs_cổ(self):
        """10. 'Bổng nhiên hắn phát hiện một cổ khí thế.' đề xuất 'Bỗng nhiên', không thay 'cổ' mù quáng."""
        text = "Bổng nhiên hắn phát hiện một cổ khí thế."
        edited, issues = self.checker.check_paragraph(text, paragraph_idx=0)
        self.assertIn("Bỗng nhiên", edited)
        self.assertIn("cổ khí thế", edited)
        self.assertNotIn("cỗ khí thế", edited)

    def test_volume_format_audio_268_and_next(self):
        """11. Tập 268 gồm chương 1069-1072, không header từng chương, tập tiếp theo là 269."""
        chaps = [
            Chapter(chapter_num=num, chapter_title=f"Tiêu đề {num}", raw_content=f"Nội dung chương {num}.")
            for num in range(1069, 1073)
        ]
        merger = VolumeMerger(chapters_per_volume=4)
        volumes = merger.build_volumes(
            chapters=chaps,
            start_volume_num=268,
            expected_start_chap=1069,
            expected_end_chap=1072,
            story_title="Phàm Nhân Tu Tiên",
        )
        self.assertEqual(len(volumes), 1)
        vol = volumes[0]
        self.assertEqual(vol.volume_num, 268)
        self.assertEqual(vol.start_chapter, 1069)
        self.assertEqual(vol.end_chapter, 1072)
        self.assertEqual(vol.filename_base, "Tap_268_Chuong_1069_den_1072")

        rendered = merger.render_volume_text(vol)
        self.assertIn("PHÀM NHÂN TU TIÊN - TẬP 268", rendered)
        self.assertIn("Đây là Tập 268, phát từ Chương 1069 đến Chương 1072.", rendered)
        self.assertIn("Hết Tập 268: Cảm ơn quý thính giả đã chú ý lắng nghe. Hẹn gặp lại các bạn trong Tập 269 tiếp theo!", rendered)
        # Không có tiêu đề chương trong nội dung
        for num in range(1069, 1073):
            self.assertNotIn(f"=== CHƯƠNG {num}", rendered)
            self.assertNotIn(f"Tiêu đề {num}", rendered)
            self.assertIn(f"Nội dung chương {num}.", rendered)

    def test_atomic_bundle_export_with_temp_files(self):
        """12. Xuất bundle qua file tạm, atomic replace và kiểm tra overwrite."""
        chaps = [
            Chapter(chapter_num=1, raw_content="Đoạn 1."),
            Chapter(chapter_num=2, raw_content="Đoạn 2."),
        ]
        merger = VolumeMerger(chapters_per_volume=2)
        volumes = merger.build_volumes(chaps, start_volume_num=1, expected_start_chap=1, expected_end_chap=2)
        out_dir = os.path.join(self.temp_dir, "export_test")

        bundle = ReportGenerator.export_volume_bundle(
            volume=volumes[0],
            output_dir=out_dir,
            merger=merger,
            issues=[],
            edited_paragraphs_map={1: ["Đoạn 1."], 2: ["Đoạn 2."]},
            overwrite=False,
        )
        for k in ["raw", "edited", "report", "changelog"]:
            self.assertTrue(os.path.exists(bundle[k]))
            # Không được còn file .tmp
            self.assertFalse(os.path.exists(bundle[k] + ".tmp"))

        # Ghi đè mà không bật overwrite -> Báo FileExistsError
        with self.assertRaises(FileExistsError):
            ReportGenerator.export_volume_bundle(
                volume=volumes[0],
                output_dir=out_dir,
                merger=merger,
                issues=[],
                edited_paragraphs_map={1: ["Đoạn 1."], 2: ["Đoạn 2."]},
                overwrite=False,
            )

    def test_markdown_escaping_pipes_and_tags(self):
        """13. Escape ký tự đặc biệt trong bảng Markdown không làm vỡ cấu trúc."""
        vol = Volume(volume_num=1, start_chapter=1, end_chapter=1, story_title="Truyện | Test")
        iss = SpellIssue(
            chapter_num=1,
            paragraph_idx=0,
            char_start=0,
            char_end=5,
            original="a|b",
            replacement="c|d",
            reason="Lý do chứa ký tự | và xuống dòng\nthử nghiệm",
        )
        stats = ReportGenerator.calculate_statistics([iss])
        md = ReportGenerator.generate_markdown_report(vol, [iss], stats)
        # Ký tự | trong cột nội dung phải được escape thành \|
        self.assertIn("a\\|b", md)
        self.assertIn("c\\|d", md)

    def test_review_decisions_persistence(self):
        """14. Quyết định duyệt được lưu vào CSDL và khôi phục sau khi mở lại."""
        issues = [
            SpellIssue(id="iss_1", chapter_num=1, paragraph_idx=0, original="a", replacement="b", status="applied"),
            SpellIssue(id="iss_2", chapter_num=1, paragraph_idx=1, original="c", replacement="d", status="rejected"),
        ]
        self.storage.save_review_decisions(story_id=1, issues=issues)
        loaded = self.storage.get_review_decisions(story_id=1)
        self.assertEqual(loaded.get("iss_1"), "applied")
        self.assertEqual(loaded.get("iss_2"), "rejected")


if __name__ == "__main__":
    unittest.main()
