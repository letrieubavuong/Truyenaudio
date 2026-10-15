"""
Background worker threads for PySide6 GUI.
Strictly separates workflow into discrete non-blocking phases:
1. CrawlWorker: Fetches or imports chapters into SQLite.
2. SpellCheckWorker: Analyzes text, runs rules & AI, generates proposals for review.
3. ExportWorker: Applies finalized user review decisions, merges volumes, and exports files.
"""
from typing import List, Dict, Any, Optional
from PySide6.QtCore import QThread, Signal
from core.storage import StorageManager
from core.crawler import NetworkCrawler
from core.importer import OfflineImporter
from core.spellchecker import VietnameseSpellChecker
from core.ai_checker import AIChecker
from core.merger import VolumeMerger
from core.reporter import ReportGenerator
from core.models import Chapter, Volume, SpellIssue


class CrawlWorker(QThread):
    progress_changed = Signal(int, int, str)
    log_message = Signal(str, str)
    chapter_saved = Signal(object)
    finished_success = Signal(object)
    finished_error = Signal(str)

    def __init__(
        self,
        storage: StorageManager,
        story_url: str,
        start_url: str,
        start_chap: int,
        end_chap: int,
        import_dir: str = "",
        delay: float = 1.5,
    ):
        super().__init__()
        self.storage = storage
        self.story_url = story_url
        self.start_url = start_url
        self.start_chap = start_chap
        self.end_chap = end_chap
        self.import_dir = import_dir
        self.delay = delay
        self.crawler = NetworkCrawler(storage=self.storage, delay_seconds=self.delay)
        self.importer = OfflineImporter(storage=self.storage)

    def pause(self):
        self.crawler.pause()

    def resume(self):
        self.crawler.resume()

    def stop(self):
        self.crawler.stop()

    def run(self):
        try:
            if self.import_dir:
                self.log_message.emit("INFO", f"Đang nạp các tệp offline từ: {self.import_dir}")
                chapters = self.importer.import_directory(
                    directory_path=self.import_dir,
                    story_url=self.story_url or "offline://local-story",
                    story_title="Phàm Nhân Tu Tiên",
                    on_progress=lambda c, t, m: self.progress_changed.emit(c, t, m),
                    on_log=lambda l, m: self.log_message.emit(l, m),
                )
                for ch in chapters:
                    self.chapter_saved.emit(ch)
                self.finished_success.emit({"type": "import", "count": len(chapters)})
            else:
                self.log_message.emit("INFO", f"Bắt đầu tải từ web: {self.start_url}")
                res = self.crawler.crawl_range(
                    story_url=self.story_url,
                    start_chapter_url=self.start_url,
                    start_chap_num=self.start_chap,
                    end_chap_num=self.end_chap,
                    on_progress=lambda c, t, m: self.progress_changed.emit(c, t, m),
                    on_log=lambda l, m: self.log_message.emit(l, m),
                    on_chapter_saved=lambda ch: self.chapter_saved.emit(ch),
                )
                self.finished_success.emit(res)
        except Exception as e:
            self.finished_error.emit(str(e))


