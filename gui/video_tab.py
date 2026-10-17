"""
Video Production Tab Widget for Truyenaudio Desktop App.
Allows users to merge audio MP3s with background images and customizable typography
to generate YouTube-ready MP4 videos.
"""
import os
import sys
import time
from typing import List, Optional, Dict, Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QMessageBox, QGroupBox, QGridLayout, QSplitter,
    QComboBox, QColorDialog, QDialog, QProgressBar, QAbstractItemView,
    QDialogButtonBox, QFormLayout
)
from PySide6.QtCore import Qt, QTimer, Signal, QCoreApplication
from PySide6.QtGui import QColor, QFont, QPixmap, QImage, QIcon

from core.video_models import AudioVideoItem, VideoConfig, parse_filename_metadata
from core.video_renderer import render_frame
from core.ffmpeg_utils import find_ffmpeg, check_ffmpeg_installed, probe_media
from gui.video_worker import VideoExportWorker, AudioMetadataWorker, ExportSummary


class ItemEditDialog(QDialog):
    """Hộp thoại chỉnh sửa thông tin metadata của một mục audio."""
    def __init__(self, item: AudioVideoItem, parent=None):
        super().__init__(parent)
        self.item = item
        self.setWindowTitle(f"Chỉnh sửa thông tin: {item.filename}")
        self.resize(480, 320)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.txt_title = QLineEdit(self.item.story_title)
        form.addRow("Tên truyện:", self.txt_title)

        self.txt_author = QLineEdit(self.item.author)
        form.addRow("Tác giả:", self.txt_author)

        self.spin_vol = QSpinBox()
        self.spin_vol.setRange(1, 99999)
        self.spin_vol.setValue(self.item.volume_num)
        form.addRow("Số tập:", self.spin_vol)

        chap_layout = QHBoxLayout()
        self.spin_start_chap = QSpinBox()
        self.spin_start_chap.setRange(1, 99999)
        self.spin_start_chap.setValue(self.item.start_chapter)
        self.spin_end_chap = QSpinBox()
        self.spin_end_chap.setRange(1, 99999)
        self.spin_end_chap.setValue(self.item.end_chapter)
        chap_layout.addWidget(QLabel("Từ chương:"))
        chap_layout.addWidget(self.spin_start_chap)
        chap_layout.addWidget(QLabel("đến:"))
        chap_layout.addWidget(self.spin_end_chap)
        form.addRow("Khoảng chương:", chap_layout)

        bg_layout = QHBoxLayout()
        self.txt_bg = QLineEdit(self.item.custom_bg_path)
        self.txt_bg.setPlaceholderText("(Để trống để dùng ảnh nền chung)")
        btn_browse_bg = QPushButton("Chọn ảnh...")
        btn_browse_bg.clicked.connect(self.browse_bg)
        bg_layout.addWidget(self.txt_bg)
        bg_layout.addWidget(btn_browse_bg)
        form.addRow("Ảnh riêng (tùy chọn):", bg_layout)

        layout.addLayout(form)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.save)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def browse_bg(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Chọn ảnh nền riêng cho tập", "", "Image Files (*.png *.jpg *.jpeg *.webp)"
        )
        if f:
            self.txt_bg.setText(f)

    def save(self):
        self.item.story_title = self.txt_title.text().strip()
        self.item.author = self.txt_author.text().strip()
        self.item.volume_num = self.spin_vol.value()
        self.item.start_chapter = self.spin_start_chap.value()
        self.item.end_chapter = self.spin_end_chap.value()
        self.item.custom_bg_path = self.txt_bg.text().strip()
        self.accept()


class LargePreviewDialog(QDialog):
    """Cửa sổ xem trước khung hình ở kích thước lớn."""
    def __init__(self, image: QImage, title: str = "Xem trước khung hình video", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1020, 620)
        layout = QVBoxLayout(self)
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignCenter)
        pix = QPixmap.fromImage(image).scaled(980, 550, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        lbl.setPixmap(pix)
        layout.addWidget(lbl)
        btn_close = QPushButton("Đóng")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)


