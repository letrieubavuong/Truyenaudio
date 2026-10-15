"""
Custom widgets for Chapter Status Table, Diff Review, and Real-time Log.
Supports keyboard and mouse review interactions, instant preview rebuilding,
and persistent decision synchronization.
"""
from typing import List, Dict, Any, Optional, Tuple
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QTextEdit, QLabel, QPushButton, QSplitter
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QTextCursor
from core.models import Chapter, Volume, SpellIssue
from core.spellchecker import VietnameseSpellChecker
from core.merger import VolumeMerger


class ChapterTableWidget(QTableWidget):
    """Bảng hiển thị trạng thái từng chương với màu sắc trực quan."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(7)
        self.setHorizontalHeaderLabels([
            "STT", "Số chương", "Tiêu đề chương", "Trạng thái", "Số đoạn", "Mã băm SHA-256", "Cảnh báo"
        ])
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.horizontalHeader().setStretchLastSection(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setAlternatingRowColors(True)

    def update_chapters(self, chapters: List[Chapter]):
        self.setRowCount(len(chapters))
        for row, ch in enumerate(chapters):
            self.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            self.setItem(row, 1, QTableWidgetItem(f"Chương {ch.chapter_num}" if ch.chapter_num is not None else "?"))
            self.setItem(row, 2, QTableWidgetItem(ch.chapter_title))

            status_item = QTableWidgetItem()
            if ch.status == "verified":
                status_item.setText("Đã xác thực")
                status_item.setForeground(QColor("#2e7d32"))
            elif ch.status == "downloaded":
                status_item.setText("Đã tải")
                status_item.setForeground(QColor("#1565c0"))
            elif ch.status == "failed":
                status_item.setText("Lỗi tải")
                status_item.setForeground(QColor("#c62828"))
            elif ch.status == "missing":
                status_item.setText("Thiếu")
                status_item.setForeground(QColor("#e65100"))
            else:
                status_item.setText(ch.status)

            self.setItem(row, 3, status_item)
            self.setItem(row, 4, QTableWidgetItem(str(len(ch.paragraphs))))
            self.setItem(row, 5, QTableWidgetItem(ch.content_hash[:12] + "..." if ch.content_hash else ""))

            warn_text = " | ".join(ch.warnings) if ch.warnings else "Bình thường"
            warn_item = QTableWidgetItem(warn_text)
            if ch.warnings:
                warn_item.setForeground(QColor("#e65100"))
            else:
                warn_item.setForeground(QColor("#757575"))
            self.setItem(row, 6, warn_item)


class DiffReviewWidget(QWidget):
    """
    Màn hình so sánh và duyệt lỗi trực quan:
    - Bên trái: Văn bản bản gốc (bất biến)
    - Bên phải: Văn bản bản sửa (cập nhật tức thì theo quyết định duyệt)
    - Bên dưới: Bảng duyệt các thay đổi (chuột và bàn phím đồng bộ)
    """
    decisions_changed = Signal(object)  # List[SpellIssue]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.issues: List[SpellIssue] = []
        self.volumes: List[Volume] = []
        self.merger: Optional[VolumeMerger] = None
        self.original_paragraphs_map: Dict[int, List[str]] = {}
        self._is_updating_table = False

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)

        toolbar_layout = QHBoxLayout()
        self.lbl_summary = QLabel("<b>Danh sách thay đổi cần duyệt (0 mục)</b>")
        toolbar_layout.addWidget(self.lbl_summary)
        toolbar_layout.addStretch()

        self.btn_select_all = QPushButton("✔ Chấp nhận tất cả")
        self.btn_reject_all = QPushButton("✖ Từ chối tất cả")
        self.btn_select_all.clicked.connect(self.select_all)
        self.btn_reject_all.clicked.connect(self.reject_all)

        toolbar_layout.addWidget(self.btn_select_all)
        toolbar_layout.addWidget(self.btn_reject_all)
        main_layout.addLayout(toolbar_layout)

        v_splitter = QSplitter(Qt.Vertical)

        diff_container = QWidget()
        diff_layout = QHBoxLayout(diff_container)
        diff_layout.setContentsMargins(0, 0, 0, 0)

        left_box = QVBoxLayout()
        left_box.addWidget(QLabel("<b>BẢN GỐC (BẤT BIẾN):</b>"))
        self.txt_original = QTextEdit()
        self.txt_original.setReadOnly(True)
        self.txt_original.setFont(QFont("Segoe UI", 10))
        left_box.addWidget(self.txt_original)
        diff_layout.addLayout(left_box)

        right_box = QVBoxLayout()
        right_box.addWidget(QLabel("<b>BẢN ĐÃ SỬA (THEO QUYẾT ĐỊNH DUYỆT):</b>"))
        self.txt_edited = QTextEdit()
        self.txt_edited.setReadOnly(True)
        self.txt_edited.setFont(QFont("Segoe UI", 10))
        right_box.addWidget(self.txt_edited)
        diff_layout.addLayout(right_box)

        v_splitter.addWidget(diff_container)

        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)

        self.table_issues = QTableWidget()
        self.table_issues.setColumnCount(9)
        self.table_issues.setHorizontalHeaderLabels([
            "Duyệt", "STT", "Chương", "Đoạn", "Nội dung gốc", "Nội dung sửa", "Nhóm lỗi", "Lý do", "Nguồn"
        ])
        self.table_issues.horizontalHeader().setStretchLastSection(True)
        self.table_issues.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_issues.itemChanged.connect(self.on_table_item_changed)
        self.table_issues.cellClicked.connect(self.on_table_cell_clicked)

        table_layout.addWidget(self.table_issues)
        v_splitter.addWidget(table_container)

        v_splitter.setSizes([350, 250])
        main_layout.addWidget(v_splitter)

    def load_data(
        self,
        issues: List[SpellIssue],
        volumes: List[Volume],
        merger: VolumeMerger,
        original_paragraphs_map: Dict[int, List[str]],
    ):
        """Nạp dữ liệu vào màn hình duyệt và hiển thị bản xem trước."""
        self.issues = issues
        self.volumes = volumes
        self.merger = merger
        self.original_paragraphs_map = original_paragraphs_map

        # Hiển thị văn bản bản gốc
        raw_parts = [self.merger.render_volume_text(v, use_edited=False) for v in self.volumes]
        self.txt_original.setPlainText("\n\n".join(raw_parts))

        # Điền bảng thay đổi
        self._is_updating_table = True
        self.table_issues.setRowCount(len(issues))

        for row, iss in enumerate(issues):
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk_item.setCheckState(Qt.Checked if iss.status == "applied" else Qt.Unchecked)
            self.table_issues.setItem(row, 0, chk_item)

            self.table_issues.setItem(row, 1, QTableWidgetItem(str(row + 1)))
            self.table_issues.setItem(row, 2, QTableWidgetItem(f"Chương {iss.chapter_num}" if iss.chapter_num is not None else "?"))
            self.table_issues.setItem(row, 3, QTableWidgetItem(f"Đoạn {iss.paragraph_idx}"))
            self.table_issues.setItem(row, 4, QTableWidgetItem(repr(iss.original)[1:-1]))
            self.table_issues.setItem(row, 5, QTableWidgetItem(repr(iss.replacement)[1:-1]))
            self.table_issues.setItem(row, 6, QTableWidgetItem(iss.category))
            self.table_issues.setItem(row, 7, QTableWidgetItem(iss.reason))
            self.table_issues.setItem(row, 8, QTableWidgetItem(iss.source))

        self._is_updating_table = False

        # Tái dựng bản xem trước đã sửa dựa trên các issue đang được duyệt
        self.rebuild_edited_preview()

    def on_table_item_changed(self, item: QTableWidgetItem):
        """Xử lý thay đổi checkbox (cả chuột và phím Space)."""
        if self._is_updating_table or item.column() != 0:
            return

        row = item.row()
        if 0 <= row < len(self.issues):
            iss = self.issues[row]
            new_status = "applied" if item.checkState() == Qt.Checked else "rejected"
            if iss.status != new_status:
                iss.status = new_status
                self.rebuild_edited_preview()
                self.decisions_changed.emit(self.issues)

    def on_table_cell_clicked(self, row: int, col: int):
        """Khi click vào dòng, cuộn bản gốc đến từ khóa tương ứng."""
        if 0 <= row < len(self.issues):
            iss = self.issues[row]
            if iss.original:
                cursor = self.txt_original.textCursor()
                pos = self.txt_original.toPlainText().find(iss.original)
                if pos != -1:
                    cursor.setPosition(pos)
                    cursor.setPosition(pos + len(iss.original), QTextCursor.KeepAnchor)
                    self.txt_original.setTextCursor(cursor)
                    self.txt_original.ensureCursorVisible()

    def get_edited_paragraphs_map(self) -> Dict[int, List[str]]:
        """
        Dựng lại bản paragraphs đã sửa cho từng chương dựa trên bản gốc và các issue có status='applied'.
        Không bao giờ sửa chồng lên nhau mà luôn xuất phát từ bản gốc bất biến.
        """
        edited_map: Dict[int, List[str]] = {}

        # Gom các issue đã duyệt theo (chapter_num, paragraph_idx)
        issues_by_chap_para: Dict[Tuple[int, int], List[SpellIssue]] = {}
        for iss in self.issues:
            if iss.status == "applied" and iss.chapter_num is not None:
                key = (iss.chapter_num, iss.paragraph_idx)
                if key not in issues_by_chap_para:
                    issues_by_chap_para[key] = []
                issues_by_chap_para[key].append(iss)

        for chap_num, paras in self.original_paragraphs_map.items():
            chap_edited_paras = []
            for p_idx, orig_text in enumerate(paras):
                p_issues = issues_by_chap_para.get((chap_num, p_idx), [])
                edited_p = VietnameseSpellChecker.apply_fixes(orig_text, p_issues, approved_only=True)
                chap_edited_paras.append(edited_p)
            edited_map[chap_num] = chap_edited_paras

        return edited_map

    def rebuild_edited_preview(self):
        """Cập nhật lại cửa sổ xem trước bản sửa và thống kê."""
        if not self.merger or not self.volumes:
            return

        edited_map = self.get_edited_paragraphs_map()
        edited_parts = [
            self.merger.render_volume_text(v, use_edited=True, chapter_paragraphs_map=edited_map)
            for v in self.volumes
        ]
        self.txt_edited.setPlainText("\n\n".join(edited_parts))

        # Cập nhật nhãn thống kê
        total = len(self.issues)
        applied = sum(1 for i in self.issues if i.status == "applied")
        rejected = sum(1 for i in self.issues if i.status == "rejected")
        pending = sum(1 for i in self.issues if i.status == "pending")

        self.lbl_summary.setText(
            f"<b>Tổng đề xuất: {total} | Đã chấp nhận: {applied} | Chờ duyệt: {pending} | Từ chối: {rejected}</b>"
        )

    def select_all(self):
        """Chấp nhận tất cả các đề xuất."""
        self._is_updating_table = True
        for row in range(self.table_issues.rowCount()):
            item = self.table_issues.item(row, 0)
            if item:
                item.setCheckState(Qt.Checked)
            if row < len(self.issues):
                self.issues[row].status = "applied"
        self._is_updating_table = False

        self.rebuild_edited_preview()
        self.decisions_changed.emit(self.issues)

    def reject_all(self):
        """Từ chối tất cả các đề xuất (trở về bản gốc)."""
        self._is_updating_table = True
        for row in range(self.table_issues.rowCount()):
            item = self.table_issues.item(row, 0)
            if item:
                item.setCheckState(Qt.Unchecked)
            if row < len(self.issues):
                self.issues[row].status = "rejected"
        self._is_updating_table = False

        self.rebuild_edited_preview()
        self.decisions_changed.emit(self.issues)
