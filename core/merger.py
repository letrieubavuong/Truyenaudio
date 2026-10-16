"""
Volume Merger for grouping chapters into audio-friendly novel volumes (default: 4 chapters per volume).
Adheres strictly to audio reading format:
- No chapter titles, no chapter number labels, and no separator lines inside volume text.
- Chapters flow consecutively, separated by a single blank line.
- Standard audio prologue and epilogue templates with so_tap, chuong_dau, chuong_cuoi, and so_tap_tiep_theo.
- Shared rendering logic across GUI and CLI.
- Normalizes trailing spaces before export: CRLF/CR -> LF, regex \\s\\n -> \\n (single pass, no loop).
- Keeps draft warning and missing chapter detection intact.
"""
import re
from typing import List, Dict, Optional, Tuple
from core.models import Chapter, Volume


def normalize_trailing_spaces(text: str) -> str:
    """
    Chuẩn hóa khoảng trắng ở cuối dòng trước khi xuất TXT:
    - Chuẩn hóa CRLF/CR thành LF.
    - Áp dụng regex \\s\\n → \\n.
    - Thực hiện đúng một lượt, không lặp thay thế đến khi hết khớp.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\s\n", "\n", text)
    return text


def is_separator_or_inserted_title(line: str, chapter_num: Optional[int] = None, chapter_title: str = "") -> bool:
    """
    Kiểm tra xem dòng có phải là dòng phân cách hoặc tiêu đề chương chèn vào hay không:
    - Bỏ các dòng phân cách như: ------------------------------------------------------------ hoặc ===...
    - Bỏ tiêu đề chương được chương trình chèn như: === CHƯƠNG 4: LUYỆN CỐT NHAI ===
    - Bỏ dòng tiêu đề khớp với chapter_title
    - Không xóa các câu văn bình thường trong truyện dù có chứa từ 'chương'.
    """
    clean = line.strip()
    if not clean:
        return False

    # 1. Dòng phân cách gồm ít nhất 3 ký tự phân cách (-, =, *, _, ~, #) có thể xen kẽ khoảng trắng
    if re.match(r"^(\s*[-=*_~#]\s*){3,}$", clean):
        return True

    # 2. Tiêu đề chương được chèn dạng === CHƯƠNG X: ... === hoặc --- CHƯƠNG X: ... ---
    if re.match(r"^={2,}\s*CHƯƠNG\s+\d+.*={2,}$", clean, re.IGNORECASE):
        return True
    if re.match(r"^[-*#]{2,}\s*CHƯƠNG\s+\d+.*[-*#]{2,}$", clean, re.IGNORECASE):
        return True

    # 3. Tiêu đề chương hoàn toàn khớp với chapter_title đã biết
    if chapter_title and clean.lower() == chapter_title.strip().lower():
        return True

    # 4. Tiêu đề dạng: "Chương X: <Tiêu đề>" khi khớp với số chương của chương đó
    if chapter_num is not None:
        if chapter_title:
            pat = rf"^(?:===|---|###)?\s*CHƯƠNG\s+{chapter_num}\s*[:\-\.]\s*{re.escape(chapter_title.strip())}\s*(?:===|---|###)?$"
            if re.match(pat, clean, re.IGNORECASE):
                return True
        # Tiêu đề độc lập chỉ có số chương và nhãn: "Chương 4" hoặc "CHƯƠNG 4:"
        if re.match(rf"^(?:===|---|###)?\s*CHƯƠNG\s+{chapter_num}\s*[:\-\.]?\s*(?:===|---|###)?$", clean, re.IGNORECASE):
            return True

    return False


class VolumeMerger:
    DEFAULT_PROLOGUE = (
        "PHÀM NHÂN TU TIÊN - TẬP {tap}\n"
        "Chào mừng các bạn đang theo dõi bộ truyện tiên hiệp Phàm Nhân Tu Tiên, tác giả Vong Ngữ.\n"
        "Đây là Tập {tap}, phát từ Chương {chuong_dau} đến Chương {chuong_cuoi}.\n"
        "Chúc các bạn có những giây phút thư giãn và trải nghiệm tuyệt vời."
    )

    DEFAULT_EPILOGUE = (
        "Hết Tập {tap}: Cảm ơn quý thính giả đã chú ý lắng nghe. Hẹn gặp lại các bạn trong Tập {tap_tiep_theo} tiếp theo!"
    )

    def __init__(
        self,
        chapters_per_volume: int = 4,
        include_prologue: bool = True,
        include_epilogue: bool = True,
        prologue_template: str = "",
        epilogue_template: str = "",
        allow_partial_last_volume: bool = False,
    ):
        self.chapters_per_volume = chapters_per_volume
        self.include_prologue = include_prologue
        self.include_epilogue = include_epilogue
        self.prologue_template = prologue_template or self.DEFAULT_PROLOGUE
        self.epilogue_template = epilogue_template or self.DEFAULT_EPILOGUE
        self.allow_partial_last_volume = allow_partial_last_volume

    def build_volumes(
        self,
        chapters: List[Chapter],
        start_volume_num: int,
        expected_start_chap: int,
        expected_end_chap: int,
        story_title: str = "Phàm Nhân Tu Tiên",
    ) -> List[Volume]:
        """
        Chia danh sách chương thành các Volume theo đúng thiết lập:
        - Mặc định 4 chương một tập.
        - Số tập lấy từ thiết lập 'Số tập bắt đầu' (start_volume_num) và tăng lần lượt (không tính cứng từ số chương).
        - chuong_dau và chuong_cuoi lấy từ các chương thực sự có trong tập.
        - so_tap_tiep_theo = so_tap + 1.
        - Phát hiện thiếu chương: đánh dấu is_draft = True, không xuất như tập hoàn chỉnh.
        - Nhóm cuối dưới 4 chương chỉ xuất khi allow_partial_last_volume == True.
        """
        volumes: List[Volume] = []

        chap_map: Dict[int, Chapter] = {}
        for c in chapters:
            if c.chapter_num is not None:
                chap_map[c.chapter_num] = c

        current_vol_num = start_volume_num
        curr_chap = expected_start_chap

        while curr_chap <= expected_end_chap:
            vol_end_chap = min(curr_chap + self.chapters_per_volume - 1, expected_end_chap)
            expected_range = list(range(curr_chap, vol_end_chap + 1))
            actual_count = len(expected_range)

            if actual_count < self.chapters_per_volume and not self.allow_partial_last_volume:
                break

            vol_chapters: List[Chapter] = []
            missing: List[int] = []

            for num in expected_range:
                if num in chap_map:
                    ch = chap_map[num]
                    if ch.status in ("failed", "missing") or not ch.raw_content:
                        missing.append(num)
                    else:
                        vol_chapters.append(ch)
                else:
                    missing.append(num)

            is_draft = len(missing) > 0

            if vol_chapters:
                chuong_dau = vol_chapters[0].chapter_num if vol_chapters[0].chapter_num is not None else curr_chap
                chuong_cuoi = vol_chapters[-1].chapter_num if vol_chapters[-1].chapter_num is not None else vol_end_chap
            else:
                chuong_dau = curr_chap
                chuong_cuoi = vol_end_chap

            so_tap = current_vol_num
            so_tap_tiep_theo = current_vol_num + 1

            format_kwargs = {
                "tap": so_tap,
                "so_tap": so_tap,
                "chuong_dau": chuong_dau,
                "chuong_cuoi": chuong_cuoi,
                "tap_tiep_theo": so_tap_tiep_theo,
                "so_tap_tiep_theo": so_tap_tiep_theo,
                "story_title": story_title or "Phàm Nhân Tu Tiên",
                "volume_num": so_tap,
                "start_chapter": chuong_dau,
                "end_chapter": chuong_cuoi,
            }

            prologue_text = ""
            if self.include_prologue:
                prologue_text = self.prologue_template.format(**format_kwargs)

            epilogue_text = ""
            if self.include_epilogue:
                epilogue_text = self.epilogue_template.format(**format_kwargs)

            volume = Volume(
                volume_num=current_vol_num,
                title=f"Tập {current_vol_num}: Chương {chuong_dau} - {chuong_cuoi}",
                story_title=story_title,
                start_chapter=chuong_dau,
                end_chapter=chuong_cuoi,
                chapters=vol_chapters,
                prologue=prologue_text,
                epilogue=epilogue_text,
                is_draft=is_draft,
                missing_chapters=missing,
            )
            volumes.append(volume)

            current_vol_num += 1
            curr_chap = vol_end_chap + 1

        return volumes

    def render_volume_text(
        self,
        volume: Volume,
        use_edited: bool = False,
        chapter_paragraphs_map: Optional[Dict[int, List[str]]] = None,
    ) -> str:
        """
        Ghép nội dung một tập thành văn bản định dạng đọc audio:
        1. Bỏ toàn bộ tiêu đề từng chương, nhãn đánh số chương và đường phân cách.
        2. Các chương nối tiếp nhau bằng một dòng trống.
        3. Mở đầu ở đầu tập, để 1 dòng trống rồi đến nội dung.
        4. Sau nội dung để 1 dòng trống rồi đến dòng kết thúc.
        5. Nếu là bản nháp thiếu chương, chèn cảnh báo DRAFT ở đầu.
        6. Chuẩn hóa khoảng trắng cuối dòng trước khi trả về:
           - CRLF/CR thành LF
           - re.sub(r"\\s\\n", "\\n", text) đúng một lượt.
        """
        blocks: List[str] = []

        if volume.is_draft:
            blocks.append(
                "************************************************************\n"
                f"CẢNH BÁO: ĐÂY LÀ BẢN NHÁP (DRAFT) - TẬP CHƯA ĐỦ {self.chapters_per_volume} CHƯƠNG HOÀN CHỈNH!\n"
                f"Danh sách chương bị thiếu/lỗi: {volume.missing_chapters}\n"
                "************************************************************"
            )

        # 1. Phần mở đầu mỗi tập (chỉ xuất 1 lần)
        if volume.prologue:
            blocks.append(volume.prologue.strip("\r\n"))

        # 2. Nội dung các chương: nối tiếp nhau bằng một dòng trống
        for ch in volume.chapters:
            if use_edited and chapter_paragraphs_map and ch.chapter_num in chapter_paragraphs_map:
                paras = chapter_paragraphs_map[ch.chapter_num]
            else:
                paras = ch.paragraphs

            for p in paras:
                clean_p = p.strip("\r\n")
                if clean_p.strip():
                    if is_separator_or_inserted_title(
                        clean_p, chapter_num=ch.chapter_num, chapter_title=ch.chapter_title
                    ):
                        continue
                    blocks.append(clean_p)

        # 3. Phần kết thúc mỗi tập (chỉ xuất 1 lần)
        if volume.epilogue:
            blocks.append(volume.epilogue.strip("\r\n"))

        raw_output = "\n\n".join(blocks) + "\n"
        return normalize_trailing_spaces(raw_output)