class SpellCheckWorker(QThread):
    progress_changed = Signal(int, int, str)
    log_message = Signal(str, str)
    issues_ready = Signal(object, object, object, object)  # (issues, chapters, volumes, original_paras_map)
    finished_analysis = Signal(int)
    finished_error = Signal(str)

    def __init__(
        self,
        storage: StorageManager,
        checker: VietnameseSpellChecker,
        merger: VolumeMerger,
        story_id: Optional[int],
        start_chap: int,
        end_chap: int,
        start_vol: int,
        do_spellcheck: bool = True,
        use_ai: bool = False,
        ai_checker: Optional[AIChecker] = None,
    ):
        super().__init__()
        self.storage = storage
        self.checker = checker
        self.merger = merger
        self.story_id = story_id
        self.start_chap = start_chap
        self.end_chap = end_chap
        self.start_vol = start_vol
        self.do_spellcheck = do_spellcheck
        self.use_ai = use_ai
        self.ai_checker = ai_checker
        self._is_stopped = False

    def stop(self):
        self._is_stopped = True

    def run(self):
        try:
            self.log_message.emit("INFO", f"Đang truy vấn các chương từ {self.start_chap} đến {self.end_chap}...")
            chapters = self.storage.get_chapters_range(
                story_id=self.story_id, start_chap=self.start_chap, end_chap=self.end_chap
            )

            if not chapters:
                self.finished_error.emit(
                    f"Không tìm thấy chương nào trong khoảng {self.start_chap} - {self.end_chap} trong CSDL."
                )
                return

            total_chaps = len(chapters)
            self.log_message.emit("INFO", f"Tìm thấy {total_chaps} chương. Đang phân tích nội dung...")

            all_issues: List[SpellIssue] = []
            original_paragraphs_map: Dict[int, List[str]] = {}

            # Tải quyết định duyệt đã lưu trước đó nếu có
            saved_decisions = self.storage.get_review_decisions(self.story_id)

            for idx, ch in enumerate(chapters, 1):
                if self._is_stopped:
                    self.log_message.emit("WARNING", "Tác vụ phân tích đã bị hủy.")
                    return

                original_paragraphs_map[ch.chapter_num] = ch.paragraphs

                if self.do_spellcheck:
                    # 1. Kiểm tra quy tắc & từ điển
                    _, rule_issues = self.checker.check_paragraph.__qualname__, []
                    _, rule_issues = self.checker.check_chapter(
                        ch.paragraphs, chapter_num=ch.chapter_num, chapter_title=ch.chapter_title
                    )

                    # 2. Kiểm tra AI tùy chọn
                    ai_issues: List[SpellIssue] = []
                    if self.use_ai and self.ai_checker and self.ai_checker.api_key:
                        self.log_message.emit("INFO", f"Chương {ch.chapter_num}: Đang phân tích qua AI...")
                        chunks = self.ai_checker.prepare_chunks(ch.paragraphs)
                        for chunk in chunks:
                            if self._is_stopped:
                                return
                            chunk_issues, err = self.ai_checker.check_chunk(
                                chunk, chapter_num=ch.chapter_num, chapter_title=ch.chapter_title
                            )
                            if err:
                                self.log_message.emit("WARNING", f"AI tại Chương {ch.chapter_num}: {err}")
                            else:
                                ai_issues.extend(chunk_issues)

                    chap_issues = rule_issues + ai_issues

                    # Khôi phục trạng thái đã duyệt trước đó nếu có trong CSDL
                    for iss in chap_issues:
                        if iss.id in saved_decisions:
                            iss.status = saved_decisions[iss.id]

                    all_issues.extend(chap_issues)
                    self.log_message.emit(
                        "INFO",
                        f"Chương {ch.chapter_num}: {len(rule_issues)} đề xuất quy tắc, {len(ai_issues)} đề xuất AI."
                    )
                else:
                    self.log_message.emit("INFO", f"Chương {ch.chapter_num}: Bỏ qua kiểm tra chính tả (đã tắt).")

                self.progress_changed.emit(idx, total_chaps, f"Đã phân tích Chương {ch.chapter_num}")

            # Xây dựng các tập Volume
            volumes = self.merger.build_volumes(
                chapters=chapters,
                start_volume_num=self.start_vol,
                expected_start_chap=self.start_chap,
                expected_end_chap=self.end_chap,
                story_title="Phàm Nhân Tu Tiên",
            )

            # Phát tín hiệu sẵn sàng để người dùng xem trước và duyệt trên giao diện
            self.issues_ready.emit(all_issues, chapters, volumes, original_paragraphs_map)
            self.finished_analysis.emit(len(all_issues))

        except Exception as e:
            self.finished_error.emit(str(e))


class ExportWorker(QThread):
    progress_changed = Signal(int, int, str)
    log_message = Signal(str, str)
    finished_success = Signal(object)
    finished_error = Signal(str)

    def __init__(
        self,
        volumes: List[Volume],
        issues: List[SpellIssue],
        edited_paragraphs_map: Dict[int, List[str]],
        output_dir: str,
        merger: VolumeMerger,
        overwrite: bool = False,
    ):
        super().__init__()
        self.volumes = volumes
        self.issues = issues
        self.edited_paragraphs_map = edited_paragraphs_map
        self.output_dir = output_dir
        self.merger = merger
        self.overwrite = overwrite
        self._is_stopped = False

    def stop(self):
        self._is_stopped = True

    def run(self):
        try:
            total_vols = len(self.volumes)
            exported_bundles = []

            for idx, vol in enumerate(self.volumes, 1):
                if self._is_stopped:
                    self.log_message.emit("WARNING", "Tác vụ xuất tập đã bị hủy.")
                    return

                vol_issues = [
                    i for i in self.issues
                    if i.chapter_num is not None and vol.start_chapter <= i.chapter_num <= vol.end_chapter
                ]

                bundle = ReportGenerator.export_volume_bundle(
                    volume=vol,
                    output_dir=self.output_dir,
                    merger=self.merger,
                    issues=vol_issues,
                    edited_paragraphs_map=self.edited_paragraphs_map,
                    overwrite=self.overwrite,
                )
                exported_bundles.append(bundle)
                self.progress_changed.emit(idx, total_vols, f"Đã xuất Tập {vol.volume_num}")
                self.log_message.emit("SUCCESS", f"Đã xuất an toàn Tập {vol.volume_num} vào {self.output_dir}")

            self.finished_success.emit(exported_bundles)
        except Exception as e:
            self.finished_error.emit(str(e))
