"""
Pronunciation dictionary and text cleaning utilities for TTS production.
Supports acronym expansion, Sino-Vietnamese reading fixes, and web watermark cleanup.
"""
import os
import re
import json
from typing import Dict, List, Tuple


DEFAULT_DICTIONARY: List[Dict[str, str]] = [
    {"source": "PNTT", "target": "Phàm Nhân Tu Tiên", "case_sensitive": True},
    {"source": "TN", "target": "Tiên Nghịch", "case_sensitive": True},
    {"source": "chap", "target": "chương", "case_sensitive": False},
    {"source": "vol", "target": "tập", "case_sensitive": False},
    {"source": "admin", "target": "quản trị viên", "case_sensitive": False},
    {"source": "2k", "target": "hai nghìn", "case_sensitive": False},
    {"source": "1k", "target": "một nghìn", "case_sensitive": False},
    {"source": "mc", "target": "nhân vật chính", "case_sensitive": False},
    {"source": "fb", "target": "phây búc", "case_sensitive": False},
    {"source": "yt", "target": "du túp", "case_sensitive": False},
]

# Danh sách watermark phổ biến từ các website truyện cần lọc bỏ khi làm sạch
WATERMARK_PATTERNS = [
    r"(?i)nguồn\s*:\s*(tamhoan\.com|vivutruyen\.com|webnovel\.vn|truyenfull|metruyenchu)",
    r"(?i)truy cập\s*(https?://)?(tamhoan\.com|vivutruyen\.com|webnovel\.vn)\s*để đọc.*",
    r"(?i)chúc các bạn đọc truyện vui vẻ.*",
    r"(?i)đọc truyện online tại\s*\S+",
    r"(?i)bạn đang theo dõi truyện tại\s*\S+",
    r"[-=_~*]{5,}",
]


class TTSDictionaryManager:
    """Quản lý từ điển phát âm lưu trữ dạng JSON."""

    def __init__(self, dict_path: str = "pronunciation_dict.json"):
        self.dict_path = os.path.abspath(dict_path)
        self.rules: List[Dict[str, Any]] = []
        self.load()

    def load(self):
        if os.path.isfile(self.dict_path):
            try:
                with open(self.dict_path, "r", encoding="utf-8") as f:
                    self.rules = json.load(f)
                    return
            except Exception:
                pass
        self.rules = list(DEFAULT_DICTIONARY)
        self.save()

    def save(self):
        try:
            with open(self.dict_path, "w", encoding="utf-8") as f:
                json.dump(self.rules, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def apply(self, text: str) -> str:
        """Thay thế các từ viết tắt / từ đặc biệt trong văn bản theo từ điển."""
        if not text:
            return ""
        result = text
        for item in self.rules:
            src = item.get("source", "").strip()
            tgt = item.get("target", "").strip()
            case_sens = item.get("case_sensitive", False)
            if not src or not tgt:
                continue

            flags = 0 if case_sens else re.IGNORECASE
            # Khớp theo ranh giới từ để tránh thay thế nhầm từ con
            pattern = r"\b" + re.escape(src) + r"\b"
            result = re.sub(pattern, tgt, result, flags=flags)
        return result


def clean_reading_text(text: str, apply_dict: bool = False, dict_manager: TTSDictionaryManager = None) -> str:
    """
    Làm sạch văn bản phục vụ đọc TTS:
    - Loại bỏ dấu phân cách rác, link web và watermark
    - Chuẩn hóa dấu ngoặc kép, dấu câu, khoảng trắng
    - Giới hạn dòng trống liên tiếp
    - Áp dụng từ điển phát âm nếu yêu cầu
    """
    if not text:
        return ""

    lines = text.splitlines()
    cleaned_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append("")
            continue

        # Kiểm tra lọc watermark
        is_watermark = False
        for pat in WATERMARK_PATTERNS:
            if re.search(pat, stripped):
                is_watermark = True
                break
        if is_watermark:
            continue

        # Chuẩn hóa khoảng trắng bên trong dòng
        l_clean = re.sub(r"[ \t]+", " ", stripped)

        # Chuẩn hóa dấu ngoặc kép cong
        l_clean = l_clean.replace("“", '"').replace("”", '"').replace("«", '"').replace("»", '"')
        l_clean = l_clean.replace("‘", "'").replace("’", "'")

        # Chuẩn hóa dấu chấm lửng
        l_clean = re.sub(r"\.{3,}", "...", l_clean)

        # Chuẩn hóa khoảng cách trước dấu câu
        l_clean = re.sub(r"\s+([,.:;!?])", r"\1", l_clean)

        cleaned_lines.append(l_clean)

    # Ghép lại và khử các dòng trống liên tiếp (tối đa 1 dòng trống)
    joined = "\n".join(cleaned_lines)
    joined = re.sub(r"\n{3,}", "\n\n", joined).strip()

    if apply_dict:
        dm = dict_manager or TTSDictionaryManager()
        joined = dm.apply(joined)

    return joined
