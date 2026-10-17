"""
Story and Source Profiles for multi-novel support.
Encapsulates story metadata, parser selection, protected terms, default URLs,
and parameterized prologue/epilogue templates without hardcoding values in shared workflows.
"""
from dataclasses import dataclass, field
from typing import Dict, Optional, List
import os


@dataclass
class StoryProfile:
    id_key: str
    title: str
    author: str
    source_domain: str
    story_url: str
    start_chapter_url: str
    default_output_dir: str
    protected_terms_file: str
    prologue_template: str
    epilogue_template: str
    parser_type: str = "auto"
    genre: str = "tiên hiệp"

    def format_prologue(self, tap: int, chuong_dau: int, chuong_cuoi: int) -> str:
        """Render parameterized prologue for this story."""
        return self.prologue_template.format(
            tap=tap,
            chuong_dau=chuong_dau,
            chuong_cuoi=chuong_cuoi,
            ten_truyen=self.title,
            tac_gia=self.author,
            the_loai=self.genre,
        )

    def format_epilogue(self, tap: int, tap_tiep_theo: int) -> str:
        """Render parameterized epilogue for this story."""
        return self.epilogue_template.format(
            tap=tap,
            tap_tiep_theo=tap_tiep_theo,
            ten_truyen=self.title,
            tac_gia=self.author,
            the_loai=self.genre,
        )


# Template chuẩn hóa có tham số dùng chung
COMMON_PROLOGUE_TEMPLATE = (
    "{ten_truyen_upper} - TẬP {tap}\n"
    "Chào mừng các bạn đang theo dõi bộ truyện {the_loai} {ten_truyen}, tác giả {tac_gia}.\n"
    "Đây là Tập {tap}, phát từ Chương {chuong_dau} đến Chương {chuong_cuoi}.\n"
    "Chúc các bạn có những giây phút thư giãn và trải nghiệm tuyệt vời."
)

COMMON_EPILOGUE_TEMPLATE = (
    "Hết Tập {tap}: Cảm ơn quý thính giả đã chú ý lắng nghe. Hẹn gặp lại các bạn trong Tập {tap_tiep_theo} tiếp theo!"
)


STORY_PROFILES: Dict[str, StoryProfile] = {
    "pham-nhan-tu-tien": StoryProfile(
        id_key="pham-nhan-tu-tien",
        title="Phàm Nhân Tu Tiên",
        author="Vong Ngữ",
        source_domain="vivutruyen.com",
        story_url="https://vivutruyen.com/truyen/pham-nhan-tu-tien",
        start_chapter_url="https://vivutruyen.com/truyen/pham-nhan-tu-tien/chuong-1-son-bien-tieu-thon-103484",
        default_output_dir="output_volumes/pham_nhan_tu_tien",
        protected_terms_file="resources/protected_terms.json",
        prologue_template=(
            "PHÀM NHÂN TU TIÊN - TẬP {tap}\n"
            "Chào mừng các bạn đang theo dõi bộ truyện tiên hiệp Phàm Nhân Tu Tiên, tác giả Vong Ngữ.\n"
            "Đây là Tập {tap}, phát từ Chương {chuong_dau} đến Chương {chuong_cuoi}.\n"
            "Chúc các bạn có những giây phút thư giãn và trải nghiệm tuyệt vời."
        ),
        epilogue_template=(
            "Hết Tập {tap}: Cảm ơn quý thính giả đã chú ý lắng nghe. Hẹn gặp lại các bạn trong Tập {tap_tiep_theo} tiếp theo!"
        ),
        parser_type="vivutruyen",
        genre="tiên hiệp",
    ),
    "tien-nghich": StoryProfile(
        id_key="tien-nghich",
        title="Tiên Nghịch",
        author="Nhĩ Căn",
        source_domain="webnovel.vn",
        story_url="https://webnovel.vn/tien-nghich",
        start_chapter_url="https://webnovel.vn/tien-nghich/chuong-1/",
        default_output_dir="output_volumes/tien_nghich",
        protected_terms_file="resources/protected_terms_tien_nghich.json",
        prologue_template=(
            "TIÊN NGHỊCH - TẬP {tap}\n"
            "Chào mừng các bạn đang theo dõi bộ truyện tiên hiệp Tiên Nghịch, tác giả Nhĩ Căn.\n"
            "Đây là Tập {tap}, phát từ Chương {chuong_dau} đến Chương {chuong_cuoi}.\n"
            "Chúc các bạn có những giây phút thư giãn và trải nghiệm tuyệt vời."
        ),
        epilogue_template=(
            "Hết Tập {tap}: Cảm ơn quý thính giả đã chú ý lắng nghe. Hẹn gặp lại các bạn trong Tập {tap_tiep_theo} tiếp theo!"
        ),
        parser_type="webnovel",
        genre="tiên hiệp",
    ),
}


def get_profile(key_or_url_or_title: str) -> StoryProfile:
    """
    Tìm hồ sơ truyện phù hợp từ khóa, URL hoặc tên truyện.
    Mặc định trả về hồ sơ Phàm Nhân Tu Tiên nếu không tìm thấy.
    """
    query = (key_or_url_or_title or "").strip().lower()
    if query in STORY_PROFILES:
        return STORY_PROFILES[query]

    for p in STORY_PROFILES.values():
        if query == p.id_key.lower():
            return p
        if p.source_domain in query:
            return p
        if p.title.lower() in query or query in p.title.lower():
            return p
        if p.story_url.lower() in query or query in p.story_url.lower():
            return p

    return STORY_PROFILES["pham-nhan-tu-tien"]


def list_profiles() -> List[StoryProfile]:
    return list(STORY_PROFILES.values())
