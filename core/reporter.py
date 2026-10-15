"""
Report and Audit Log Generator.
Generates for each volume:
1. RAW TXT: immutable original text
2. EDITED TXT: text after approved/applied fixes
3. Markdown Report: full statistics by 5 categories, counts (applied, pending, rejected), detailed audit table
4. JSON Changelog: machine-readable audit trail
"""
import os
import json
from datetime import datetime
from typing import List, Dict, Any, Tuple
from core.models import Volume, SpellIssue
from core.merger import VolumeMerger


class ReportGenerator:
    CATEGORY_LABELS = {
        "chinh_ta": "Lỗi chính tả / từ vựng",
        "ten_rieng": "Tên riêng / Thuật ngữ",
        "dau_cau": "Dấu câu",
        "khoang_trang": "Khoảng trắng",
        "gach_duoi_thua": "Dấu gạch dưới thừa / Rác ký tự",
        "lap_cau": "Lỗi trùng lặp câu",
    }

    @classmethod
    def calculate_statistics(cls, issues: List[SpellIssue]) -> Dict[str, Any]:
        """
        Tính toán thống kê theo quy ước:
        - Một thay đổi liên tục, không chồng lấn = 1 vị trí.
        - Lỗi xuất hiện ở nhiều nơi tính riêng.
        - Phân biệt: Tổng đề xuất, Số đã áp dụng, Số chưa xử lý (pending), Số từ chối (rejected).
        - Phân tách theo 5 nhóm lỗi chính.
        """
        stats = {
            "total_suggestions": len(issues),
            "applied": sum(1 for i in issues if i.status == "applied"),
            "pending": sum(1 for i in issues if i.status == "pending"),
            "rejected": sum(1 for i in issues if i.status == "rejected"),
            "by_category": {},
        }

        # Khởi tạo các nhóm
        for cat_key in [
            "chinh_ta",
            "dau_cau",
            "khoang_trang",
            "gach_duoi_thua",
            "lap_cau",
            "ten_rieng",
        ]:
            stats["by_category"][cat_key] = {
                "total": 0,
                "applied": 0,
                "pending": 0,
                "rejected": 0,
            }

        for issue in issues:
            cat = issue.category if issue.category in stats["by_category"] else "chinh_ta"
            stats["by_category"][cat]["total"] += 1
            if issue.status == "applied":
                stats["by_category"][cat]["applied"] += 1
            elif issue.status == "pending":
                stats["by_category"][cat]["pending"] += 1
            elif issue.status == "rejected":
                stats["by_category"][cat]["rejected"] += 1

        return stats

    @classmethod
    def generate_markdown_report(
        cls,
        volume: Volume,
        issues: List[SpellIssue],
        stats: Dict[str, Any],
    ) -> str:
        """Tạo báo cáo chi tiết bằng định dạng Markdown."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_note = "HOÀN CHỈNH" if not volume.is_draft else f"BẢN NHÁP (THIẾU CHƯƠNG: {volume.missing_chapters})"

        md = []
        md.append(f"# BÁO CÁO HIỆU ĐÍNH VÀ KIỂM TRA CHÍNH TẢ")
        md.append(f"**Tác phẩm:** {volume.story_title or 'Phàm Nhân Tu Tiên'}")
        md.append(f"**Tập:** {volume.volume_num} (Chương {volume.start_chapter} đến Chương {volume.end_chapter})")
        md.append(f"**Thời gian xuất:** {now_str}")
        md.append(f"**Trạng thái tập:** {status_note}")
        md.append("\n---\n")

        md.append("## 1. TỔNG QUAN VÀ THỐNG KÊ LỖI")
        md.append(f"- **Tổng số vị trí phát hiện / đề xuất:** **{stats['total_suggestions']}**")
        md.append(f"- **Số thay đổi đã áp dụng:** **{stats['applied']}**")
        md.append(f"- **Số thay đổi chờ duyệt (Pending):** **{stats['pending']}**")
        md.append(f"- **Số đề xuất bị từ chối (Rejected):** **{stats['rejected']}**")
        md.append(f"- *Lưu ý:* Chuẩn hóa Unicode NFC không tính vào số lỗi chính tả.\n")

        md.append("### Bảng thống kê theo nhóm lỗi:")
        md.append("| Nhóm lỗi | Tổng số | Đã áp dụng | Chờ duyệt | Từ chối |")
        md.append("| :--- | :---: | :---: | :---: | :---: |")

        for cat_key, label in cls.CATEGORY_LABELS.items():
            cat_data = stats["by_category"].get(cat_key, {"total": 0, "applied": 0, "pending": 0, "rejected": 0})
            md.append(f"| {label} | {cat_data['total']} | {cat_data['applied']} | {cat_data['pending']} | {cat_data['rejected']} |")

        md.append("\n---\n")
        md.append("## 2. DANH SÁCH CHI TIẾT TỪNG THAY ĐỔI")
        if not issues:
            md.append("*Không phát hiện lỗi hoặc không có đề xuất thay đổi nào.*")
        else:
            md.append("| STT | Chương | Đoạn | Vị trí (Ký tự) | Nội dung gốc | Nội dung sửa | Nhóm lỗi | Lý do | Nguồn | Trạng thái |")
            md.append("| :---: | :---: | :---: | :---: | :--- | :--- | :--- | :--- | :---: | :---: |")

            for idx, iss in enumerate(issues, 1):
                chap_name = f"Chương {iss.chapter_num}" if iss.chapter_num else "Chương ?"
                orig_disp = repr(iss.original)[1:-1] if iss.original else "(rỗng)"
                rep_disp = repr(iss.replacement)[1:-1] if iss.replacement else "(xóa)"
                cat_label = cls.CATEGORY_LABELS.get(iss.category, iss.category)
                status_badge = "Đã áp dụng" if iss.status == "applied" else ("Chờ duyệt" if iss.status == "pending" else "Từ chối")

                md.append(
                    f"| {idx} | {chap_name} | Đoạn {iss.paragraph_idx} | {iss.char_start}-{iss.char_end} | "
                    f"`{orig_disp}` | `{rep_disp}` | {cat_label} | {iss.reason} | {iss.source} | {status_badge} |"
                )

        md.append("\n---\n")
        md.append("*Báo cáo được sinh tự động bởi Công cụ Xử lý và Hiệu đính Truyện.*")

        return "\n".join(md)

    @classmethod
    def export_volume_bundle(
        cls,
        volume: Volume,
        output_dir: str,
        merger: VolumeMerger,
        issues: List[SpellIssue],
        edited_paragraphs_map: Dict[int, List[str]],
        overwrite: bool = False,
    ) -> Dict[str, str]:
        """
        Xuất toàn bộ 4 tệp cho tập vào thư mục output_dir:
        1. RAW TXT
        2. EDITED TXT
        3. REPORT MD
        4. CHANGELOG JSON
        Trả về dict {type: file_path}
        """
        os.makedirs(output_dir, exist_ok=True)
        base_name = volume.filename_base

        raw_path = os.path.join(output_dir, f"{base_name}_RAW.txt")
        edited_path = os.path.join(output_dir, f"{base_name}_EDITED.txt")
        report_path = os.path.join(output_dir, f"{base_name}_REPORT.md")
        json_path = os.path.join(output_dir, f"{base_name}_CHANGELOG.json")

        # Kiểm tra ghi đè an toàn
        for p in [raw_path, edited_path, report_path, json_path]:
            if os.path.exists(p) and not overwrite:
                raise FileExistsError(
                    f"Tệp '{os.path.basename(p)}' đã tồn tại. Vui lòng bật cờ 'Ghi đè' (overwrite) nếu muốn ghi đè."
                )

        # 1. Render RAW TXT (UTF-8)
        raw_text = merger.render_volume_text(volume, use_edited=False)
        with open(raw_path, "w", encoding="utf-8", newline="") as f:
            f.write(raw_text)

        # 2. Render EDITED TXT (UTF-8)
        edited_text = merger.render_volume_text(
            volume, use_edited=True, chapter_paragraphs_map=edited_paragraphs_map
        )
        with open(edited_path, "w", encoding="utf-8", newline="") as f:
            f.write(edited_text)

        # 3. Tính toán thống kê & xuất Báo cáo Markdown
        stats = cls.calculate_statistics(issues)
        report_md = cls.generate_markdown_report(volume, issues, stats)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_md)

        # 4. Xuất JSON Changelog
        audit_data = {
            "volume_num": volume.volume_num,
            "story_title": volume.story_title,
            "start_chapter": volume.start_chapter,
            "end_chapter": volume.end_chapter,
            "is_draft": volume.is_draft,
            "missing_chapters": volume.missing_chapters,
            "created_at": datetime.now().isoformat(),
            "statistics": stats,
            "issues": [i.to_dict() for i in issues],
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(audit_data, f, ensure_ascii=False, indent=2)

        return {
            "raw": raw_path,
            "edited": edited_path,
            "report": report_path,
            "changelog": json_path,
        }
