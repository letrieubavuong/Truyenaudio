"""
Data models for story chapters, volumes, spellcheck issues, and audit logs.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid


@dataclass
class SpellIssue:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    chapter_num: Optional[int] = None
    chapter_title: str = ""
    paragraph_idx: int = 0
    char_start: int = 0
    char_end: int = 0
    original: str = ""
    replacement: str = ""
    category: str = "chinh_ta"  # 'chinh_ta', 'dau_cau', 'khoang_trang', 'lap_cau', 'gach_duoi_thua', 'ten_rieng'
    reason: str = ""
    source: str = "rule"  # 'rule', 'dictionary', 'ai'
    status: str = "applied"  # 'applied', 'pending', 'rejected'

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "chapter_num": self.chapter_num,
            "chapter_title": self.chapter_title,
            "paragraph_idx": self.paragraph_idx,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "original": self.original,
            "replacement": self.replacement,
            "category": self.category,
            "reason": self.reason,
            "source": self.source,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpellIssue":
        return cls(**data)


@dataclass
class Chapter:
    id: Optional[int] = None
    story_id: Optional[int] = None
    chapter_num: Optional[int] = None
    chapter_title: str = ""
    source_url: str = ""
    raw_content: str = ""
    content_hash: str = ""
    fetch_time: Optional[datetime] = None
    status: str = "downloaded"  # 'downloaded', 'verified', 'failed', 'missing'
    prev_url: str = ""
    next_url: str = ""
    warnings: List[str] = field(default_factory=list)

    @property
    def paragraphs(self) -> List[str]:
        """Tách raw content thành danh sách các đoạn văn không rỗng."""
        if not self.raw_content:
            return []
        lines = [p.strip() for p in self.raw_content.split("\n")]
        return [l for l in lines if l]


@dataclass
class Volume:
    volume_num: int
    title: str = ""
    story_title: str = ""
    start_chapter: int = 0
    end_chapter: int = 0
    chapters: List[Chapter] = field(default_factory=list)
    prologue: str = ""
    epilogue: str = ""
    is_draft: bool = False
    missing_chapters: List[int] = field(default_factory=list)

    @property
    def filename_base(self) -> str:
        """Tên tệp cơ bản theo quy ước: Tap_{volume_num}_Chuong_{start}_den_{end}"""
        base = f"Tap_{self.volume_num}_Chuong_{self.start_chapter}_den_{self.end_chapter}"
        if self.is_draft:
            base += "_DRAFT"
        return base


@dataclass
class StoryInfo:
    id: Optional[int] = None
    url: str = ""
    title: str = ""
    author: str = ""
    total_chapters: int = 0
    status: str = "active"
