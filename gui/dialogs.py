"""
Configuration dialogs for AI settings, custom dictionaries, protected terms, and templates.
"""
import json
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel, QLineEdit,
    QPushButton, QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QComboBox, QGroupBox, QFormLayout
)
from PySide6.QtCore import Qt


class SettingsDialog(QDialog):
    def __init__(
        self,
        parent=None,
        dict_path: str = "resources/default_dictionary.json",
        terms_path: str = "resources/protected_terms.json",
    ):
        super().__init__(parent)
        self.setWindowTitle("Cài đặt hệ thống & Từ điển")
        self.resize(750, 550)
        from core.utils import get_resource_path
        self.dict_path = get_resource_path(dict_path)
        self.terms_path = get_resource_path(terms_path)

        self.init_ui()
        self.load_settings()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        self.tabs = QTabWidget()

        # Tab 1: Cấu hình AI
        self.tab_ai = self.create_ai_tab()
        self.tabs.addTab(self.tab_ai, "Cấu hình AI")

        # Tab 2: Từ điển sửa lỗi
        self.tab_dict = self.create_dict_tab()
        self.tabs.addTab(self.tab_dict, "Từ điển sửa lỗi")

        # Tab 3: Tên riêng được bảo vệ
        self.tab_terms = self.create_terms_tab()
        self.tabs.addTab(self.tab_terms, "Từ ngữ bảo vệ")

        main_layout.addWidget(self.tabs)

        # Nút Đóng & Lưu
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()

        self.btn_save_all = QPushButton("Lưu cài đặt")
        self.btn_save_all.setStyleSheet("background-color: #1976d2; color: white; padding: 6px 16px; font-weight: bold;")
        self.btn_save_all.clicked.connect(self.save_all)

        self.btn_close = QPushButton("Đóng")
        self.btn_close.clicked.connect(self.reject)

        bottom_layout.addWidget(self.btn_save_all)
        bottom_layout.addWidget(self.btn_close)
        main_layout.addLayout(bottom_layout)

    def create_ai_tab(self):
        widget = QGroupBox("Thiết lập nhà cung cấp mô hình ngôn ngữ lớn (LLM)")
        layout = QFormLayout(widget)

        self.combo_provider = QComboBox()
        self.combo_provider.addItems(["openai_compatible", "gemini"])
        layout.addRow("Nhà cung cấp (Provider):", self.combo_provider)

        self.txt_api_key = QLineEdit()
        self.txt_api_key.setEchoMode(QLineEdit.Password)
        self.txt_api_key.setPlaceholderText("Nhập API Key (ví dụ: sk-...)")
        layout.addRow("API Key:", self.txt_api_key)

        self.txt_model = QLineEdit("gpt-4o-mini")
        self.txt_model.setPlaceholderText("gpt-4o-mini hoặc gemini-2.5-flash...")
        layout.addRow("Tên mô hình (Model):", self.txt_model)

        self.txt_base_url = QLineEdit("https://api.openai.com/v1")
        self.txt_base_url.setPlaceholderText("URL endpoint (dành cho OpenAI-compatible)")
        layout.addRow("Base URL:", self.txt_base_url)

        lbl_note = QLabel(
            "<i>Lưu ý: Chế độ AI là tùy chọn. Hệ thống không tự động gửi dữ liệu khi chưa bật.<br>"
            "Tài khoản ChatGPT Plus không bao gồm API Key thương mại.</i>"
        )
        lbl_note.setStyleSheet("color: #616161; margin-top: 10px;")
        layout.addRow(lbl_note)

        return widget

    def create_dict_tab(self):
        widget = QGroupBox("Danh sách các cặp từ thay thế trong từ điển")
        layout = QVBoxLayout(widget)

        # Bảng từ điển
        self.table_dict = QTableWidget()
        self.table_dict.setColumnCount(2)
        self.table_dict.setHorizontalHeaderLabels(["Từ viết sai / Lỗi", "Từ sửa đúng"])
        self.table_dict.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table_dict)

        # Thanh thêm từ
        add_layout = QHBoxLayout()
        self.input_wrong = QLineEdit()
        self.input_wrong.setPlaceholderText("Từ sai (ví dụ: nguời)")
        self.input_correct = QLineEdit()
        self.input_correct.setPlaceholderText("Từ đúng (ví dụ: người)")
        self.btn_add_dict = QPushButton("Thêm từ")
        self.btn_del_dict = QPushButton("Xóa dòng chọn")

        self.btn_add_dict.clicked.connect(self.add_dict_item)
        self.btn_del_dict.clicked.connect(self.del_dict_item)

        add_layout.addWidget(self.input_wrong)
        add_layout.addWidget(self.input_correct)
        add_layout.addWidget(self.btn_add_dict)
        add_layout.addWidget(self.btn_del_dict)
        layout.addLayout(add_layout)

        return widget

    def create_terms_tab(self):
        widget = QGroupBox("Danh sách danh từ riêng, nhân vật, môn phái, địa danh cần bảo vệ")
        layout = QVBoxLayout(widget)

        self.txt_terms = QTextEdit()
        self.txt_terms.setPlaceholderText("Mỗi dòng một tên riêng hoặc thuật ngữ (ví dụ: Hàn Lập, Thất Huyền Môn...)")
        layout.addWidget(self.txt_terms)

        return widget

    def load_settings(self):
        # Nạp từ điển
        if os.path.exists(self.dict_path):
            try:
                with open(self.dict_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    reps = data.get("replacements", {})
                    self.table_dict.setRowCount(len(reps))
                    for row, (k, v) in enumerate(reps.items()):
                        self.table_dict.setItem(row, 0, QTableWidgetItem(k))
                        self.table_dict.setItem(row, 1, QTableWidgetItem(v))
            except Exception:
                pass

        # Nạp terms
        if os.path.exists(self.terms_path):
            try:
                with open(self.terms_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    terms = data.get("terms", [])
                    self.txt_terms.setPlainText("\n".join(terms))
            except Exception:
                pass

    def add_dict_item(self):
        w = self.input_wrong.text().strip()
        c = self.input_correct.text().strip()
        if not w or not c:
            QMessageBox.warning(self, "Thiếu dữ liệu", "Vui lòng nhập cả từ sai và từ đúng.")
            return

        row = self.table_dict.rowCount()
        self.table_dict.insertRow(row)
        self.table_dict.setItem(row, 0, QTableWidgetItem(w))
        self.table_dict.setItem(row, 1, QTableWidgetItem(c))
        self.input_wrong.clear()
        self.input_correct.clear()

    def del_dict_item(self):
        curr_row = self.table_dict.currentRow()
        if curr_row >= 0:
            self.table_dict.removeRow(curr_row)

    def save_all(self):
        # 1. Lưu từ điển
        reps = {}
        for r in range(self.table_dict.rowCount()):
            item_k = self.table_dict.item(r, 0)
            item_v = self.table_dict.item(r, 1)
            if item_k and item_v and item_k.text().strip():
                reps[item_k.text().strip()] = item_v.text().strip()

        dict_data = {"description": "Từ điển sửa lỗi chính tả", "replacements": reps, "context_rules": []}
        try:
            with open(self.dict_path, "w", encoding="utf-8") as f:
                json.dump(dict_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "Lỗi lưu từ điển", str(e))
            return

        # 2. Lưu từ bảo vệ
        lines = [l.strip() for l in self.txt_terms.toPlainText().splitlines() if l.strip()]
        terms_data = {"description": "Danh sách danh từ riêng được bảo vệ", "terms": lines}
        try:
            with open(self.terms_path, "w", encoding="utf-8") as f:
                json.dump(terms_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "Lỗi lưu từ bảo vệ", str(e))
            return

        QMessageBox.information(self, "Thành công", "Đã lưu cài đặt từ điển và từ bảo vệ thành công!")
        self.accept()
