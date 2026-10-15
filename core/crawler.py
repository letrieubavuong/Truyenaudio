"""
Sequential Network Crawler with Strict Safety, Rate Limiting, Retry, and Resumption.
Features:
- Sequential downloads (never concurrent spam)
- Configurable delay (1.5s - 3.0s) and timeout
- Finite retries (max 2) with backoff
- Immediate stop upon HTTP 403, 429, or Cloudflare challenge detection
- Redirect check (detects redirects back to homepage or story page)
- Loop detection (tracks visited URLs)
- SQLite resumption: checks if chapter is already verified before fetching
"""
import time
import requests
from typing import Optional, Callable, Dict, Any, Set
from urllib.parse import urlparse

from core.models import Chapter, StoryInfo
from core.parser import SourceParser
from core.storage import StorageManager


class NetworkCrawler:
    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        storage: StorageManager,
        delay_seconds: float = 1.5,
        timeout_seconds: int = 20,
        max_retries: int = 2,
        user_agent: str = "",
    ):
        self.storage = storage
        self.delay_seconds = delay_seconds
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.user_agent = user_agent or self.DEFAULT_USER_AGENT

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
        })

        self._is_paused = False
        self._is_stopped = False

    def pause(self):
        self._is_paused = True

    def resume(self):
        self._is_paused = False

    def stop(self):
        self._is_stopped = True

    def fetch_url(self, url: str) -> Tuple[Optional[str], Optional[str], Optional[int]]:
        """
        Tải một URL với timeout, retry hữu hạn, kiểm tra redirect và mã HTTP.
        Trả về: (html_content, error_message, status_code)
        """
        for attempt in range(1, self.max_retries + 1):
            if self._is_stopped:
                return None, "Tác vụ đã bị người dùng hủy.", None

            try:
                response = self.session.get(url, timeout=self.timeout_seconds, allow_redirects=True)
                status_code = response.status_code

                # Kiểm tra chuyển hướng về trang chủ hoặc mục lục
                final_url = response.url
                parsed_final = urlparse(final_url)
                if parsed_final.path in ("", "/", "/truyen/pham-nhan-tu-tien", "/truyen/pham-nhan-tu-tien/"):
                    if url != final_url:
                        return None, f"Bị chuyển hướng về trang chủ ({final_url}). Dừng lại.", status_code

                # Kiểm tra HTTP 403, 429
                if status_code in (403, 429):
                    return None, f"Máy chủ trả về HTTP {status_code} (Bị từ chối hoặc giới hạn tần suất). Dừng thu thập tự động theo quy định.", status_code

                if status_code != 200:
                    if attempt < self.max_retries:
                        time.sleep(2.0 * attempt)
                        continue
                    return None, f"HTTP {status_code}: Máy chủ phản hồi mã không thành công.", status_code

                # Giải mã UTF-8
                response.encoding = response.apparent_encoding or "utf-8"
                html_text = response.text

                # Kiểm tra Cloudflare Challenge trong nội dung
                lower_text = html_text.lower()
                if "just a moment..." in lower_text or "cf-browser-verification" in lower_text:
                    return None, "Phát hiện màn hình thử thách bảo mật Cloudflare (CAPTCHA/Challenge). Dừng lại ngay.", 403

                return html_text, None, 200

            except requests.exceptions.Timeout:
                if attempt < self.max_retries:
                    time.sleep(2.0 * attempt)
                    continue
                return None, f"Quá thời gian chờ ({self.timeout_seconds}s) khi kết nối tới máy chủ.", None
            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries:
                    time.sleep(2.0 * attempt)
                    continue
                return None, f"Lỗi kết nối mạng: {str(e)}", None

        return None, "Không thể kết nối sau số lần thử tối đa.", None

    def crawl_range(
        self,
        story_url: str,
        start_chapter_url: str,
        start_chap_num: int,
        end_chap_num: int,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        on_log: Optional[Callable[[str, str], None]] = None,
        on_chapter_saved: Optional[Callable[[Chapter], None]] = None,
    ) -> Dict[str, Any]:
        """
        Thu thập tuần tự theo liên kết chương tiếp theo (nextChap) từ start_chap_num đến end_chap_num.
        Hỗ trợ resume từ SQLite database.
        """
        self._is_stopped = False
        self._is_paused = False

        def log(level: str, msg: str):
            if on_log:
                on_log(level, msg)

        log("INFO", f"Bắt đầu tác vụ thu thập từ Chương {start_chap_num} đến {end_chap_num}")
        story = self.storage.get_or_create_story(url=story_url)

        visited_urls: Set[str] = set()
        current_url = start_chapter_url
        current_num = start_chap_num
        total_to_fetch = end_chap_num - start_chap_num + 1
        fetched_count = 0

        while current_url and current_num <= end_chap_num:
            if self._is_stopped:
                log("WARNING", "Đã dừng thu thập theo yêu cầu người dùng.")
                break

            while self._is_paused:
                if self._is_stopped:
                    break
                time.sleep(0.5)

            # Phát hiện vòng lặp URL
            if current_url in visited_urls:
                log("ERROR", f"Phát hiện vòng lặp URL đã xử lý: {current_url}. Dừng lại để tránh lặp vô tận.")
                break
            visited_urls.add(current_url)

            # Kiểm tra CSDL xem chương đã tải chưa (Resume)
            existing_chap = self.storage.get_chapter_by_url(current_url)
            if not existing_chap and current_num:
                existing_chap = self.storage.get_chapter_by_num(story.id, current_num)

            if existing_chap and existing_chap.status in ("verified", "downloaded") and existing_chap.raw_content:
                log("INFO", f"Chương {existing_chap.chapter_num or current_num} đã có trong CSDL (Khôi phục tiến độ). Bỏ qua không tải lại.")
                current_url = existing_chap.next_url
                current_num = (existing_chap.chapter_num or current_num) + 1
                fetched_count += 1
                if on_progress:
                    on_progress(fetched_count, total_to_fetch, f"Đã có: Chương {existing_chap.chapter_num}")
                continue

            # Tải qua mạng
            log("INFO", f"Đang tải: {current_url}")
            html_text, err, status_code = self.fetch_url(current_url)

            if err:
                log("ERROR", f"Tải thất bại tại {current_url}: {err}")
                # Lưu trạng thái thất bại vào DB để theo dõi
                failed_chap = Chapter(
                    story_id=story.id,
                    chapter_num=current_num,
                    chapter_title=f"Chương {current_num} (Lỗi tải)",
                    source_url=current_url,
                    raw_content="",
                    status="failed",
                    warnings=[err],
                )
                self.storage.save_chapter(failed_chap)
                break

            # Phân tích nội dung
            parsed = SourceParser.parse_chapter_html(html_text, current_url=current_url)
            if "error" in parsed:
                log("ERROR", f"Phân tích thất bại: {parsed['error']}")
                break

            chap_num = parsed["chapter_num"] or current_num
            chapter = Chapter(
                story_id=story.id,
                chapter_num=chap_num,
                chapter_title=parsed["chapter_title"],
                source_url=current_url,
                raw_content=parsed["raw_content"],
                content_hash=parsed["content_hash"],
                status="verified",
                prev_url=parsed["prev_url"],
                next_url=parsed["next_url"],
                warnings=parsed["warnings"],
            )

            self.storage.save_chapter(chapter)
            log("SUCCESS", f"Đã lưu Chương {chap_num}: '{chapter.chapter_title}' ({len(parsed['paragraphs'])} đoạn, SHA256: {chapter.content_hash[:8]}...)")

            if on_chapter_saved:
                on_chapter_saved(chapter)

            fetched_count += 1
            if on_progress:
                on_progress(fetched_count, total_to_fetch, f"Hoàn thành Chương {chap_num}")

            # Chuyển sang chương tiếp theo
            next_url = parsed["next_url"]
            if not next_url:
                log("WARNING", f"Không tìm thấy liên kết 'Chương tiếp theo' tại Chương {chap_num}.")
                break

            current_url = next_url
            current_num = chap_num + 1

            # Tạm nghỉ delay tôn trọng máy chủ
            time.sleep(self.delay_seconds)

        log("INFO", f"Tác vụ hoàn thành. Đã xử lý {fetched_count}/{total_to_fetch} chương.")
        return {
            "fetched_count": fetched_count,
            "total_requested": total_to_fetch,
            "is_stopped": self._is_stopped,
        }
