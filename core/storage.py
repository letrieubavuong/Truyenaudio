"""
SQLite Storage Manager for story chapters, progress tracking, and resuming tasks.
Ensures immutability of original content, manages multi-story isolation,
supports versioning when URLs change content, and persists user review decisions.
"""
from contextlib import contextmanager
import sqlite3
import json
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from core.models import Chapter, StoryInfo, SpellIssue


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
        """Khởi tạo cấu trúc bảng SQLite và thực hiện migration nếu cần."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1. Bảng truyện
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

            # 2. Bảng chương
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chapters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    story_id INTEGER,
                    chapter_num INTEGER,
                    chapter_title TEXT,
                    source_url TEXT UNIQUE,
                    raw_content TEXT,
                    content_hash TEXT,
                    version INTEGER DEFAULT 1,
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

            # Migration: Kiểm tra cột version trong chapters nếu database cũ đã có
            cursor.execute("PRAGMA table_info(chapters)")
            columns = [row["name"] for row in cursor.fetchall()]
            if "version" not in columns:
                try:
                    cursor.execute("ALTER TABLE chapters ADD COLUMN version INTEGER DEFAULT 1")
                except Exception:
                    pass

            # 3. Bảng lưu trữ các phiên bản nội dung khi cùng URL có nội dung mới (Bất biến)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chapter_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chapter_id INTEGER,
                    story_id INTEGER,
                    chapter_num INTEGER,
                    chapter_title TEXT,
                    source_url TEXT,
                    raw_content TEXT,
                    content_hash TEXT,
                    version INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(chapter_id) REFERENCES chapters(id)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ver_chap ON chapter_versions(chapter_id)")

            # 4. Bảng lưu trữ quyết định duyệt lỗi (Audit Review Decisions)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS review_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    issue_id TEXT UNIQUE,
                    story_id INTEGER,
                    chapter_num INTEGER,
                    paragraph_idx INTEGER,
                    char_start INTEGER,
                    char_end INTEGER,
                    original TEXT,
                    replacement TEXT,
                    status TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rev_story ON review_decisions(story_id, chapter_num)")

            conn.commit()

    def get_or_create_story(self, url: str, title: str = "", author: str = "") -> StoryInfo:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM stories WHERE url = ?", (url,))
            row = cursor.fetchone()
            if row:
                if title and not row["title"]:
                    cursor.execute(
                        "UPDATE stories SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (title, row["id"]),
                    )
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

    def get_story_by_url(self, url: str) -> Optional[StoryInfo]:
        """Truy vấn thông tin truyện theo URL."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM stories WHERE url = ?", (url,))
            row = cursor.fetchone()
            if not row:
                return None
            return StoryInfo(
                id=row["id"],
                url=row["url"],
                title=row["title"],
                author=row["author"],
                total_chapters=row["total_chapters"],
            )

    def get_all_stories(self) -> List[StoryInfo]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM stories ORDER BY id ASC")
            rows = cursor.fetchall()
            return [
                StoryInfo(
                    id=r["id"],
                    url=r["url"],
                    title=r["title"],
                    author=r["author"],
                    total_chapters=r["total_chapters"],
                )
                for r in rows
            ]

    def get_default_story_id(self) -> int:
        """Lấy story_id hợp lệ đầu tiên hoặc mới nhất trong CSDL, không dùng số 1 nếu không tồn tại."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM stories ORDER BY id ASC LIMIT 1")
            row = cursor.fetchone()
            if row:
                return row["id"]
            # Nếu chưa có câu chuyện nào, tạo mặc định
            cursor.execute(
                "INSERT INTO stories (url, title) VALUES (?, ?)",
                ("https://vivutruyen.com/truyen/pham-nhan-tu-tien", "Phàm Nhân Tu Tiên"),
            )
            conn.commit()
            return cursor.lastrowid

    def save_chapter(self, chapter: Chapter) -> int:
        """
        Lưu hoặc cập nhật chương vào SQLite.
        BẢO ĐẢM BẤT BIẾN:
        - Nếu cùng source_url có nội dung khác, lưu phiên bản mới vào chapter_versions với hash và thời gian.
        - Phát hiện và cảnh báo nếu cùng chapter_num nhưng khác source_url trong cùng một truyện.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Đảm bảo story_id được thiết lập
            if not chapter.story_id:
                chapter.story_id = self.get_default_story_id()

            # 1. Kiểm tra xem có chương nào khác có cùng chapter_num nhưng khác source_url không
            if chapter.chapter_num is not None:
                cursor.execute(
                    "SELECT id, source_url, chapter_title FROM chapters WHERE story_id = ? AND chapter_num = ? AND source_url != ?",
                    (chapter.story_id, chapter.chapter_num, chapter.source_url or ""),
                )
                diff_source = cursor.fetchone()
                if diff_source:
                    warn = f"Cảnh báo: Chương {chapter.chapter_num} đã tồn tại từ URL khác: {diff_source['source_url']}."
                    if warn not in chapter.warnings:
                        chapter.warnings.append(warn)

            # 2. Kiểm tra xem có chương nào khác có cùng content_hash không
            if chapter.content_hash:
                cursor.execute(
                    "SELECT chapter_num, chapter_title FROM chapters WHERE story_id = ? AND content_hash = ? AND source_url != ?",
                    (chapter.story_id, chapter.content_hash, chapter.source_url or ""),
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

            # 3. Kiểm tra xem source_url đã tồn tại chưa
            cursor.execute("SELECT * FROM chapters WHERE source_url = ?", (chapter.source_url,))
            existing = cursor.fetchone()

            if existing:
                chap_id = existing["id"]
                existing_hash = existing["content_hash"] or ""
                current_ver = existing["version"] or 1

                # BẢN NỘI DUNG GỐC ĐÃ LẤY VỀ LÀ BẤT BIẾN:
                # Nếu nội dung mới khác nội dung cũ (khác hash), lưu phiên bản mới vào chapter_versions
                if chapter.content_hash and chapter.content_hash != existing_hash:
                    new_ver = current_ver + 1
                    cursor.execute("""
                        INSERT INTO chapter_versions (
                            chapter_id, story_id, chapter_num, chapter_title,
                            source_url, raw_content, content_hash, version
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        chap_id,
                        chapter.story_id,
                        chapter.chapter_num,
                        chapter.chapter_title,
                        chapter.source_url,
                        chapter.raw_content,
                        chapter.content_hash,
                        new_ver,
                    ))
                    # Giữ nguyên raw_content gốc của bản đầu tiên để bất biến, cập nhật version và metadata
                    cursor.execute("""
                        UPDATE chapters SET
                            chapter_num = COALESCE(?, chapter_num),
                            chapter_title = COALESCE(?, chapter_title),
                            version = ?,
                            status = ?,
                            prev_url = COALESCE(?, prev_url),
                            next_url = COALESCE(?, next_url),
                            warnings = ?
                        WHERE id = ?
                    """, (
                        chapter.chapter_num,
                        chapter.chapter_title,
                        new_ver,
                        chapter.status,
                        chapter.prev_url,
                        chapter.next_url,
                        warnings_json,
                        chap_id,
                    ))
                else:
                    # Cùng nội dung, chỉ cập nhật metadata
                    cursor.execute("""
                        UPDATE chapters SET
                            chapter_num = COALESCE(?, chapter_num),
                            chapter_title = COALESCE(?, chapter_title),
                            status = ?,
                            prev_url = COALESCE(?, prev_url),
                            next_url = COALESCE(?, next_url),
                            warnings = ?
                        WHERE id = ?
                    """, (
                        chapter.chapter_num,
                        chapter.chapter_title,
                        chapter.status,
                        chapter.prev_url,
                        chapter.next_url,
                        warnings_json,
                        chap_id,
                    ))

                conn.commit()
                chapter.id = chap_id
                chapter.version = current_ver
                return chap_id
            else:
                cursor.execute("""
                    INSERT INTO chapters (
                        story_id, chapter_num, chapter_title, source_url,
                        raw_content, content_hash, version, fetch_time, status,
                        prev_url, next_url, warnings
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    chapter.story_id,
                    chapter.chapter_num,
                    chapter.chapter_title,
                    chapter.source_url,
                    chapter.raw_content,
                    chapter.content_hash,
                    1,
                    fetch_time_str,
                    chapter.status,
                    chapter.prev_url,
                    chapter.next_url,
                    warnings_json,
                ))
                conn.commit()
                chap_id = cursor.lastrowid
                chapter.id = chap_id
                chapter.version = 1
                return chap_id

    def get_chapter_by_num(self, story_id: Optional[int], chapter_num: int) -> Optional[Chapter]:
        s_id = story_id if story_id is not None else self.get_default_story_id()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM chapters WHERE story_id = ? AND chapter_num = ?",
                (s_id, chapter_num),
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
        self, story_id: Optional[int], start_chap: int, end_chap: int
    ) -> List[Chapter]:
        s_id = story_id if story_id is not None else self.get_default_story_id()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM chapters
                WHERE story_id = ? AND chapter_num >= ? AND chapter_num <= ?
                ORDER BY chapter_num ASC
            """, (s_id, start_chap, end_chap))
            rows = cursor.fetchall()
            return [self._row_to_chapter(r) for r in rows]

    def get_all_chapters(self, story_id: Optional[int] = None) -> List[Chapter]:
        s_id = story_id if story_id is not None else self.get_default_story_id()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM chapters
                WHERE story_id = ?
                ORDER BY chapter_num ASC
            """, (s_id,))
            rows = cursor.fetchall()
            return [self._row_to_chapter(r) for r in rows]

    def detect_gaps_in_range(
        self, story_id: Optional[int], start_chap: int, end_chap: int
    ) -> List[int]:
        s_id = story_id if story_id is not None else self.get_default_story_id()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT chapter_num FROM chapters
                WHERE story_id = ? AND chapter_num >= ? AND chapter_num <= ?
                  AND status IN ('downloaded', 'verified')
            """, (s_id, start_chap, end_chap))
            existing = {r["chapter_num"] for r in cursor.fetchall() if r["chapter_num"] is not None}
            missing = [num for num in range(start_chap, end_chap + 1) if num not in existing]
            return missing

    def save_review_decisions(self, story_id: Optional[int], issues: List[SpellIssue]):
        """Lưu hoặc cập nhật trạng thái duyệt (applied/rejected) của người dùng vào CSDL."""
        s_id = story_id if story_id is not None else self.get_default_story_id()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for iss in issues:
                cursor.execute("""
                    INSERT INTO review_decisions (
                        issue_id, story_id, chapter_num, paragraph_idx,
                        char_start, char_end, original, replacement, status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(issue_id) DO UPDATE SET
                        status = excluded.status,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    iss.id,
                    s_id,
                    iss.chapter_num,
                    iss.paragraph_idx,
                    iss.char_start,
                    iss.char_end,
                    iss.original,
                    iss.replacement,
                    iss.status,
                ))
            conn.commit()

    def get_review_decisions(self, story_id: Optional[int] = None) -> Dict[str, str]:
        """Tải các quyết định duyệt đã lưu (issue_id -> status)."""
        s_id = story_id if story_id is not None else self.get_default_story_id()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT issue_id, status FROM review_decisions WHERE story_id = ?",
                (s_id,),
            )
            rows = cursor.fetchall()
            return {r["issue_id"]: r["status"] for r in rows}

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

        ver = 1
        if "version" in row.keys() and row["version"] is not None:
            ver = row["version"]

        return Chapter(
            id=row["id"],
            story_id=row["story_id"],
            chapter_num=row["chapter_num"],
            chapter_title=row["chapter_title"] or "",
            source_url=row["source_url"] or "",
            raw_content=row["raw_content"] or "",
            content_hash=row["content_hash"] or "",
            version=ver,
            fetch_time=fetch_time,
            status=row["status"] or "downloaded",
            prev_url=row["prev_url"] or "",
            next_url=row["next_url"] or "",
            warnings=warnings,
        )
