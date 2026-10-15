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
from typing import Optional, Callable, Dict, Any, Set, Tuple
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

    def fetch_url(
        self, url: str, story_url: str = ""
    ) -> Tuple[Optional[str], Optional[str], Optional[int], Dict[str, Any]]:
        """
        Tải một URL với timeout, retry hữu hạn, kiểm tra redirect và mã HTTP.
        Trả về: (html_content, error_message, status_code, diag_info)
        Không ghi cookie, token hoặc thông tin bí mật vào thông tin chẩn đoán.
        """
        diag_info: Dict[str, Any] = {
            "requested_url": url,
            "final_url": url,
            "status_code": None,
            "content_type": "",
            "content_length": 0,
            "is_redirected": False,
        }

        for attempt in range(1, self.max_retries + 1):
            if self._is_stopped:
                return None, "Tác vụ đã bị người dùng hủy.", None, diag_info

            try:
                response = self.session.get(url, timeout=self.timeout_seconds, allow_redirects=True)
                status_code = response.status_code
                final_url = response.url

                diag_info["final_url"] = final_url
                diag_info["status_code"] = status_code
                diag_info["content_type"] = response.headers.get("Content-Type", "")
                diag_info["content_length"] = len(response.content) if response.content else 0
                diag_info["is_redirected"] = (final_url != url)

                # Kiểm tra chuyển hướng về trang chủ hoặc mục lục truyện
                if final_url != url:
                    parsed_final = urlparse(final_url)
                    parsed_story = urlparse(story_url) if story_url else None
                    if (
                        parsed_final.path in ("", "/", "/index.html", "/login")
                        or (parsed_story and parsed_final.path.rstrip("/") == parsed_story.path.rstrip("/"))
                    ):
                        return (
                            None,
                            f"Bị chuyển hướng về trang chủ/mục lục ({final_url}). Dừng lại.",
                            status_code,
                            diag_info,
                        )

                # Kiểm tra HTTP 403, 429
                if status_code in (403, 429):
                    reason = (
                        "Bị từ chối truy cập (403 Forbidden)"
                        if status_code == 403
                        else "Bị giới hạn tần suất yêu cầu (429 Too Many Requests)"
                    )
                    return (
                        None,
                        f"Máy chủ trả về HTTP {status_code} ({reason}). Dừng thu thập tự động theo quy định.",
                        status_code,
                        diag_info,
                    )

                if status_code != 200:
                    if attempt < self.max_retries:
                        time.sleep(2.0 * attempt)
                        continue
                    return (
                        None,
                        f"HTTP {status_code}: Máy chủ phản hồi mã không thành công.",
                        status_code,
                        diag_info,
                    )

                # Giải mã UTF-8
                response.encoding = response.apparent_encoding or "utf-8"
                html_text = response.text

                # Kiểm tra Cloudflare Challenge / CAPTCHA trong nội dung
                lower_text = html_text.lower()
                if (
                    "just a moment..." in lower_text
                    or "cf-browser-verification" in lower_text
                    or "challenge-running" in lower_text
                ):
                    return (
                        None,
                        "Phát hiện màn hình thử thách bảo mật Cloudflare (CAPTCHA/Challenge). Dừng lại ngay.",
                        403,
                        diag_info,
                    )

                # Kiểm tra nội dung rỗng
                if not html_text.strip():
                    return (
                        None,
                        "Phản hồi rỗng (0 ký tự nội dung từ máy chủ).",
                        200,
                        diag_info,
                    )

                return html_text, None, 200, diag_info

            except requests.exceptions.Timeout:
                if attempt < self.max_retries:
                    time.sleep(2.0 * attempt)
                    continue
                return (
                    None,
                    f"Quá thời gian chờ ({self.timeout_seconds}s) khi kết nối tới máy chủ.",
                    None,
                    diag_info,
                )
            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries:
                    time.sleep(2.0 * attempt)
                    continue
                return None, f"Lỗi kết nối mạng: {str(e)}", None, diag_info

        return None, "Không thể kết nối sau số lần thử tối đa.", None, diag_info

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
        Đảm bảo tải đúng và đủ dải chương, tách biệt hoàn toàn với số chương/tập.
        Ghi log chẩn đoán đầy đủ cho từng chương (không log cookie/token/secrets).
        """
        self._is_stopped = False
        self._is_paused = False

        def log(level: str, msg: str):
            if on_log:
                on_log(level, msg)

        log("INFO", f"Bắt đầu tác vụ thu thập: Chương {start_chap_num} đến Chương {end_chap_num}")
        story = self.storage.get_or_create_story(url=story_url)

        visited_urls: Set[str] = set()
        current_url = SourceParser._resolve_url(start_chapter_url, base_url=story_url)
        current_num = start_chap_num
        total_to_fetch = end_chap_num - start_chap_num + 1
        fetched_count = 0
        stop_reason: Optional[str] = None

        while current_num <= end_chap_num:
            if self._is_stopped:
                stop_reason = "Đã dừng thu thập theo yêu cầu người dùng."
                log("WARNING", f"[DỪNG] {stop_reason}")
                break

            while self._is_paused:
                if self._is_stopped:
                    break
                time.sleep(0.5)

            # Kiểm tra nếu mất liên kết URL chương tiếp theo
            if not current_url:
                stop_reason = f"Thiếu liên kết để tải Chương {current_num} (chương trước không cung cấp liên kết kế tiếp)."
                log("WARNING", f"[DỪNG] {stop_reason}")
                break

            # Phát hiện vòng lặp URL (kiểm tra trước resume để chặn đứng vòng lặp kể cả khi dữ liệu đã có trong CSDL)
            if current_url in visited_urls:
                stop_reason = f"Phát hiện vòng lặp URL đã xử lý: {current_url}. Dừng lại để tránh lặp vô tận."
                log("ERROR", f"[DỪNG] {stop_reason}")
                break
            visited_urls.add(current_url)

            # Kiểm tra CSDL xem chương đã tải chưa (Resume)
            existing_chap = self.storage.get_chapter_by_url(current_url)
            if not existing_chap and current_num:
                existing_chap = self.storage.get_chapter_by_num(story.id, current_num)

            if existing_chap and existing_chap.status in ("verified", "downloaded") and existing_chap.raw_content:
                chap_display_num = existing_chap.chapter_num or current_num
                log("INFO", f"[BỎ QUA] Chương {chap_display_num} đã có trong CSDL (Khôi phục tiến độ). Bỏ qua không tải lại.")

                # Chuẩn hóa existing_chap.next_url để tránh dính file:// hoặc path tương đối
                cand_next = existing_chap.next_url or ""
                if cand_next:
                    cand_next = SourceParser._resolve_url(cand_next, current_url=current_url, base_url=story_url)

                current_url = cand_next
                current_num = chap_display_num + 1
                fetched_count += 1
                if on_progress:
                    on_progress(fetched_count, total_to_fetch, f"Đã có: Chương {chap_display_num}")
                continue

            # Tải qua mạng
            log("INFO", f"Đang yêu cầu tải Chương {current_num} tại: {current_url}")
            html_text, err, status_code, diag = self.fetch_url(current_url, story_url=story_url)

            # Ghi log chẩn đoán chi tiết cho yêu cầu HTTP
            log("INFO", (
                f"[CHẨN ĐOÁN] Chương dự kiến: {current_num} | "
                f"URL yêu cầu: {diag.get('requested_url', current_url)} | "
                f"URL sau chuyển hướng: {diag.get('final_url', current_url)} | "
                f"HTTP status: {status_code or 'N/A'} | "
                f"Content-Type: {diag.get('content_type', 'N/A')} | "
                f"Kích thước phản hồi: {diag.get('content_length', 0)} bytes"
            ))

            if err:
                stop_reason = f"Lỗi tải tại Chương {current_num} ({current_url}): {err}"
                log("ERROR", f"[DỪNG] {stop_reason}")
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
            parsed = SourceParser.parse_chapter_html(
                html_text,
                current_url=diag.get("final_url", current_url),
                base_url=story_url,
            )
            if "error" in parsed:
                stop_reason = f"Phân tích thất bại tại Chương {current_num}: {parsed['error']}"
                log("ERROR", f"[DỪNG] {stop_reason}")
                break

            chap_num = parsed["chapter_num"] or current_num
            paragraphs = parsed["paragraphs"]
            para_count = len(paragraphs)
            char_count = len(parsed["raw_content"])
            next_url = parsed["next_url"]
            next_source = parsed.get("next_source", "none")

            # Ghi log chẩn đoán nội dung trích xuất và nguồn liên kết
            log("INFO", (
                f"[CHẨN ĐOÁN] Số chương đọc được: {chap_num} | "
                f"Số đoạn: {para_count} | Số ký tự: {char_count} | "
                f"URL chương tiếp theo: {next_url or '(Không có)'} | "
                f"Nguồn lấy liên kết: {next_source}"
            ))

            chapter = Chapter(
                story_id=story.id,
                chapter_num=chap_num,
                chapter_title=parsed["chapter_title"] or f"Chương {chap_num}",
                source_url=current_url,
                raw_content=parsed["raw_content"],
                content_hash=parsed["content_hash"],
                status="verified",
                prev_url=parsed["prev_url"],
                next_url=next_url,
                warnings=parsed["warnings"],
            )

            self.storage.save_chapter(chapter)
            log("SUCCESS", f"Đã lưu Chương {chap_num}: '{chapter.chapter_title}' ({para_count} đoạn, SHA256: {chapter.content_hash[:8]}...)")

            if on_chapter_saved:
                on_chapter_saved(chapter)

            fetched_count += 1
            if on_progress:
                on_progress(fetched_count, total_to_fetch, f"Hoàn thành Chương {chap_num}")

            # Đã đạt đến số chương kết thúc mong muốn
            if chap_num >= end_chap_num:
                log("SUCCESS", f"Đã thu thập đủ khoảng chương yêu cầu ({start_chap_num} - {end_chap_num}).")
                break

            # Kiểm tra liên kết tiếp theo cho chương tiếp theo
            if not next_url:
                stop_reason = f"Thiếu liên kết chương tiếp theo sau Chương {chap_num}. Không thể tải Chương {chap_num + 1}."
                log("WARNING", f"[DỪNG] {stop_reason}")
                break

            current_url = next_url
            current_num = chap_num + 1

            # Tạm nghỉ delay tôn trọng máy chủ
            time.sleep(self.delay_seconds)

        is_success = (fetched_count == total_to_fetch)
        if is_success:
            status_msg = f"Hoàn thành thu thập đủ: {fetched_count}/{total_to_fetch} chương."
            log("SUCCESS", status_msg)
        else:
            status_msg = f"Chưa hoàn tất: {fetched_count}/{total_to_fetch} chương. Lý do: {stop_reason or 'Tác vụ dừng sớm hơn yêu cầu.'}"
            log("WARNING", status_msg)

        return {
            "success": is_success,
            "fetched_count": fetched_count,
            "total_requested": total_to_fetch,
            "start_chap": start_chap_num,
            "end_chap": end_chap_num,
            "status_message": status_msg,
            "stop_reason": stop_reason,
            "is_stopped": self._is_stopped,
        }
