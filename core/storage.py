"""
SQLite Storage Manager for story chapters, progress tracking, and resuming tasks.
Ensures immutability of original content and detects duplicate hashes, gaps, and missing chapters.
"""
from contextlib import contextmanager
import sqlite3
import json
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from core.models import Chapter, StoryInfo


class StorageManager:
    def __init__(self, db_path: str = "crawler_state.db"):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        """Khởi tạo cấu trúc bảng SQLite nếu chưa tồn tại."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Bảng truyện
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE,
                    title TEXT,
                    author TEXT,
                    total_chapters INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Bảng chương
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chapters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    story_id INTEGER,
                    chapter_num INTEGER,
                    chapter_title TEXT,
                    source_url TEXT UNIQUE,
                    raw_content TEXT,
                    content_hash TEXT,
                    fetch_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'downloaded',
                    prev_url TEXT,
                    next_url TEXT,
                    warnings TEXT,
                    FOREIGN KEY(story_id) REFERENCES stories(id)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chap_num ON chapters(story_id, chapter_num)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chap_hash ON chapters(content_hash)")
            conn.commit()

    def get_or_create_story(self, url: str, title: str = "", author: str = "") -> StoryInfo:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM stories WHERE url = ?", (url,))
            row = cursor.fetchone()
            if row:
                if title and not row["title"]:
                    cursor.execute("UPDATE stories SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (title, row["id"]))
                    conn.commit()
                return StoryInfo(
                    id=row["id"],
                    url=row["url"],
                    title=title or row["title"],
                    author=row["author"],
                    total_chapters=row["total_chapters"],
                )
            cursor.execute(
                "INSERT INTO stories (url, title, author) VALUES (?, ?, ?)",
                (url, title, author),
            )
            conn.commit()
            return StoryInfo(id=cursor.lastrowid, url=url, title=title, author=author)

    def save_chapter(self, chapter: Chapter) -> int:
        """
        Lưu hoặc cập nhật chương vào SQLite.
        Kiểm tra cảnh báo trùng hash với chương khác.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Kiểm tra xem có chương nào khác có cùng content_hash không
            if chapter.content_hash:
                cursor.execute(
                    "SELECT chapter_num, chapter_title FROM chapters WHERE content_hash = ? AND source_url != ?",
                    (chapter.content_hash, chapter.source_url or ""),
                )
                dup = cursor.fetchone()
                if dup:
                    warn = f"Cảnh báo: Nội dung trùng lặp nguyên văn (SHA-256) với Chương {dup['chapter_num']}: {dup['chapter_title']}."
                    if warn not in chapter.warnings:
                        chapter.warnings.append(warn)

            warnings_json = json.dumps(chapter.warnings, ensure_ascii=False)
            fetch_time_str = (
                chapter.fetch_time.isoformat()
                if chapter.fetch_time
                else datetime.now().isoformat()
            )

            # Kiểm tra xem source_url đã tồn tại chưa
            cursor.execute("SELECT id, raw_content FROM chapters WHERE source_url = ?", (chapter.source_url,))
            row = cursor.fetchone()

            if row:
                # Đã có, cập nhật lại trạng thái và metadata, giữ nguyên bản raw nếu đã có
                chap_id = row["id"]
                cursor.execute("""
                    UPDATE chapters SET
                        story_id = COALESCE(?, story_id),
                        chapter_num = COALESCE(?, chapter_num),
                        chapter_title = COALESCE(?, chapter_title),
                        raw_content = COALESCE(?, raw_content),
                        content_hash = COALESCE(?, content_hash),
                        status = ?,
                        prev_url = COALESCE(?, prev_url),
                        next_url = COALESCE(?, next_url),
                        warnings = ?
                    WHERE id = ?
                """, (
                    chapter.story_id,
                    chapter.chapter_num,
                    chapter.chapter_title,
                    chapter.raw_content,
                    chapter.content_hash,
                    chapter.status,
                    chapter.prev_url,
                    chapter.next_url,
                    warnings_json,
                    chap_id,
                ))
                conn.commit()
                chapter.id = chap_id
                return chap_id
            else:
                cursor.execute("""
                    INSERT INTO chapters (
                        story_id, chapter_num, chapter_title, source_url,
                        raw_content, content_hash, fetch_time, status,
                        prev_url, next_url, warnings
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    chapter.story_id,
                    chapter.chapter_num,
                    chapter.chapter_title,
                    chapter.source_url,
                    chapter.raw_content,
                    chapter.content_hash,
                    fetch_time_str,
                    chapter.status,
                    chapter.prev_url,
                    chapter.next_url,
                    warnings_json,
                ))
                conn.commit()
                chap_id = cursor.lastrowid
                chapter.id = chap_id
                return chap_id

    def get_chapter_by_num(self, story_id: int, chapter_num: int) -> Optional[Chapter]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM chapters WHERE story_id = ? AND chapter_num = ?",
                (story_id, chapter_num),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_chapter(row)

    def get_chapter_by_url(self, source_url: str) -> Optional[Chapter]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM chapters WHERE source_url = ?", (source_url,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_chapter(row)

    def get_chapters_range(
        self, story_id: int, start_chap: int, end_chap: int
    ) -> List[Chapter]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM chapters
                WHERE story_id = ? AND chapter_num >= ? AND chapter_num <= ?
                ORDER BY chapter_num ASC
            """, (story_id, start_chap, end_chap))
            rows = cursor.fetchall()
            return [self._row_to_chapter(r) for r in rows]

    def get_all_chapters(self, story_id: int) -> List[Chapter]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM chapters
                WHERE story_id = ?
                ORDER BY chapter_num ASC
            """, (story_id,))
            rows = cursor.fetchall()
            return [self._row_to_chapter(r) for r in rows]

    def detect_gaps_in_range(
        self, story_id: int, start_chap: int, end_chap: int
    ) -> List[int]:
        """Phát hiện các chương bị thiếu trong khoảng [start_chap, end_chap]."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT chapter_num FROM chapters
                WHERE story_id = ? AND chapter_num >= ? AND chapter_num <= ?
                  AND status IN ('downloaded', 'verified')
            """, (story_id, start_chap, end_chap))
            existing = {r["chapter_num"] for r in cursor.fetchall() if r["chapter_num"] is not None}
            missing = [num for num in range(start_chap, end_chap + 1) if num not in existing]
            return missing

    def _row_to_chapter(self, row: sqlite3.Row) -> Chapter:
        warnings = []
        if row["warnings"]:
            try:
                warnings = json.loads(row["warnings"])
            except Exception:
                warnings = [row["warnings"]]

        fetch_time = None
        if row["fetch_time"]:
            try:
                fetch_time = datetime.fromisoformat(row["fetch_time"])
            except Exception:
                pass

        return Chapter(
            id=row["id"],
            story_id=row["story_id"],
            chapter_num=row["chapter_num"],
            chapter_title=row["chapter_title"] or "",
            source_url=row["source_url"] or "",
            raw_content=row["raw_content"] or "",
            content_hash=row["content_hash"] or "",
            fetch_time=fetch_time,
            status=row["status"] or "downloaded",
            prev_url=row["prev_url"] or "",
            next_url=row["next_url"] or "",
            warnings=warnings,
        )