class VideoProductionTab(QWidget):
    log_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = VideoConfig()
        self.items: List[AudioVideoItem] = []
        self.worker: Optional[VideoExportWorker] = None
        self.meta_worker: Optional[AudioMetadataWorker] = None
        self.import_progress_dialog: Optional[QProgressDialog] = None
        self._current_preview_image: Optional[QImage] = None

        self.init_ui()
        self.detect_ffmpeg()
        self.update_preview()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        splitter = QSplitter(Qt.Horizontal)

        # ----------------- CỘT TRÁI: DANH SÁCH AUDIO -----------------
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        audio_group = QGroupBox("1. Danh Sách Audio MP3")
        audio_layout = QVBoxLayout(audio_group)

        # Thanh nút thao tác danh sách
        btn_bar = QHBoxLayout()
        self.btn_add_files = QPushButton("➕ Thêm tệp MP3...")
        self.btn_add_files.clicked.connect(self.add_audio_files)
        self.btn_add_folder = QPushButton("📁 Thêm thư mục MP3...")
        self.btn_add_folder.clicked.connect(self.add_audio_folder)
        self.btn_remove = QPushButton("✖ Xóa")
        self.btn_remove.clicked.connect(self.remove_selected_items)
        self.btn_sort = QPushButton("🔢 Sắp xếp theo tập")
        self.btn_sort.clicked.connect(self.sort_items_by_volume)
        self.btn_edit = QPushButton("✏ Sửa thông tin")
        self.btn_edit.clicked.connect(self.edit_selected_item)

        btn_bar.addWidget(self.btn_add_files)
        btn_bar.addWidget(self.btn_add_folder)
        btn_bar.addWidget(self.btn_sort)
        btn_bar.addWidget(self.btn_edit)
        btn_bar.addWidget(self.btn_remove)
        audio_layout.addLayout(btn_bar)

        # Bảng danh sách
        self.table_audio = QTableWidget()
        self.table_audio.setColumnCount(7)
        self.table_audio.setHorizontalHeaderLabels([
            "Tệp Audio", "Thời lượng", "Tên truyện", "Tập", "Khoảng chương", "Trạng thái", "Tiến độ"
        ])
        self.table_audio.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_audio.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_audio.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_audio.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_audio.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_audio.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table_audio.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table_audio.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_audio.itemSelectionChanged.connect(self.on_selection_changed)
        self.table_audio.itemDoubleClicked.connect(self.edit_selected_item)
        audio_layout.addWidget(self.table_audio)

        left_layout.addWidget(audio_group)
        splitter.addWidget(left_widget)

        # ----------------- CỘT PHẢI: CẤU HÌNH & XEM TRƯỚC -----------------
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Nhóm Cấu hình ảnh nền & chữ
        cfg_group = QGroupBox("2. Ảnh Nền & Thiết Kế Khung Hình")
        cfg_layout = QGridLayout(cfg_group)

        # Chọn ảnh nền
        cfg_layout.addWidget(QLabel("Ảnh nền chung:"), 0, 0)
        self.txt_bg_path = QLineEdit()
        self.txt_bg_path.setPlaceholderText("Chọn ảnh PNG/JPG làm nền video...")
        self.txt_bg_path.textChanged.connect(self.on_config_changed)
        cfg_layout.addWidget(self.txt_bg_path, 0, 1, 1, 3)

        self.btn_choose_bg = QPushButton("Chọn ảnh...")
        self.btn_choose_bg.clicked.connect(self.choose_bg_image)
        cfg_layout.addWidget(self.btn_choose_bg, 0, 4)

        # Chế độ ảnh nền & Độ phân giải
        cfg_layout.addWidget(QLabel("Chế độ hiển thị:"), 1, 0)
        self.combo_bg_mode = QComboBox()
        self.combo_bg_mode.addItem("Cắt đầy khung (Fill/Crop - Không méo)", "crop_fill")
        self.combo_bg_mode.addItem("Hiển thị toàn ảnh (Fit/Letterbox - Viền nền)", "fit_letterbox")
        self.combo_bg_mode.currentIndexChanged.connect(self.on_config_changed)
        cfg_layout.addWidget(self.combo_bg_mode, 1, 1)

        cfg_layout.addWidget(QLabel("Độ phân giải:"), 1, 2)
        self.combo_resolution = QComboBox()
        self.combo_resolution.addItem("1920 × 1080 (Full HD 16:9)", (1920, 1080))
        self.combo_resolution.addItem("1280 × 720 (HD 16:9)", (1280, 720))
        self.combo_resolution.currentIndexChanged.connect(self.on_config_changed)
        cfg_layout.addWidget(self.combo_resolution, 1, 3, 1, 2)

        # Tùy chọn hiển thị các dòng chữ
        chk_text_layout = QHBoxLayout()
        self.chk_show_title = QCheckBox("Tên truyện")
        self.chk_show_title.setChecked(True)
        self.chk_show_title.stateChanged.connect(self.on_config_changed)
        self.chk_show_author = QCheckBox("Tác giả")
        self.chk_show_author.setChecked(True)
        self.chk_show_author.stateChanged.connect(self.on_config_changed)
        self.chk_show_vol = QCheckBox("Số tập")
        self.chk_show_vol.setChecked(True)
        self.chk_show_vol.stateChanged.connect(self.on_config_changed)
        self.chk_show_chaps = QCheckBox("Khoảng chương")
        self.chk_show_chaps.setChecked(True)
        self.chk_show_chaps.stateChanged.connect(self.on_config_changed)

        chk_text_layout.addWidget(QLabel("<b>Hiển thị:</b>"))
        chk_text_layout.addWidget(self.chk_show_title)
        chk_text_layout.addWidget(self.chk_show_author)
        chk_text_layout.addWidget(self.chk_show_vol)
        chk_text_layout.addWidget(self.chk_show_chaps)
        chk_text_layout.addStretch()
        cfg_layout.addLayout(chk_text_layout, 2, 0, 1, 5)

        # Tùy chọn Font, Màu sắc, Viền chữ
        style_layout = QHBoxLayout()
        style_layout.addWidget(QLabel("Font chữ:"))
        self.combo_font = QComboBox()
        self.combo_font.addItems(["Segoe UI", "Arial", "Tahoma", "Times New Roman", "Verdana", "Roboto"])
        self.combo_font.currentTextChanged.connect(self.on_config_changed)
        style_layout.addWidget(self.combo_font)

        self.btn_color_text = QPushButton("Màu chữ")
        self.btn_color_text.clicked.connect(self.choose_text_color)
        style_layout.addWidget(self.btn_color_text)

        self.btn_color_stroke = QPushButton("Màu viền")
        self.btn_color_stroke.clicked.connect(self.choose_stroke_color)
        style_layout.addWidget(self.btn_color_stroke)

        self.chk_shadow = QCheckBox("Bóng chữ")
        self.chk_shadow.setChecked(True)
        self.chk_shadow.stateChanged.connect(self.on_config_changed)
        style_layout.addWidget(self.chk_shadow)

        cfg_layout.addLayout(style_layout, 3, 0, 1, 5)

        right_layout.addWidget(cfg_group)

        # Khung Xem Trước (Preview)
        prev_group = QGroupBox("3. Khung Hình Xem Trước (Khớp 100% Video Xuất)")
        prev_layout = QVBoxLayout(prev_group)

        self.lbl_preview = QLabel("Đang dựng khung hình...")
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        self.lbl_preview.setMinimumHeight(240)
        self.lbl_preview.setStyleSheet("background-color: #111; border: 1px solid #444; border-radius: 4px;")
        prev_layout.addWidget(self.lbl_preview)

        prev_btn_bar = QHBoxLayout()
        self.btn_large_preview = QPushButton("🔍 Xem kích thước lớn")
        self.btn_large_preview.clicked.connect(self.open_large_preview)
        prev_btn_bar.addStretch()
        prev_btn_bar.addWidget(self.btn_large_preview)
        prev_layout.addLayout(prev_btn_bar)

        right_layout.addWidget(prev_group)
        splitter.addWidget(right_widget)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        main_layout.addWidget(splitter, 1)

        # ----------------- KHU VỰC DƯỚI: ĐIỀU KHIỂN XUẤT VIDEO -----------------
        bot_group = QGroupBox("4. Thiết Lập Đầu Ra & Tiến Trình Xuất Video")
        bot_layout = QGridLayout(bot_group)

        bot_layout.addWidget(QLabel("Thư mục xuất video:"), 0, 0)
        self.txt_out_dir = QLineEdit(os.path.abspath("output_videos"))
        bot_layout.addWidget(self.txt_out_dir, 0, 1, 1, 2)

        self.btn_choose_out_dir = QPushButton("Chọn thư mục...")
        self.btn_choose_out_dir.clicked.connect(self.choose_output_dir)
        bot_layout.addWidget(self.btn_choose_out_dir, 0, 3)

        self.btn_check_ffmpeg = QPushButton("⚙ Kiểm tra FFmpeg")
        self.btn_check_ffmpeg.clicked.connect(self.test_ffmpeg)
        bot_layout.addWidget(self.btn_check_ffmpeg, 0, 4)

        # Chế độ xử lý tệp trùng / đã tồn tại
        bot_layout.addWidget(QLabel("Xử lý tệp đã tồn tại:"), 1, 0)
        self.combo_overwrite = QComboBox()
        self.combo_overwrite.addItem("Tự đổi tên nếu trùng (vd: _1.mp4)", "rename")
        self.combo_overwrite.addItem("Bỏ qua nếu tệp đã tồn tại", "skip")
        self.combo_overwrite.addItem("Ghi đè an toàn tệp cũ", "overwrite")
        self.combo_overwrite.currentIndexChanged.connect(self.on_overwrite_mode_changed)
        bot_layout.addWidget(self.combo_overwrite, 1, 1, 1, 2)

        # Hàng nút hành động
        act_layout = QHBoxLayout()
        self.btn_export_selected = QPushButton("▶ Xuất mục đã chọn")
        self.btn_export_selected.setStyleSheet("background-color: #1565c0; color: white; font-weight: bold; padding: 6px 14px;")
        self.btn_export_selected.clicked.connect(self.export_selected)

        self.btn_export_all = QPushButton("⏩ Xuất tất cả")
        self.btn_export_all.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 6px 16px;")
        self.btn_export_all.clicked.connect(self.export_all)

        self.btn_retry_failed = QPushButton("🔄 Xuất lại mục lỗi/hủy")
        self.btn_retry_failed.setStyleSheet("background-color: #e65100; color: white; font-weight: bold; padding: 6px 14px;")
        self.btn_retry_failed.clicked.connect(self.export_failed_or_cancelled)

        self.btn_cancel = QPushButton("⏹ Hủy tác vụ")
        self.btn_cancel.setStyleSheet("background-color: #c62828; color: white; font-weight: bold; padding: 6px 14px;")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_export)

        self.btn_open_out_folder = QPushButton("📂 Mở thư mục kết quả")
        self.btn_open_out_folder.clicked.connect(self.open_output_folder)

        act_layout.addWidget(self.btn_export_selected)
        act_layout.addWidget(self.btn_export_all)
        act_layout.addWidget(self.btn_retry_failed)
        act_layout.addWidget(self.btn_cancel)
        act_layout.addWidget(self.btn_open_out_folder)
        act_layout.addStretch()

        self.lbl_time_info = QLabel("Thời gian đã chạy: 00:00 | Còn lại: --:--")
        self.lbl_time_info.setStyleSheet("color: #444; font-weight: bold;")
        act_layout.addWidget(self.lbl_time_info)

        bot_layout.addLayout(act_layout, 2, 0, 1, 5)

        # Thanh tiến độ kép: Tập hiện tại & Toàn bộ hàng đợi
        prog_layout = QVBoxLayout()
        
        p1_box = QHBoxLayout()
        p1_box.addWidget(QLabel("Tiến độ tập hiện tại:"))
        self.prog_item = QProgressBar()
        self.prog_item.setValue(0)
        p1_box.addWidget(self.prog_item)
        prog_layout.addLayout(p1_box)

        p2_box = QHBoxLayout()
        p2_box.addWidget(QLabel("Tiến độ toàn hàng đợi:"))
        self.prog_queue = QProgressBar()
        self.prog_queue.setValue(0)
        p2_box.addWidget(self.prog_queue)
        prog_layout.addLayout(p2_box)

        bot_layout.addLayout(prog_layout, 3, 0, 1, 5)
        main_layout.addWidget(bot_group)

        # Timer cập nhật thời gian chạy
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.timeout.connect(self.update_elapsed_time)
        self.start_epoch = 0.0

    # ----------------- LOGGING & NOTIFICATIONS -----------------
    def log(self, level: str, msg: str):
        self.log_requested.emit(level, msg)

    # ----------------- AUDIO LIST MANAGEMENT -----------------
    def add_audio_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Chọn các tệp âm thanh MP3", "", "Audio Files (*.mp3 *.wav *.m4a *.aac)"
        )
        if files:
            self._import_audio_paths(files)

    def add_audio_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục chứa tệp MP3")
        if folder:
            cand = []
            for root, _, fs in os.walk(folder):
                for f in fs:
                    if f.lower().endswith((".mp3", ".wav", ".m4a", ".aac")):
                        cand.append(os.path.join(root, f))
            self._import_audio_paths(cand)

    def _import_audio_paths(self, filepaths: List[str]):
        if not filepaths:
            return

        if self.meta_worker and self.meta_worker.isRunning():
            QMessageBox.information(
                self, "Đang xử lý", "Tiến trình nạp tệp âm thanh trước đó đang chạy. Vui lòng đợi hoàn tất."
            )
            return

        existing_paths = {os.path.abspath(it.audio_path) for it in self.items}

        self.btn_add_files.setEnabled(False)
        self.btn_add_folder.setEnabled(False)

        self.meta_worker = AudioMetadataWorker(
            filepaths=filepaths,
            existing_paths=existing_paths,
            ffprobe_path=self.config.ffprobe_path,
        )
        self.meta_worker.progress.connect(self._on_meta_progress)
        self.meta_worker.item_probed.connect(self._on_meta_item_probed)
        self.meta_worker.all_finished.connect(self._on_meta_all_finished)

        self.import_progress_dialog = QProgressDialog(
            "Đang kiểm tra tệp âm thanh...", "Hủy", 0, len(filepaths), self
        )
        self.import_progress_dialog.setWindowTitle("Nạp tệp âm thanh vào danh sách")
        self.import_progress_dialog.setWindowModality(Qt.WindowModal)
        self.import_progress_dialog.setMinimumDuration(200)
        self.import_progress_dialog.canceled.connect(self._cancel_metadata_import)

        self.meta_worker.start()

    def _on_meta_progress(self, current: int, total: int, filename: str):
        if self.import_progress_dialog:
            self.import_progress_dialog.setValue(current)
            self.import_progress_dialog.setLabelText(f"Đang kiểm tra [{current}/{total}]: {filename}")

    def _on_meta_item_probed(self, data: dict):
        status = data.get("status")
        norm_path = data.get("path", "")
        fname = data.get("filename", "")

        if status == "valid":
            # Đảm bảo không trùng với mục đã có trong self.items
            if any(os.path.abspath(it.audio_path) == norm_path for it in self.items):
                return
            dur = data.get("duration", 0.0)
            item = AudioVideoItem(audio_path=norm_path, duration=dur)
            meta = data.get("metadata", {})
            if "volume_num" in meta:
                item.volume_num = meta["volume_num"]
            if "start_chapter" in meta and "end_chapter" in meta:
                item.start_chapter = meta["start_chapter"]
                item.end_chapter = meta["end_chapter"]
            if "story_title" in meta:
                item.story_title = meta["story_title"]
            if "author" in meta:
                item.author = meta["author"]
            self.items.append(item)
            self.refresh_table()

        elif status == "error":
            err_msg = data.get("error", "Tệp âm thanh không hợp lệ")
            self.log("ERROR", f"Bỏ qua tệp hỏng '{fname}': {err_msg}")

        elif status == "duplicate":
            self.log("INFO", f"Bỏ qua tệp trùng lặp: {fname}")

    def _on_meta_all_finished(self, added_count: int, skipped_dup: int, error_count: int):
        if self.import_progress_dialog:
            self.import_progress_dialog.close()
            self.import_progress_dialog = None

        self.btn_add_files.setEnabled(True)
        self.btn_add_folder.setEnabled(True)
        self.refresh_table()

        if self.items:
            self.table_audio.selectRow(len(self.items) - 1)
            self.update_preview()

        msg = f"Đã nạp xong danh sách: {added_count} tệp hợp lệ."
        if skipped_dup > 0:
            msg += f" Bỏ qua {skipped_dup} tệp trùng lặp."
        if error_count > 0:
            msg += f" Bỏ qua {error_count} tệp lỗi/hỏng."
        self.log("INFO" if error_count == 0 else "WARNING", msg)

        if error_count > 0:
            QMessageBox.warning(
                self,
                "Tệp không hợp lệ",
                f"Đã bỏ qua {error_count} tệp âm thanh không hợp lệ (không đọc được, thiếu luồng audio hoặc thời lượng bằng 0).\nXem nhật ký để biết chi tiết."
            )

    def _cancel_metadata_import(self):
        if self.meta_worker and self.meta_worker.isRunning():
            self.meta_worker.cancel()
            self.log("WARNING", "Đã yêu cầu hủy nạp tệp âm thanh.")

    def add_direct_items(self, items_data: List[dict]) -> int:
        """Thêm trực tiếp các mục MP3 với metadata chính xác từ thẻ Sản Xuất Audio."""
        added_count = 0
        for data in items_data:
            path = data.get("audio_path")
            if not path or not os.path.isfile(path):
                continue
            norm_path = os.path.abspath(path)
            if any(os.path.abspath(it.audio_path) == norm_path for it in self.items):
                continue
            item = AudioVideoItem(
                audio_path=norm_path,
                duration=data.get("duration", 0.0),
                story_title=data.get("story_title", ""),
                author=data.get("author", ""),
                volume_num=data.get("volume_num", 1),
                start_chapter=data.get("start_chapter", 1),
                end_chapter=data.get("end_chapter", 1),
            )
            self.items.append(item)
            added_count += 1
        self.refresh_table()
        if self.items:
            self.table_audio.selectRow(len(self.items) - 1)
            self.update_preview()
        return added_count

    def remove_selected_items(self):
        selected_rows = sorted({idx.row() for idx in self.table_audio.selectedIndexes()}, reverse=True)
        if not selected_rows:
            return
        for r in selected_rows:
            if 0 <= r < len(self.items):
                del self.items[r]
        self.refresh_table()
        self.update_preview()

    def sort_items_by_volume(self):
        """Sắp xếp tự nhiên theo số tập tránh 10 đứng trước 2."""
        self.items.sort(key=lambda x: (x.volume_num, x.start_chapter, x.filename))
        self.refresh_table()
        self.log("INFO", "Đã sắp xếp danh sách audio theo thứ tự số tập.")

    def edit_selected_item(self):
        row = self.table_audio.currentRow()
        if 0 <= row < len(self.items):
            dlg = ItemEditDialog(self.items[row], self)
            if dlg.exec():
                self.refresh_table()
                self.update_preview()

    def refresh_table(self):
        self.table_audio.setRowCount(len(self.items))
        for row, it in enumerate(self.items):
            self.table_audio.setItem(row, 0, QTableWidgetItem(it.filename))
            self.table_audio.setItem(row, 1, QTableWidgetItem(it.display_duration))
            self.table_audio.setItem(row, 2, QTableWidgetItem(it.story_title or "--"))
            self.table_audio.setItem(row, 3, QTableWidgetItem(f"Tập {it.volume_num}"))
            self.table_audio.setItem(row, 4, QTableWidgetItem(f"Chương {it.start_chapter} – {it.end_chapter}"))

            st_map = {
                "waiting": "Chờ xử lý",
                "processing": "Đang kết xuất...",
                "completed": "Hoàn tất",
                "skipped": "Đã bỏ qua",
                "error": "Lỗi",
                "cancelled": "Đã hủy",
            }
            color_map = {
                "waiting": "#555",
                "processing": "#1565c0",
                "completed": "#2e7d32",
                "skipped": "#00838f",
                "error": "#c62828",
                "cancelled": "#e65100",
            }
            item_st = QTableWidgetItem(st_map.get(it.status, it.status))
            item_st.setForeground(QColor(color_map.get(it.status, "#000")))
            self.table_audio.setItem(row, 5, item_st)

            prog_str = f"{it.progress:.0f}%" if it.progress > 0 else "0%"
            self.table_audio.setItem(row, 6, QTableWidgetItem(prog_str))

    def on_selection_changed(self):
        self.update_preview()

    # ----------------- CONFIG & PREVIEW -----------------
    def choose_bg_image(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Chọn ảnh nền chung cho video", "", "Image Files (*.png *.jpg *.jpeg *.webp)"
        )
        if f:
            self.txt_bg_path.setText(f)

    def choose_text_color(self):
        c = QColorDialog.getColor(QColor(self.config.text_color), self, "Chọn màu chữ chính")
        if c.isValid():
            self.config.text_color = c.name()
            self.btn_color_text.setStyleSheet(f"background-color: {c.name()}; color: {'#000' if c.lightness() > 128 else '#fff'};")
            self.update_preview()

    def choose_stroke_color(self):
        c = QColorDialog.getColor(QColor(self.config.stroke_color), self, "Chọn màu viền chữ")
        if c.isValid():
            self.config.stroke_color = c.name()
            self.btn_color_stroke.setStyleSheet(f"background-color: {c.name()}; color: {'#000' if c.lightness() > 128 else '#fff'};")
            self.update_preview()

    def on_config_changed(self):
        self.config.bg_image_path = self.txt_bg_path.text().strip()
        self.config.bg_mode = self.combo_bg_mode.currentData()
        res = self.combo_resolution.currentData()
        if res:
            self.config.width, self.config.height = res
        self.config.show_title = self.chk_show_title.isChecked()
        self.config.show_author = self.chk_show_author.isChecked()
        self.config.show_volume = self.chk_show_vol.isChecked()
        self.config.show_chapters = self.chk_show_chaps.isChecked()
        self.config.font_family = self.combo_font.currentText()
        self.config.has_shadow = self.chk_shadow.isChecked()
        self.update_preview()

    def get_active_item(self) -> AudioVideoItem:
        row = self.table_audio.currentRow()
        if 0 <= row < len(self.items):
            return self.items[row]
        # Nếu chưa chọn mục nào, dùng mục mẫu hiển thị
        return AudioVideoItem(
            audio_path="sample.mp3",
            story_title="Tiên Nghịch",
            author="Nhĩ Căn",
            volume_num=1,
            start_chapter=1,
            end_chapter=4
        )

    def update_preview(self):
        item = self.get_active_item()
        try:
            img = render_frame(item, self.config)
            self._current_preview_image = img
            scaled = QPixmap.fromImage(img).scaled(
                self.lbl_preview.width() - 8,
                self.lbl_preview.height() - 8,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.lbl_preview.setPixmap(scaled)
        except Exception as e:
            self.lbl_preview.setText(f"<font color='red'>Lỗi hiển thị xem trước:<br>{e}</font>")

    def open_large_preview(self):
        if self._current_preview_image:
            dlg = LargePreviewDialog(self._current_preview_image, "Khung hình xem trước kích thước lớn (1080p)", self)
            dlg.exec()

    # ----------------- EXPORTING -----------------
    def choose_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu video")
        if d:
            self.txt_out_dir.setText(d)
            self.config.output_dir = d

    def detect_ffmpeg(self):
        ok, f_ver, _ = check_ffmpeg_installed(self.config.ffmpeg_path, self.config.ffprobe_path)
        if ok:
            self.log("INFO", f"Đã kết nối FFmpeg: {f_ver}")
        else:
            self.log("WARNING", f"Chưa tìm thấy FFmpeg: {f_ver}")

    def test_ffmpeg(self):
        ok, f_ver, p_ver = check_ffmpeg_installed(self.config.ffmpeg_path, self.config.ffprobe_path)
        if ok:
            QMessageBox.information(
                self, "Kiểm tra FFmpeg",
                f"✅ FFmpeg và ffprobe đã sẵn sàng hoạt động!\n\n- FFmpeg: {f_ver}\n- ffprobe: {p_ver}"
            )
        else:
            QMessageBox.warning(
                self, "Thiếu FFmpeg",
                f"❌ Chưa phát hiện FFmpeg trên máy:\n{f_ver}\n\nVui lòng cài đặt FFmpeg và đưa vào PATH hoặc cấu hình vị trí tệp."
            )

    def open_output_folder(self):
        folder = self.txt_out_dir.text().strip()
        if os.path.exists(folder):
            os.startfile(folder)
        else:
            QMessageBox.warning(self, "Thư mục không tồn tại", f"Thư mục '{folder}' chưa được tạo.")

    def on_overwrite_mode_changed(self):
        self.config.overwrite_mode = self.combo_overwrite.currentData()

    def export_selected(self):
        rows = sorted({idx.row() for idx in self.table_audio.selectedIndexes()})
        if not rows:
            QMessageBox.information(self, "Chưa chọn mục", "Vui lòng chọn ít nhất một mục audio trong bảng để xuất.")
            return
        selected_items = [self.items[r] for r in rows if 0 <= r < len(self.items)]
        self._start_export(selected_items)

    def export_all(self):
        if not self.items:
            QMessageBox.information(self, "Danh sách rỗng", "Vui lòng thêm ít nhất một tệp MP3 vào danh sách.")
            return
        self._start_export(self.items)

    def export_failed_or_cancelled(self):
        retry_items = [it for it in self.items if it.status in ("error", "cancelled")]
        if not retry_items:
            QMessageBox.information(
                self, "Không có mục cần chạy lại", "Không tìm thấy mục nào có trạng thái lỗi hoặc đã hủy."
            )
            return
        self._start_export(retry_items)

    def _start_export(self, items_to_export: List[AudioVideoItem]):
        ok, f_ver, _ = check_ffmpeg_installed(self.config.ffmpeg_path, self.config.ffprobe_path)
        if not ok:
            QMessageBox.critical(self, "Thiếu FFmpeg", f"Không thể xuất video: {f_ver}")
            return

        self.config.output_dir = self.txt_out_dir.text().strip() or "output_videos"
        self.config.overwrite_mode = self.combo_overwrite.currentData()
        os.makedirs(self.config.output_dir, exist_ok=True)

        # Lọc và kiểm tra các mục hợp lệ
        valid_items: List[AudioVideoItem] = []
        for it in items_to_export:
            if not os.path.isfile(it.audio_path) or it.duration <= 0:
                it.status = "error"
                it.error_message = "Tệp audio không tồn tại hoặc thời lượng không hợp lệ."
            else:
                it.status = "waiting"
                it.progress = 0.0
                it.error_message = ""
                valid_items.append(it)

        self.refresh_table()

        if not valid_items:
            QMessageBox.warning(
                self, "Không có mục hợp lệ", "Tất cả các mục được chọn đều không hợp lệ hoặc thiếu tệp audio."
            )
            return

        self.btn_export_selected.setEnabled(False)
        self.btn_export_all.setEnabled(False)
        self.btn_retry_failed.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.prog_item.setValue(0)
        self.prog_queue.setValue(0)

        self.start_epoch = time.time()
        self.elapsed_timer.start(1000)

        self.worker = VideoExportWorker(valid_items, self.config)
        self.worker.item_started.connect(self.on_worker_item_started)
        self.worker.item_progress.connect(self.on_worker_item_progress)
        self.worker.queue_progress.connect(self.on_worker_queue_progress)
        self.worker.item_finished.connect(self.on_worker_item_finished)
        self.worker.item_skipped.connect(self.on_worker_item_skipped)
        self.worker.item_failed.connect(self.on_worker_item_failed)
        self.worker.item_cancelled.connect(self.on_worker_item_cancelled)
        self.worker.log_message.connect(self.log)
        self.worker.all_finished.connect(self.on_worker_all_finished)
        self.worker.start()

    def cancel_export(self):
        if self.worker and self.worker.isRunning():
            self.btn_cancel.setEnabled(False)
            self.log("WARNING", "Đang dừng tiến trình xuất video...")
            self.worker.cancel()

    def update_elapsed_time(self):
        if self.start_epoch > 0:
            elapsed = int(time.time() - self.start_epoch)
            mins = elapsed // 60
            secs = elapsed % 60
            self.lbl_time_info.setText(f"Thời gian đã chạy: {mins:02d}:{secs:02d}")

    def on_worker_item_started(self, item_id: str):
        for it in self.items:
            if it.id == item_id:
                it.status = "processing"
                break
        self.refresh_table()

    def on_worker_item_progress(self, item_id: str, pct: float):
        for it in self.items:
            if it.id == item_id:
                it.progress = pct
                break
        self.prog_item.setValue(int(pct))
        self.refresh_table()

    def on_worker_queue_progress(self, completed: int, total: int, q_pct: float, eta_str: str):
        self.prog_queue.setValue(int(q_pct))
        elapsed = int(time.time() - self.start_epoch) if self.start_epoch > 0 else 0
        mins = elapsed // 60
        secs = elapsed % 60
        self.lbl_time_info.setText(f"Thời gian đã chạy: {mins:02d}:{secs:02d} | Còn lại: {eta_str}")

    def on_worker_item_finished(self, item_id: str, out_path: str):
        for it in self.items:
            if it.id == item_id:
                it.status = "completed"
                it.output_path = out_path
                it.progress = 100.0
                break
        self.refresh_table()

    def on_worker_item_skipped(self, item_id: str, reason: str):
        for it in self.items:
            if it.id == item_id:
                it.status = "skipped"
                it.error_message = reason
                it.progress = 100.0
                break
        self.refresh_table()

    def on_worker_item_cancelled(self, item_id: str):
        for it in self.items:
            if it.id == item_id:
                it.status = "cancelled"
                it.error_message = "Đã bị hủy bởi người dùng."
                break
        self.refresh_table()

    def on_worker_item_failed(self, item_id: str, err: str):
        for it in self.items:
            if it.id == item_id:
                it.status = "error"
                it.error_message = err
                break
        self.refresh_table()

    def on_worker_all_finished(self, summary: Any):
        self.elapsed_timer.stop()
        self.btn_export_selected.setEnabled(True)
        self.btn_export_all.setEnabled(True)
        self.btn_retry_failed.setEnabled(True)
        self.btn_cancel.setEnabled(False)

        if isinstance(summary, dict):
            status = summary.get("status", "hoàn tất")
            succ = summary.get("success", 0)
            skip = summary.get("skipped", 0)
            err = summary.get("error", 0)
            canc = summary.get("cancelled", 0)
        elif isinstance(summary, (tuple, list)):
            succ = summary[0]
            err = summary[1] if len(summary) > 1 else 0
            skip = 0
            canc = 0
            status = "hoàn tất có lỗi" if err > 0 else "hoàn tất"
        else:
            status = getattr(summary, "status", "hoàn tất")
            succ = getattr(summary, "success_count", 0)
            skip = getattr(summary, "skipped_count", 0)
            err = getattr(summary, "error_count", 0)
            canc = getattr(summary, "cancelled_count", 0)

        # Cập nhật thanh tiến độ theo trạng thái thực tế
        if status == "đã hủy":
            # Sau khi hủy, tiến độ giữ đúng phần đã xử lý; không ép thành 100%
            self.prog_item.setValue(0)
        elif status == "hoàn tất có lỗi":
            self.prog_queue.setValue(100)
            self.prog_item.setValue(0)
        else:
            self.prog_queue.setValue(100)
            self.prog_item.setValue(100)

        self.refresh_table()

        summary_msg = (
            f"Tổng kết xuất video [{status.upper()}]: "
            f"{succ} thành công, {skip} bỏ qua, {err} lỗi, {canc} đã hủy."
        )
        if status == "đã hủy":
            self.log("WARNING", summary_msg)
        elif status == "hoàn tất có lỗi":
            self.log("ERROR", summary_msg)
        else:
            self.log("SUCCESS", summary_msg)

    def is_busy(self) -> bool:
        """Kiểm tra có bất kỳ worker nào đang chạy trong tab không."""
        return (self.worker is not None and self.worker.isRunning()) or (
            self.meta_worker is not None and self.meta_worker.isRunning()
        )

    def stop_all_workers(self):
        """Yêu cầu hủy dừng an toàn mọi worker."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
        if self.meta_worker and self.meta_worker.isRunning():
            self.meta_worker.cancel()

    def wait_all_workers(self, timeout_ms: int = 5000) -> bool:
        """Chờ tất cả worker dừng mà không làm đơ giao diện."""
        start = time.time()
        while (time.time() - start) * 1000 < timeout_ms:
            busy = False
            if self.worker and self.worker.isRunning():
                busy = True
                self.worker.wait(50)
            if self.meta_worker and self.meta_worker.isRunning():
                busy = True
                self.meta_worker.wait(50)
            if not busy:
                return True
            QCoreApplication.processEvents()
        return not self.is_busy()
