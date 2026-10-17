"""
Audio Production Studio Tab Widget for Truyenaudio Desktop App.
Matches the modern dark glassmorphic Studio UI:
- Left: "VĂN BẢN ĐỌC" with emotion tags, sample templates, live counters, and text cleaning tools.
- Right: "Giọng đọc (25)" with gender filters, rich voice cards, sample preview, and speed slider.
- Bottom: Floating action & player bar with "Tạo giọng nói", subtitles toggle, built-in player, WAV/MP3 export, and 1-click video transfer.
"""
import os
import sys
import re
import time
import shutil
import subprocess
from typing import List, Optional, Dict, Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QDoubleSpinBox, QSlider, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QMessageBox, QGroupBox, QGridLayout, QSplitter,
    QProgressBar, QAbstractItemView, QDialog, QDialogButtonBox,
    QFormLayout, QTextEdit, QScrollArea, QFrame, QSizePolicy, QMenu
)
from PySide6.QtCore import Qt, QTimer, Signal, QUrl, QSize
from PySide6.QtGui import QColor, QFont, QIcon, QTextCursor
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from core.tts_models import TTSItem, TTSChunk, TTSConfig, TTSEnvStatus, TTSVoice, get_default_voices
from core.tts_chunker import TextChunker
from core.tts_manifest import TTSManifestManager
from core.tts_adapter import TTSAdapter
from core.tts_assembler import TTSAudioAssembler
from core.tts_dictionary import TTSDictionaryManager, clean_reading_text
from core.ffmpeg_utils import find_ffmpeg, probe_media, get_subprocess_hidden_kwargs
from core.video_models import parse_filename_metadata
from gui.tts_worker import TTSQueueWorker, TTSPreviewWorker


# Default sample text matching user screenshot
DEFAULT_STUDIO_TEXT = (
    "PHÀM NHÂN TU TIÊN - TẬP 260\n"
    "Chào mừng các bạn đang theo dõi bộ truyện tiên hiệp Phàm Nhân Tu Tiên, tác giả Vong Ngữ.\n"
    "Đây là Tập 260, phát từ Chương 1037 đến Chương 1040.\n"
    "Chúc các bạn có những giây phút thư giãn và trải nghiệm tuyệt vời.\n"
    "Ngân Nguyệt sau khi thân hình đứng vững lại, sắc mặt tái nhợt nhưng lại hướng \"Hoa Thiên Kỳ\" khóe miệng đột nhiên lộ ra một tia giễu cợt.\n"
    "\"Người là ta. Ta cũng là ngươi. Nếu là để cho người nào biết được việc này. Ngươi cho rằng tình cảnh của ngươi có thể tốt hơn chỗ nào? Huống hồ mặc dù người mà người nọ cưới là Linh Lung. Nhưng hắn sủng ái nhiều nhất vẫn là ta? Chớ quên.\""
)


# ---------------------------------------------------------------------------
# DIALOGS
# ---------------------------------------------------------------------------

class TTSDictionaryDialog(QDialog):
    """Cửa sổ quản lý từ điển phát âm / quy tắc đọc tên riêng và từ viết tắt."""
    def __init__(self, dict_manager: TTSDictionaryManager, parent=None):
        super().__init__(parent)
        self.dm = dict_manager
        self.setWindowTitle("📖 Từ điển phát âm & Quy tắc thay thế")
        self.resize(600, 420)
        self.setStyleSheet("""
            QDialog { background-color: #0f141c; color: #f1f5f9; }
            QLabel { color: #cbd5e1; }
            QTableWidget {
                background-color: #131926;
                color: #f1f5f9;
                gridline-color: #1e293b;
                border: 1px solid #1e293b;
                border-radius: 6px;
            }
            QHeaderView::section {
                background-color: #1e293b;
                color: #94a3b8;
                padding: 6px;
                font-weight: bold;
                border: none;
            }
            QPushButton {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #334155;
                padding: 6px 14px;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #334155; }
        """)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        info = QLabel("Quản lý các từ viết tắt, tên riêng hoặc từ Hán Việt cần chuẩn hóa khi phát âm:")
        layout.addWidget(info)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Từ viết tắt / Gốc", "Đọc thành", "Phân biệt HOA/thường"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.table)

        self.load_table()

        btn_bar = QHBoxLayout()
        btn_add = QPushButton("➕ Thêm từ")
        btn_add.clicked.connect(self.add_row)
        btn_del = QPushButton("🗑️ Xóa dòng")
        btn_del.clicked.connect(self.del_row)
        btn_save = QPushButton("💾 Lưu thay đổi")
        btn_save.setStyleSheet("background-color: #0284c7; font-weight: bold;")
        btn_save.clicked.connect(self.save_and_close)

        btn_bar.addWidget(btn_add)
        btn_bar.addWidget(btn_del)
        btn_bar.addStretch()
        btn_bar.addWidget(btn_save)
        layout.addLayout(btn_bar)

    def load_table(self):
        self.table.setRowCount(len(self.dm.rules))
        for r, item in enumerate(self.dm.rules):
            self.table.setItem(r, 0, QTableWidgetItem(item.get("source", "")))
            self.table.setItem(r, 1, QTableWidgetItem(item.get("target", "")))
            case_sens = "Có" if item.get("case_sensitive", False) else "Không"
            self.table.setItem(r, 2, QTableWidgetItem(case_sens))

    def add_row(self):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem("PNTT"))
        self.table.setItem(r, 1, QTableWidgetItem("Phàm Nhân Tu Tiên"))
        self.table.setItem(r, 2, QTableWidgetItem("Không"))

    def del_row(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)

    def save_and_close(self):
        new_rules = []
        for r in range(self.table.rowCount()):
            src = self.table.item(r, 0).text().strip() if self.table.item(r, 0) else ""
            tgt = self.table.item(r, 1).text().strip() if self.table.item(r, 1) else ""
            cs_text = self.table.item(r, 2).text().strip().lower() if self.table.item(r, 2) else "không"
            case_sens = (cs_text in ("có", "yes", "true", "1"))
            if src and tgt:
                new_rules.append({"source": src, "target": tgt, "case_sensitive": case_sens})
        self.dm.rules = new_rules
        self.dm.save()
        self.accept()


class TTSSettingsDialog(QDialog):
    """Hộp thoại cấu hình nâng cao động cơ VieNeu-TTS."""
    def __init__(self, config: TTSConfig, env_status: TTSEnvStatus, parent=None):
        super().__init__(parent)
        self.config = config
        self.env_status = env_status
        self.setWindowTitle("⚙ Cấu hình Engine VieNeu-TTS")
        self.resize(520, 360)
        self.setStyleSheet("""
            QDialog { background-color: #0f141c; color: #f1f5f9; }
            QLabel { color: #cbd5e1; }
            QLineEdit, QComboBox, QSpinBox {
                background-color: #131926;
                color: #f1f5f9;
                border: 1px solid #1e293b;
                padding: 6px;
                border-radius: 6px;
            }
            QPushButton {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #334155;
                padding: 6px 14px;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #334155; }
        """)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)

        # Python path
        py_box = QHBoxLayout()
        self.txt_py = QLineEdit(self.config.python_path)
        self.txt_py.setPlaceholderText("(Để trống để tự động nhận diện venv_tts hoặc .venv)")
        btn_browse = QPushButton("Chọn...")
        btn_browse.clicked.connect(self.browse_python)
        py_box.addWidget(self.txt_py)
        py_box.addWidget(btn_browse)
        form.addRow("Python TTS:", py_box)

        # Model
        self.combo_model = QComboBox()
        self.combo_model.addItems(["v3_turbo (Mặc định)", "v3nano"])
        if self.config.model_name == "v3nano":
            self.combo_model.setCurrentIndex(1)
        form.addRow("Model VieNeu:", self.combo_model)

        # Backend
        self.combo_backend = QComboBox()
        self.combo_backend.addItems(["onnx (CPU chuẩn)", "pytorch (GPU)"])
        if self.config.backend == "pytorch":
            self.combo_backend.setCurrentIndex(1)
        form.addRow("Backend:", self.combo_backend)

        # Pauses
        self.spin_sent = QSpinBox()
        self.spin_sent.setRange(0, 3000)
        self.spin_sent.setValue(self.config.pause_sentence_ms)
        self.spin_sent.setSuffix(" ms")
        form.addRow("Nghỉ câu:", self.spin_sent)

        self.spin_para = QSpinBox()
        self.spin_para.setRange(0, 5000)
        self.spin_para.setValue(self.config.pause_paragraph_ms)
        self.spin_para.setSuffix(" ms")
        form.addRow("Nghỉ đoạn:", self.spin_para)

        self.spin_chap = QSpinBox()
        self.spin_chap.setRange(0, 10000)
        self.spin_chap.setValue(self.config.pause_chapter_ms)
        self.spin_chap.setSuffix(" ms")
        form.addRow("Nghỉ chương:", self.spin_chap)

        # Bitrate
        self.combo_bitrate = QComboBox()
        self.combo_bitrate.addItems(["192k (Khuyến nghị)", "128k", "256k", "320k"])
        for idx, br in enumerate(["192k", "128k", "256k", "320k"]):
            if br in self.config.mp3_bitrate:
                self.combo_bitrate.setCurrentIndex(idx)
        form.addRow("Bitrate MP3:", self.combo_bitrate)

        layout.addLayout(form)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.save)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def browse_python(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Chọn python.exe môi trường TTS", "", "Python Executable (python.exe);;All Files (*)"
        )
        if f:
            self.txt_py.setText(f)

    def save(self):
        self.config.python_path = self.txt_py.text().strip()
        self.config.model_name = self.combo_model.currentText().split()[0]
        self.config.backend = self.combo_backend.currentText().split()[0]
        self.config.pause_sentence_ms = self.spin_sent.value()
        self.config.pause_paragraph_ms = self.spin_para.value()
        self.config.pause_chapter_ms = self.spin_chap.value()
        self.config.mp3_bitrate = self.combo_bitrate.currentText().split()[0]
        self.accept()


