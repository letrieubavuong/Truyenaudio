"""
Unit tests with Mock HTTP for Crawler Diagnostics, Safety, and Boundary Crossing:
1. 12-chapter chain crossing volume boundaries (4->5 and 8->9) and merging into 3 volumes.
2. Relative next chapter URLs and avoiding the HTML class='next' trap on 'Chương trước'.
3. Chapter 5 returning HTTP 403 Forbidden.
4. Chapter 5 returning HTTP 429 Too Many Requests.
5. Chapter 5 redirecting to homepage or story index.
6. Missing next chapter link after Chapter 4 (reports navigation failure, not full success).
7. Next URL looping back to an already visited chapter.
8. Resuming crawl range 1-12 when chapters 1-4 already exist in DB.
"""
import unittest
from unittest.mock import MagicMock, patch
import os
import shutil
import tempfile
from typing import Dict, Any, Optional

from core.models import Chapter, StoryInfo
from core.crawler import NetworkCrawler
from core.storage import StorageManager
from core.parser import SourceParser
from core.merger import VolumeMerger


def make_mock_html(
    chapter_num: int,
    chapter_title: str,
    next_url: Optional[str] = None,
    prev_url: Optional[str] = None,
    include_script_vars: bool = True,
    class_next_trap: bool = False,
) -> str:
    """Tạo mã HTML giả lập cấu trúc chuẩn của vivutruyen.com."""
    script_part = ""
    if include_script_vars:
        n_val = f"'{next_url}'" if next_url else "''"
        p_val = f"'{prev_url}'" if prev_url else "''"
        script_part = f"""
        <script>
            var bid = "pham-nhan-tu-tien";
            var id = "{103480 + chapter_num}";
            var bname = "Phàm Nhân Tu Tiên";
            var prevChap = {p_val};
            var nextChap = {n_val};
        </script>
        """

    # Giao diện điều hướng HTML
    nav_part = ""
    if class_next_trap and prev_url and next_url:
        # Tái hiện bẫy: Cả Chương trước và Chương tiếp đều mang class='next'
        nav_part = f"""
        <div class="chapter_control" id="gotochap">
            <a href="{prev_url}" class="next">&#60;&#60; Chương trước</a>
            <a href="javascript:void(0);" class="btn-dschuong"></a>
            <a href="{next_url}" class="next">Chương tiếp &#62;&#62;</a>
        </div>
        """
    else:
        prev_tag = f'<a href="{prev_url}" class="back">&#60;&#60; Chương trước</a>' if prev_url else ''
        next_tag = f'<a href="{next_url}" class="next">Chương tiếp &#62;&#62;</a>' if next_url else ''
        nav_part = f"""
        <div class="chapter_control" id="gotochap">
            {prev_tag}
            <a href="javascript:void(0);" class="btn-dschuong"></a>
            {next_tag}
        </div>
        """

    paragraphs_html = "".join([
        f"<p>Đây là nội dung đoạn thứ {i} của {chapter_title}. Tu tiên giả vượt qua thử thách gian nan.</p>"
        for i in range(1, 15)
    ])

    return f"""<!doctype html>
    <html lang="vi">
    <head>
        <meta charset="UTF-8" />
        <title>Phàm Nhân Tu Tiên - {chapter_title}</title>
        {script_part}
    </head>
    <body>
        {nav_part}
        <div>
            <h1 class="current-book">
                <a href="/truyen/pham-nhan-tu-tien">Phàm Nhân Tu Tiên</a>
                <span class="current-chapter">{chapter_title}</span>
            </h1>
        </div>
        <div class="truyen">
            {chapter_title}
            {paragraphs_html}
        </div>
        {nav_part}
    </body>
    </html>
    """


