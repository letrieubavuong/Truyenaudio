"""
Custom widgets for Chapter Status Table, Diff Review, and Real-time Log.
"""
from typing import List, Dict, Any, Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QTextEdit, QLabel, QPushButton, QSplitter, QCheckBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QTextCursor, QTextCharFormat
from core.models import Chapter, SpellIssue


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
            self.setItem(row, 1, QTableWidgetItem(f"Chương {ch.chapter_num}" if ch.chapter_num else "?"))
            self.setItem(row, 2, QTableWidgetItem(ch.chapter_title))

            # Trạng thái
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
    - Bên trái: Văn bản bản gốc
    - Bên phải: Văn bản bản sửa
    - Bên dưới: Bảng danh sách các thay đổi để duyệt / từ chối từng mục
    """
    issue_status_changed = Signal(str, str)  # (issue_id, new_status)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.issues: List[SpellIssue] = []
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # Thanh tiêu đề và công cụ
        toolbar_layout = QHBoxLayout()
        self.lbl_summary = QLabel("<b>Danh sách thay đổi cần duyệt (0 mục)</b>")
        toolbar_layout.addWidget(self.lbl_summary)

        toolbar_layout.addStretch()

        self.btn_select_all = QPushButton("Duyệt tất cả")
        self.btn_reject_all = QPushButton("Từ chối tất cả")
        self.btn_select_all.clicked.connect(self.select_all)
        self.btn_reject_all.clicked.connect(self.reject_all)

        toolbar_layout.addWidget(self.btn_select_all)
        toolbar_layout.addWidget(self.btn_reject_all)
        main_layout.addLayout(toolbar_layout)

        # Splitter dọc chia 2 phần: Trên là so sánh Side-by-side, dưới là bảng duyệt
        v_splitter = QSplitter(Qt.Vertical)

        # Khung Side-by-side
        diff_container = QWidget()
        diff_layout = QHBoxLayout(diff_container)
        diff_layout.setContentsMargins(0, 0, 0, 0)

        # Cột trái: Bản gốc
        left_box = QVBoxLayout()
        left_box.addWidget(QLabel("<b>BẢN GỐC (BẤT BIẾN):</b>"))
        self.txt_original = QTextEdit()
        self.txt_original.setReadOnly(True)
        self.txt_original.setFont(QFont("Segoe UI", 10))
        left_box.addWidget(self.txt_original)
        diff_layout.addLayout(left_box)

        # Cột phải: Bản đã sửa
        right_box = QVBoxLayout()
        right_box.addWidget(QLabel("<b>BẢN ĐÃ SỬA (SAU DUYỆT):</b>"))
        self.txt_edited = QTextEdit()
        self.txt_edited.setReadOnly(True)
        self.txt_edited.setFont(QFont("Segoe UI", 10))
        right_box.addWidget(self.txt_edited)
        diff_layout.addLayout(right_box)

        v_splitter.addWidget(diff_container)

        # Khung dưới: Bảng duyệt các thay đổi
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
        self.table_issues.cellClicked.connect(self.on_table_cell_clicked)

        table_layout.addWidget(self.table_issues)
        v_splitter.addWidget(table_container)

        v_splitter.setSizes([350, 250])
        main_layout.addWidget(v_splitter)

    def load_data(
        self,
        issues: List[SpellIssue],
        raw_text: str,
        edited_text: str,
    ):
        self.issues = issues
        self.txt_original.setPlainText(raw_text)
        self.txt_edited.setPlainText(edited_text)
        self.lbl_summary.setText(f"<b>Danh sách thay đổi cần duyệt ({len(issues)} mục)</b>")

        self.table_issues.setRowCount(len(issues))
        for row, iss in enumerate(issues):
            # Checkbox duyệt
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk_item.setCheckState(Qt.Checked if iss.status == "applied" else Qt.Unchecked)
            self.table_issues.setItem(row, 0, chk_item)

            self.table_issues.setItem(row, 1, QTableWidgetItem(str(row + 1)))
            self.table_issues.setItem(row, 2, QTableWidgetItem(f"Chương {iss.chapter_num}" if iss.chapter_num else "?"))
            self.table_issues.setItem(row, 3, QTableWidgetItem(f"Đoạn {iss.paragraph_idx}"))
            self.table_issues.setItem(row, 4, QTableWidgetItem(repr(iss.original)[1:-1]))
            self.table_issues.setItem(row, 5, QTableWidgetItem(repr(iss.replacement)[1:-1]))
            self.table_issues.setItem(row, 6, QTableWidgetItem(iss.category))
            self.table_issues.setItem(row, 7, QTableWidgetItem(iss.reason))
            self.table_issues.setItem(row, 8, QTableWidgetItem(iss.source))

    def on_table_cell_clicked(self, row, col):
        if 0 <= row < len(self.issues):
            iss = self.issues[row]
            # Nếu click vào cột checkbox 0
            if col == 0:
                item = self.table_issues.item(row, 0)
                is_checked = item.checkState() == Qt.Checked
                iss.status = "applied" if is_checked else "rejected"
                self.issue_status_changed.emit(iss.id, iss.status)

            # Cuộn văn bản tới từ khóa
            if iss.original:
                cursor = self.txt_original.textCursor()
                pos = self.txt_original.toPlainText().find(iss.original)
                if pos != -1:
                    cursor.setPosition(pos)
                    cursor.setPosition(pos + len(iss.original), QTextCursor.KeepAnchor)
                    self.txt_original.setTextCursor(cursor)
                    self.txt_original.ensureCursorVisible()

    def select_all(self):
        for row in range(self.table_issues.rowCount()):
            item = self.table_issues.item(row, 0)
            if item:
                item.setCheckState(Qt.Checked)
            if row < len(self.issues):
                self.issues[row].status = "applied"

    def reject_all(self):
        for row in range(self.table_issues.rowCount()):
            item = self.table_issues.item(row, 0)
            if item:
                item.setCheckState(Qt.Unchecked)
            if row < len(self.issues):
                self.issues[row].status = "rejected"