# ---------------------------------------------------------------------------
# VOICE CARD WIDGET
# ---------------------------------------------------------------------------

class VoiceCardWidget(QFrame):
    """
    Thẻ hiển thị từng giọng đọc chuẩn hóa theo thiết kế studio:
    - Biểu tượng giới tính tròn Nam ♂ (xanh dương) / Nữ ♀ (hồng)
    - Tên giọng + Ngôi sao vàng ⭐ + Nhãn vùng miền (Bắc / Nam / Trung)
    - Dòng mô tả phong cách và tần số 48 kHz
    - Nút nghe thử tròn ▶
    - Dấu tích chọn ✓ màu xanh ngọc khi được chọn
    """
    clicked = Signal(object)           # self
    preview_clicked = Signal(object)   # voice

    def __init__(self, voice: TTSVoice, is_selected: bool = False, parent=None):
        super().__init__(parent)
        self.voice = voice
        self.is_selected = is_selected
        self.is_playing_preview = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(66)
        self.init_ui()
        self.update_style()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 12, 8)
        layout.setSpacing(10)

        # 1. Avatar giới tính tròn
        is_male = (self.voice.gender == "Nam")
        badge_bg = "#0284c7" if is_male else "#db2777"
        gender_sym = "♂" if is_male else "♀"

        self.lbl_gender = QLabel(gender_sym)
        self.lbl_gender.setFixedSize(38, 38)
        self.lbl_gender.setAlignment(Qt.AlignCenter)
        self.lbl_gender.setStyleSheet(f"""
            background-color: {badge_bg};
            color: #ffffff;
            font-size: 20px;
            font-weight: bold;
            border-radius: 19px;
        """)
        layout.addWidget(self.lbl_gender)

        # 2. Thông tin giọng
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        info_layout.setContentsMargins(0, 0, 0, 0)

        # Hàng 1: Tên + Sao + Vùng miền
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        self.lbl_name = QLabel(self.voice.display_name)
        self.lbl_name.setStyleSheet("font-size: 13px; font-weight: bold; color: #ffffff;")
        top_row.addWidget(self.lbl_name)

        if self.voice.starred:
            lbl_star = QLabel("⭐")
            lbl_star.setStyleSheet("font-size: 11px;")
            top_row.addWidget(lbl_star)

        reg_badge = QLabel(self.voice.region or "Bắc")
        reg_badge.setStyleSheet("""
            background-color: #1e293b;
            color: #94a3b8;
            font-size: 10px;
            font-weight: bold;
            padding: 2px 6px;
            border-radius: 4px;
            border: 1px solid #334155;
        """)
        top_row.addWidget(reg_badge)
        top_row.addStretch()

        info_layout.addLayout(top_row)

        # Hàng 2: Mô tả (Nam · Bắc · Phong cách tự nhiên · 48 kHz)
        desc_text = self.voice.description or f"{self.voice.gender} · {self.voice.region} · {self.voice.style} · 48 kHz"
        self.lbl_desc = QLabel(desc_text)
        self.lbl_desc.setStyleSheet("font-size: 11px; color: #94a3b8;")
        info_layout.addWidget(self.lbl_desc)

        layout.addLayout(info_layout, stretch=1)

        # 3. Nút nghe thử mẫu
        self.btn_preview = QPushButton("▶")
        self.btn_preview.setFixedSize(30, 30)
        self.btn_preview.setCursor(Qt.PointingHandCursor)
        self.btn_preview.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #ffffff;
                font-size: 12px;
                border-radius: 15px;
                border: 1px solid #334155;
            }
            QPushButton:hover {
                background-color: #06d6a0;
                color: #000000;
                border-color: #06d6a0;
            }
        """)
        self.btn_preview.clicked.connect(self._on_preview_clicked)
        layout.addWidget(self.btn_preview)

        # 4. Dấu kiểm chọn ✓
        self.lbl_check = QLabel("✓")
        self.lbl_check.setFixedSize(22, 22)
        self.lbl_check.setAlignment(Qt.AlignCenter)
        self.lbl_check.setStyleSheet("""
            background-color: #06d6a0;
            color: #0b0e14;
            font-size: 13px;
            font-weight: bold;
            border-radius: 11px;
        """)
        self.lbl_check.setVisible(self.is_selected)
        layout.addWidget(self.lbl_check)

    def _on_preview_clicked(self):
        self.preview_clicked.emit(self.voice)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self)
        super().mousePressEvent(event)

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self.lbl_check.setVisible(selected)
        self.update_style()

    def set_playing(self, playing: bool):
        self.is_playing_preview = playing
        self.btn_preview.setText("⏸" if playing else "▶")
        if playing:
            self.btn_preview.setStyleSheet("""
                QPushButton {
                    background-color: #06d6a0;
                    color: #000000;
                    font-size: 12px;
                    border-radius: 15px;
                    border: 1px solid #06d6a0;
                }
            """)
        else:
            self.btn_preview.setStyleSheet("""
                QPushButton {
                    background-color: #1e293b;
                    color: #ffffff;
                    font-size: 12px;
                    border-radius: 15px;
                    border: 1px solid #334155;
                }
                QPushButton:hover {
                    background-color: #06d6a0;
                    color: #000000;
                    border-color: #06d6a0;
                }
            """)

    def update_style(self):
        if self.is_selected:
            self.setStyleSheet("""
                VoiceCardWidget {
                    background-color: #0f2738;
                    border: 1.5px solid #06d6a0;
                    border-radius: 10px;
                }
            """)
        else:
            self.setStyleSheet("""
                VoiceCardWidget {
                    background-color: #131926;
                    border: 1px solid #1e293b;
                    border-radius: 10px;
                }
                VoiceCardWidget:hover {
                    background-color: #172033;
                    border: 1px solid #334155;
                }
            """)


# ---------------------------------------------------------------------------
# MAIN AUDIO PRODUCTION STUDIO TAB
# ---------------------------------------------------------------------------

class AudioProductionTab(QWidget):
    """
    Giao diện Studio Sản Xuất Audio (Tab 4):
    Mô phỏng 100% bố cục và phong cách thiết kế Studio theo ảnh người dùng cung cấp.
    """

    # Tín hiệu chuyển giao sang Tab Sản Xuất Video
    transfer_to_video_requested = Signal(list)  # Danh sách dict hoặc item cho Video tab
    log_requested = Signal(str, str)            # level, message

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = TTSConfig()
        self.env_status = TTSEnvStatus()
        self.dict_manager = TTSDictionaryManager()
        self.items: List[TTSItem] = []
        self.voice_cards: List[VoiceCardWidget] = []

        # Quản lý phát âm thanh
        self.media_player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(1.0)
        self.is_slider_tracking = False

        # Workers
        self.queue_worker: Optional[TTSQueueWorker] = None
        self.preview_worker: Optional[TTSPreviewWorker] = None
        self.active_preview_voice: Optional[str] = None
        self.start_epoch = 0.0

        # Lưu trữ tệp âm thanh gần nhất
        self.current_audio_path: str = ""
        self.current_audio_duration: float = 0.0

        # Khởi tạo bảng hàng đợi ngầm (để giữ 100% tương thích test và batch)
        self.table_queue = QTableWidget(0, 8)
        self.table_queue.setHorizontalHeaderLabels([
            "Tập", "Khoảng chương", "Số từ / Ký tự", "Giọng / Model",
            "Đoạn hoàn tất", "Trạng thái", "Thời lượng MP3", "Tệp kết quả / Ghi chú"
        ])

        self.init_ui()
        self.setup_audio_events()

        # Nạp trước 25 giọng mặc định ngay lập tức để giao diện sẵn sàng
        self.populate_voice_cards(get_default_voices())

        # Kiểm tra môi trường ban đầu sau khi nạp UI
        QTimer.singleShot(100, self.check_environment)

    def init_ui(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #0b0e14;
                color: #f1f5f9;
                font-family: 'Segoe UI', 'Roboto', 'Arial', sans-serif;
            }
        """)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(10)

        # ---------------- BỘ TÁCH CHÍNH TRÁI / PHẢI ----------------
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #1e293b;
                width: 2px;
            }
        """)

        # ================= 1. CỘT TRÁI: VĂN BẢN ĐỌC =================
        left_panel = QFrame()
        left_panel.setStyleSheet("""
            QFrame {
                background-color: #111625;
                border: 1px solid #1e293b;
                border-radius: 10px;
            }
        """)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(14, 12, 14, 12)
        left_layout.setSpacing(8)

        # Thanh tiêu đề & nút công cụ
        header_bar = QHBoxLayout()
        lbl_title = QLabel("📄 VĂN BẢN ĐỌC")
        lbl_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #38bdf8; letter-spacing: 0.5px;")
        header_bar.addWidget(lbl_title)

        header_bar.addStretch()

        # Nút nạp tập truyện từ dự án
        self.btn_load_volume = QPushButton("📚 Nạp tập...")
        self.btn_load_volume.setToolTip("Nạp văn bản của một tập từ thư mục output_volumes")
        self.btn_load_volume.clicked.connect(self.choose_volume_to_load)
        self.style_header_button(self.btn_load_volume)
        header_bar.addWidget(self.btn_load_volume)

        # Nút Làm sạch
        self.btn_clean_text = QPushButton("🧹 Làm sạch")
        self.btn_clean_text.setToolTip("Lọc sạch khoảng trắng thừa, dấu ngoặc kép và quảng cáo web")
        self.btn_clean_text.clicked.connect(self.do_clean_text)
        self.style_header_button(self.btn_clean_text)
        header_bar.addWidget(self.btn_clean_text)

        # Nút Từ điển
        self.btn_dict = QPushButton("📖 Từ điển")
        self.btn_dict.setToolTip("Quản lý quy tắc phát âm tên riêng / từ viết tắt")
        self.btn_dict.clicked.connect(self.open_dictionary_dialog)
        self.style_header_button(self.btn_dict)
        header_bar.addWidget(self.btn_dict)

        # Nút Dán
        self.btn_paste = QPushButton("📋 Dán")
        self.btn_paste.clicked.connect(self.do_paste_text)
        self.style_header_button(self.btn_paste)
        header_bar.addWidget(self.btn_paste)

        # Nút Chép
        self.btn_copy = QPushButton("📑 Chép")
        self.btn_copy.clicked.connect(self.do_copy_text)
        self.style_header_button(self.btn_copy)
        header_bar.addWidget(self.btn_copy)

        # Nút Xóa
        self.btn_clear_text = QPushButton("🗑️ Xóa")
        self.btn_clear_text.clicked.connect(self.do_clear_text)
        self.style_header_button(self.btn_clear_text, is_danger=True)
        header_bar.addWidget(self.btn_clear_text)

        left_layout.addLayout(header_bar)

        # Trình soạn thảo văn bản
        self.txt_content = QTextEdit()
        self.txt_content.setPlainText(DEFAULT_STUDIO_TEXT)
        self.txt_content.setStyleSheet("""
            QTextEdit {
                background-color: #0c1017;
                color: #f1f5f9;
                border: 1px solid #1e293b;
                border-radius: 8px;
                padding: 12px;
                font-size: 13px;
                line-height: 1.6;
            }
            QTextEdit:focus {
                border: 1px solid #0284c7;
            }
        """)
        self.txt_content.textChanged.connect(self.update_text_statistics)
        left_layout.addWidget(self.txt_content, stretch=1)

        # Hàng Tag Cảm xúc
        tag_box = QHBoxLayout()
        tag_box.setSpacing(6)
        lbl_tag = QLabel("✨ Tag Cảm xúc:")
        lbl_tag.setStyleSheet("font-size: 12px; font-weight: bold; color: #fbbf24;")
        tag_box.addWidget(lbl_tag)

        self.btn_tag_laugh = QPushButton("😄 Cười [cười]")
        self.btn_tag_cough = QPushButton("📢 Hắng giọng [hắng giọng]")
        self.btn_tag_sigh = QPushButton("💨 Thở dài [thở dài]")
        self.btn_tag_pause = QPushButton("⏸️ Nghỉ [nghỉ 1s]")

        for btn, tag in [
            (self.btn_tag_laugh, " [cười] "),
            (self.btn_tag_cough, " [hắng giọng] "),
            (self.btn_tag_sigh, " [thở dài] "),
            (self.btn_tag_pause, " [nghỉ 1s] "),
        ]:
            self.style_tag_button(btn)
            btn.clicked.connect(lambda checked, t=tag: self.insert_tag(t))
            tag_box.addWidget(btn)

        tag_box.addStretch()
        left_layout.addLayout(tag_box)

        # Hàng Mẫu
        sample_box = QHBoxLayout()
        sample_box.setSpacing(6)
        lbl_sample = QLabel("🎭 Mẫu:")
        lbl_sample.setStyleSheet("font-size: 12px; font-weight: bold; color: #fbbf24;")
        sample_box.addWidget(lbl_sample)

        samples = [
            ("Giới thiệu", "Chào mừng các bạn đang theo dõi bộ truyện, chúc các bạn có những giây phút thư giãn tuyệt vời.\n"),
            ("Cảm xúc", "Thật không thể tin nổi! [thở dài] Mọi chuyện lại diễn ra theo cách này...\n"),
            ("Thuyết minh", "Kính mời quý thính giả cùng tiếp tục theo dõi diễn biến tiếp theo của câu chuyện.\n"),
            ("Kể chuyện", "Trời dần về khuya, không gian tĩnh lặng như tờ, chỉ còn lại tiếng gió rít từng hồi ngoài khe cửa...\n"),
            ("Quảng cáo", "Các bạn hãy nhấn Thích (Like) và Đăng ký (Subscribe) kênh để đón nghe tập mới nhất nhé!\n"),
        ]
        for name, text in samples:
            btn = QPushButton(name)
            self.style_sample_button(btn)
            btn.clicked.connect(lambda checked, t=text: self.insert_sample_text(t))
            sample_box.addWidget(btn)

        sample_box.addStretch()
        left_layout.addLayout(sample_box)

        # Thanh thống kê văn bản
        stat_bar = QHBoxLayout()
        self.lbl_stats = QLabel("0 ký tự  •  0 từ  •  0 câu")
        self.lbl_stats.setStyleSheet("color: #94a3b8; font-size: 12px;")
        stat_bar.addWidget(self.lbl_stats)

        stat_bar.addStretch()

        self.lbl_estimate = QLabel("Ước tính: ~0s audio")
        self.lbl_estimate.setStyleSheet("color: #38bdf8; font-size: 12px; font-weight: bold;")
        stat_bar.addWidget(self.lbl_estimate)

        left_layout.addLayout(stat_bar)

        splitter.addWidget(left_panel)

        # ================= 2. CỘT PHẢI: GIỌNG ĐỌC & TỐC ĐỘ =================
        right_panel = QFrame()
        right_panel.setFixedWidth(390)
        right_panel.setStyleSheet("""
            QFrame {
                background-color: #111625;
                border: 1px solid #1e293b;
                border-radius: 10px;
            }
        """)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(10)

        # Thanh tiêu đề Giọng đọc + Lọc giới tính
        voice_header = QHBoxLayout()
        self.lbl_voice_count = QLabel("🎙️ Giọng đọc (25)")
        self.lbl_voice_count.setStyleSheet("font-size: 14px; font-weight: bold; color: #ffffff;")
        voice_header.addWidget(self.lbl_voice_count)

        voice_header.addStretch()

        # Bộ lọc Tất cả / Nữ / Nam
        filter_box = QHBoxLayout()
        filter_box.setSpacing(2)

        self.btn_filter_all = QPushButton("Tất cả")
        self.btn_filter_female = QPushButton("Nữ")
        self.btn_filter_male = QPushButton("Nam")

        self.active_filter = "all"
        for f_btn, f_type in [
            (self.btn_filter_all, "all"),
            (self.btn_filter_female, "Nữ"),
            (self.btn_filter_male, "Nam"),
        ]:
            f_btn.setCheckable(True)
            f_btn.setFixedSize(50, 26)
            f_btn.clicked.connect(lambda checked, t=f_type: self.set_voice_filter(t))
            filter_box.addWidget(f_btn)

        self.btn_filter_all.setChecked(True)
        self.update_filter_button_styles()
        voice_header.addLayout(filter_box)

        right_layout.addLayout(voice_header)

        # Danh sách thẻ giọng đọc cuộn dọc
        self.scroll_voices = QScrollArea()
        self.scroll_voices.setWidgetResizable(True)
        self.scroll_voices.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                border: none;
                background: #0f141c;
                width: 6px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #334155;
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(2, 2, 2, 2)
        self.cards_layout.setSpacing(6)
        self.scroll_voices.setWidget(self.cards_container)
        right_layout.addWidget(self.scroll_voices, stretch=1)

        # Khung điều khiển Tốc độ đọc
        speed_box = QFrame()
        speed_box.setStyleSheet("""
            QFrame {
                background-color: #131926;
                border: 1px solid #1e293b;
                border-radius: 8px;
                padding: 6px;
            }
        """)
        speed_layout = QVBoxLayout(speed_box)
        speed_layout.setContentsMargins(8, 8, 8, 8)
        speed_layout.setSpacing(6)

        # Hàng tiêu đề & số đo tốc độ
        speed_row = QHBoxLayout()
        lbl_speed_icon = QLabel("🎚️ Tốc độ đọc")
        lbl_speed_icon.setStyleSheet("font-size: 12px; font-weight: bold; color: #38bdf8;")
        speed_row.addWidget(lbl_speed_icon)

        speed_row.addStretch()

        self.btn_speed_down = QPushButton("-")
        self.btn_speed_down.setFixedSize(24, 24)
        self.btn_speed_down.clicked.connect(self.speed_step_down)
        self.style_stepper_button(self.btn_speed_down)
        speed_row.addWidget(self.btn_speed_down)

        self.lbl_speed_val = QLabel("1.10")
        self.lbl_speed_val.setStyleSheet("font-size: 13px; font-weight: bold; color: #06d6a0; min-width: 38px; qproperty-alignment: AlignCenter;")
        speed_row.addWidget(self.lbl_speed_val)

        self.btn_speed_up = QPushButton("+")
        self.btn_speed_up.setFixedSize(24, 24)
        self.btn_speed_up.clicked.connect(self.speed_step_up)
        self.style_stepper_button(self.btn_speed_up)
        speed_row.addWidget(self.btn_speed_up)

        self.btn_speed_reset = QPushButton("Chuẩn")
        self.btn_speed_reset.setFixedHeight(24)
        self.btn_speed_reset.clicked.connect(self.speed_reset)
        self.style_stepper_button(self.btn_speed_reset)
        speed_row.addWidget(self.btn_speed_reset)

        speed_layout.addLayout(speed_row)

        # Thanh trượt tốc độ
        self.slider_speed = QSlider(Qt.Horizontal)
        self.slider_speed.setRange(75, 150)
        self.slider_speed.setValue(110)
        self.slider_speed.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #1e293b;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #06d6a0;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #06d6a0;
                width: 14px;
                height: 14px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 7px;
            }
        """)
        self.slider_speed.valueChanged.connect(self.on_speed_slider_changed)
        speed_layout.addWidget(self.slider_speed)

        # Nhãn biên giới hạn
        limit_row = QHBoxLayout()
        lbl_slow = QLabel("0.75x (Chậm)")
        lbl_slow.setStyleSheet("font-size: 10px; color: #64748b;")
        lbl_fast = QLabel("1.50x (Nhanh)")
        lbl_fast.setStyleSheet("font-size: 10px; color: #64748b;")
        limit_row.addWidget(lbl_slow)
        limit_row.addStretch()
        limit_row.addWidget(lbl_fast)
        speed_layout.addLayout(limit_row)

        right_layout.addWidget(speed_box)

        # Nút Cấu hình nâng cao
        self.btn_advanced_cfg = QPushButton("⚙ Cấu hình Engine TTS...")
        self.btn_advanced_cfg.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #94a3b8;
                border: 1px dashed #334155;
                padding: 6px;
                border-radius: 6px;
                font-size: 11px;
            }
            QPushButton:hover {
                color: #ffffff;
                border-color: #64748b;
            }
        """)
        self.btn_advanced_cfg.clicked.connect(self.open_settings_dialog)
        right_layout.addWidget(self.btn_advanced_cfg)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)

        root_layout.addWidget(splitter, stretch=1)

        # ================= 3. THANH ĐIỀU KHIỂN & PHÁT ÂM THANH DƯỚI CÙNG =================
        bottom_bar = QFrame()
        bottom_bar.setFixedHeight(72)
        bottom_bar.setStyleSheet("""
            QFrame {
                background-color: #0d121c;
                border: 1px solid #1e293b;
                border-radius: 10px;
            }
        """)
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(14, 8, 14, 8)
        bottom_layout.setSpacing(14)

        # 1. Nút Tạo giọng nói chính (Gradient Teal/Cyan)
        self.btn_generate = QPushButton("▶  Tạo giọng nói")
        self.btn_generate.setFixedHeight(46)
        self.btn_generate.setCursor(Qt.PointingHandCursor)
        self.btn_generate.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00b4d8, stop:1 #06d6a0);
                color: #0b0e14;
                font-size: 13px;
                font-weight: bold;
                padding: 0 18px;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0ea5e9, stop:1 #10b981);
            }
            QPushButton:pressed {
                background: #0096c7;
            }
            QPushButton:disabled {
                background: #334155;
                color: #64748b;
            }
        """)
        self.btn_generate.clicked.connect(self.start_studio_generation)
        bottom_layout.addWidget(self.btn_generate)

        # 2. Nút Bật/Tắt Phụ đề
        self.btn_subtitles = QPushButton("🎞️ Phụ đề")
        self.btn_subtitles.setCheckable(True)
        self.btn_subtitles.setChecked(False)
        self.btn_subtitles.setFixedHeight(42)
        self.btn_subtitles.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #94a3b8;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 0 12px;
                font-size: 12px;
            }
            QPushButton:checked {
                background-color: #0f2738;
                color: #06d6a0;
                border: 1px solid #06d6a0;
                font-weight: bold;
            }
        """)
        self.btn_subtitles.toggled.connect(self.on_subtitles_toggled)
        bottom_layout.addWidget(self.btn_subtitles)

        # 3. Nút mở Hàng đợi tập (Batch)
        self.btn_queue_view = QPushButton("📋 Hàng đợi")
        self.btn_queue_view.setFixedHeight(42)
        self.btn_queue_view.setToolTip("Xem danh sách các tập trong hàng đợi gộp")
        self.btn_queue_view.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #cbd5e1;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 0 12px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #334155;
            }
        """)
        self.btn_queue_view.clicked.connect(self.open_queue_dialog)
        bottom_layout.addWidget(self.btn_queue_view)

        # 4. Trạng thái & Trình phát âm thanh ở giữa
        player_center = QVBoxLayout()
        player_center.setSpacing(2)
        player_center.setContentsMargins(0, 0, 0, 0)

        # Dòng trạng thái (Đã tạo xong / Đang tạo)
        status_line = QHBoxLayout()
        self.lbl_status_badge = QLabel("⚪ Sẵn sàng tạo âm thanh")
        self.lbl_status_badge.setStyleSheet("font-size: 12px; font-weight: bold; color: #ffffff;")
        status_line.addWidget(self.lbl_status_badge)

        self.lbl_status_sub = QLabel("")
        self.lbl_status_sub.setStyleSheet("font-size: 11px; color: #06d6a0;")
        status_line.addWidget(self.lbl_status_sub)
        status_line.addStretch()
        player_center.addLayout(status_line)

        # Dòng thanh tua âm thanh (Seekbar)
        seek_line = QHBoxLayout()
        seek_line.setSpacing(8)

        self.lbl_cur_time = QLabel("00:00")
        self.lbl_cur_time.setStyleSheet("font-size: 11px; color: #94a3b8; min-width: 36px;")
        seek_line.addWidget(self.lbl_cur_time)

        self.slider_seek = QSlider(Qt.Horizontal)
        self.slider_seek.setRange(0, 1000)
        self.slider_seek.setValue(0)
        self.slider_seek.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #1e293b;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #00b4d8;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #00b4d8;
                width: 12px;
                height: 12px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 6px;
            }
        """)
        self.slider_seek.sliderPressed.connect(self.on_seek_pressed)
        self.slider_seek.sliderReleased.connect(self.on_seek_released)
        seek_line.addWidget(self.slider_seek, stretch=1)

        self.lbl_total_time = QLabel("--:--")
        self.lbl_total_time.setStyleSheet("font-size: 11px; color: #94a3b8; min-width: 36px;")
        seek_line.addWidget(self.lbl_total_time)

        player_center.addLayout(seek_line)
        bottom_layout.addLayout(player_center, stretch=1)

        # 5. Cụm nút Play / Pause & Xuất tệp
        self.btn_play_pause = QPushButton("▶")
        self.btn_play_pause.setFixedSize(36, 36)
        self.btn_play_pause.setCursor(Qt.PointingHandCursor)
        self.btn_play_pause.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #06d6a0;
                font-size: 15px;
                font-weight: bold;
                border-radius: 18px;
                border: 1px solid #334155;
            }
            QPushButton:hover {
                background-color: #06d6a0;
                color: #000000;
            }
        """)
        self.btn_play_pause.clicked.connect(self.toggle_playback)
        bottom_layout.addWidget(self.btn_play_pause)

        # Nút Xuất WAV
        self.btn_export_wav = QPushButton("⬇ WAV")
        self.btn_export_wav.setFixedHeight(36)
        self.style_export_button(self.btn_export_wav)
        self.btn_export_wav.clicked.connect(self.export_wav_file)
        bottom_layout.addWidget(self.btn_export_wav)

        # Nút Xuất MP3
        self.btn_export_mp3 = QPushButton("⬇ MP3")
        self.btn_export_mp3.setFixedHeight(36)
        self.style_export_button(self.btn_export_mp3)
        self.btn_export_mp3.clicked.connect(self.export_mp3_file)
        bottom_layout.addWidget(self.btn_export_mp3)

        # Nút Sang Video
        self.btn_to_video = QPushButton("🎬 Sang Video")
        self.btn_to_video.setFixedHeight(36)
        self.btn_to_video.setStyleSheet("""
            QPushButton {
                background-color: #7c3aed;
                color: #ffffff;
                font-size: 12px;
                font-weight: bold;
                border-radius: 6px;
                padding: 0 12px;
                border: none;
            }
            QPushButton:hover { background-color: #6d28d9; }
        """)
        self.btn_to_video.clicked.connect(self.transfer_to_video)
        bottom_layout.addWidget(self.btn_to_video)

        # Nút Âm lượng
        self.btn_volume = QPushButton("🔊")
        self.btn_volume.setFixedSize(32, 32)
        self.btn_volume.setStyleSheet("background: transparent; border: none; font-size: 16px; color: #94a3b8;")
        self.btn_volume.clicked.connect(self.toggle_mute)
        bottom_layout.addWidget(self.btn_volume)

        root_layout.addWidget(bottom_bar)

        # Cập nhật thông số ban đầu
        self.update_text_statistics()

    # ---------------------------------------------------------------------------
    # STYLING HELPERS
    # ---------------------------------------------------------------------------
    def style_header_button(self, btn: QPushButton, is_danger: bool = False):
        bg = "#1e293b"
        hover_bg = "#dc2626" if is_danger else "#334155"
        txt = "#f87171" if is_danger else "#cbd5e1"
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {txt};
                font-size: 11px;
                padding: 4px 10px;
                border-radius: 6px;
                border: 1px solid #334155;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
                color: #ffffff;
            }}
        """)

    def style_tag_button(self, btn: QPushButton):
        btn.setStyleSheet("""
            QPushButton {
                background-color: #131926;
                color: #cbd5e1;
                font-size: 11px;
                padding: 4px 8px;
                border-radius: 6px;
                border: 1px solid #252d43;
            }
            QPushButton:hover {
                background-color: #1e293b;
                color: #06d6a0;
                border-color: #06d6a0;
            }
        """)

    def style_sample_button(self, btn: QPushButton):
        btn.setStyleSheet("""
            QPushButton {
                background-color: #131926;
                color: #94a3b8;
                font-size: 11px;
                padding: 3px 8px;
                border-radius: 10px;
                border: 1px solid #1e293b;
            }
            QPushButton:hover {
                background-color: #1e293b;
                color: #ffffff;
                border-color: #38bdf8;
            }
        """)

    def style_stepper_button(self, btn: QPushButton):
        btn.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #f1f5f9;
                font-size: 11px;
                font-weight: bold;
                border-radius: 4px;
                border: 1px solid #334155;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #06d6a0;
            }
        """)

    def style_export_button(self, btn: QPushButton):
        btn.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #cbd5e1;
                font-size: 11px;
                font-weight: bold;
                border-radius: 6px;
                padding: 0 10px;
                border: 1px solid #334155;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #ffffff;
            }
        """)

    def update_filter_button_styles(self):
        for btn, f_type in [
            (self.btn_filter_all, "all"),
            (self.btn_filter_female, "Nữ"),
            (self.btn_filter_male, "Nam"),
        ]:
            if self.active_filter == f_type:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #0284c7;
                        color: #ffffff;
                        font-size: 11px;
                        font-weight: bold;
                        border-radius: 4px;
                        border: none;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #1e293b;
                        color: #94a3b8;
                        font-size: 11px;
                        border-radius: 4px;
                        border: 1px solid #334155;
                    }
                    QPushButton:hover {
                        color: #f1f5f9;
                    }
                """)

    # ---------------------------------------------------------------------------
    # AUDIO EVENTS & CONTROLS
    # ---------------------------------------------------------------------------
    def setup_audio_events(self):
        self.media_player.positionChanged.connect(self.on_player_position_changed)
        self.media_player.durationChanged.connect(self.on_player_duration_changed)
        self.media_player.playbackStateChanged.connect(self.on_playback_state_changed)

    def on_player_position_changed(self, pos_ms: int):
        if not self.is_slider_tracking:
            dur_ms = self.media_player.duration()
            if dur_ms > 0:
                val = int((pos_ms / dur_ms) * 1000)
                self.slider_seek.setValue(val)
            self.lbl_cur_time.setText(self.format_time_ms(pos_ms))

    def on_player_duration_changed(self, dur_ms: int):
        self.lbl_total_time.setText(self.format_time_ms(dur_ms))

    def on_playback_state_changed(self, state):
        if state == QMediaPlayer.PlayingState:
            self.btn_play_pause.setText("⏸")
        else:
            self.btn_play_pause.setText("▶")
            if self.active_preview_voice:
                for card in self.voice_cards:
                    card.set_playing(False)
                self.active_preview_voice = None

    def toggle_playback(self):
        if self.media_player.playbackState() == QMediaPlayer.PlayingState:
            self.media_player.pause()
        else:
            if self.current_audio_path and os.path.isfile(self.current_audio_path):
                self.media_player.play()
            elif self.items and self.items[-1].output_mp3_path:
                self.load_audio_file(self.items[-1].output_mp3_path)
                self.media_player.play()
            else:
                # Nghe thử câu ngắn mẫu
                self.start_preview_for_voice(self.config.voice_id)

    def on_seek_pressed(self):
        self.is_slider_tracking = True

    def on_seek_released(self):
        self.is_slider_tracking = False
        dur_ms = self.media_player.duration()
        if dur_ms > 0:
            target_ms = int((self.slider_seek.value() / 1000.0) * dur_ms)
            self.media_player.setPosition(target_ms)

    def toggle_mute(self):
        cur = self.audio_output.volume()
        if cur > 0:
            self.audio_output.setVolume(0.0)
            self.btn_volume.setText("🔇")
        else:
            self.audio_output.setVolume(1.0)
            self.btn_volume.setText("🔊")

    def load_audio_file(self, file_path: str):
        if os.path.isfile(file_path):
            self.current_audio_path = os.path.abspath(file_path)
            self.media_player.setSource(QUrl.fromLocalFile(self.current_audio_path))
            try:
                info = probe_media(file_path)
                self.current_audio_duration = info.get("duration", 0.0)
                self.lbl_total_time.setText(self.format_time_sec(self.current_audio_duration))
            except Exception:
                pass

    def format_time_ms(self, ms: int) -> str:
        s = ms // 1000
        return self.format_time_sec(s)

    def format_time_sec(self, s: float) -> str:
        mins = int(s // 60)
        secs = int(s % 60)
        return f"{mins:02d}:{secs:02d}"

    # ---------------------------------------------------------------------------
    # VOICE LIST & SELECTION
    # ---------------------------------------------------------------------------
    def check_environment(self):
        py_bin = self.config.python_path
        self.env_status = TTSAdapter.check_environment(py_bin)

        # Đảm bảo luôn có 25 giọng hiển thị
        voices = self.env_status.voices or get_default_voices()
        self.populate_voice_cards(voices)

        if self.env_status.available:
            self.log("INFO", f"Môi trường VieNeu-TTS sẵn sàng ({self.env_status.device_name}).")
        else:
            self.log("WARNING", "Chưa kết nối môi trường Python TTS chuyên dụng; chế độ kiểm thử Studio đang hoạt động.")

    def populate_voice_cards(self, voices: List[TTSVoice]):
        # Xóa các card cũ
        while self.cards_layout.count() > 0:
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.voice_cards.clear()

        # Tạo danh sách mới
        selected_found = False
        for v in voices:
            is_sel = (v.voice_id == self.config.voice_id)
            if is_sel:
                selected_found = True
            card = VoiceCardWidget(v, is_selected=is_sel, parent=self.cards_container)
            card.clicked.connect(self.on_voice_card_selected)
            card.preview_clicked.connect(self.on_voice_preview_clicked)
            self.voice_cards.append(card)
            self.cards_layout.addWidget(card)

        # Mặc định chọn thẻ đầu tiên nếu chưa có
        if not selected_found and self.voice_cards:
            self.voice_cards[0].set_selected(True)
            self.config.voice_id = self.voice_cards[0].voice.voice_id

        self.cards_layout.addStretch()
        self.apply_voice_filter()

    def set_voice_filter(self, filter_type: str):
        self.active_filter = filter_type
        self.update_filter_button_styles()
        self.apply_voice_filter()

    def apply_voice_filter(self):
        visible_count = 0
        for card in self.voice_cards:
            if self.active_filter == "all":
                card.setVisible(True)
                visible_count += 1
            elif self.active_filter == "Nam":
                is_match = (card.voice.gender == "Nam")
                card.setVisible(is_match)
                if is_match:
                    visible_count += 1
            elif self.active_filter == "Nữ":
                is_match = (card.voice.gender == "Nữ")
                card.setVisible(is_match)
                if is_match:
                    visible_count += 1

        self.lbl_voice_count.setText(f"🎙️ Giọng đọc ({visible_count})")

    def on_voice_card_selected(self, selected_card: VoiceCardWidget):
        for card in self.voice_cards:
            card.set_selected(card == selected_card)
        self.config.voice_id = selected_card.voice.voice_id
        self.lbl_status_badge.setText(f"⚪ Đã chọn giọng: {selected_card.voice.display_name}")

    def on_voice_preview_clicked(self, voice: TTSVoice):
        if self.active_preview_voice == voice.voice_id and self.media_player.playbackState() == QMediaPlayer.PlayingState:
            self.media_player.stop()
            self.active_preview_voice = None
            for card in self.voice_cards:
                card.set_playing(False)
            return

        self.start_preview_for_voice(voice.voice_id)

    def start_preview_for_voice(self, voice_id: str):
        self.active_preview_voice = voice_id
        for card in self.voice_cards:
            card.set_playing(card.voice.voice_id == voice_id)

        sample_text = f"Xin chào, đây là giọng đọc thử nghiệm của {voice_id} trên hệ thống Truyenaudio."
        out_wav = os.path.abspath(os.path.join("output_volumes", ".tts_cache", "previews", f"{voice_id}.wav"))
        os.makedirs(os.path.dirname(out_wav), exist_ok=True)

        self.lbl_status_badge.setText(f"Đang tạo mẫu nghe thử: {voice_id}...")
        self.preview_worker = TTSPreviewWorker(
            python_path=self.config.python_path,
            text=sample_text,
            voice_id=voice_id,
            out_wav=out_wav,
            model_name=self.config.model_name,
            backend=self.config.backend,
            mock=not self.env_status.available,
            parent=self,
        )
        self.preview_worker.preview_finished.connect(self.on_preview_finished)
        self.preview_worker.start()

    def on_preview_finished(self, success: bool, out_res: str, dur: float):
        if success and os.path.isfile(out_res):
            self.load_audio_file(out_res)
            self.media_player.play()
            self.lbl_status_badge.setText(f"Đang nghe thử: {self.active_preview_voice} ({dur:.1f}s)")
        else:
            self.lbl_status_badge.setText("Lỗi tạo mẫu nghe thử")
            for card in self.voice_cards:
                card.set_playing(False)
            self.active_preview_voice = None
            if not self.env_status.available:
                QMessageBox.warning(
                    self, "Chưa cài đặt Động cơ TTS",
                    "Chưa cài đặt thư viện tạo giọng đọc (edge-tts hoặc vieneu).\n"
                    "Hãy mở terminal và chạy: pip install edge-tts"
                )
            else:
                QMessageBox.warning(
                    self, "Lỗi tạo nghe thử",
                    f"Không thể tạo âm thanh nghe thử:\n{out_res}"
                )

    # ---------------------------------------------------------------------------
    # SPEED ADJUSTMENT
    # ---------------------------------------------------------------------------
    def on_speed_slider_changed(self, val: int):
        spd = val / 100.0
        self.config.speed = spd
        self.lbl_speed_val.setText(f"{spd:.2f}")
        self.update_text_statistics()

    def speed_step_down(self):
        val = max(75, self.slider_speed.value() - 5)
        self.slider_speed.setValue(val)

    def speed_step_up(self):
        val = min(150, self.slider_speed.value() + 5)
        self.slider_speed.setValue(val)

    def speed_reset(self):
        self.slider_speed.setValue(100)

    # ---------------------------------------------------------------------------
    # TEXT EDITING & STATISTICS
    # ---------------------------------------------------------------------------
    def update_text_statistics(self):
        text = self.txt_content.toPlainText()
        chars = len(text)
        words = len(text.split())
        sentences = len(re.findall(r"[.!?]+(?:\s+|$)", text)) or (1 if text.strip() else 0)

        self.lbl_stats.setText(f"{chars:,} ký tự  •  {words:,} từ  •  {sentences:,} câu")

        # Ước tính thời lượng âm thanh dựa trên tốc độ và tỷ lệ đọc trung bình tiếng Việt (~11.25 ký tự / giây)
        spd = getattr(self.config, "speed", 1.0) or 1.0
        est_sec = int(chars / (11.25 * spd)) if chars > 0 else 0
        self.lbl_estimate.setText(f"Ước tính: ~{est_sec}s audio")

    def insert_tag(self, tag: str):
        cursor = self.txt_content.textCursor()
        cursor.insertText(tag)
        self.txt_content.setTextCursor(cursor)
        self.txt_content.setFocus()

    def insert_sample_text(self, sample_text: str):
        cursor = self.txt_content.textCursor()
        cursor.insertText(sample_text)
        self.txt_content.setTextCursor(cursor)
        self.txt_content.setFocus()

    def do_clean_text(self):
        orig = self.txt_content.toPlainText()
        cleaned = clean_reading_text(orig, apply_dict=True, dict_manager=self.dict_manager)
        self.txt_content.setPlainText(cleaned)
        self.log("INFO", "Đã làm sạch văn bản và áp dụng từ điển phát âm.")

    def do_paste_text(self):
        self.txt_content.paste()

    def do_copy_text(self):
        self.txt_content.selectAll()
        self.txt_content.copy()

    def do_clear_text(self):
        if len(self.txt_content.toPlainText().strip()) > 100:
            ans = QMessageBox.question(
                self, "Xóa văn bản", "Bạn có chắc chắn muốn xóa toàn bộ văn bản đang đọc?",
                QMessageBox.Yes | QMessageBox.No
            )
            if ans != QMessageBox.Yes:
                return
        self.txt_content.clear()

    def open_dictionary_dialog(self):
        dlg = TTSDictionaryDialog(self.dict_manager, self)
        dlg.exec()

    def open_settings_dialog(self):
        dlg = TTSSettingsDialog(self.config, self.env_status, self)
        if dlg.exec() == QDialog.Accepted:
            self.check_environment()

    def on_subtitles_toggled(self, checked: bool):
        self.config.generate_subtitles = checked

    # ---------------------------------------------------------------------------
    # TẢI TẬP TRUYỆN TỪ DỰ ÁN
    # ---------------------------------------------------------------------------
    def choose_volume_to_load(self):
        base_dir = "output_volumes"
        if not os.path.isdir(base_dir):
            QMessageBox.information(self, "Chưa có tập", "Chưa tìm thấy thư mục 'output_volumes'. Hãy gộp tập trước.")
            return

        vol_files = []
        for root, _, files in os.walk(base_dir):
            if ".tts_cache" in root:
                continue
            for f in sorted(files):
                if f.endswith("_EDITED.txt") or (f.endswith(".txt") and not any(f.endswith(sfx) for sfx in ("_RAW.txt", "_REPORT.md", "_CHANGELOG.json"))):
                    vol_files.append(os.path.join(root, f))

        if not vol_files:
            # Cho phép chọn tệp TXT bất kỳ
            f, _ = QFileDialog.getOpenFileName(self, "Chọn tệp TXT tập truyện", "", "Text Files (*.txt);;All Files (*)")
            if f:
                self.load_txt_file(f)
            return

        menu = QMenu(self)
        for vf in vol_files[:25]:
            fname = os.path.basename(vf)
            action = menu.addAction(fname)
            action.triggered.connect(lambda checked, p=vf: self.load_txt_file(p))

        menu.addSeparator()
        act_other = menu.addAction("Chọn tệp khác...")
        act_other.triggered.connect(lambda: self.browse_and_load_txt())
        menu.exec(self.btn_load_volume.mapToGlobal(self.btn_load_volume.rect().bottomLeft()))

    def browse_and_load_txt(self):
        f, _ = QFileDialog.getOpenFileName(self, "Chọn tệp TXT", "", "Text Files (*.txt);;All Files (*)")
        if f:
            self.load_txt_file(f)

    def load_txt_file(self, file_path: str):
        try:
            with open(file_path, "r", encoding="utf-8") as fp:
                text = fp.read()
            self.txt_content.setPlainText(text)
            self._add_txt_file_to_queue(file_path)
            self.lbl_status_badge.setText(f"⚪ Đã nạp: {os.path.basename(file_path)}")
            self.log("INFO", f"Đã nạp văn bản từ: {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi đọc tệp", f"Không thể đọc tệp văn bản: {e}")

    # ---------------------------------------------------------------------------
    # TỔNG HỢP ÂM THANH (TẠO GIỌNG NÓI)
    # ---------------------------------------------------------------------------
    def start_studio_generation(self):
        text = self.txt_content.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Thiếu văn bản", "Vui lòng nhập hoặc dán nội dung văn bản muốn tạo giọng đọc.")
            return

        # Kiểm tra FFmpeg
        ff_bin, _ = find_ffmpeg()
        if not ff_bin:
            QMessageBox.critical(self, "Thiếu FFmpeg", "Không tìm thấy FFmpeg trên hệ thống để xuất âm thanh.")
            return

        # Nếu worker đang chạy, nút này đóng vai trò hủy
        if self.queue_worker and self.queue_worker.isRunning():
            ans = QMessageBox.question(self, "Xác nhận dừng", "Bạn có chắc chắn muốn hủy quá trình tạo giọng nói?", QMessageBox.Yes | QMessageBox.No)
            if ans == QMessageBox.Yes:
                self.queue_worker.request_cancel()
                self.btn_generate.setText("▶  Tạo giọng nói")
            return

        # Tách tiêu đề dòng đầu tiên để đặt metadata nếu có
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        first_line = lines[0] if lines else "Tập Truyện"
        meta = parse_filename_metadata(first_line)

        chunks = TextChunker.chunk_text(text)
        item_id = f"item_{int(time.time() * 1000)}"
        item = TTSItem(
            item_id=item_id,
            story_title=meta.get("story_title") or first_line[:40],
            author=meta.get("author") or "",
            volume_num=meta.get("volume_num", 1),
            start_chap=meta.get("start_chapter", 1),
            end_chap=meta.get("end_chapter", 1),
            source="studio",
            raw_text=text,
            word_count=len(text.split()),
            char_count=len(text),
            chunks=chunks,
            chunks_total=len(chunks),
            chunks_done=0,
            status="waiting",
        )

        self.items.append(item)
        self.refresh_table()

        # Cập nhật giao diện sang trạng thái đang chạy
        self.btn_generate.setText("⏹️  Hủy tạo")
        self.btn_generate.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                color: #ffffff;
                font-size: 13px;
                font-weight: bold;
                padding: 0 18px;
                border-radius: 8px;
                border: none;
            }
        """)
        self.lbl_status_badge.setText(f"🔵 Đang tạo âm thanh ({self.config.voice_id})...")
        self.lbl_status_badge.setStyleSheet("color: #38bdf8; font-weight: bold;")
        self.start_epoch = time.time()

        # Khởi chạy worker
        self.queue_worker = TTSQueueWorker(
            items=[item],
            config=self.config,
            mock=not self.env_status.available,
            parent=self,
        )
        self.queue_worker.item_status_changed.connect(self._on_studio_item_status_changed)
        self.queue_worker.item_progress.connect(self._on_studio_item_progress)
        self.queue_worker.item_finished.connect(self._on_studio_item_finished)
        self.queue_worker.queue_finished.connect(self._on_studio_queue_finished)
        self.queue_worker.log_message.connect(self.log)
        self.queue_worker.start()

    def _on_studio_item_status_changed(self, item_id: str, status: str, error_msg: str):
        if status == "error":
            self.lbl_status_badge.setText("❌ Lỗi tạo âm thanh")
            self.lbl_status_badge.setStyleSheet("color: #f87171; font-weight: bold;")
            self.lbl_status_sub.setText(error_msg[:120] if error_msg else "Đã xảy ra lỗi.")
        elif status == "synthesizing":
            self.lbl_status_badge.setText(f"🔵 Đang tạo âm thanh ({self.config.voice_id})...")
            self.lbl_status_badge.setStyleSheet("color: #38bdf8; font-weight: bold;")
        elif status == "assembling":
            self.lbl_status_badge.setText("🔄 Đang ghép nối âm thanh & xuất MP3...")
            self.lbl_status_badge.setStyleSheet("color: #a78bfa; font-weight: bold;")

    def _on_studio_item_progress(self, item_id: str, done: int, total: int, speed: float, eta_str: str):
        pct = int((done / total) * 100) if total > 0 else 0
        spd_str = f"{speed:.1f}" if speed > 0 else "--"
        self.lbl_status_badge.setText(f"🔵 Đang tạo: {pct}% ({done}/{total} đoạn)")
        self.lbl_status_sub.setText(f"⚡ Tốc độ: {spd_str} ký tự/s | Còn lại: {eta_str}")
        self.refresh_table()

    def _on_studio_item_finished(self, item_id: str, mp3_path: str, duration: float):
        self.current_audio_path = mp3_path
        self.current_audio_duration = duration
        self.load_audio_file(mp3_path)
        self.refresh_table()

    def _on_studio_queue_finished(self, completed: int, skipped: int, errors: int):
        self.btn_generate.setText("▶  Tạo giọng nói")
        self.btn_generate.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00b4d8, stop:1 #06d6a0);
                color: #0b0e14;
                font-size: 13px;
                font-weight: bold;
                padding: 0 18px;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0ea5e9, stop:1 #10b981);
            }
        """)

        elapsed = time.time() - self.start_epoch
        if completed > 0 and self.current_audio_path:
            self.lbl_status_badge.setText(f"🟢 Đã Tạo Xong ({self.config.voice_id})")
            self.lbl_status_badge.setStyleSheet("color: #06d6a0; font-weight: bold;")
            self.lbl_status_sub.setText(f"⚡ Tạo xong: {elapsed:.1f}s")
            self.log("INFO", f"Xuất bản MP3 thành công: {self.current_audio_path}")
            # Tự động phát âm thanh
            self.media_player.play()
        else:
            if not self.lbl_status_badge.text().startswith("❌"):
                self.lbl_status_badge.setText("⚠️ Chưa hoàn tất hoặc bị hủy")
                self.lbl_status_badge.setStyleSheet("color: #f87171; font-weight: bold;")

    # ---------------------------------------------------------------------------
    # XUẤT TỆP & CHUYỂN TIẾP SANG VIDEO
    # ---------------------------------------------------------------------------
    def export_wav_file(self):
        if not self.current_audio_path or not os.path.isfile(self.current_audio_path):
            QMessageBox.information(self, "Chưa có âm thanh", "Vui lòng tạo giọng nói trước khi xuất tệp WAV.")
            return

        dest_wav, _ = QFileDialog.getSaveFileName(self, "Lưu tệp âm thanh WAV", "audio.wav", "WAV Audio (*.wav)")
        if dest_wav:
            ff_bin, _ = find_ffmpeg()
            subprocess.run([ff_bin, "-y", "-i", self.current_audio_path, dest_wav], check=False, **get_subprocess_hidden_kwargs())
            QMessageBox.information(self, "Thành công", f"Đã lưu tệp WAV tại:\n{dest_wav}")

    def export_mp3_file(self):
        if not self.current_audio_path or not os.path.isfile(self.current_audio_path):
            QMessageBox.information(self, "Chưa có âm thanh", "Vui lòng tạo giọng nói trước khi xuất tệp MP3.")
            return

        dest_mp3, _ = QFileDialog.getSaveFileName(self, "Lưu tệp âm thanh MP3", os.path.basename(self.current_audio_path), "MP3 Audio (*.mp3)")
        if dest_mp3:
            shutil.copy2(self.current_audio_path, dest_mp3)
            QMessageBox.information(self, "Thành công", f"Đã lưu tệp MP3 tại:\n{dest_mp3}")

    def transfer_to_video(self):
        """
        Chuyển trực tiếp các tập MP3 đã hoàn thành sang Tab Sản Xuất Video kèm metadata chính xác.
        """
        ready_items = [it for it in self.items if it.status == "completed" and os.path.isfile(it.output_mp3_path)]
        if not ready_items and self.current_audio_path and os.path.isfile(self.current_audio_path):
            # Tạo một item nhanh từ audio studio hiện tại
            dummy_item = {
                "audio_path": self.current_audio_path,
                "story_title": "Truyen Audio",
                "author": "",
                "volume_num": 1,
                "start_chapter": 1,
                "end_chapter": 4,
                "duration": self.current_audio_duration or 100.0,
            }
            self.transfer_to_video_requested.emit([dummy_item])
            self.log("INFO", "Đã chuyển âm thanh Studio hiện tại sang Tab Sản Xuất Video.")
            return

        if not ready_items:
            QMessageBox.information(self, "Chưa có tập hoàn thành", "Chưa có tệp MP3 nào hoàn thành để chuyển sang làm video.")
            return

        transfer_data = []
        for it in ready_items:
            transfer_data.append({
                "audio_path": it.output_mp3_path,
                "story_title": it.story_title,
                "author": it.author,
                "volume_num": it.volume_num,
                "start_chapter": it.start_chap,
                "end_chapter": it.end_chap,
                "duration": it.duration_sec,
            })

        self.transfer_to_video_requested.emit(transfer_data)
        self.log("INFO", f"Đã chuyển {len(transfer_data)} tập MP3 sang Tab Sản Xuất Video.")

    # ---------------------------------------------------------------------------
    # TƯƠNG THÍCH HÀNG ĐỢI (BATCH COMPATIBILITY)
    # ---------------------------------------------------------------------------
    def open_queue_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("📋 Hàng đợi sản xuất tập truyện (Batch)")
        dlg.resize(900, 520)
        dlg_layout = QVBoxLayout(dlg)

        # Đưa bảng table_queue vào dialog
        dlg_layout.addWidget(self.table_queue)

        btn_bar = QHBoxLayout()
        btn_add = QPushButton("➕ Thêm tập từ dự án")
        btn_add.clicked.connect(self.add_from_project_volumes)
        btn_start_all = QPushButton("⏩ Tạo tất cả hàng đợi")
        btn_start_all.setStyleSheet("background-color: #2e7d32; font-weight: bold;")
        btn_start_all.clicked.connect(self.start_all)
        btn_cls = QPushButton("Đóng")
        btn_cls.clicked.connect(dlg.accept)

        btn_bar.addWidget(btn_add)
        btn_bar.addWidget(btn_start_all)
        btn_bar.addStretch()
        btn_bar.addWidget(btn_cls)
        dlg_layout.addLayout(btn_bar)

        dlg.exec()

    def add_from_project_volumes(self):
        base_dir = "output_volumes"
        if not os.path.isdir(base_dir):
            return
        added_count = 0
        for root, _, files in os.walk(base_dir):
            if ".tts_cache" in root:
                continue
            for f in sorted(files):
                if f.endswith("_EDITED.txt") or (f.endswith(".txt") and not any(f.endswith(sfx) for sfx in ("_RAW.txt", "_REPORT.md", "_CHANGELOG.json"))):
                    full_p = os.path.join(root, f)
                    if self._add_txt_file_to_queue(full_p):
                        added_count += 1
        self.refresh_table()

    def _add_txt_file_to_queue(self, file_path: str) -> bool:
        norm_p = os.path.abspath(file_path)
        if any(os.path.abspath(it.text_source_path) == norm_p for it in self.items):
            return False
        try:
            with open(norm_p, "r", encoding="utf-8") as fp:
                raw_text = fp.read()
        except Exception:
            return False

        if not raw_text.strip():
            return False

        fname = os.path.basename(norm_p)
        meta = parse_filename_metadata(fname)
        chunks = TextChunker.chunk_text(raw_text)

        item_id = f"item_{int(time.time() * 1000)}_{len(self.items) + 1}"
        item = TTSItem(
            item_id=item_id,
            story_title=meta.get("story_title") or "Truyen",
            author=meta.get("author") or "",
            volume_num=meta.get("volume_num", 1),
            start_chap=meta.get("start_chapter", 1),
            end_chap=meta.get("end_chapter", 1),
            source="general",
            raw_text=raw_text,
            text_source_path=norm_p,
            word_count=len(raw_text.split()),
            char_count=len(raw_text),
            chunks=chunks,
            chunks_total=len(chunks),
            chunks_done=0,
            status="waiting",
        )
        self.items.append(item)
        self.refresh_table()
        return True

    def start_all(self):
        if not self.items:
            return
        self.start_studio_generation()

    def refresh_table(self):
        self.table_queue.setRowCount(len(self.items))
        for i, item in enumerate(self.items):
            self.table_queue.setItem(i, 0, QTableWidgetItem(f"Tập {item.volume_num:03d}"))
            self.table_queue.setItem(i, 1, QTableWidgetItem(f"{item.start_chap} - {item.end_chap}"))
            self.table_queue.setItem(i, 2, QTableWidgetItem(f"{item.word_count:,} từ ({item.char_count:,} ký tự)"))
            self.table_queue.setItem(i, 3, QTableWidgetItem(f"{self.config.voice_id} ({self.config.model_name})"))
            self.table_queue.setItem(i, 4, QTableWidgetItem(f"{item.chunks_done} / {item.chunks_total}"))

            st_item = QTableWidgetItem(item.status)
            if item.status == "completed":
                st_item.setText("Đã hoàn tất")
                st_item.setForeground(QColor("#2e7d32"))
            elif item.status == "synthesizing":
                st_item.setText("Đang đọc...")
                st_item.setForeground(QColor("#1565c0"))
            self.table_queue.setItem(i, 5, st_item)

            dur_str = "--:--"
            if item.duration_sec > 0:
                mins = int(item.duration_sec // 60)
                secs = int(item.duration_sec % 60)
                dur_str = f"{mins:02d}:{secs:02d}"
            self.table_queue.setItem(i, 6, QTableWidgetItem(dur_str))
            self.table_queue.setItem(i, 7, QTableWidgetItem(os.path.basename(item.output_mp3_path) if item.output_mp3_path else ""))

    def log(self, level: str, msg: str):
        self.log_requested.emit(level, msg)
