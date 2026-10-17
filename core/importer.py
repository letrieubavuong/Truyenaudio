"""
Offline Chapter Importer for HTML and TXT files.
Ensures seamless workflow when network crawling is restricted or when processing offline archives.
Extracts chapters, verifies integrity, sorts, and stores into SQLite.
"""
import os
import re
from typing import Optional, Callable, List
from core.models import Chapter, StoryInfo
from core.parser import SourceParser
from core.storage import StorageManager
from core.profiles import get_profile, detect_source_from_url


class OfflineImporter:
    def __init__(self, storage: StorageManager):
        self.storage = storage

    def import_directory(
        self,
        directory_path: str,
        story_url: str = "",
        story_title: str = "",
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        on_log: Optional[Callable[[str, str], None]] = None,
    ) -> List[Chapter]:
        """
        Quét và nạp tất cả các file HTML hoặc TXT trong thư mục vào CSDL.
        Hỗ trợ HTML lưu từ trình duyệt nguồn TamHoan, Webnovel, Vivutruyen.
        Bảo toàn thông tin nguồn, URL canonical, không dùng file:// làm link tải mạng.
        """
        def log(level: str, msg: str):
            if on_log:
                on_log(level, msg)

        if not os.path.exists(directory_path):
            log("ERROR", f"Thư mục không tồn tại: {directory_path}")
            return []

        profile = get_profile(story_url or story_title or "pham-nhan-tu-tien")
        final_url = story_url or profile.story_url
        final_title = story_title or profile.title
        final_author = profile.author

        story = self.storage.get_or_create_story(url=final_url, title=final_title, author=final_author)

        # Lấy danh sách file được hỗ trợ
        supported_exts = (".html", ".htm", ".txt")
        files = [
            f for f in os.listdir(directory_path)
            if os.path.isfile(os.path.join(directory_path, f)) and f.lower().endswith(supported_exts)
        ]

        if not files:
            log("WARNING", f"Không tìm thấy file .html hoặc .txt nào trong {directory_path}")
            return []

        # Sắp xếp tự nhiên theo số chương trong tên file
        def natural_sort_key(filename: str):
            match = re.search(r"(\d+)", filename)
            return int(match.group(1)) if match else 999999

        files.sort(key=natural_sort_key)
        total_files = len(files)
        log("INFO", f"Tìm thấy {total_files} tệp trong thư mục. Đang tiến hành phân tích và nhập...")

        imported_chapters: List[Chapter] = []

        for idx, filename in enumerate(files, 1):
            filepath = os.path.join(directory_path, filename)
            ext = os.path.splitext(filename)[1].lower()

            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

                detected_canonical = ""
                if ext in (".html", ".htm"):
                    # Kiểm tra canonical URL hoặc og:url từ HTML đã lưu của trình duyệt
                    m_canon = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', content, re.IGNORECASE)
                    if not m_canon:
                        m_canon = re.search(r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']', content, re.IGNORECASE)
                    if not m_canon:
                        m_canon = re.search(r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']', content, re.IGNORECASE)
                    if m_canon:
                        cand_url = m_canon.group(1).strip()
                        if cand_url.startswith("http://") or cand_url.startswith("https://"):
                            detected_canonical = cand_url

                # Nhận diện nguồn
                source_id = ""
                if detected_canonical:
                    source_id = detect_source_from_url(detected_canonical)
                if not source_id:
                    source_id = SourceParser.detect_source(content, current_url=detected_canonical, base_url=story_url)

                # Xác định base URL
                if source_id == "tamhoan":
                    web_base = "https://tamhoan.com"
                elif source_id == "webnovel":
                    web_base = "https://webnovel.vn"
                else:
                    web_base = story_url if story_url.startswith("http") else "https://vivutruyen.com"

                if ext in (".html", ".htm"):
                    parsed = SourceParser.parse_chapter_html(
                        content,
                        current_url=detected_canonical or f"file://{filepath}",
                        base_url=web_base,
                    )
                else:
                    parsed = SourceParser.parse_raw_text_file(content, default_filename=filename)

                chap_num = parsed.get("chapter_num")
                # Nếu parser chưa tìm thấy số chương, thử trích xuất từ tên file
                if chap_num is None:
                    m_f = re.search(r"(?:chuong|chap|c)[-_\s]*(\d+)", filename, re.IGNORECASE)
                    if m_f:
                        chap_num = int(m_f.group(1))
                    else:
                        m_any = re.search(r"(\d+)", filename)
                        # Nếu là số quá lớn (như ID bài viết 205299 trên tamhoan), không tự ý coi là số chương
                        if m_any:
                            num_val = int(m_any.group(1))
                            if num_val < 50000:
                                chap_num = num_val

                warnings = list(parsed.get("warnings", []))
                if chap_num is None:
                    warn_msg = f"Không xác định được số chương từ tệp '{filename}'. Vui lòng bổ sung hoặc đổi tên tệp (ví dụ: chuong_1.html)."
                    log("WARNING", warn_msg)
                    warnings.append(warn_msg)

                # Tuyệt đối không sử dụng đường dẫn file:// làm URL chương tiếp để crawler tải mạng
                raw_next = parsed.get("next_url", "")
                raw_prev = parsed.get("prev_url", "")
                next_url = ""
                prev_url = ""
                if raw_next and (raw_next.startswith("http://") or raw_next.startswith("https://")):
                    next_url = SourceParser._resolve_url(raw_next, base_url=web_base)
                if raw_prev and (raw_prev.startswith("http://") or raw_prev.startswith("https://")):
                    prev_url = SourceParser._resolve_url(raw_prev, base_url=web_base)

                final_source_url = detected_canonical if detected_canonical else f"file://{os.path.abspath(filepath)}"

                chapter = Chapter(
                    story_id=story.id,
                    chapter_num=chap_num,
                    chapter_title=parsed["chapter_title"] or (f"Chương {chap_num}" if chap_num else filename),
                    source_url=final_source_url,
                    raw_content=parsed["raw_content"],
                    content_hash=parsed["content_hash"],
                    status="verified" if (chap_num is not None and parsed["raw_content"].strip()) else "downloaded",
                    prev_url=prev_url,
                    next_url=next_url,
                    warnings=warnings,
                    source=source_id,
                )

                self.storage.save_chapter(chapter)
                imported_chapters.append(chapter)

                num_label = f"Chương {chap_num}" if chap_num else "Chương (chưa xác định)"
                log("SUCCESS", f"Đã nhập: {filename} -> {num_label}: '{chapter.chapter_title}' ({len(parsed['paragraphs'])} đoạn, Nguồn: {source_id or 'offline'})")
                if on_progress:
                    on_progress(idx, total_files, f"Đã nhập {filename}")

            except Exception as e:
                log("ERROR", f"Lỗi khi đọc file {filename}: {str(e)}")

        log("INFO", f"Hoàn tất nạp offline: {len(imported_chapters)}/{total_files} chương đã lưu vào CSDL.")
        return imported_chapters
