"""
Main Window for Vietnamese Story Collector, Spell Checker & Volume Merger.
Built with PySide6, clean light aesthetic, robust background threading,
intuitive side-by-side diff review, and separate review/export phases.
"""
import os
import sys
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QCheckBox, QTabWidget, QProgressBar, QTextEdit,
    QFileDialog, QMessageBox, QGroupBox, QGridLayout, QStatusBar
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QFont

from core.storage import StorageManager
from core.models import Chapter, Volume, SpellIssue
from core.spellchecker import VietnameseSpellChecker
from core.ai_checker import AIChecker
from core.merger import VolumeMerger
from gui.widgets import ChapterTableWidget, DiffReviewWidget
from gui.dialogs import SettingsDialog
from gui.workers import CrawlWorker, SpellCheckWorker, ExportWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bộ Thu Thập, Hiệu Đính & Gộp Tập Truyện - Phàm Nhân Tu Tiên")
        self.resize(1180, 820)
        self.setMinimumSize(950, 680)

        self.storage = StorageManager("crawler_state.db")
        self.spell_checker = VietnameseSpellChecker()
        self.ai_checker = AIChecker(protected_terms=self.spell_checker.protected_terms)

        self.crawl_worker: Optional[CrawlWorker] = None
        self.spell_worker: Optional[SpellCheckWorker] = None
        self.export_worker: Optional[ExportWorker] = None

        self.offline_import_dir: str = ""
        self.current_story_id: int = self.storage.get_default_story_id()
        self.current_volumes: List[Volume] = []
        self.current_merger: Optional[VolumeMerger] = None

        self.init_ui()
        self.load_initial_data()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(12, 10, 12, 10)

        # 1. KHU VỰC CẤU HÌNH NGUỒN & THIẾT LẬP
        top_group = QGroupBox("1. Nguồn Dữ Liệu & Phương Thức Thu Thập")
        top_layout = QGridLayout(top_group)

        top_layout.addWidget(QLabel("URL Truyện:"), 0, 0)
        self.txt_story_url = QLineEdit("https://vivutruyen.com/truyen/pham-nhan-tu-tien")
        top_layout.addWidget(self.txt_story_url, 0, 1, 1, 3)

        top_layout.addWidget(QLabel("URL Chương bắt đầu:"), 1, 0)
        self.txt_start_url = QLineEdit("https://vivutruyen.com/truyen/pham-nhan-tu-tien/chuong-1-son-bien-tieu-thon-103484")
        top_layout.addWidget(self.txt_start_url, 1, 1, 1, 2)

        self.btn_select_import_dir = QPushButton("📁 Nạp tệp máy tính (Offline)...")
        self.btn_select_import_dir.clicked.connect(self.choose_import_dir)
        top_layout.addWidget(self.btn_select_import_dir, 1, 3)

        self.lbl_import_hint = QLabel("<i>Đang dùng: Tải trực tiếp qua mạng</i>")
        self.lbl_import_hint.setStyleSheet("color: #555;")
        top_layout.addWidget(self.lbl_import_hint, 2, 1, 1, 3)

        main_layout.addWidget(top_group)

        # 2. KHU VỰC CẤU HÌNH GỘP TẬP & SỬA LỖI
        cfg_group = QGroupBox("2. Cấu Hình Gộp Tập & Hiệu Đính Chính Tả")
        cfg_layout = QGridLayout(cfg_group)

        cfg_layout.addWidget(QLabel("Chương bắt đầu:"), 0, 0)
        self.spin_start_chap = QSpinBox()
        self.spin_start_chap.setRange(1, 99999)
        self.spin_start_chap.setValue(1)
        self.spin_start_chap.setToolTip("Khoảng tải: Chương bắt đầu thu thập từ nguồn")
        self.spin_start_chap.valueChanged.connect(self.on_start_chap_changed)
        cfg_layout.addWidget(self.spin_start_chap, 0, 1)

        cfg_layout.addWidget(QLabel("Chương kết thúc:"), 0, 2)
        self.spin_end_chap = QSpinBox()
        self.spin_end_chap.setRange(1, 99999)
        self.spin_end_chap.setValue(12)
        self.spin_end_chap.setToolTip("Khoảng tải: Chương kết thúc thu thập (ví dụ: 1 đến 12 tải đủ 12 chương)")
        cfg_layout.addWidget(self.spin_end_chap, 0, 3)

        cfg_layout.addWidget(QLabel("Số chương / Tập:"), 0, 4)
        self.spin_per_vol = QSpinBox()
        self.spin_per_vol.setRange(1, 100)
        self.spin_per_vol.setValue(4)
        self.spin_per_vol.setToolTip("Số chương mỗi tập (mặc định 4) CHỈ phục vụ bước gộp file TXT, không giới hạn số chương tải.")
        cfg_layout.addWidget(self.spin_per_vol, 0, 5)

        cfg_layout.addWidget(QLabel("Số tập bắt đầu:"), 0, 6)
        self.spin_start_vol = QSpinBox()
        self.spin_start_vol.setRange(1, 99999)
        self.spin_start_vol.setValue(1)
        cfg_layout.addWidget(self.spin_start_vol, 0, 7)

        cfg_layout.addWidget(QLabel("Thư mục xuất:"), 1, 0)
        self.txt_output_dir = QLineEdit(os.path.abspath("output_volumes"))
        cfg_layout.addWidget(self.txt_output_dir, 1, 1, 1, 5)

        self.btn_choose_out = QPushButton("Chọn thư mục...")
        self.btn_choose_out.clicked.connect(self.choose_output_dir)
        cfg_layout.addWidget(self.btn_choose_out, 1, 6)

        self.btn_open_settings = QPushButton("⚙ Cài đặt từ điển / AI...")
        self.btn_open_settings.clicked.connect(self.open_settings)
        cfg_layout.addWidget(self.btn_open_settings, 1, 7)

        chk_layout = QHBoxLayout()
        self.chk_download = QCheckBox("Thu thập / Nạp dữ liệu")
        self.chk_download.setChecked(True)
        self.chk_spellcheck = QCheckBox("Sửa lỗi chính tả")
        self.chk_spellcheck.setChecked(True)
        self.chk_merge = QCheckBox("Gộp tập TXT")
        self.chk_merge.setChecked(True)
        self.chk_use_ai = QCheckBox("Bật sửa bằng AI (Tùy chọn)")
        self.chk_use_ai.setChecked(False)
        self.chk_overwrite = QCheckBox("Ghi đè file nếu đã có")
        self.chk_overwrite.setChecked(False)
        self.chk_allow_partial = QCheckBox("Xuất nhóm cuối (< 4 chương)")
        self.chk_allow_partial.setChecked(False)
        self.chk_export_reports = QCheckBox("Xuất kèm báo cáo (.md, .json)")
        self.chk_export_reports.setChecked(False)
        self.chk_export_reports.setToolTip("Mặc định chỉ xuất duy nhất 1 file TXT hoàn chỉnh. Bật tùy chọn này nếu muốn tạo thêm file báo cáo .md và nhật ký .json.")

        chk_layout.addWidget(self.chk_download)
        chk_layout.addWidget(self.chk_spellcheck)
        chk_layout.addWidget(self.chk_merge)
        chk_layout.addWidget(self.chk_use_ai)
        chk_layout.addWidget(self.chk_overwrite)
        chk_layout.addWidget(self.chk_allow_partial)
        chk_layout.addWidget(self.chk_export_reports)
        chk_layout.addStretch()

        cfg_layout.addLayout(chk_layout, 2, 0, 1, 8)
        main_layout.addWidget(cfg_group)

        # 3. THANH ĐIỀU KHIỂN & TIẾN ĐỘ
        ctrl_layout = QHBoxLayout()
        self.btn_start = QPushButton("▶ Bắt đầu phân tích")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.clicked.connect(self.start_process)

        self.btn_export = QPushButton("💾 Áp dụng và xuất tập...")
        self.btn_export.setEnabled(False)
        self.btn_export.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 6px 14px;")
        self.btn_export.clicked.connect(self.start_export)

        self.btn_pause = QPushButton("⏸ Tạm dừng")
        self.btn_pause.setObjectName("btn_pause")
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self.pause_process)

        self.btn_resume = QPushButton("⏯ Tiếp tục")
        self.btn_resume.setEnabled(False)
        self.btn_resume.clicked.connect(self.resume_process)

        self.btn_stop = QPushButton("⏹ Hủy bỏ")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_process)

        ctrl_layout.addWidget(self.btn_start)
        ctrl_layout.addWidget(self.btn_export)
        ctrl_layout.addWidget(self.btn_pause)
        ctrl_layout.addWidget(self.btn_resume)
        ctrl_layout.addWidget(self.btn_stop)
        ctrl_layout.addSpacing(20)

        self.prog_bar = QProgressBar()
        self.prog_bar.setValue(0)
        ctrl_layout.addWidget(self.prog_bar, 1)

        main_layout.addLayout(ctrl_layout)

        # 4. TAB NỘI DUNG CHÍNH
        self.tabs_main = QTabWidget()

        # Tab 1: Bảng chương & Nhật ký
        tab1_widget = QWidget()
        tab1_layout = QVBoxLayout(tab1_widget)
        tab1_layout.setContentsMargins(4, 6, 4, 4)

        self.table_chapters = ChapterTableWidget()
        tab1_layout.addWidget(QLabel("<b>Trạng thái từng chương trong Cơ sở dữ liệu:</b>"))
        tab1_layout.addWidget(self.table_chapters, 2)

        tab1_layout.addWidget(QLabel("<b>Nhật ký tác vụ (Log):</b>"))
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        log_font = QFont("Consolas")
        log_font.setPointSize(10)
        self.txt_log.setFont(log_font)
        self.txt_log.setMaximumHeight(150)
        tab1_layout.addWidget(self.txt_log, 1)

        self.tabs_main.addTab(tab1_widget, "📋 Bảng Chương & Tiến Độ")

        # Tab 2: Xem trước & Duyệt lỗi
        self.diff_widget = DiffReviewWidget()
        self.diff_widget.decisions_changed.connect(self.on_decisions_changed)
        self.tabs_main.addTab(self.diff_widget, "🔍 Xem Trước & Duyệt Lỗi")

        # Tab 3: Báo cáo & Thư mục xuất
        tab3_widget = QWidget()
        tab3_layout = QVBoxLayout(tab3_widget)
        tab3_layout.setContentsMargins(6, 6, 6, 6)

        tab3_top = QHBoxLayout()
        tab3_top.addWidget(QLabel("<b>Báo cáo Markdown của tập vừa xuất:</b>"))
        tab3_top.addStretch()
        self.btn_open_folder = QPushButton("📂 Mở thư mục xuất...")
        self.btn_open_folder.clicked.connect(self.open_output_folder)
        tab3_top.addWidget(self.btn_open_folder)
        tab3_layout.addLayout(tab3_top)

        self.txt_report_viewer = QTextEdit()
        self.txt_report_viewer.setReadOnly(True)
        report_font = QFont("Segoe UI")
        report_font.setPointSize(10)
        self.txt_report_viewer.setFont(report_font)
        tab3_layout.addWidget(self.txt_report_viewer)

        self.tabs_main.addTab(tab3_widget, "📊 Báo Cáo Markdown")

        main_layout.addWidget(self.tabs_main, 1)

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Sẵn sàng hoạt động.")

    def load_initial_data(self):
        """Nạp danh sách chương hiện có trong SQLite lên bảng hiển thị."""
        story_info = self.storage.get_or_create_story(
            url=self.txt_story_url.text().strip(),
            title="Phàm Nhân Tu Tiên"
        )
        self.current_story_id = story_info.id or 1
        chapters = self.storage.get_all_chapters(story_id=self.current_story_id)
        self.table_chapters.update_chapters(chapters)
        if chapters:
            self.log("INFO", f"Đã nạp {len(chapters)} chương từ CSDL lưu trữ SQLite (Story ID: {self.current_story_id}).")

    def log(self, level: str, msg: str):
        color_map = {
            "INFO": "#0d47a1",
            "SUCCESS": "#1b5e20",
            "WARNING": "#e65100",
            "ERROR": "#b71c1c",
        }
        color = color_map.get(level, "#212529")
        html = f'<span style="color: {color};"><b>[{level}]</b> {msg}</span>'
        self.txt_log.append(html)
        self.status_bar.showMessage(msg)

    def choose_import_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục chứa tệp HTML hoặc TXT chương truyện")
        if d:
            self.offline_import_dir = d
            self.lbl_import_hint.setText(f"<i>Đang dùng nguồn Offline: <b>{d}</b></i>")
            self.log("INFO", f"Đã chọn thư mục nạp offline: {d}")

    def choose_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục xuất tệp tập truyện")
        if d:
            self.txt_output_dir.setText(d)

    def open_output_folder(self):
        folder = self.txt_output_dir.text().strip()
        if os.path.exists(folder):
            os.startfile(folder)
        else:
            QMessageBox.warning(self, "Thư mục không tồn tại", f"Thư mục '{folder}' chưa được tạo.")

    def open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec():
            self.spell_checker.load_resources()
            self.ai_checker.set_protected_terms(self.spell_checker.protected_terms)
            self.log("SUCCESS", "Đã cập nhật cấu hình từ điển và danh từ riêng bảo vệ.")

    def on_decisions_changed(self, issues: List[SpellIssue]):
        """Lưu lại quyết định duyệt vào SQLite để bảo toàn tiến độ."""
        self.storage.save_review_decisions(self.current_story_id, issues)

    def on_start_chap_changed(self, val: int):
        if hasattr(self, "storage") and self.storage:
            ch = self.storage.get_chapter_by_num(self.current_story_id, val)
            if ch and ch.source_url and ch.source_url.startswith("http"):
                self.txt_start_url.setText(ch.source_url)

    def start_process(self):
        start_chap = self.spin_start_chap.value()
        end_chap = self.spin_end_chap.value()
        if start_chap > end_chap:
            QMessageBox.warning(self, "Lỗi phạm vi", "Chương bắt đầu không được lớn hơn chương kết thúc.")
            return

        story_info = self.storage.get_or_create_story(
            url=self.txt_story_url.text().strip(),
            title="Phàm Nhân Tu Tiên"
        )
        self.current_story_id = story_info.id or 1

        self.btn_start.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.btn_pause.setEnabled(True if self.chk_download.isChecked() and not self.offline_import_dir else False)
        self.btn_resume.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.prog_bar.setValue(0)

        do_download = self.chk_download.isChecked()

        if do_download:
            req_start_url = self.txt_start_url.text().strip()
            if start_chap > 1 and "chuong-1-" in req_start_url:
                target_chap = self.storage.get_chapter_by_num(self.current_story_id, start_chap)
                if target_chap and target_chap.source_url and target_chap.source_url.startswith("http"):
                    req_start_url = target_chap.source_url

            self.crawl_worker = CrawlWorker(
                storage=self.storage,
                story_url=self.txt_story_url.text().strip(),
                start_url=req_start_url,
                start_chap=start_chap,
                end_chap=end_chap,
                import_dir=self.offline_import_dir,
            )
            self.crawl_worker.progress_changed.connect(self.on_progress)
            self.crawl_worker.log_message.connect(self.log)
            self.crawl_worker.chapter_saved.connect(self.on_chapter_saved)
            self.crawl_worker.finished_success.connect(self.on_crawl_finished)
            self.crawl_worker.finished_error.connect(self.on_worker_error)
            self.crawl_worker.start()
        else:
            self.start_spellcheck_analysis()

    def on_progress(self, curr, total, msg):
        pct = int((curr / max(1, total)) * 100)
        self.prog_bar.setValue(pct)
        self.status_bar.showMessage(msg)

    def on_chapter_saved(self, chapter: Chapter):
        chapters = self.storage.get_all_chapters(story_id=self.current_story_id)
        self.table_chapters.update_chapters(chapters)

    def on_crawl_finished(self, res):
        chapters = self.storage.get_all_chapters(story_id=self.current_story_id)
        self.table_chapters.update_chapters(chapters)

        is_success = res.get("success", False) if isinstance(res, dict) else True
        fetched = res.get("fetched_count", 0) if isinstance(res, dict) else len(chapters)
        total = res.get("total_requested", 0) if isinstance(res, dict) else len(chapters)
        status_msg = res.get("status_message", "") if isinstance(res, dict) else ""
        stop_reason = res.get("stop_reason", "") if isinstance(res, dict) else ""
        status_category = res.get("status", "") if isinstance(res, dict) else ("completed" if is_success else "incomplete")
        cached_count = res.get("cached_count", 0) if isinstance(res, dict) else 0
        downloaded_count = res.get("downloaded_count", 0) if isinstance(res, dict) else 0
        missing_count = res.get("missing_count", 0) if isinstance(res, dict) else 0

        if not is_success or status_category != "completed" or (total > 0 and fetched < total):
            category_names = {
                "blocked": "Bị chặn truy cập (HTTP 403/429 hoặc trang thử thách)",
                "network_error": "Lỗi kết nối mạng",
                "parse_error": "Lỗi phân tích cú pháp HTML hoặc điều hướng",
                "stopped_by_user": "Người dùng đã dừng",
                "incomplete": "Chưa hoàn tất",
            }
            cat_label = category_names.get(status_category, "Chưa hoàn tất")
            reason_text = stop_reason or status_msg or "Tác vụ dừng sớm hơn yêu cầu."
            warning_msg = (
                f"Tác vụ kết thúc [{cat_label}]: {fetched}/{total} chương "
                f"(Từ cache: {cached_count}, Tải mới: {downloaded_count}, Còn thiếu: {missing_count}). "
                f"Chi tiết: {reason_text}"
            )
            self.log("WARNING", warning_msg)
            self.status_bar.showMessage(f"{cat_label}: {fetched}/{total} chương (Thiếu {missing_count})")

            # Hộp thoại cảnh báo chưa hoàn tất
            reply = QMessageBox.warning(
                self,
                f"Thu thập chưa hoàn tất: {cat_label}",
                f"Trạng thái: {cat_label}\n"
                f"Tiến độ: {fetched}/{total} chương\n"
                f"- Số chương từ cache: {cached_count}\n"
                f"- Số chương tải mới: {downloaded_count}\n"
                f"- Số chương còn thiếu: {missing_count}\n\n"
                f"Nguyên nhân: {reason_text}\n\n"
                f"Bạn có muốn tiếp tục hiệu đính và xuất các chương đã có ({fetched} chương) không?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes and fetched > 0:
                self.start_spellcheck_analysis()
            else:
                self.btn_start.setEnabled(True)
                self.btn_stop.setEnabled(False)
                self.btn_pause.setEnabled(False)
                self.btn_resume.setEnabled(False)
        else:
            success_msg = (
                f"Hoàn tất thu thập dữ liệu: {fetched}/{total} chương "
                f"(Từ cache: {cached_count}, Tải mới: {downloaded_count})."
            )
            self.log("SUCCESS", success_msg)
            self.status_bar.showMessage(f"Đã tải đủ {fetched}/{total} chương")
            self.start_spellcheck_analysis()

    def start_spellcheck_analysis(self):
        self.log("INFO", "Bắt đầu bước phân tích chính tả và chuẩn bị dữ liệu duyệt...")
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(False)

        merger = VolumeMerger(
            chapters_per_volume=self.spin_per_vol.value(),
            allow_partial_last_volume=self.chk_allow_partial.isChecked(),
        )
        self.current_merger = merger

        self.spell_worker = SpellCheckWorker(
            storage=self.storage,
            checker=self.spell_checker,
            merger=merger,
            story_id=self.current_story_id,
            start_chap=self.spin_start_chap.value(),
            end_chap=self.spin_end_chap.value(),
            start_vol=self.spin_start_vol.value(),
            do_spellcheck=self.chk_spellcheck.isChecked(),
            use_ai=self.chk_use_ai.isChecked(),
            ai_checker=self.ai_checker if self.chk_use_ai.isChecked() else None,
        )
        self.spell_worker.progress_changed.connect(self.on_progress)
        self.spell_worker.log_message.connect(self.log)
        self.spell_worker.issues_ready.connect(self.on_issues_ready)
        self.spell_worker.finished_analysis.connect(self.on_analysis_finished)
        self.spell_worker.finished_error.connect(self.on_worker_error)
        self.spell_worker.start()

    def on_issues_ready(
        self,
        issues: List[SpellIssue],
        chapters: List[Chapter],
        volumes: List[Volume],
        original_paragraphs_map: Dict[int, List[str]],
    ):
        self.current_volumes = volumes
        self.diff_widget.load_data(
            issues=issues,
            volumes=volumes,
            merger=self.current_merger,
            original_paragraphs_map=original_paragraphs_map,
        )
        self.log("INFO", f"Đã nạp {len(issues)} đề xuất vào màn hình duyệt lỗi.")

    def on_analysis_finished(self, total_issues: int):
        self.log("SUCCESS", f"Hoàn tất phân tích ({total_issues} đề xuất). Sẵn sàng để duyệt.")
        self.prog_bar.setValue(100)
        self.btn_start.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.btn_stop.setEnabled(False)

        # Chuyển người dùng sang Tab 2 để duyệt lỗi trước khi xuất
        self.tabs_main.setCurrentIndex(1)
        self.status_bar.showMessage("Vui lòng duyệt các đề xuất, sau đó bấm 'Áp dụng và xuất tập...'.")

    def start_export(self):
        """Bắt đầu bước xuất tập chính thức sau khi người dùng đã duyệt."""
        if not self.current_volumes or not self.current_merger:
            QMessageBox.warning(self, "Chưa có dữ liệu", "Vui lòng chạy phân tích trước khi xuất tập.")
            return

        final_issues = self.diff_widget.issues
        edited_paragraphs_map = self.diff_widget.get_edited_paragraphs_map()
        out_dir = self.txt_output_dir.text().strip()

        # Kiểm tra ghi đè an toàn trước khi chạy
        export_reports = self.chk_export_reports.isChecked()
        if not self.chk_overwrite.isChecked():
            for vol in self.current_volumes:
                target_fname = f"{vol.filename_base}_EDITED.txt" if export_reports else f"{vol.filename_base}.txt"
                target_path = os.path.join(out_dir, target_fname)
                if os.path.exists(target_path):
                    QMessageBox.warning(
                        self,
                        "Tệp đã tồn tại",
                        f"Tệp '{target_fname}' đã tồn tại trong thư mục xuất.\n"
                        "Vui lòng bật cờ 'Ghi đè file nếu đã có' hoặc đổi thư mục xuất."
                    )
                    return

        self.btn_start.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.prog_bar.setValue(0)
        self.log("INFO", f"Bắt đầu xuất {len(self.current_volumes)} tập vào: {out_dir}...")

        self.export_worker = ExportWorker(
            volumes=self.current_volumes,
            issues=final_issues,
            edited_paragraphs_map=edited_paragraphs_map,
            output_dir=out_dir,
            merger=self.current_merger,
            overwrite=self.chk_overwrite.isChecked(),
            export_reports=export_reports,
        )
        self.export_worker.progress_changed.connect(self.on_progress)
        self.export_worker.log_message.connect(self.log)
        self.export_worker.finished_success.connect(self.on_export_finished)
        self.export_worker.finished_error.connect(self.on_worker_error)
        self.export_worker.start()

    def on_export_finished(self, bundles: List[Dict[str, str]]):
        self.log("SUCCESS", f"Hoàn tất xuất file! Đã xuất an toàn {len(bundles)} tập truyện.")
        self.prog_bar.setValue(100)

        if bundles and bundles[0].get("report"):
            try:
                with open(bundles[0]["report"], "r", encoding="utf-8") as f:
                    self.txt_report_viewer.setPlainText(f.read())
                self.tabs_main.setCurrentIndex(2)
            except Exception:
                pass

        QMessageBox.information(
            self,
            "Xuất tập thành công",
            f"Đã xuất thành công {len(bundles)} tập truyện vào thư mục:\n{self.txt_output_dir.text()}"
        )
        self.reset_controls()

    def on_worker_error(self, err_msg: str):
        self.log("ERROR", f"Tác vụ gặp lỗi: {err_msg}")
        QMessageBox.critical(self, "Lỗi tác vụ", err_msg)
        self.reset_controls()

    def pause_process(self):
        if self.crawl_worker and self.crawl_worker.isRunning():
            self.crawl_worker.pause()
            self.btn_pause.setEnabled(False)
            self.btn_resume.setEnabled(True)
            self.log("WARNING", "Đã tạm dừng tác vụ thu thập.")

    def resume_process(self):
        if self.crawl_worker and self.crawl_worker.isRunning():
            self.crawl_worker.resume()
            self.btn_pause.setEnabled(True)
            self.btn_resume.setEnabled(False)
            self.log("INFO", "Tiếp tục tác vụ thu thập.")

    def stop_process(self):
        if self.crawl_worker and self.crawl_worker.isRunning():
            self.crawl_worker.stop()
        if self.spell_worker and self.spell_worker.isRunning():
            self.spell_worker.stop()
        if self.export_worker and self.export_worker.isRunning():
            self.export_worker.stop()
        self.log("WARNING", "Đã hủy tác vụ theo yêu cầu người dùng.")
        self.reset_controls()

    def reset_controls(self):
        self.btn_start.setEnabled(True)
        self.btn_export.setEnabled(True if self.current_volumes else False)
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(False)
        self.btn_stop.setEnabled(False)

    def closeEvent(self, event):
        """Dọn dẹp an toàn các worker thread khi người dùng đóng cửa sổ."""
        for worker in [self.crawl_worker, self.spell_worker, self.export_worker]:
            if worker and worker.isRunning():
                if hasattr(worker, "stop"):
                    worker.stop()
                worker.quit()
                worker.wait(1000)
        event.accept()