class TestCrawlerDiagnostics(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_diagnostics.db")
        self.storage = StorageManager(self.db_path)
        self.crawler = NetworkCrawler(
            storage=self.storage,
            delay_seconds=0.01,  # Tăng tốc độ chạy test
            timeout_seconds=5,
            max_retries=1,
        )
        self.story_url = "https://vivutruyen.com/truyen/pham-nhan-tu-tien"
        self.start_url = "https://vivutruyen.com/truyen/pham-nhan-tu-tien/chuong-1-son-bien-tieu-thon-103484"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_mock_response(
        self,
        text: str,
        status_code: int = 200,
        url: str = "",
        content_type: str = "text/html; charset=utf-8",
    ):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.text = text
        mock_resp.content = text.encode("utf-8")
        mock_resp.url = url
        mock_resp.headers = {"Content-Type": content_type}
        mock_resp.apparent_encoding = "utf-8"
        return mock_resp

    def test_crawl_12_chapters_crossing_boundaries(self):
        """1. Kiểm tra chuỗi 12 chương, đi qua ranh giới 4->5 và 8->9, gộp đủ 3 tập."""
        url_map = {}
        for i in range(1, 13):
            curr_url = f"https://vivutruyen.com/truyen/pham-nhan-tu-tien/chuong-{i}-slug-{103483 + i}"
            prev_rel = f"/truyen/pham-nhan-tu-tien/chuong-{i-1}-slug-{103483 + i - 1}" if i > 1 else ""
            next_rel = f"/truyen/pham-nhan-tu-tien/chuong-{i+1}-slug-{103483 + i + 1}" if i < 12 else ""
            html = make_mock_html(
                chapter_num=i,
                chapter_title=f"Chương {i}: Tiêu Đề Chương {i}",
                next_url=next_rel,
                prev_url=prev_rel,
                include_script_vars=True,
            )
            url_map[curr_url] = html

        def mock_get(url, **kwargs):
            self.assertIn(url, url_map)
            return self._create_mock_response(url_map[url], status_code=200, url=url)

        with patch.object(self.crawler.session, "get", side_effect=mock_get):
            res = self.crawler.crawl_range(
                story_url=self.story_url,
                start_chapter_url=list(url_map.keys())[0],
                start_chap_num=1,
                end_chap_num=12,
            )

        self.assertTrue(res["success"])
        self.assertEqual(res["fetched_count"], 12)
        self.assertEqual(res["total_requested"], 12)
        self.assertIsNone(res["stop_reason"])

        # Kiểm tra CSDL đủ 12 chương
        story = self.storage.get_story_by_url(self.story_url)
        chapters = self.storage.get_chapters_range(story.id, 1, 12)
        self.assertEqual(len(chapters), 12)

        # Kiểm tra gộp 12 chương với per_vol=4 -> 3 tập chính xác
        merger = VolumeMerger(chapters_per_volume=4)
        volumes = merger.build_volumes(chapters, start_volume_num=1, expected_start_chap=1, expected_end_chap=12)
        self.assertEqual(len(volumes), 3)
        self.assertEqual([c.chapter_num for c in volumes[0].chapters], [1, 2, 3, 4])
        self.assertEqual([c.chapter_num for c in volumes[1].chapters], [5, 6, 7, 8])
        self.assertEqual([c.chapter_num for c in volumes[2].chapters], [9, 10, 11, 12])

    def test_relative_next_urls_and_class_next_trap(self):
        """2. URL chương tiếp theo dạng tương đối và xử lý bẫy class='next' trên thẻ Chương trước."""
        curr_url = "https://vivutruyen.com/truyen/pham-nhan-tu-tien/chuong-4-luyen-cot-nhai-103487"
        prev_rel = "/truyen/pham-nhan-tu-tien/chuong-3-that-huyen-mon-103486"
        next_rel = "/truyen/pham-nhan-tu-tien/chuong-5-mac-dai-phu-103488"

        # Giả lập HTML không có script_vars, chỉ có thẻ HTML có class='next' ở cả 2 nút
        html = make_mock_html(
            chapter_num=4,
            chapter_title="Chương 4: Luyện Cốt Nhai",
            next_url=next_rel,
            prev_url=prev_rel,
            include_script_vars=False,
            class_next_trap=True,
        )

        parsed = SourceParser.parse_chapter_html(
            html, current_url=curr_url, base_url=self.story_url
        )

        # Bắt buộc phải chọn Chương 5, tuyệt đối không chọn Chương 3
        self.assertEqual(
            parsed["next_url"],
            "https://vivutruyen.com/truyen/pham-nhan-tu-tien/chuong-5-mac-dai-phu-103488",
        )
        self.assertIn("chuong-5", parsed["next_url"])
        self.assertNotIn("chuong-3", parsed["next_url"])
        self.assertIn("html_nav", parsed["next_source"])

    def test_chapter_5_returns_403(self):
        """3. Chương 5 trả HTTP 403 Forbidden -> Dừng đúng cách, báo chương bị chặn, không vượt cơ chế bảo vệ."""
        url_map = {}
        for i in range(1, 5):
            curr_url = f"https://vivutruyen.com/truyen/pham-nhan-tu-tien/chuong-{i}-slug-{103483 + i}"
            next_rel = f"/truyen/pham-nhan-tu-tien/chuong-{i+1}-slug-{103483 + i + 1}"
            url_map[curr_url] = make_mock_html(i, f"Chương {i}", next_url=next_rel)

        chap5_url = "https://vivutruyen.com/truyen/pham-nhan-tu-tien/chuong-5-slug-103488"

        def mock_get(url, **kwargs):
            if url == chap5_url:
                return self._create_mock_response(
                    "<html><head><title>403 Forbidden</title></head><body>Access Denied</body></html>",
                    status_code=403,
                    url=chap5_url,
                )
            return self._create_mock_response(url_map[url], status_code=200, url=url)

        with patch.object(self.crawler.session, "get", side_effect=mock_get):
            res = self.crawler.crawl_range(
                story_url=self.story_url,
                start_chapter_url=list(url_map.keys())[0],
                start_chap_num=1,
                end_chap_num=12,
            )

        self.assertFalse(res["success"])
        self.assertEqual(res["fetched_count"], 4)
        self.assertEqual(res["total_requested"], 12)
        self.assertIn("403", res["stop_reason"])
        self.assertIn("Chương 5", res["stop_reason"])
        self.assertTrue(res["status_message"].startswith("Chưa hoàn tất: 4/12 chương"))

        # Kiểm tra bản ghi lỗi được ghi vào DB
        story = self.storage.get_story_by_url(self.story_url)
        failed_chap = self.storage.get_chapter_by_num(story.id, 5)
        self.assertIsNotNone(failed_chap)
        self.assertEqual(failed_chap.status, "failed")

    def test_chapter_5_returns_429(self):
        """4. Chương 5 trả HTTP 429 Too Many Requests -> Dừng an toàn và báo rõ lý do."""
        url_map = {}
        for i in range(1, 5):
            curr_url = f"https://vivutruyen.com/truyen/pham-nhan-tu-tien/chuong-{i}-slug-{103483 + i}"
            next_rel = f"/truyen/pham-nhan-tu-tien/chuong-{i+1}-slug-{103483 + i + 1}"
            url_map[curr_url] = make_mock_html(i, f"Chương {i}", next_url=next_rel)

        chap5_url = "https://vivutruyen.com/truyen/pham-nhan-tu-tien/chuong-5-slug-103488"

        def mock_get(url, **kwargs):
            if url == chap5_url:
                return self._create_mock_response(
                    "Too Many Requests",
                    status_code=429,
                    url=chap5_url,
                )
            return self._create_mock_response(url_map[url], status_code=200, url=url)

        with patch.object(self.crawler.session, "get", side_effect=mock_get):
            res = self.crawler.crawl_range(
                story_url=self.story_url,
                start_chapter_url=list(url_map.keys())[0],
                start_chap_num=1,
                end_chap_num=12,
            )

        self.assertFalse(res["success"])
        self.assertEqual(res["fetched_count"], 4)
        self.assertIn("429", res["stop_reason"])
        self.assertTrue(res["status_message"].startswith("Chưa hoàn tất: 4/12 chương"))

    def test_chapter_5_redirects_to_homepage(self):
        """5. Chương 5 bị chuyển hướng về trang chủ -> Dừng lại, thông báo chuyển hướng."""
        url_map = {}
        for i in range(1, 5):
            curr_url = f"https://vivutruyen.com/truyen/pham-nhan-tu-tien/chuong-{i}-slug-{103483 + i}"
            next_rel = f"/truyen/pham-nhan-tu-tien/chuong-{i+1}-slug-{103483 + i + 1}"
            url_map[curr_url] = make_mock_html(i, f"Chương {i}", next_url=next_rel)

        chap5_url = "https://vivutruyen.com/truyen/pham-nhan-tu-tien/chuong-5-slug-103488"

        def mock_get(url, **kwargs):
            if url == chap5_url:
                # Trả về URL sau redirect là trang chủ
                return self._create_mock_response(
                    "<html><body>Trang chu vivutruyen</body></html>",
                    status_code=200,
                    url="https://vivutruyen.com/",
                )
            return self._create_mock_response(url_map[url], status_code=200, url=url)

        with patch.object(self.crawler.session, "get", side_effect=mock_get):
            res = self.crawler.crawl_range(
                story_url=self.story_url,
                start_chapter_url=list(url_map.keys())[0],
                start_chap_num=1,
                end_chap_num=12,
            )

        self.assertFalse(res["success"])
        self.assertEqual(res["fetched_count"], 4)
        self.assertIn("trang chủ", res["stop_reason"])
        self.assertTrue(res["status_message"].startswith("Chưa hoàn tất: 4/12 chương"))

    def test_missing_next_link_after_chapter_4(self):
        """6. Chương 4 không có liên kết tiếp theo -> Báo lỗi điều hướng, không thông báo hoàn tất."""
        url_map = {}
        for i in range(1, 5):
            curr_url = f"https://vivutruyen.com/truyen/pham-nhan-tu-tien/chuong-{i}-slug-{103483 + i}"
            # Chương 4 không có next_url
            next_rel = f"/truyen/pham-nhan-tu-tien/chuong-{i+1}-slug-{103483 + i + 1}" if i < 4 else ""
            url_map[curr_url] = make_mock_html(i, f"Chương {i}", next_url=next_rel)

        def mock_get(url, **kwargs):
            return self._create_mock_response(url_map[url], status_code=200, url=url)

        with patch.object(self.crawler.session, "get", side_effect=mock_get):
            res = self.crawler.crawl_range(
                story_url=self.story_url,
                start_chapter_url=list(url_map.keys())[0],
                start_chap_num=1,
                end_chap_num=12,
            )

        self.assertFalse(res["success"])
        self.assertEqual(res["fetched_count"], 4)
        self.assertEqual(res["total_requested"], 12)
        self.assertIn("Thiếu liên kết", res["stop_reason"])
        self.assertTrue(res["status_message"].startswith("Chưa hoàn tất: 4/12 chương"))

    def test_next_url_loop_back_to_previous_chapter(self):
        """7. Liên kết tiếp theo quay lại chương 2 -> Phát hiện vòng lặp, dừng ngay lập tức."""
        url_map = {}
        for i in range(1, 5):
            curr_url = f"https://vivutruyen.com/truyen/pham-nhan-tu-tien/chuong-{i}-slug-{103483 + i}"
            # Chương 4 trỏ ngược về Chương 2
            next_rel = f"/truyen/pham-nhan-tu-tien/chuong-2-slug-103485" if i == 4 else f"/truyen/pham-nhan-tu-tien/chuong-{i+1}-slug-{103483 + i + 1}"
            url_map[curr_url] = make_mock_html(i, f"Chương {i}", next_url=next_rel)

        def mock_get(url, **kwargs):
            return self._create_mock_response(url_map[url], status_code=200, url=url)

        with patch.object(self.crawler.session, "get", side_effect=mock_get):
            res = self.crawler.crawl_range(
                story_url=self.story_url,
                start_chapter_url=list(url_map.keys())[0],
                start_chap_num=1,
                end_chap_num=12,
            )

        self.assertFalse(res["success"])
        self.assertEqual(res["fetched_count"], 4)
        self.assertIn("vòng lặp URL", res["stop_reason"])
        self.assertTrue(res["status_message"].startswith("Chưa hoàn tất: 4/12 chương"))

    def test_resume_after_chapters_1_to_4_already_in_db(self):
        """8. Tiếp tục tác vụ 1-12 khi đã có chương 1-4 trong DB (kể cả khi next_url dính file://)."""
        story = self.storage.get_or_create_story(self.story_url)

        # Lưu trước chương 1-4 vào DB với next_url dính file:// (mô phỏng dữ liệu import trước đây)
        for i in range(1, 5):
            next_u = (
                f"file://data/truyen/pham-nhan-tu-tien/chuong-{i+1}-slug-{103483 + i + 1}"
                if i < 4
                else "file://data/truyen/pham-nhan-tu-tien/chuong-5-slug-103488"
            )
            ch = Chapter(
                story_id=story.id,
                chapter_num=i,
                chapter_title=f"Chương {i}",
                source_url=f"file:///sample/chuong_{i}.html",
                raw_content="Nội dung chương có sẵn trong CSDL",
                status="verified",
                next_url=next_u,
            )
            self.storage.save_chapter(ch)

        # Tạo mock cho các chương còn lại 5-12
        url_map = {}
        for i in range(5, 13):
            curr_url = f"https://vivutruyen.com/truyen/pham-nhan-tu-tien/chuong-{i}-slug-{103483 + i}"
            next_rel = f"/truyen/pham-nhan-tu-tien/chuong-{i+1}-slug-{103483 + i + 1}" if i < 12 else ""
            url_map[curr_url] = make_mock_html(i, f"Chương {i}", next_url=next_rel)

        def mock_get(url, **kwargs):
            # Không được gọi tải lại chương 1-4
            self.assertFalse(any(f"chuong-{c}-" in url for c in range(1, 5)))
            self.assertIn(url, url_map)
            return self._create_mock_response(url_map[url], status_code=200, url=url)

        with patch.object(self.crawler.session, "get", side_effect=mock_get):
            res = self.crawler.crawl_range(
                story_url=self.story_url,
                start_chapter_url="https://vivutruyen.com/truyen/pham-nhan-tu-tien/chuong-1-slug-103484",
                start_chap_num=1,
                end_chap_num=12,
            )

        self.assertTrue(res["success"])
        self.assertEqual(res["fetched_count"], 12)
        self.assertEqual(res["total_requested"], 12)

        # Kiểm tra tất cả 12 chương đều có trong DB
        all_chaps = self.storage.get_chapters_range(story.id, 1, 12)
        self.assertEqual(len(all_chaps), 12)


if __name__ == "__main__":
    unittest.main()
