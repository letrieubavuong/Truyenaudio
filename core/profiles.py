"""
Story and Source Profiles for multi-novel support.
Encapsulates story metadata, source/provider definitions, parser selection,
protected terms, default URLs, and parameterized prologue/epilogue templates.
Decouples 'Story' (bộ truyện) from 'Source/Provider' (nguồn cung cấp).
"""
from dataclasses import dataclass, field
from typing import Dict, Optional, List
from urllib.parse import urlparse
import copy
import os


def normalize_hostname(url_or_domain: str) -> str:
    """
    Chuẩn hóa hostname từ URL hoặc tên miền theo tiêu chuẩn nghiêm ngặt:
    - Loại bỏ schema (http://, https://, //)
    - Loại bỏ cổng (port)
    - Loại bỏ đường dẫn, query param và fragment
    - Loại bỏ tiền tố 'www.'
    - Chuyển về chữ thường (lowercase)
    Ví dụ:
      'https://www.tamhoan.com/tien-nghich/205299' -> 'tamhoan.com'
      'TAMHOAN.COM:443' -> 'tamhoan.com'
      'http://webnovel.vn/tien-nghich' -> 'webnovel.vn'
      'vivutruyen.com' -> 'vivutruyen.com'
    """
    if not url_or_domain:
        return ""
    cand = url_or_domain.strip().lower()
    if not (cand.startswith("http://") or cand.startswith("https://") or cand.startswith("//")):
        cand = "//" + cand
    parsed = urlparse(cand)
    host = parsed.netloc or parsed.path.split("/")[0]
    host = host.split(":")[0].strip()
    if host.startswith("www."):
        host = host[4:]
    return host


def detect_source_from_url(url_or_domain: str) -> str:
    """
    Nhận diện định danh nguồn từ hostname đã chuẩn hóa (không dùng kiểm tra chuỗi lỏng lẻo).
    Trả về: 'tamhoan', 'webnovel', 'vivutruyen', hoặc '' nếu không khớp.
    """
    host = normalize_hostname(url_or_domain)
    if host == "tamhoan.com":
        return "tamhoan"
    if host == "webnovel.vn":
        return "webnovel"
    if host == "vivutruyen.com":
        return "vivutruyen"
    return ""


@dataclass
class SourceProfile:
    """Định nghĩa cấu hình một nguồn cung cấp dữ liệu cho truyện."""
    source_id: str             # 'webnovel', 'tamhoan', 'vivutruyen'
    domain: str                # 'webnovel.vn', 'tamhoan.com', 'vivutruyen.com'
    display_name: str          # Tên hiển thị người dùng: 'webnovel.vn', 'tamhoan.com'
    story_url: str             # URL trang thông tin truyện tại nguồn này
    start_chapter_url: str     # URL mặc định của chương bắt đầu (Chương 1)
    parser_type: str           # Loại parser: 'webnovel', 'tamhoan', 'vivutruyen'
    default_output_dir: str    # Thư mục xuất mặc định phân biệt nguồn


