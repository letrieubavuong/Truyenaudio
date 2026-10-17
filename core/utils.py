"""
Utility helpers for path resolution, resource bundling and runtime environment detection.
"""
import sys
import os


def get_project_root() -> str:
    """Trả về đường dẫn tuyệt đối đến thư mục gốc của dự án."""
    if getattr(sys, "frozen", False):
        # Khi đóng gói PyInstaller
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    # Khi chạy trực tiếp từ mã nguồn
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_resource_path(relative_path: str) -> str:
    """
    Tìm đường dẫn tệp tài nguyên, tương thích hoàn toàn cả khi chạy script Python trực tiếp
    và khi đóng gói thành file thực thi độc lập (PyInstaller .exe).
    """
    if not relative_path:
        return relative_path

    # Nếu đã là đường dẫn tuyệt đối và tệp tồn tại
    if os.path.isabs(relative_path) and os.path.exists(relative_path):
        return relative_path

    # 1. Kiểm tra trong bundle tạm PyInstaller (_MEIPASS - chế độ --onefile)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cand = os.path.join(meipass, relative_path)
        if os.path.exists(cand):
            return cand

    # 2. Kiểm tra bên cạnh tệp thực thi (.exe - chế độ --onedir hoặc đặt ngoài exe)
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        cand = os.path.join(exe_dir, relative_path)
        if os.path.exists(cand):
            return cand

    # 3. Kiểm tra tương đối so với thư mục gốc dự án (chứa core/ và app.py)
    root = get_project_root()
    cand = os.path.join(root, relative_path)
    if os.path.exists(cand):
        return cand

    # 4. Kiểm tra thư mục làm việc hiện tại
    cand = os.path.abspath(relative_path)
    if os.path.exists(cand):
        return cand

    # Fallback mặc định
    return os.path.join(root, relative_path)
