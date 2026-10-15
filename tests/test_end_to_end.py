"""
End-to-End integration test covering the entire pipeline:
Import offline -> SQLite storage -> Spell check -> Volume merge -> Export bundle.
"""
import os
import sys
import json
import unittest
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.storage import StorageManager
from core.importer import OfflineImporter
from core.spellchecker import VietnameseSpellChecker
from core.merger import VolumeMerger
from core.reporter import ReportGenerator


class TestEndToEndPipeline(unittest.TestCase):
    def setUp(self):
        self.test_dir = "tests/test_workspace"
        os.makedirs(self.test_dir, exist_ok=True)
        self.db_path = os.path.join(self.test_dir, "test_pipeline.db")
        self.output_dir = os.path.join(self.test_dir, "output")
        os.makedirs(self.output_dir, exist_ok=True)

        self.storage = StorageManager(db_path=self.db_path)
        self.importer = OfflineImporter(self.storage)
        self.checker = VietnameseSpellChecker(
            dictionary_path="resources/default_dictionary.json",
            protected_terms_path="resources/protected_terms.json",
        )

    def tearDown(self):
        # Dọn dẹp sau test nếu cần
        pass

    def test_full_pipeline_4_chapters(self):
        # 1. Nạp 4 chương mẫu từ data/sample_chapters
        sample_dir = "data/sample_chapters"
        imported = self.importer.import_directory(
            directory_path=sample_dir,
            story_title="Phàm Nhân Tu Tiên",
        )
        self.assertEqual(len(imported), 4)

        # 2. Truy vấn từ SQLite
        chapters = self.storage.get_chapters_range(story_id=1, start_chap=1, end_chap=4)
        self.assertEqual(len(chapters), 4)
        for i, ch in enumerate(chapters, 1):
            self.assertEqual(ch.chapter_num, i)
            self.assertGreater(len(ch.paragraphs), 10)

        # 3. Hiệu đính chính tả và lưu danh sách đoạn đã sửa
        all_volume_issues = []
        edited_paragraphs_map = {}

        for ch in chapters:
            edited_paras, issues = self.checker.check_chapter(
                ch.paragraphs, chapter_num=ch.chapter_num, chapter_title=ch.chapter_title
            )
            edited_paragraphs_map[ch.chapter_num] = edited_paras
            all_volume_issues.extend(issues)

        self.assertGreater(len(all_volume_issues), 0)
        print(f"\n[End-to-End Test] Total spellcheck issues detected across 4 chapters: {len(all_volume_issues)}")

        # 4. Gộp tập với số tập bắt đầu 268 (theo ví dụ đề bài)
        merger = VolumeMerger(chapters_per_volume=4, allow_partial_last_volume=False)
        volumes = merger.build_volumes(
            chapters=chapters,
            start_volume_num=268,
            expected_start_chap=1,
            expected_end_chap=4,
            story_title="Phàm Nhân Tu Tiên",
        )
        self.assertEqual(len(volumes), 1)
        vol = volumes[0]
        self.assertEqual(vol.volume_num, 268)
        self.assertFalse(vol.is_draft)
        self.assertEqual(len(vol.chapters), 4)

        # 5. Xuất trọn bộ 4 tệp bundle
        exported_files = ReportGenerator.export_volume_bundle(
            volume=vol,
            output_dir=self.output_dir,
            merger=merger,
            issues=all_volume_issues,
            edited_paragraphs_map=edited_paragraphs_map,
            overwrite=True,
        )

        for key, fpath in exported_files.items():
            self.assertTrue(os.path.exists(fpath), f"File {fpath} does not exist!")
            self.assertGreater(os.path.getsize(fpath), 0, f"File {fpath} is empty!")
            print(f"- Exported {key.upper()}: {fpath} ({os.path.getsize(fpath)} bytes)")

        # 6. Kiểm tra nội dung file RAW và EDITED
        with open(exported_files["raw"], "r", encoding="utf-8") as f:
            raw_content = f.read()
        with open(exported_files["edited"], "r", encoding="utf-8") as f:
            edited_content = f.read()

        # Bản raw có chứa _ _ _ _
        self.assertIn("_ _ _ _", raw_content)
        # Bản edited KHÔNG còn chứa _ _ _ _
        self.assertNotIn("_ _ _ _", edited_content)

        # Kiểm tra cấu trúc audio mở đầu & kết thúc
        for content in [raw_content, edited_content]:
            self.assertIn("PHÀM NHÂN TU TIÊN - TẬP 268", content)
            self.assertIn("Chào mừng các bạn đang theo dõi bộ truyện tiên hiệp Phàm Nhân Tu Tiên, tác giả Vong Ngữ.", content)
            self.assertIn("Đây là Tập 268, phát từ Chương 1 đến Chương 4.", content)
            self.assertIn("Chúc các bạn có những giây phút thư giãn và trải nghiệm tuyệt vời.", content)
            self.assertIn("Hết Tập 268: Cảm ơn quý thính giả đã chú ý lắng nghe. Hẹn gặp lại các bạn trong Tập 269 tiếp theo!", content)
            # Tuyệt đối không xuất tiêu đề chương và đường phân cách
            self.assertNotIn("===", content)
            self.assertNotIn("------------------------------------------------------------", content)

        # Xuống dòng LF thực tế trên đĩa sau khi chuẩn hóa CRLF/CR thành LF
        with open(exported_files["edited"], "rb") as fb:
            raw_bytes = fb.read()
        self.assertIn(b"\n", raw_bytes)
        self.assertNotIn(b"\r\n", raw_bytes)

        # 7. Kiểm tra file CHANGELOG JSON
        with open(exported_files["changelog"], "r", encoding="utf-8") as f:
            changelog_data = json.load(f)
        self.assertEqual(changelog_data["volume_num"], 268)
        self.assertEqual(len(changelog_data["issues"]), len(all_volume_issues))
        self.assertIn("statistics", changelog_data)
        print("[End-to-End Test] All assertions passed successfully!")


if __name__ == "__main__":
    unittest.main()