@dataclass
class StoryProfile:
    """
    Hồ sơ bộ truyện độc lập với nguồn cung cấp.
    Hỗ trợ nhiều nguồn khác nhau (sources) cho cùng một bộ truyện.
    """
    id_key: str
    title: str
    author: str
    genre: str = "tiên hiệp"
    protected_terms_file: str = ""
    prologue_template: str = ""
    epilogue_template: str = ""
    sources: Dict[str, SourceProfile] = field(default_factory=dict)
    default_source_id: str = ""
    active_source_id: Optional[str] = None

    def get_source(self, source_id: str = "") -> Optional[SourceProfile]:
        """Lấy cấu hình nguồn theo source_id, hoặc nguồn đang active, hoặc nguồn mặc định."""
        sid = source_id or self.active_source_id or self.default_source_id
        if sid and sid in self.sources:
            return self.sources[sid]
        if self.sources:
            return next(iter(self.sources.values()))
        return None

    def set_active_source(self, source_id: str) -> bool:
        """Kích hoạt nguồn được chọn cho hồ sơ truyện này."""
        sid = (source_id or "").strip().lower()
        # Thử ánh xạ từ domain sang source_id nếu cần
        if sid in ["tamhoan.com", "tamhoan"]:
            sid = "tamhoan"
        elif sid in ["webnovel.vn", "webnovel"]:
            sid = "webnovel"
        elif sid in ["vivutruyen.com", "vivutruyen"]:
            sid = "vivutruyen"

        if sid in self.sources:
            self.active_source_id = sid
            return True
        return False

    # Các thuộc tính tương thích ngược chuyển tiếp tới nguồn đang kích hoạt
    @property
    def source_domain(self) -> str:
        src = self.get_source()
        return src.domain if src else ""

    @property
    def story_url(self) -> str:
        src = self.get_source()
        return src.story_url if src else ""

    @property
    def start_chapter_url(self) -> str:
        src = self.get_source()
        return src.start_chapter_url if src else ""

    @property
    def default_output_dir(self) -> str:
        src = self.get_source()
        return src.default_output_dir if src else ""

    @property
    def parser_type(self) -> str:
        src = self.get_source()
        return src.parser_type if src else "auto"

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
        genre="tiên hiệp",
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
        default_source_id="vivutruyen",
        sources={
            "vivutruyen": SourceProfile(
                source_id="vivutruyen",
                domain="vivutruyen.com",
                display_name="vivutruyen.com",
                story_url="https://vivutruyen.com/truyen/pham-nhan-tu-tien",
                start_chapter_url="https://vivutruyen.com/truyen/pham-nhan-tu-tien/chuong-1-son-bien-tieu-thon-103484",
                parser_type="vivutruyen",
                default_output_dir="output_volumes/pham_nhan_tu_tien",
            )
        },
    ),
    "tien-nghich": StoryProfile(
        id_key="tien-nghich",
        title="Tiên Nghịch",
        author="Nhĩ Căn",
        genre="tiên hiệp",
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
        default_source_id="webnovel",
        sources={
            "webnovel": SourceProfile(
                source_id="webnovel",
                domain="webnovel.vn",
                display_name="webnovel.vn",
                story_url="https://webnovel.vn/tien-nghich",
                start_chapter_url="https://webnovel.vn/tien-nghich/chuong-1/",
                parser_type="webnovel",
                default_output_dir="output_volumes/tien_nghich/webnovel",
            ),
            "tamhoan": SourceProfile(
                source_id="tamhoan",
                domain="tamhoan.com",
                display_name="tamhoan.com",
                story_url="https://tamhoan.com/truyen/tien-nghich",
                start_chapter_url="https://tamhoan.com/tien-nghich/203612",
                parser_type="tamhoan",
                default_output_dir="output_volumes/tien_nghich/tamhoan",
            ),
        },
    ),
}


def get_profile(key_or_url_or_title: str, source_id: str = "") -> StoryProfile:
    """
    Tìm hồ sơ truyện phù hợp từ khóa, URL hoặc tên truyện.
    Cho phép chỉ định nguồn cụ thể qua source_id hoặc tự động nhận diện từ URL.
    Trả về bản sao StoryProfile với active_source_id tương ứng.
    """
    query = (key_or_url_or_title or "").strip().lower()
    detected_source = detect_source_from_url(query) or (source_id or "").strip().lower()
    if detected_source in ["tamhoan.com"]:
        detected_source = "tamhoan"
    elif detected_source in ["webnovel.vn"]:
        detected_source = "webnovel"
    elif detected_source in ["vivutruyen.com"]:
        detected_source = "vivutruyen"

    chosen_profile: Optional[StoryProfile] = None

    # Khớp chính xác id_key
    if query in STORY_PROFILES:
        chosen_profile = STORY_PROFILES[query]
    elif query in ["tien-nghich-tamhoan", "tien-nghich/tamhoan"]:
        chosen_profile = STORY_PROFILES["tien-nghich"]
        detected_source = "tamhoan"
    elif query in ["tien-nghich-webnovel", "tien-nghich/webnovel"]:
        chosen_profile = STORY_PROFILES["tien-nghich"]
        detected_source = "webnovel"

    if not chosen_profile:
        # Tìm theo domain hoặc title hoặc story_url
        for p in STORY_PROFILES.values():
            if query == p.id_key.lower():
                chosen_profile = p
                break
            for s in p.sources.values():
                if s.domain in query or query == s.domain:
                    chosen_profile = p
                    detected_source = detected_source or s.source_id
                    break
                if s.story_url.lower() in query or query in s.story_url.lower():
                    chosen_profile = p
                    detected_source = detected_source or s.source_id
                    break
            if chosen_profile:
                break
            if p.title.lower() in query or query in p.title.lower():
                chosen_profile = p
                break

    if not chosen_profile:
        chosen_profile = STORY_PROFILES["pham-nhan-tu-tien"]

    # Tạo bản sao nông để gán active_source_id mà không ảnh hưởng trạng thái global
    prof_copy = copy.copy(chosen_profile)
    if detected_source and detected_source in prof_copy.sources:
        prof_copy.active_source_id = detected_source
    else:
        prof_copy.active_source_id = prof_copy.default_source_id

    return prof_copy


def list_profiles() -> List[StoryProfile]:
    return list(STORY_PROFILES.values())
