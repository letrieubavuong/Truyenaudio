"""
Background worker threads for PySide6 GUI to prevent UI freezing.
Supports crawling, offline importing, spellchecking, and merging with pause/resume/stop.
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


class SpellCheckMergeWorker(QThread):
    progress_changed = Signal(int, int, str)
    log_message = Signal(str, str)
    issues_ready = Signal(object, object)  # (issues, edited_paragraphs_map)
    finished_success = Signal(object)  # list of exported volume bundles
    finished_error = Signal(str)

    def __init__(
        self,
        storage: StorageManager,
        checker: VietnameseSpellChecker,
        merger: VolumeMerger,
        start_chap: int,
        end_chap: int,
        start_vol: int,
        output_dir: str,
        overwrite: bool = False,
        use_ai: bool = False,
        ai_checker: Optional[AIChecker] = None,
    ):
        super().__init__()
        self.storage = storage
        self.checker = checker
        self.merger = merger
        self.start_chap = start_chap
        self.end_chap = end_chap
        self.start_vol = start_vol
        self.output_dir = output_dir
        self.overwrite = overwrite
        self.use_ai = use_ai
        self.ai_checker = ai_checker
        self._is_stopped = False

    def stop(self):
        self._is_stopped = True

    def run(self):
        try:
            self.log_message.emit("INFO", f"Đang truy vấn các chương từ {self.start_chap} đến {self.end_chap}...")
            chapters = self.storage.get_chapters_range(story_id=1, start_chap=self.start_chap, end_chap=self.end_chap)

            if not chapters:
                self.finished_error.emit(f"Không tìm thấy chương nào trong khoảng {self.start_chap} - {self.end_chap} trong CSDL.")
                return

            total_chaps = len(chapters)
            self.log_message.emit("INFO", f"Tìm thấy {total_chaps} chương. Bắt đầu kiểm tra và sửa lỗi chính tả...")

            all_issues: List[SpellIssue] = []
            edited_paragraphs_map: Dict[int, List[str]] = {}

            for idx, ch in enumerate(chapters, 1):
                if self._is_stopped:
                    self.log_message.emit("WARNING", "Tác vụ đã bị hủy.")
                    return

                # 1. Kiểm tra theo quy tắc
                edited_paras, issues = self.checker.check_chapter(
                    ch.paragraphs, chapter_num=ch.chapter_num, chapter_title=ch.chapter_title
                )

                # 2. Kiểm tra AI tùy chọn nếu được kích hoạt
                if self.use_ai and self.ai_checker and self.ai_checker.api_key:
                    chunks = self.ai_checker.prepare_chunks(edited_paras)
                    for chunk in chunks:
                        ai_issues, err = self.ai_checker.check_chunk(
                            chunk, chapter_num=ch.chapter_num, chapter_title=ch.chapter_title
                        )
                        if err:
                            self.log_message.emit("WARNING", f"Lỗi AI tại Chương {ch.chapter_num}: {err}")
                        else:
                            issues.extend(ai_issues)

                edited_paragraphs_map[ch.chapter_num] = edited_paras
                all_issues.extend(issues)

                self.progress_changed.emit(idx, total_chaps, f"Đã kiểm tra Chương {ch.chapter_num}")
                self.log_message.emit("SUCCESS", f"Chương {ch.chapter_num}: Phát hiện {len(issues)} vị trí cần xử lý.")

            # Phát tín hiệu để UI hiển thị màn hình xem trước và danh sách duyệt
            self.issues_ready.emit(all_issues, edited_paragraphs_map)

            # 3. Gộp tập và xuất file
            self.log_message.emit("INFO", f"Bắt đầu gộp tập (mỗi {self.merger.chapters_per_volume} chương, tập bắt đầu {self.start_vol})...")
            volumes = self.merger.build_volumes(
                chapters=chapters,
                start_volume_num=self.start_vol,
                expected_start_chap=self.start_chap,
                expected_end_chap=self.end_chap,
                story_title="Phàm Nhân Tu Tiên",
            )

            exported_bundles = []
            for vol in volumes:
                if self._is_stopped:
                    break
                vol_issues = [
                    i for i in all_issues if i.chapter_num and vol.start_chapter <= i.chapter_num <= vol.end_chapter
                ]
                bundle = ReportGenerator.export_volume_bundle(
                    volume=vol,
                    output_dir=self.output_dir,
                    merger=self.merger,
                    issues=vol_issues,
                    edited_paragraphs_map=edited_paragraphs_map,
                    overwrite=self.overwrite,
                )
                exported_bundles.append(bundle)
                self.log_message.emit("SUCCESS", f"Đã xuất thành công Tập {vol.volume_num} vào {self.output_dir}")

            self.finished_success.emit(exported_bundles)

        except Exception as e:
            self.finished_error.emit(str(e))
