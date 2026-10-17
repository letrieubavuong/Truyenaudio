"""
Data models for VieNeu-TTS Audio Production Pipeline.
Includes configurations, items, chunks, voice profiles, and environment status.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import hashlib
import json


@dataclass
class TTSVoice:
    voice_id: str
    display_name: str
    gender: str = ""        # "Nam", "Nữ"
    region: str = "Bắc"     # "Bắc", "Nam", "Trung"
    style: str = "Phong cách tự nhiên"
    sample_rate: int = 48000
    starred: bool = True
    description: str = ""


def get_default_voices() -> List[TTSVoice]:
    """Danh sách 25 giọng đọc chuẩn tiếng Việt phân loại theo Nam/Nữ và vùng miền."""
    return [
        TTSVoice("Hải Đăng", "Hải Đăng", "Nam", "Bắc", "Phong cách tự nhiên", 48000, True, "Nam · Bắc · Phong cách tự nhiên · 48 kHz"),
        TTSVoice("Adam bựa", "Adam bựa", "Nam", "Bắc", "Phong cách tự nhiên", 48000, True, "Nam · Bắc · Phong cách tự nhiên · 48 kHz"),
        TTSVoice("Trúc Ly", "Trúc Ly", "Nữ", "Bắc", "Phong cách tự nhiên", 48000, True, "Nữ · Bắc · Phong cách tự nhiên · 48 kHz"),
        TTSVoice("Thiện Minh", "Thiện Minh", "Nam", "Bắc", "Phong cách kể chuyện", 48000, True, "Nam · Bắc · Phong cách kể chuyện · 48 kHz"),
        TTSVoice("Mai Anh", "Mai Anh", "Nữ", "Bắc", "Phong cách tin tức", 48000, True, "Nữ · Bắc · Phong cách tin tức · 48 kHz"),
        TTSVoice("Thùy Dung", "Thùy Dung", "Nữ", "Nam", "Phong cách ngọt ngào", 48000, True, "Nữ · Nam · Phong cách ngọt ngào · 48 kHz"),
        TTSVoice("Minh Quang", "Minh Quang", "Nam", "Bắc", "Phong cách trầm ấm", 48000, True, "Nam · Bắc · Phong cách trầm ấm · 48 kHz"),
        TTSVoice("Thu Hà", "Thu Hà", "Nữ", "Bắc", "Phong cách dịu dàng", 48000, True, "Nữ · Bắc · Phong cách dịu dàng · 48 kHz"),
        TTSVoice("Thanh Trúc", "Thanh Trúc", "Nữ", "Nam", "Phong cách truyền cảm", 48000, True, "Nữ · Nam · Phong cách truyền cảm · 48 kHz"),
        TTSVoice("Tuấn Anh", "Tuấn Anh", "Nam", "Bắc", "Phong cách diễn cảm", 48000, False, "Nam · Bắc · Phong cách diễn cảm · 48 kHz"),
        TTSVoice("Bảo Ngọc", "Bảo Ngọc", "Nữ", "Nam", "Phong cách trong trẻo", 48000, False, "Nữ · Nam · Phong cách trong trẻo · 48 kHz"),
        TTSVoice("Mạnh Cường", "Mạnh Cường", "Nam", "Bắc", "Phong cách mạnh mẽ", 48000, False, "Nam · Bắc · Phong cách mạnh mẽ · 48 kHz"),
        TTSVoice("Hoài An", "Hoài An", "Nữ", "Bắc", "Phong cách kể chuyện", 48000, False, "Nữ · Bắc · Phong cách kể chuyện · 48 kHz"),
        TTSVoice("Duy Khang", "Duy Khang", "Nam", "Nam", "Phong cách tự nhiên", 48000, False, "Nam · Nam · Phong cách tự nhiên · 48 kHz"),
        TTSVoice("Ngọc Huyền", "Ngọc Huyền", "Nữ", "Bắc", "Phong cách thanh lịch", 48000, False, "Nữ · Bắc · Phong cách thanh lịch · 48 kHz"),
        TTSVoice("Minh Hoàng", "Minh Hoàng", "Nam", "Nam", "Phong cách ấm áp", 48000, False, "Nam · Nam · Phong cách ấm áp · 48 kHz"),
        TTSVoice("Quỳnh Nga", "Quỳnh Nga", "Nữ", "Nam", "Phong cách nhẹ nhàng", 48000, False, "Nữ · Nam · Phong cách nhẹ nhàng · 48 kHz"),
        TTSVoice("Thanh Tùng", "Thanh Tùng", "Nam", "Nam", "Phong cách hào hùng", 48000, False, "Nam · Nam · Phong cách hào hùng · 48 kHz"),
        TTSVoice("Phương Linh", "Phương Linh", "Nữ", "Bắc", "Phong cách diễn cảm", 48000, False, "Nữ · Bắc · Phong cách diễn cảm · 48 kHz"),
        TTSVoice("Bảo Quốc", "Bảo Quốc", "Nam", "Nam", "Phong cách truyền cảm", 48000, False, "Nam · Nam · Phong cách truyền cảm · 48 kHz"),
        TTSVoice("Hương Giang", "Hương Giang", "Nữ", "Trung", "Phong cách mộc mạc", 48000, False, "Nữ · Trung · Phong cách mộc mạc · 48 kHz"),
        TTSVoice("Hùng Dũng", "Hùng Dũng", "Nam", "Trung", "Phong cách dứt khoát", 48000, False, "Nam · Trung · Phong cách dứt khoát · 48 kHz"),
        TTSVoice("Diễm My", "Diễm My", "Nữ", "Nam", "Phong cách cuốn hút", 48000, False, "Nữ · Nam · Phong cách cuốn hút · 48 kHz"),
        TTSVoice("Đức Thắng", "Đức Thắng", "Nam", "Bắc", "Phong cách kiếm hiệp", 48000, False, "Nam · Bắc · Phong cách kiếm hiệp · 48 kHz"),
        TTSVoice("Kim Ngân", "Kim Ngân", "Nữ", "Bắc", "Phong cách hoạt hình", 48000, False, "Nữ · Bắc · Phong cách hoạt hình · 48 kHz"),
    ]


@dataclass
class TTSEnvStatus:
    available: bool = False
    python_path: str = ""
    sdk_version: str = ""
    backends: List[str] = field(default_factory=lambda: ["onnx"])
    current_backend: str = "onnx"
    cuda_available: bool = False
    device_name: str = "CPU"
    voices: List[TTSVoice] = field(default_factory=list)
    models: List[str] = field(default_factory=lambda: ["v3_turbo", "v3nano"])
    default_model: str = "v3_turbo"
    error_message: str = ""


@dataclass
class TTSConfig:
    python_path: str = ""
    model_name: str = "v3_turbo"
    backend: str = "onnx"
    precision: str = "fp32"
    voice_id: str = "Hải Đăng"
    sample_rate: int = 48000
    speed: float = 1.0
    generate_subtitles: bool = False
    pause_sentence_ms: int = 250
    pause_paragraph_ms: int = 500
    pause_chapter_ms: int = 1500
    mp3_bitrate: str = "192k"
    overwrite_mode: str = "overwrite"  # overwrite, skip, rename
    cache_dir: str = ""

    def compute_hash(self) -> str:
        """Băm các thông số ảnh hưởng trực tiếp tới âm thanh đầu ra."""
        cfg_str = f"{self.model_name}|{self.backend}|{self.precision}|{self.voice_id}|{self.sample_rate}|{self.speed:.2f}|{self.pause_sentence_ms}|{self.pause_paragraph_ms}|{self.pause_chapter_ms}"
        return hashlib.sha256(cfg_str.encode("utf-8")).hexdigest()[:16]


@dataclass
class TTSChunk:
    index: int
    text: str
    text_hash: str
    char_count: int
    word_count: int
    paragraph_idx: int
    is_chapter_boundary: bool = False
    wav_path: str = ""
    duration_sec: float = 0.0
    sample_count: int = 0
    status: str = "pending"  # pending, synthesizing, completed, error
    error_msg: str = ""


@dataclass
class TTSItem:
    item_id: str
    story_title: str
    author: str = ""
    volume_num: int = 1
    start_chap: int = 1
    end_chap: int = 1
    source: str = ""
    raw_text: str = ""
    text_source_path: str = ""
    word_count: int = 0
    char_count: int = 0
    chunks: List[TTSChunk] = field(default_factory=list)
    chunks_done: int = 0
    chunks_total: int = 0
    status: str = "waiting"  # waiting, loading_model, synthesizing, assembling, completed, skipped, cancelled, error
    duration_sec: float = 0.0
    output_mp3_path: str = ""
    manifest_dir: str = ""
    error_msg: str = ""
    chars_per_sec: float = 0.0
    eta_seconds: Optional[float] = None
    created_at: str = ""
    updated_at: str = ""

    def get_progress_percent(self) -> int:
        if self.chunks_total <= 0:
            return 0
        if self.status == "completed":
            return 100
        # Không bao giờ hiển thị 100% khi chỉ mới tổng hợp xong chunks mà chưa ghép MP3
        pct = int((self.chunks_done / self.chunks_total) * 95)
        return min(pct, 95)
