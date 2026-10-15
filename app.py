"""
Main application launcher for the Vietnamese Story Collector, Spell Checker & Volume Merger.
"""
import sys
import os

# Cấu hình UTF-8 cho môi trường Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from gui.main_window import MainWindow


def main():
    # Kích hoạt hỗ trợ DPI cao trên màn hình Windows
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("PNTT Truyen Manager")

    # Nạp stylesheet nền sáng hiện đại
    qss_path = os.path.join(os.path.dirname(__file__), "resources", "styles.qss")
    if os.path.exists(qss_path):
        try:
            with open(qss_path, "r", encoding="utf-8") as f:
                app.setStyleSheet(f.read())
        except Exception as e:
            print(f"[!] Không thể nạp stylesheet: {e}")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
