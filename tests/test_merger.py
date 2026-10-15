"""
Unit tests for VolumeMerger with Audio Reading Format and Trailing Spaces Normalization.
"""
import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.models import Chapter
from core.merger import VolumeMerger, normalize_trailing_spaces


class TestVolumeMerger(unittest.TestCase):
    def test_normalize_trailing_spaces_rules(self):
        """
        Kiểm tra:
        - Chuẩn hóa CRLF/CR thành LF.
        - Áp dụng regex \\s\\n -> \\n.
        - Thực hiện đúng một lượt, không lặp thay thế đến khi hết khớp.
        """
        # CRLF và CR -> LF
        text_crlf = "Dòng 1\r\nDòng 2\rDòng 3\n"
        norm = normalize_trailing_spaces(text_crlf)
        self.assertEqual(norm, "Dòng 1\nDòng 2\nDòng 3\n")

        # Khoảng trắng đơn ở cuối dòng
        text_single = "Đoạn văn kết thúc bằng dấu cách \n"
        self.assertEqual(normalize_trailing_spaces(text_single), "Đoạn văn kết thúc bằng dấu cách\n")

        # Hai khoảng trắng ở cuối dòng: thực hiện đúng một lượt -> chỉ bớt 1 khoảng trắng
        text_double = "Đoạn văn có hai dấu cách  \n"
        self.assertEqual(normalize_trailing_spaces(text_double), "Đoạn văn có hai dấu cách \n")

    def test_merge_exact_example_from_user(self):
        """
        Kiểm tra đúng ví dụ trong đề bài:
        Người dùng nhập chương 1069–1076, tập bắt đầu 268:
        -> Tap_268_Chuong_1069_den_1072.txt
        -> Tap_269_Chuong_1073_den_1076.txt
        """
        chapters = []
        for n in range(1069, 1077):
            ch = Chapter(
                chapter_num=n,
                chapter_title=f"Chương {n}: Tiêu Đề {n}",
                raw_content=f"Đoạn 1 của chương {n}.\n\nĐoạn 2 của chương {n}.",
                status="verified",
            )
            chapters.append(ch)

        merger = VolumeMerger(chapters_per_volume=4)
        volumes = merger.build_volumes(
            chapters=chapters,
            start_volume_num=268,
            expected_start_chap=1069,
            expected_end_chap=1076,
            story_title="Phàm Nhân Tu Tiên",
        )

        self.assertEqual(len(volumes), 2)

        # Tập 268
        vol268 = volumes[0]
        self.assertEqual(vol268.volume_num, 268)
        self.assertEqual(vol268.start_chapter, 1069)
        self.assertEqual(vol268.end_chapter, 1072)
        self.assertEqual(vol268.filename_base, "Tap_268_Chuong_1069_den_1072")
        self.assertFalse(vol268.is_draft)

        # Render văn bản tập 268 và kiểm tra audio format
        text268 = merger.render_volume_text(vol268)

        # 1. Kiểm tra mở đầu chuẩn
        expected_prologue = (
            "PHÀM NHÂN TU TIÊN - TẬP 268\n"
            "Chào mừng các bạn đang theo dõi bộ truyện tiên hiệp Phàm Nhân Tu Tiên, tác giả Vong Ngữ.\n"
            "Đây là Tập 268, phát từ Chương 1069 đến Chương 1072.\n"
            "Chúc các bạn có những giây phút thư giãn và trải nghiệm tuyệt vời."
        )
        self.assertIn(expected_prologue, text268)

        # 2. Kiểm tra KHÔNG CÓ tiêu đề chương và đường phân cách
        self.assertNotIn("===", text268)
        self.assertNotIn("------------------------------------------------------------", text268)
        self.assertNotIn("Chương 1069: Tiêu Đề 1069", text268)
        self.assertNotIn("Chương 1070: Tiêu Đề 1070", text268)

        # 3. Kiểm tra nội dung truyện vẫn đầy đủ
        self.assertIn("Đoạn 1 của chương 1069.", text268)
        self.assertIn("Đoạn 2 của chương 1069.", text268)
        self.assertIn("Đoạn 1 của chương 1070.", text268)
        self.assertIn("Đoạn 2 của chương 1072.", text268)

        # 4. Kiểm tra dòng kết thúc chuẩn
        expected_epilogue_268 = "Hết Tập 268: Cảm ơn quý thính giả đã chú ý lắng nghe. Hẹn gặp lại các bạn trong Tập 269 tiếp theo!"
        self.assertIn(expected_epilogue_268, text268)

        # 5. Kiểm tra kết thúc dòng bằng LF, không còn CRLF
        self.assertNotIn("\r", text268)

        # Tập 269
        vol269 = volumes[1]
        self.assertEqual(vol269.volume_num, 269)
        self.assertEqual(vol269.start_chapter, 1073)
        self.assertEqual(vol269.end_chapter, 1076)
        self.assertEqual(vol269.filename_base, "Tap_269_Chuong_1073_den_1076")
        self.assertFalse(vol269.is_draft)

        text269 = merger.render_volume_text(vol269)
        expected_prologue_269 = (
            "PHÀM NHÂN TU TIÊN - TẬP 269\n"
            "Chào mừng các bạn đang theo dõi bộ truyện tiên hiệp Phàm Nhân Tu Tiên, tác giả Vong Ngữ.\n"
            "Đây là Tập 269, phát từ Chương 1073 đến Chương 1076.\n"
            "Chúc các bạn có những giây phút thư giãn và trải nghiệm tuyệt vời."
        )
        self.assertIn(expected_prologue_269, text269)

        expected_epilogue_269 = "Hết Tập 269: Cảm ơn quý thính giả đã chú ý lắng nghe. Hẹn gặp lại các bạn trong Tập 270 tiếp theo!"
        self.assertIn(expected_epilogue_269, text269)

    def test_missing_chapter_creates_draft(self):
        """Nếu thiếu một chương thì tập đó phải được đánh dấu là bản nháp (DRAFT)."""
        chapters = [
            Chapter(chapter_num=1, chapter_title="Chương 1", raw_content="Đoạn 1", status="verified"),
            Chapter(chapter_num=2, chapter_title="Chương 2", raw_content="Đoạn 2", status="verified"),
            # Thiếu chương 3
            Chapter(chapter_num=4, chapter_title="Chương 4", raw_content="Đoạn 4", status="verified"),
        ]

        merger = VolumeMerger(chapters_per_volume=4)
        volumes = merger.build_volumes(
            chapters=chapters,
            start_volume_num=1,
            expected_start_chap=1,
            expected_end_chap=4,
        )

        self.assertEqual(len(volumes), 1)
        self.assertTrue(volumes[0].is_draft)
        self.assertEqual(volumes[0].missing_chapters, [3])
        self.assertIn("DRAFT", volumes[0].filename_base)

        text_draft = merger.render_volume_text(volumes[0])
        self.assertIn("CẢNH BÁO: ĐÂY LÀ BẢN NHÁP (DRAFT)", text_draft)

    def test_partial_last_group_flag(self):
        """Nhóm cuối dưới 4 chương chỉ xuất khi allow_partial_last_volume == True."""
        chapters = [
            Chapter(chapter_num=1, chapter_title="Chương 1", raw_content="Nội dung 1", status="verified"),
            Chapter(chapter_num=2, chapter_title="Chương 2", raw_content="Nội dung 2", status="verified"),
        ]

        # allow_partial = False -> không xuất tập thiếu
        merger_strict = VolumeMerger(chapters_per_volume=4, allow_partial_last_volume=False)
        vols_strict = merger_strict.build_volumes(chapters, 1, 1, 2)
        self.assertEqual(len(vols_strict), 0)

        # allow_partial = True -> cho phép xuất
        merger_lax = VolumeMerger(chapters_per_volume=4, allow_partial_last_volume=True)
        vols_lax = merger_lax.build_volumes(chapters, 1, 1, 2)
        self.assertEqual(len(vols_lax), 1)
        self.assertEqual(vols_lax[0].start_chapter, 1)
        self.assertEqual(vols_lax[0].end_chapter, 2)


if __name__ == "__main__":
    unittest.main()
