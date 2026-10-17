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

            # Migration: Kiểm tra cột version và source trong chapters nếu database cũ đã có
            cursor.execute("PRAGMA table_info(chapters)")
            columns = [row["name"] for row in cursor.fetchall()]
            if "version" not in columns:
                try:
                    cursor.execute("ALTER TABLE chapters ADD COLUMN version INTEGER DEFAULT 1")
                except Exception:
                    pass
            if "source" not in columns:
                try:
                    cursor.execute("ALTER TABLE chapters ADD COLUMN source TEXT DEFAULT ''")
                    cursor.execute("UPDATE chapters SET source = 'webnovel' WHERE (source IS NULL OR source = '') AND source_url LIKE '%webnovel.vn%'")
                    cursor.execute("UPDATE chapters SET source = 'tamhoan' WHERE (source IS NULL OR source = '') AND source_url LIKE '%tamhoan.com%'")
                    cursor.execute("UPDATE chapters SET source = 'vivutruyen' WHERE (source IS NULL OR source = '') AND source_url LIKE '%vivutruyen.com%'")
                except Exception:
                    pass
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chap_source_num ON chapters(story_id, source, chapter_num)")

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

            # 4. Bảng lưu trữ quyết định duyệt lỗi (Audit Review Decisions) đa truyện, phân biệt theo phiên bản/hash nội dung
            cursor.execute("PRAGMA table_info(review_decisions)")
            rev_cols = [row["name"] for row in cursor.fetchall()]
            if rev_cols and "content_hash" not in rev_cols:
                # Migration an toàn: Di chuyển CSDL cũ sang bảng v2 có ràng buộc đa truyện & hash
                story_expr = "COALESCE(story_id, 1)" if "story_id" in rev_cols else "1"
                chap_expr = "chapter_num" if "chapter_num" in rev_cols else "NULL"
                para_expr = "paragraph_idx" if "paragraph_idx" in rev_cols else "NULL"
                cstart_expr = "char_start" if "char_start" in rev_cols else "NULL"
                cend_expr = "char_end" if "char_end" in rev_cols else "NULL"
                orig_expr = "original" if "original" in rev_cols else "NULL"
                rep_expr = "replacement" if "replacement" in rev_cols else "NULL"
                stat_expr = "status" if "status" in rev_cols else "'applied'"
                time_expr = "updated_at" if "updated_at" in rev_cols else "CURRENT_TIMESTAMP"

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS review_decisions_v2 (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        story_id INTEGER NOT NULL,
                        content_hash TEXT NOT NULL,
                        issue_id TEXT NOT NULL,
                        chapter_num INTEGER,
                        paragraph_idx INTEGER,
                        char_start INTEGER,
                        char_end INTEGER,
                        original TEXT,
                        replacement TEXT,
                        source TEXT,
                        status TEXT,
                        user_decision TEXT,
                        applied_status TEXT,
                        applied_reason TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(story_id, content_hash, issue_id, original, replacement)
                    )
                """)
                cursor.execute(f"""
                    INSERT OR IGNORE INTO review_decisions_v2 (
                        id, story_id, content_hash, issue_id, chapter_num, paragraph_idx,
                        char_start, char_end, original, replacement, status, updated_at
                    )
                    SELECT
                        id, {story_expr}, 'legacy_unverified', issue_id, {chap_expr}, {para_expr},
                        {cstart_expr}, {cend_expr}, {orig_expr}, {rep_expr}, {stat_expr}, {time_expr}
                    FROM review_decisions
                """)
                cursor.execute("DROP TABLE review_decisions")
                cursor.execute("ALTER TABLE review_decisions_v2 RENAME TO review_decisions")
            elif not rev_cols:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS review_decisions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        story_id INTEGER NOT NULL,
                        content_hash TEXT NOT NULL,
                        issue_id TEXT NOT NULL,
                        chapter_num INTEGER,
                        paragraph_idx INTEGER,
                        char_start INTEGER,
                        char_end INTEGER,
                        original TEXT,
                        replacement TEXT,
                        source TEXT,
                        status TEXT,
                        user_decision TEXT,
                        applied_status TEXT,
                        applied_reason TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(story_id, content_hash, issue_id, original, replacement)
                    )
                """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rev_lookup ON review_decisions(story_id, content_hash)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rev_story_chap ON review_decisions(story_id, chapter_num)")

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

            # Tự động nhận diện source nếu chapter chưa có
            if not getattr(chapter, "source", ""):
                if chapter.source_url:
                    from core.profiles import detect_source_from_url
                    chapter.source = detect_source_from_url(chapter.source_url) or ""
                if not getattr(chapter, "source", "") and chapter.story_id:
                    cursor.execute("SELECT url FROM stories WHERE id = ?", (chapter.story_id,))
                    st_row = cursor.fetchone()
                    if st_row and st_row["url"]:
                        from core.profiles import detect_source_from_url
                        chapter.source = detect_source_from_url(st_row["url"]) or ""

            # 1. Kiểm tra xem có chương nào khác có cùng chapter_num trong CÙNG source không
            if chapter.chapter_num is not None:
                if chapter.source:
                    cursor.execute(
                        "SELECT id, source_url, chapter_title FROM chapters WHERE story_id = ? AND source = ? AND chapter_num = ? AND source_url != ?",
                        (chapter.story_id, chapter.source, chapter.chapter_num, chapter.source_url or ""),
                    )
                else:
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
                            warnings = ?,
                            source = CASE WHEN ? != '' THEN ? ELSE source END
                        WHERE id = ?
                    """, (
                        chapter.chapter_num,
                        chapter.chapter_title,
                        new_ver,
                        chapter.status,
                        chapter.prev_url,
                        chapter.next_url,
                        warnings_json,
                        chapter.source or "",
                        chapter.source or "",
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
                            warnings = ?,
                            source = CASE WHEN ? != '' THEN ? ELSE source END
                        WHERE id = ?
                    """, (
                        chapter.chapter_num,
                        chapter.chapter_title,
                        chapter.status,
                        chapter.prev_url,
                        chapter.next_url,
                        warnings_json,
                        chapter.source or "",
                        chapter.source or "",
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
                        prev_url, next_url, warnings, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    chapter.source or "",
                ))
                conn.commit()
                chap_id = cursor.lastrowid
                chapter.id = chap_id
                chapter.version = 1
                return chap_id

    def get_chapter_by_num(self, story_id: Optional[int], chapter_num: int, source: str = "") -> Optional[Chapter]:
        s_id = story_id if story_id is not None else self.get_default_story_id()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            row = None
            if source:
                cursor.execute(
                    "SELECT * FROM chapters WHERE story_id = ? AND source = ? AND chapter_num = ?",
                    (s_id, source, chapter_num),
                )
                row = cursor.fetchone()
                if not row:
                    cursor.execute(
                        "SELECT * FROM chapters WHERE story_id = ? AND (source = '' OR source IS NULL) AND chapter_num = ?",
                        (s_id, chapter_num),
                    )
                    row = cursor.fetchone()
            else:
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
        self, story_id: Optional[int], start_chap: int, end_chap: int, source: str = ""
    ) -> List[Chapter]:
        s_id = story_id if story_id is not None else self.get_default_story_id()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            rows = []
            if source:
                cursor.execute("""
                    SELECT * FROM chapters
                    WHERE story_id = ? AND source = ? AND chapter_num >= ? AND chapter_num <= ?
                    ORDER BY chapter_num ASC
                """, (s_id, source, start_chap, end_chap))
                rows = cursor.fetchall()
                if not rows:
                    cursor.execute("""
                        SELECT * FROM chapters
                        WHERE story_id = ? AND (source = '' OR source IS NULL) AND chapter_num >= ? AND chapter_num <= ?
                        ORDER BY chapter_num ASC
                    """, (s_id, start_chap, end_chap))
                    rows = cursor.fetchall()
            else:
                cursor.execute("""
                    SELECT * FROM chapters
                    WHERE story_id = ? AND chapter_num >= ? AND chapter_num <= ?
                    ORDER BY chapter_num ASC
                """, (s_id, start_chap, end_chap))
                rows = cursor.fetchall()
            return [self._row_to_chapter(r) for r in rows]

    def get_all_chapters(self, story_id: Optional[int] = None, source: str = "") -> List[Chapter]:
        s_id = story_id if story_id is not None else self.get_default_story_id()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            rows = []
            if source:
                cursor.execute("""
                    SELECT * FROM chapters
                    WHERE story_id = ? AND source = ?
                    ORDER BY chapter_num ASC
                """, (s_id, source))
                rows = cursor.fetchall()
                if not rows:
                    cursor.execute("""
                        SELECT * FROM chapters
                        WHERE story_id = ? AND (source = '' OR source IS NULL)
                        ORDER BY chapter_num ASC
                    """, (s_id,))
                    rows = cursor.fetchall()
            else:
                cursor.execute("""
                    SELECT * FROM chapters
                    WHERE story_id = ?
                    ORDER BY chapter_num ASC
                """, (s_id,))
                rows = cursor.fetchall()
            return [self._row_to_chapter(r) for r in rows]

    def detect_gaps_in_range(
        self, story_id: Optional[int], start_chap: int, end_chap: int, source: str = ""
    ) -> List[int]:
        s_id = story_id if story_id is not None else self.get_default_story_id()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if source:
                cursor.execute("""
                    SELECT chapter_num FROM chapters
                    WHERE story_id = ? AND source = ? AND chapter_num >= ? AND chapter_num <= ?
                      AND status IN ('downloaded', 'verified')
                """, (s_id, source, start_chap, end_chap))
            else:
                cursor.execute("""
                    SELECT chapter_num FROM chapters
                    WHERE story_id = ? AND chapter_num >= ? AND chapter_num <= ?
                      AND status IN ('downloaded', 'verified')
                """, (s_id, start_chap, end_chap))
            existing = {r["chapter_num"] for r in cursor.fetchall() if r["chapter_num"] is not None}
            missing = [num for num in range(start_chap, end_chap + 1) if num not in existing]
            return missing

    def update_chapter_navigation(
        self, chapter_id: int, prev_url: Optional[str] = None, next_url: Optional[str] = None
    ) -> bool:
        """Cập nhật liên kết điều hướng cho chương đã lưu mà không ghi đè raw_content bất biến."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            updates = []
            params = []
            if prev_url is not None:
                updates.append("prev_url = ?")
                params.append(prev_url)
            if next_url is not None:
                updates.append("next_url = ?")
                params.append(next_url)
            if not updates:
                return False
            params.append(chapter_id)
            cursor.execute(f"UPDATE chapters SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()
            return cursor.rowcount > 0

    def save_review_decisions(self, story_id: Optional[int], issues: List[SpellIssue]):
        """
        Lưu hoặc cập nhật trạng thái duyệt của người dùng vào CSDL.
        Bảo đảm định danh duy nhất theo (story_id, content_hash, issue_id, original, replacement),
        tuyệt đối không bị ghi đè chéo giữa 2 truyện hoặc khi nội dung thay đổi.
        """
        s_id = story_id if story_id is not None else self.get_default_story_id()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for iss in issues:
                c_hash = iss.original_hash or "unhashed"
                u_dec = getattr(iss, "user_decision", "approved" if iss.status == "applied" else iss.status)
                app_stat = getattr(iss, "applied_status", iss.status)
                app_reason = getattr(iss, "applied_reason", "")

                cursor.execute("""
                    INSERT INTO review_decisions (
                        story_id, content_hash, issue_id, chapter_num, paragraph_idx,
                        char_start, char_end, original, replacement, source, status,
                        user_decision, applied_status, applied_reason, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(story_id, content_hash, issue_id, original, replacement) DO UPDATE SET
                        status = excluded.status,
                        user_decision = excluded.user_decision,
                        applied_status = excluded.applied_status,
                        applied_reason = excluded.applied_reason,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    s_id,
                    c_hash,
                    iss.id,
                    iss.chapter_num,
                    iss.paragraph_idx,
                    iss.char_start,
                    iss.char_end,
                    iss.original,
                    iss.replacement,
                    iss.source,
                    iss.status,
                    u_dec,
                    app_stat,
                    app_reason,
                ))
            conn.commit()

    def get_review_decisions(
        self, story_id: Optional[int] = None, content_hash: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Tải các quyết định duyệt đã lưu theo story_id và content_hash.
        Trả về dict ánh xạ decision signature -> status.
        Không khôi phục quyết định cũ khi nội dung hoặc đề xuất đã thay đổi.
        """
        s_id = story_id if story_id is not None else self.get_default_story_id()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if content_hash:
                cursor.execute("""
                    SELECT issue_id, original, replacement, status
                    FROM review_decisions
                    WHERE story_id = ? AND content_hash = ?
                """, (s_id, content_hash))
            else:
                # Nếu không truyền hash cụ thể, không tải các bản ghi legacy_unverified để tránh tự áp dụng sai
                cursor.execute("""
                    SELECT issue_id, original, replacement, status
                    FROM review_decisions
                    WHERE story_id = ? AND content_hash != 'legacy_unverified'
                """, (s_id,))

            rows = cursor.fetchall()
            decisions: Dict[str, str] = {}
            for r in rows:
                sig = f"{r['issue_id']}_{r['original']}_{r['replacement']}"
                decisions[sig] = r["status"]
                decisions[r["issue_id"]] = r["status"]
            return decisions

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

        src = ""
        if "source" in row.keys() and row["source"] is not None:
            src = row["source"]

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
            source=src,
        )
