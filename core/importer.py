"""
Offline Chapter Importer for HTML and TXT files.
Ensures seamless workflow when network crawling is restricted or when processing offline archives.
Extracts chapters, verifies integrity, sorts, and stores into SQLite.
"""
import os
import re
from typing import List, Dict, Any, Optional, Callable
from core.models import Chapter, StoryInfo
from core.parser import SourceParser
from core.storage import StorageManager


class OfflineImporter:
    def __init__(self, storage: StorageManager):
        self.storage = storage

    def import_directory(
        self,
        directory_path: str,
        story_url: str = "offline://local-story",
        story_title: str = "Phàm Nhân Tu Tiên",
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        on_log: Optional[Callable[[str, str], None]] = None,
    ) -> List[Chapter]:
        """
        Quét và nạp tất cả các file HTML hoặc TXT trong thư mục vào CSDL.
        """
        def log(level: str, msg: str):
            if on_log:
                on_log(level, msg)

        if not os.path.exists(directory_path):
            log("ERROR", f"Thư mục không tồn tại: {directory_path}")
            return []

        story = self.storage.get_or_create_story(url=story_url, title=story_title)

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

                if ext in (".html", ".htm"):
                    parsed = SourceParser.parse_chapter_html(content, current_url=f"file://{filepath}")
                else:
                    parsed = SourceParser.parse_raw_text_file(content, default_filename=filename)

                chap_num = parsed["chapter_num"]
                # Nếu parser chưa tìm thấy số chương, thử trích xuất từ tên file
                if chap_num is None:
                    m = re.search(r"(\d+)", filename)
                    if m:
                        chap_num = int(m.group(1))

                chapter = Chapter(
                    story_id=story.id,
                    chapter_num=chap_num,
                    chapter_title=parsed["chapter_title"] or f"Chương {chap_num or idx}",
                    source_url=f"file://{os.path.abspath(filepath)}",
                    raw_content=parsed["raw_content"],
                    content_hash=parsed["content_hash"],
                    status="verified",
                    prev_url=parsed.get("prev_url", ""),
                    next_url=parsed.get("next_url", ""),
                    warnings=parsed.get("warnings", []),
                )

                self.storage.save_chapter(chapter)
                imported_chapters.append(chapter)

                log("SUCCESS", f"Đã nhập: {filename} -> Chương {chap_num}: '{chapter.chapter_title}' ({len(parsed['paragraphs'])} đoạn)")
                if on_progress:
                    on_progress(idx, total_files, f"Đã nhập {filename}")

            except Exception as e:
                log("ERROR", f"Lỗi khi đọc file {filename}: {str(e)}")

        log("INFO", f"Hoàn tất nạp offline: {len(imported_chapters)}/{total_files} chương đã lưu vào CSDL.")
        return imported_chapters
