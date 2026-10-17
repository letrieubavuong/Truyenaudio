"""
Data models for Video Production module:
- AudioVideoItem: Represents an audio track and its novel metadata.
- VideoConfig: Rendering, typography, and FFmpeg encoding configurations.
"""
from dataclasses import dataclass, field
import uuid
import os
import re
from typing import Optional, Dict, Any


@dataclass
class AudioVideoItem:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    audio_path: str = ""
    filename: str = ""
    duration: float = 0.0
    story_title: str = ""
    author: str = ""
    volume_num: int = 1
    start_chapter: int = 1
    end_chapter: int = 4
    custom_bg_path: str = ""
    status: str = "waiting"  # 'waiting', 'processing', 'completed', 'error', 'cancelled'
    progress: float = 0.0
    error_message: str = ""
    output_path: str = ""

    def __post_init__(self):
        if self.audio_path and not self.filename:
            self.filename = os.path.basename(self.audio_path)

    @property
    def display_duration(self) -> str:
        """Định dạng thời lượng mm:ss hoặc hh:mm:ss."""
        if self.duration <= 0:
            return "--:--"
        total_sec = int(self.duration)
        hrs = total_sec // 3600
        mins = (total_sec % 3600) // 60
        secs = total_sec % 60
        if hrs > 0:
            return f"{hrs:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    def suggested_output_filename(self) -> str:
        """Gợi ý tên tệp MP4: {ten_truyen}_Tap_{tap:03d}.mp4 hoặc Tap_{tap:03d}.mp4"""
        clean_title = re.sub(r'[\\/*?:"<>|]', "", self.story_title).replace(" ", "_")
        if clean_title:
            return f"{clean_title}_Tap_{self.volume_num:03d}.mp4"
        return f"Tap_{self.volume_num:03d}.mp4"


@dataclass
class VideoConfig:
    width: int = 1920
    height: int = 1080
    bg_image_path: str = ""
    bg_mode: str = "crop_fill"  # 'crop_fill' or 'fit_letterbox'
    show_title: bool = True
    show_author: bool = True
    show_volume: bool = True
    show_chapters: bool = True
    font_family: str = "Segoe UI"
    title_size: int = 56
    author_size: int = 34
    volume_size: int = 48
    chapters_size: int = 36
    text_color: str = "#FFFFFF"
    stroke_color: str = "#000000"
    stroke_width: int = 3
    has_shadow: bool = True
    shadow_color: str = "#000000"
    shadow_offset: int = 4
    safe_margin: int = 80
    output_dir: str = "output_videos"
    audio_bitrate: str = "192k"
    ffmpeg_path: str = ""
    ffprobe_path: str = ""
    overwrite_mode: str = "rename"  # 'overwrite', 'skip', 'rename'

    def to_dict(self) -> Dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "bg_image_path": self.bg_image_path,
            "bg_mode": self.bg_mode,
            "show_title": self.show_title,
            "show_author": self.show_author,
            "show_volume": self.show_volume,
            "show_chapters": self.show_chapters,
            "font_family": self.font_family,
            "title_size": self.title_size,
            "author_size": self.author_size,
            "volume_size": self.volume_size,
            "chapters_size": self.chapters_size,
            "text_color": self.text_color,
            "stroke_color": self.stroke_color,
            "stroke_width": self.stroke_width,
            "has_shadow": self.has_shadow,
            "shadow_color": self.shadow_color,
            "shadow_offset": self.shadow_offset,
            "safe_margin": self.safe_margin,
            "output_dir": self.output_dir,
            "audio_bitrate": self.audio_bitrate,
            "ffmpeg_path": self.ffmpeg_path,
            "ffprobe_path": self.ffprobe_path,
            "overwrite_mode": self.overwrite_mode,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoConfig":
        valid = {k: v for k, v in data.items() if hasattr(cls, k)}
        return cls(**valid)


def parse_filename_metadata(filename: str) -> Dict[str, Any]:
    """
    Gợi ý thông tin truyện, số tập, khoảng chương từ tên tệp audio (e.g. Tap_001_Chuong_1_den_4.mp3).
    Không dùng để ghi đè metadata đã có trừ khi người dùng xác nhận.
    """
    clean_name = os.path.splitext(os.path.basename(filename))[0]
    res: Dict[str, Any] = {}

    # Tìm tập: Tap_12, Tap 12, Vol_12, Vol 12, Tap12
    m_vol = re.search(r"(?:tap|vol|tập)[_\-\s]*(\d+)", clean_name, re.IGNORECASE)
    if m_vol:
        res["volume_num"] = int(m_vol.group(1))

    # Tìm khoảng chương: Chuong_1_den_4, Chuong 1 - 4, c1-c4, 1-4
    m_chap = re.search(r"(?:chuong|chương|c)[_\-\s]*(\d+)[_\-\s]*(?:den|đến|to|[-_])[_\-\s]*(?:chuong|chương|c)?[_\-\s]*(\d+)", clean_name, re.IGNORECASE)
    if m_chap:
        res["start_chapter"] = int(m_chap.group(1))
        res["end_chapter"] = int(m_chap.group(2))
    else:
        # Thử tìm dạng 1-4 ở cuối
        m_range = re.search(r"(\d+)\s*[-_]\s*(\d+)$", clean_name)
        if m_range:
            res["start_chapter"] = int(m_range.group(1))
            res["end_chapter"] = int(m_range.group(2))

    # Tên truyện nhận diện sơ bộ
    lower_name = clean_name.lower()
    if "pham-nhan" in lower_name or "pham_nhan" in lower_name or "pntt" in lower_name:
        res["story_title"] = "Phàm Nhân Tu Tiên"
        res["author"] = "Vong Ngữ"
    elif "tien-nghich" in lower_name or "tien_nghich" in lower_name or "tiên nghịch" in lower_name:
        res["story_title"] = "Tiên Nghịch"
        res["author"] = "Nhĩ Căn"

    return res


@dataclass
class EncodeResult:
    """Kết quả mã hóa video, phân biệt rõ xuất thành công hay bỏ qua."""
    output_path: str = ""
    status: str = "completed"  # 'completed' hoặc 'skipped'
    message: str = ""

    def __str__(self) -> str:
        return self.output_path

    def __fspath__(self) -> str:
        return self.output_path

    def endswith(self, suffix, *args) -> bool:
        return self.output_path.endswith(suffix, *args)

    def startswith(self, prefix, *args) -> bool:
        return self.output_path.startswith(prefix, *args)

    def __eq__(self, other) -> bool:
        if isinstance(other, str):
            return self.output_path == other
        if isinstance(other, EncodeResult):
            return self.output_path == other.output_path and self.status == other.status
        return False
