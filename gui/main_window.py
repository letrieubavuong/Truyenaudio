"""
Main Window for Vietnamese Story Collector, Spell Checker & Volume Merger.
Built with PySide6, clean light aesthetic, robust background threading,
and intuitive side-by-side diff review.
"""
import os
import sys
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QCheckBox, QTabWidget, QProgressBar, QTextEdit,
    QFileDialog, QMessageBox, QGroupBox, QGridLayout, QStatusBar
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QFont

from core.storage import StorageManager
from core.models import Chapter, SpellIssue
from core.spellchecker import VietnameseSpellChecker
from core.ai_checker import AIChecker
from core.merger import VolumeMerger
from gui.widgets import ChapterTableWidget, DiffReviewWidget
from gui.dialogs import SettingsDialog
from gui.workers import CrawlWorker, SpellCheckMergeWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bộ Thu Thập, Hiệu Đính & Gộp Tập Truyện - Phàm Nhân Tu Tiên")
        self.resize(1180, 820)
        self.setMinimumSize(950, 680)

        self.storage = StorageManager("crawler_state.db")
        self.spell_checker = VietnameseSpellChecker()
        self.ai_checker = AIChecker()

        self.crawl_worker: Optional[CrawlWorker] = None
        self.merge_worker: Optional[SpellCheckMergeWorker] = None
        self.offline_import_dir: str = ""

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

        # Hàng 0: Phạm vi chương & số tập
        cfg_layout.addWidget(QLabel("Chương bắt đầu:"), 0, 0)
        self.spin_start_chap = QSpinBox()
        self.spin_start_chap.setRange(1, 99999)
        self.spin_start_chap.setValue(1)
        cfg_layout.addWidget(self.spin_start_chap, 0, 1)

        cfg_layout.addWidget(QLabel("Chương kết thúc:"), 0, 2)
        self.spin_end_chap = QSpinBox()
        self.spin_end_chap.setRange(1, 99999)
        self.spin_end_chap.setValue(4)
        cfg_layout.addWidget(self.spin_end_chap, 0, 3)

        cfg_layout.addWidget(QLabel("Số chương / Tập:"), 0, 4)
        self.spin_per_vol = QSpinBox()
        self.spin_per_vol.setRange(1, 100)
        self.spin_per_vol.setValue(4)  # Mặc định 4
        cfg_layout.addWidget(self.spin_per_vol, 0, 5)

        cfg_layout.addWidget(QLabel("Số tập bắt đầu:"), 0, 6)
        self.spin_start_vol = QSpinBox()
        self.spin_start_vol.setRange(1, 99999)
        self.spin_start_vol.setValue(1)
        cfg_layout.addWidget(self.spin_start_vol, 0, 7)

        # Hàng 1: Thư mục xuất
        cfg_layout.addWidget(QLabel("Thư mục xuất:"), 1, 0)
        self.txt_output_dir = QLineEdit(os.path.abspath("output_volumes"))
        cfg_layout.addWidget(self.txt_output_dir, 1, 1, 1, 5)

        self.btn_choose_out = QPushButton("Chọn thư mục...")
        self.btn_choose_out.clicked.connect(self.choose_output_dir)
        cfg_layout.addWidget(self.btn_choose_out, 1, 6)

        self.btn_open_settings = QPushButton("⚙ Cài đặt từ điển / AI...")
        self.btn_open_settings.clicked.connect(self.open_settings)
        cfg_layout.addWidget(self.btn_open_settings, 1, 7)

        # Hàng 2: Các cờ tùy chọn
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

        chk_layout.addWidget(self.chk_download)
        chk_layout.addWidget(self.chk_spellcheck)
        chk_layout.addWidget(self.chk_merge)
        chk_layout.addWidget(self.chk_use_ai)
        chk_layout.addWidget(self.chk_overwrite)
        chk_layout.addWidget(self.chk_allow_partial)
        chk_layout.addStretch()

        cfg_layout.addLayout(chk_layout, 2, 0, 1, 8)
        main_layout.addWidget(cfg_group)

        # 3. THANH ĐIỀU KHIỂN & TIẾN ĐỘ
        ctrl_layout = QHBoxLayout()
        self.btn_start = QPushButton("▶ Bắt đầu")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.clicked.connect(self.start_process)

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
        self.txt_log.setFont(QFont("Consolas", 10))
        self.txt_log.setMaximumHeight(150)
        tab1_layout.addWidget(self.txt_log, 1)

        self.tabs_main.addTab(tab1_widget, "📋 Bảng Chương & Tiến Độ")

        # Tab 2: Xem trước & Duyệt lỗi
        self.diff_widget = DiffReviewWidget()
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
        self.txt_report_viewer.setFont(QFont("Segoe UI", 10))
        tab3_layout.addWidget(self.txt_report_viewer)

        self.tabs_main.addTab(tab3_widget, "📊 Báo Cáo Markdown")

        main_layout.addWidget(self.tabs_main, 1)

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Sẵn sàng hoạt động.")

    def load_initial_data(self):
        """Nạp danh sách chương hiện có trong SQLite lên bảng hiển thị."""
        chapters = self.storage.get_all_chapters(story_id=1)
        self.table_chapters.update_chapters(chapters)
        if chapters:
            self.log("INFO", f"Đã nạp {len(chapters)} chương từ CSDL lưu trữ SQLite.")

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
            # Tải lại từ điển
            self.spell_checker.load_resources()
            self.log("SUCCESS", "Đã cập nhật cấu hình từ điển và danh từ riêng bảo vệ.")

    def start_process(self):
        start_chap = self.spin_start_chap.value()
        end_chap = self.spin_end_chap.value()
        if start_chap > end_chap:
            QMessageBox.warning(self, "Lỗi phạm vi", "Chương bắt đầu không được lớn hơn chương kết thúc.")
            return

        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_resume.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.prog_bar.setValue(0)

        do_download = self.chk_download.isChecked()

        if do_download:
            # Chạy bước 1: Thu thập hoặc Nạp offline
            self.crawl_worker = CrawlWorker(
                storage=self.storage,
                story_url=self.txt_story_url.text().strip(),
                start_url=self.txt_start_url.text().strip(),
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
            # Bỏ qua bước tải, chạy trực tiếp gộp & sửa lỗi
            self.start_spellcheck_and_merge()

    def on_progress(self, curr, total, msg):
        pct = int((curr / max(1, total)) * 100)
        self.prog_bar.setValue(pct)
        self.status_bar.showMessage(msg)

    def on_chapter_saved(self, chapter: Chapter):
        # Cập nhật lại bảng
        chapters = self.storage.get_all_chapters(story_id=1)
        self.table_chapters.update_chapters(chapters)

    def on_crawl_finished(self, res):
        self.log("SUCCESS", "Hoàn tất giai đoạn thu thập / nạp dữ liệu.")
        # Cập nhật bảng
        chapters = self.storage.get_all_chapters(story_id=1)
        self.table_chapters.update_chapters(chapters)

        # Chuyển sang bước 2: Sửa lỗi & Gộp tập
        if self.chk_spellcheck.isChecked() or self.chk_merge.isChecked():
            self.start_spellcheck_and_merge()
        else:
            self.reset_controls()

    def start_spellcheck_and_merge(self):
        self.log("INFO", "Bắt đầu bước hiệu đính chính tả và gộp tập...")
        merger = VolumeMerger(
            chapters_per_volume=self.spin_per_vol.value(),
            allow_partial_last_volume=self.chk_allow_partial.isChecked(),
        )

        self.merge_worker = SpellCheckMergeWorker(
            storage=self.storage,
            checker=self.spell_checker,
            merger=merger,
            start_chap=self.spin_start_chap.value(),
            end_chap=self.spin_end_chap.value(),
            start_vol=self.spin_start_vol.value(),
            output_dir=self.txt_output_dir.text().strip(),
            overwrite=self.chk_overwrite.isChecked(),
            use_ai=self.chk_use_ai.isChecked(),
            ai_checker=self.ai_checker if self.chk_use_ai.isChecked() else None,
        )
        self.merge_worker.progress_changed.connect(self.on_progress)
        self.merge_worker.log_message.connect(self.log)
        self.merge_worker.issues_ready.connect(self.on_issues_ready)
        self.merge_worker.finished_success.connect(self.on_merge_finished)
        self.merge_worker.finished_error.connect(self.on_worker_error)
        self.merge_worker.start()

    def on_issues_ready(self, issues: List[SpellIssue], edited_paragraphs_map: Dict[int, List[str]]):
        # Nạp dữ liệu vào màn hình xem trước đúng định dạng TXT sẽ xuất
        chapters = self.storage.get_chapters_range(
            story_id=1,
            start_chap=self.spin_start_chap.value(),
            end_chap=self.spin_end_chap.value(),
        )
        merger = VolumeMerger(
            chapters_per_volume=self.spin_per_vol.value(),
            allow_partial_last_volume=self.chk_allow_partial.isChecked(),
        )
        volumes = merger.build_volumes(
            chapters=chapters,
            start_volume_num=self.spin_start_vol.value(),
            expected_start_chap=self.spin_start_chap.value(),
            expected_end_chap=self.spin_end_chap.value(),
            story_title="Phàm Nhân Tu Tiên",
        )

        raw_parts = [merger.render_volume_text(v, use_edited=False) for v in volumes]
        edited_parts = [
            merger.render_volume_text(v, use_edited=True, chapter_paragraphs_map=edited_paragraphs_map)
            for v in volumes
        ]

        raw_full = "\r\n\r\n".join(raw_parts)
        edited_full = "\r\n\r\n".join(edited_parts)

        self.diff_widget.load_data(issues, raw_full, edited_full)
        self.log("INFO", f"Đã tải {len(issues)} đề xuất vào màn hình Xem trước & Duyệt lỗi.")

    def on_merge_finished(self, bundles: List[Dict[str, str]]):
        self.log("SUCCESS", f"Hoàn tất toàn bộ quy trình! Đã xuất {len(bundles)} tập.")
        self.prog_bar.setValue(100)

        # Hiển thị báo cáo của tập đầu tiên lên tab Report
        if bundles and "report" in bundles[0]:
            try:
                with open(bundles[0]["report"], "r", encoding="utf-8") as f:
                    self.txt_report_viewer.setPlainText(f.read())
            except Exception:
                pass

        QMessageBox.information(
            self,
            "Hoàn thành xuất tập",
            f"Đã xử lý và xuất thành công {len(bundles)} tập truyện vào thư mục:\n{self.txt_output_dir.text()}"
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
            self.log("WARNING", "Đã tạm dừng tác vụ.")

    def resume_process(self):
        if self.crawl_worker and self.crawl_worker.isRunning():
            self.crawl_worker.resume()
            self.btn_pause.setEnabled(True)
            self.btn_resume.setEnabled(False)
            self.log("INFO", "Tiếp tục tác vụ.")

    def stop_process(self):
        if self.crawl_worker and self.crawl_worker.isRunning():
            self.crawl_worker.stop()
        if self.merge_worker and self.merge_worker.isRunning():
            self.merge_worker.stop()
        self.log("WARNING", "Đang dừng tác vụ theo yêu cầu người dùng...")
        self.reset_controls()

    def reset_controls(self):
        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(False)
        self.btn_stop.setEnabled(False)
