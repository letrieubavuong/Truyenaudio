"""
Unit tests for StorageManager.
"""
import unittest
import os
import uuid
from core.models import Chapter
from core.storage import StorageManager


class TestStorageManager(unittest.TestCase):
    def setUp(self):
        os.makedirs("tests/test_workspace", exist_ok=True)
        self.db_path = f"tests/test_workspace/test_storage_{uuid.uuid4().hex[:8]}.db"
        self.storage = StorageManager(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    def test_save_and_retrieve_chapter(self):
        ch = Chapter(
            story_id=1,
            chapter_num=10,
            chapter_title="Chương 10: Khởi Đầu",
            source_url="https://example.com/ch10",
            raw_content="Nội dung chương 10...",
            content_hash="hash123456",
            status="verified",
        )
        chap_id = self.storage.save_chapter(ch)
        self.assertGreater(chap_id, 0)

        retrieved = self.storage.get_chapter_by_num(1, 10)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.chapter_title, "Chương 10: Khởi Đầu")
        self.assertEqual(retrieved.content_hash, "hash123456")

    def test_detect_duplicate_hash(self):
        ch1 = Chapter(
            story_id=1,
            chapter_num=11,
            chapter_title="Chương 11",
            source_url="https://example.com/ch11",
            raw_content="Nội dung trùng...",
            content_hash="same_hash_abc",
            status="verified",
        )
        self.storage.save_chapter(ch1)

        ch2 = Chapter(
            story_id=1,
            chapter_num=12,
            chapter_title="Chương 12",
            source_url="https://example.com/ch12",
            raw_content="Nội dung trùng...",
            content_hash="same_hash_abc",
            status="verified",
        )
        self.storage.save_chapter(ch2)

        # ch2 phải có cảnh báo trùng hash
        self.assertTrue(any("Nội dung trùng lặp" in w for w in ch2.warnings))

    def test_detect_gaps(self):
        for n in [1, 2, 4, 5]:
            ch = Chapter(
                story_id=1,
                chapter_num=n,
                chapter_title=f"Chương {n}",
                source_url=f"https://example.com/ch{n}",
                raw_content="Nội dung...",
                status="verified",
            )
            self.storage.save_chapter(ch)

        missing = self.storage.detect_gaps_in_range(story_id=1, start_chap=1, end_chap=5)
        self.assertEqual(missing, [3])


if __name__ == "__main__":
    unittest.main()
