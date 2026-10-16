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
import re
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
        seen_content_hashes: Set[str] = set()
        current_url = SourceParser._resolve_url(start_chapter_url, base_url=story_url)
        current_num = start_chap_num
        total_to_fetch = end_chap_num - start_chap_num + 1
        cached_count = 0
        downloaded_count = 0
        stop_reason: Optional[str] = None
        status_category: str = "completed"
        last_processed_chap_num: Optional[int] = None

        # Nếu start_chap_num > 1 và URL bắt đầu truyền vào là chương 1 (hoặc mặc định),
        # kiểm tra xem CSDL đã có URL trực tiếp của start_chap_num không để tối ưu điểm xuất phát
        if start_chap_num > 1 and current_url and ("chuong-1-" in current_url or "c-1" in current_url):
            target_chap = self.storage.get_chapter_by_num(story.id, start_chap_num)
            if target_chap and target_chap.source_url and target_chap.source_url.startswith("http"):
                current_url = target_chap.source_url
                log("INFO", f"Tự động điều chỉnh URL bắt đầu tới Chương {start_chap_num} từ CSDL: {current_url}")

        while current_num <= end_chap_num:
            if self._is_stopped:
                stop_reason = "Đã dừng thu thập theo yêu cầu người dùng."
                status_category = "stopped_by_user"
                log("WARNING", f"[DỪNG] {stop_reason}")
                break

            while self._is_paused:
                if self._is_stopped:
                    break
                time.sleep(0.5)

            # Kiểm tra nếu mất liên kết URL chương tiếp theo
            if not current_url:
                stop_reason = f"Thiếu liên kết để tải Chương {current_num} (chương trước không cung cấp liên kết kế tiếp)."
                status_category = "incomplete"
                log("WARNING", f"[DỪNG] {stop_reason}")
                break

            # Phát hiện vòng lặp URL (kiểm tra trước resume để chặn đứng vòng lặp kể cả khi dữ liệu đã có trong CSDL)
            if current_url in visited_urls:
                stop_reason = f"Phát hiện vòng lặp URL đã xử lý: {current_url}. Dừng lại để tránh lặp vô tận."
                status_category = "incomplete"
                log("ERROR", f"[DỪNG] {stop_reason}")
                break
            visited_urls.add(current_url)

            # Kiểm tra CSDL xem chương đã tải chưa (Resume)
            existing_chap = self.storage.get_chapter_by_url(current_url)
            if not existing_chap:
                # Trích xuất số chương từ URL (ví dụ: chuong-1, c-1)
                m_num = re.search(r"(?:chuong|c)[-_](\d+)", current_url, re.IGNORECASE)
                cand_chap_num = int(m_num.group(1)) if m_num else current_num
                if cand_chap_num:
                    cand_chap = self.storage.get_chapter_by_num(story.id, cand_chap_num)
                    if cand_chap:
                        is_offline = not cand_chap.source_url or not cand_chap.source_url.startswith("http")
                        same_slug = bool(m_num and cand_chap.source_url and f"chuong-{cand_chap_num}" in cand_chap.source_url.lower())
                        if is_offline or same_slug:
                            existing_chap = cand_chap

            if existing_chap and existing_chap.status in ("verified", "downloaded") and existing_chap.raw_content:
                chap_display_num = existing_chap.chapter_num or current_num
                last_processed_chap_num = chap_display_num
                if existing_chap.content_hash:
                    seen_content_hashes.add(existing_chap.content_hash)

                # Chuẩn hóa existing_chap.next_url để tránh dính file:// hoặc path tương đối
                cand_next = existing_chap.next_url or ""
                if cand_next:
                    cand_next = SourceParser._resolve_url(cand_next, current_url=current_url, base_url=story_url)

                # Nếu cần tải tiếp (chưa tới end_chap_num) mà bản lưu lại thiếu next_url:
                # Không được coi là đủ dữ liệu; tiến hành tải lại trang chương hiện tại để khôi phục điều hướng
                needs_more = (chap_display_num < end_chap_num or current_num < end_chap_num)
                if needs_more and (not cand_next or not cand_next.strip()):
                    refetch_url = (
                        existing_chap.source_url
                        if (existing_chap.source_url and existing_chap.source_url.startswith("http"))
                        else (current_url if current_url.startswith("http") else "")
                    )
                    if refetch_url:
                        log("INFO", f"Chương {chap_display_num} trong CSDL thiếu liên kết kế tiếp. Đang tải lại '{refetch_url}' để khôi phục điều hướng...")
                        re_html, re_err, re_status, re_diag = self.fetch_url(refetch_url, story_url=story_url)
                        if re_status in (403, 429):
                            stop_reason = f"Máy chủ trả về HTTP {re_status} khi tải lại Chương {chap_display_num} để khôi phục điều hướng."
                            status_category = "blocked"
                            log("ERROR", f"[DỪNG] {stop_reason}")
                            break
                        if re_err:
                            stop_reason = f"Lỗi tải lại trang Chương {chap_display_num} để khôi phục điều hướng: {re_err}"
                            status_category = "network_error"
                            log("ERROR", f"[DỪNG] {stop_reason}")
                            break
                        if re_html:
                            re_refetch = re_diag.get("final_url", refetch_url)
                            re_parsed = SourceParser.parse_chapter_html(re_html, current_url=re_refetch, base_url=story_url)
                            rec_next = re_parsed.get("next_url", "")
                            if rec_next:
                                cand_next = SourceParser._resolve_url(rec_next, current_url=re_refetch, base_url=story_url)
                                if existing_chap.id:
                                    self.storage.update_chapter_navigation(existing_chap.id, next_url=cand_next)
                                log("SUCCESS", f"Đã khôi phục thành công liên kết kế tiếp từ trang mạng: {cand_next} (Nguồn: {re_parsed.get('next_source', 'web')})")

                if needs_more and (not cand_next or not cand_next.strip()):
                    stop_reason = f"Không tìm thấy liên kết chương tiếp theo sau Chương {chap_display_num} (bản lưu thiếu liên kết và tải lại trang không tìm thấy)."
                    status_category = "incomplete"
                    log("WARNING", f"[DỪNG] {stop_reason}")
                    if chap_display_num >= start_chap_num:
                        cached_count += 1
                    break

                current_url = cand_next

                # Phân biệt giữa chương trong dải [start_chap_num, end_chap_num]
                # và chương nằm trước dải cần tải (tua nhanh qua cache để đến điểm xuất phát)
                if chap_display_num >= start_chap_num:
                    log("INFO", f"[BỎ QUA] Chương {chap_display_num} đã có trong CSDL (Khôi phục tiến độ). Bỏ qua không tải lại.")
                    cached_count += 1
                    current_num = max(current_num, chap_display_num + 1)
                    if on_progress:
                        on_progress(cached_count + downloaded_count, total_to_fetch, f"Đã có: Chương {chap_display_num}")
                else:
                    log("INFO", f"[TUA NHANH] Chương {chap_display_num} đã có trong CSDL (Đang tìm tới Chương {start_chap_num}).")
                    current_num = max(start_chap_num, chap_display_num + 1)
                    if on_progress:
                        on_progress(cached_count + downloaded_count, total_to_fetch, f"Đang tua tới Chương {start_chap_num}...")

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
                if status_code in (403, 429) or "cloudflare" in err.lower() or "captcha" in err.lower():
                    status_category = "blocked"
                    stop_reason = f"Bị chặn truy cập (HTTP {status_code}) tại Chương {current_num} ({current_url}): {err}"
                elif any(k in err.lower() for k in ["thời gian chờ", "kết nối mạng", "timed out", "timeout", "connection"]):
                    status_category = "network_error"
                    stop_reason = f"Lỗi kết nối mạng tại Chương {current_num} ({current_url}): {err}"
                else:
                    status_category = "network_error" if (status_code == 0 or status_code is None) else "incomplete"
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
                status_category = "parse_error"
                log("ERROR", f"[DỪNG] {stop_reason}")
                break

            chap_num = parsed["chapter_num"] or current_num
            paragraphs = parsed["paragraphs"]
            para_count = len(paragraphs)
            char_count = len(parsed["raw_content"])
            next_url = parsed["next_url"]
            next_source = parsed.get("next_source", "none")
            content_hash = parsed["content_hash"]

            # Kiểm tra nội dung rỗng hoặc trang không hợp lệ (Không đánh dấu verified)
            if not parsed["raw_content"].strip() or para_count == 0:
                stop_reason = f"Phát hiện nội dung rỗng hoặc trang không hợp lệ tại Chương {current_num} ({current_url})."
                status_category = "parse_error"
                log("ERROR", f"[DỪNG] {stop_reason}")
                failed_chap = Chapter(
                    story_id=story.id,
                    chapter_num=current_num,
                    chapter_title=f"Chương {current_num} (Nội dung rỗng/lỗi)",
                    source_url=current_url,
                    raw_content="",
                    status="failed",
                    warnings=[stop_reason],
                )
                self.storage.save_chapter(failed_chap)
                break

            # Phát hiện nội dung trùng lặp bất thường (chuyển hướng ngầm hoặc trang lỗi)
            if content_hash in seen_content_hashes:
                stop_reason = f"Phát hiện nội dung trùng lặp bất thường với chương đã tải trước đó (SHA256: {content_hash[:8]}...). Trang có thể bị lặp hoặc chuyển hướng ngầm."
                status_category = "incomplete"
                log("ERROR", f"[DỪNG] {stop_reason}")
                break
            seen_content_hashes.add(content_hash)

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
                content_hash=content_hash,
                status="verified",
                prev_url=parsed["prev_url"],
                next_url=next_url,
                warnings=parsed["warnings"],
            )

            self.storage.save_chapter(chapter)
            log("SUCCESS", f"Đã lưu Chương {chap_num}: '{chapter.chapter_title}' ({para_count} đoạn, SHA256: {content_hash[:8]}...)")

            if on_chapter_saved:
                on_chapter_saved(chapter)

            downloaded_count += 1
            last_processed_chap_num = chap_num
            if on_progress:
                on_progress(cached_count + downloaded_count, total_to_fetch, f"Hoàn thành Chương {chap_num}")

            # Đã đạt đến số chương kết thúc mong muốn
            if chap_num >= end_chap_num:
                log("SUCCESS", f"Đã thu thập đủ khoảng chương yêu cầu ({start_chap_num} - {end_chap_num}).")
                break

            # Kiểm tra liên kết tiếp theo cho chương tiếp theo
            if not next_url:
                stop_reason = f"Thiếu liên kết chương tiếp theo sau Chương {chap_num}. Không thể tải Chương {chap_num + 1}."
                status_category = "incomplete"
                log("WARNING", f"[DỪNG] {stop_reason}")
                break

            current_url = next_url
            current_num = max(current_num, chap_num + 1)

            # Tạm nghỉ delay tôn trọng máy chủ
            time.sleep(self.delay_seconds)

        fetched_count = cached_count + downloaded_count
        missing_count = max(0, total_to_fetch - fetched_count)
        has_reached_end = (downloaded_count > 0 or cached_count > 0) and (
            (last_processed_chap_num is not None and last_processed_chap_num >= end_chap_num)
            or current_num > end_chap_num
        )
        is_completed = (status_category == "completed") and (
            (fetched_count >= total_to_fetch and missing_count == 0) or has_reached_end
        )

        if is_completed:
            status_category = "completed"
            status_msg = f"Hoàn tất thu thập đủ: {fetched_count}/{total_to_fetch} chương (Tải mới: {downloaded_count}, Từ cache: {cached_count})."
            log("SUCCESS", status_msg)
        else:
            if not status_category or status_category == "completed":
                status_category = "incomplete"
            status_msg = (
                f"Chưa hoàn tất: {fetched_count}/{total_to_fetch} chương "
                f"(Tải mới: {downloaded_count}, Từ cache: {cached_count}, Còn thiếu: {missing_count}). "
                f"Lý do: {stop_reason or 'Tác vụ dừng sớm hơn yêu cầu.'}"
            )
            log("WARNING", status_msg)

        return {
            "success": is_completed,
            "status": status_category,
            "fetched_count": fetched_count,
            "cached_count": cached_count,
            "downloaded_count": downloaded_count,
            "missing_count": missing_count,
            "total_requested": total_to_fetch,
            "start_chap": start_chap_num,
            "end_chap": end_chap_num,
            "status_message": status_msg,
            "stop_reason": stop_reason,
            "is_stopped": self._is_stopped,
        }
