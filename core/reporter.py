"""
Report and Audit Log Generator.
Generates for each volume:
1. RAW TXT: immutable original text
2. EDITED TXT: text after approved/applied fixes
3. Markdown Report: full statistics by categories, counts (applied, pending, rejected), detailed audit table with escaped special characters
4. JSON Changelog: machine-readable audit trail
Supports atomic writes via temporary files to prevent half-finished bundles.
"""
import os
import json
from datetime import datetime
from typing import List, Dict, Any, Tuple
from core.models import Volume, SpellIssue
from core.merger import VolumeMerger


def escape_md(text: str) -> str:
    """Thoát các ký tự đặc biệt để không làm vỡ bảng Markdown."""
    if not text:
        return ""
    text = str(text).replace("|", "\\|").replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return text


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
        - Tổng số đề xuất = applied + pending + rejected + skipped.
        - Số đã áp dụng chỉ tính các thay đổi thực sự có trạng thái 'applied' (applied_status == 'applied').
        - Tách riêng: Chờ duyệt (pending), Từ chối (rejected), và Không áp dụng được / xung đột (skipped).
        """
        applied_count = sum(1 for i in issues if getattr(i, "applied_status", i.status) == "applied")
        pending_count = sum(
            1 for i in issues
            if getattr(i, "user_decision", i.status) == "pending" or getattr(i, "applied_status", "") == "skipped_pending"
        )
        rejected_count = sum(
            1 for i in issues
            if getattr(i, "user_decision", i.status) == "rejected" or getattr(i, "applied_status", "") == "skipped_rejected"
        )
        skipped_count = sum(
            1 for i in issues
            if getattr(i, "applied_status", i.status) in ("skipped_conflict", "skipped_mismatch")
        )

        stats = {
            "total_suggestions": len(issues),
            "applied": applied_count,
            "pending": pending_count,
            "rejected": rejected_count,
            "skipped": skipped_count,
            "by_category": {},
        }

        for cat_key in cls.CATEGORY_LABELS.keys():
            stats["by_category"][cat_key] = {
                "total": 0,
                "applied": 0,
                "pending": 0,
                "rejected": 0,
                "skipped": 0,
            }

        for issue in issues:
            cat = issue.category if issue.category in stats["by_category"] else "chinh_ta"
            stats["by_category"][cat]["total"] += 1
            app_st = getattr(issue, "applied_status", issue.status)
            u_dec = getattr(issue, "user_decision", issue.status)

            if app_st == "applied":
                stats["by_category"][cat]["applied"] += 1
            elif app_st in ("skipped_conflict", "skipped_mismatch"):
                stats["by_category"][cat]["skipped"] += 1
            elif u_dec == "rejected" or app_st == "skipped_rejected":
                stats["by_category"][cat]["rejected"] += 1
            elif u_dec == "pending" or app_st == "skipped_pending":
                stats["by_category"][cat]["pending"] += 1

        return stats

    @classmethod
    def generate_markdown_report(
        cls,
        volume: Volume,
        issues: List[SpellIssue],
        stats: Dict[str, Any],
    ) -> str:
        """Tạo báo cáo chi tiết bằng định dạng Markdown với ký tự đặc biệt được escape an toàn."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_note = "HOÀN CHỈNH" if not volume.is_draft else f"BẢN NHÁP (THIẾU CHƯƠNG: {volume.missing_chapters})"

        md = []
        md.append("# BÁO CÁO HIỆU ĐÍNH VÀ KIỂM TRA CHÍNH TẢ")
        md.append(f"**Tác phẩm:** {escape_md(volume.story_title or 'Phàm Nhân Tu Tiên')}")
        md.append(f"**Tập:** {volume.volume_num} (Chương {volume.start_chapter} đến Chương {volume.end_chapter})")
        md.append(f"**Thời gian xuất:** {now_str}")
        md.append(f"**Trạng thái tập:** {status_note}")
        md.append("\n---\n")

        md.append("## 1. TỔNG QUAN VÀ THỐNG KÊ LỖI")
        md.append(f"- **Tổng số vị trí phát hiện / đề xuất:** **{stats['total_suggestions']}**")
        md.append(f"- **Số thay đổi đã áp dụng thực tế:** **{stats['applied']}**")
        md.append(f"- **Số thay đổi chờ duyệt (Pending):** **{stats['pending']}**")
        md.append(f"- **Số đề xuất bị từ chối (Rejected):** **{stats['rejected']}**")
        md.append(f"- **Số đề xuất không áp dụng được / xung đột (Skipped):** **{stats.get('skipped', 0)}**")
        md.append(f"- *Lưu ý:* Chuẩn hóa Unicode NFC không tính vào số lỗi chính tả.\n")

        md.append("### Bảng thống kê theo nhóm lỗi:")
        md.append("| Nhóm lỗi | Tổng số | Đã áp dụng | Chờ duyệt | Từ chối | Không áp dụng được |")
        md.append("| :--- | :---: | :---: | :---: | :---: | :---: |")

        for cat_key, label in cls.CATEGORY_LABELS.items():
            cat_data = stats["by_category"].get(
                cat_key, {"total": 0, "applied": 0, "pending": 0, "rejected": 0, "skipped": 0}
            )
            md.append(
                f"| {label} | {cat_data['total']} | {cat_data['applied']} | {cat_data['pending']} | "
                f"{cat_data['rejected']} | {cat_data.get('skipped', 0)} |"
            )

        md.append("\n---\n")
        md.append("## 2. DANH SÁCH CHI TIẾT TỪNG THAY ĐỔI")
        if not issues:
            md.append("*Không phát hiện lỗi hoặc không có đề xuất thay đổi nào.*")
        else:
            md.append(
                "| STT | Chương | Đoạn | Vị trí (Ký tự) | Nội dung gốc | Nội dung sửa | Nhóm lỗi | "
                "Lý do | Nguồn | Quyết định | Kết quả áp dụng |"
            )
            md.append("| :---: | :---: | :---: | :---: | :--- | :--- | :--- | :--- | :---: | :---: | :--- |")

            for idx, iss in enumerate(issues, 1):
                chap_name = f"Chương {iss.chapter_num}" if iss.chapter_num else "Chương ?"
                orig_disp = escape_md(repr(iss.original)[1:-1]) if iss.original else "(rỗng)"
                rep_disp = escape_md(repr(iss.replacement)[1:-1]) if iss.replacement else "(xóa)"
                cat_label = cls.CATEGORY_LABELS.get(iss.category, iss.category)
                reason_disp = escape_md(iss.reason)

                u_dec = getattr(iss, "user_decision", "approved" if iss.status == "applied" else iss.status)
                app_st = getattr(iss, "applied_status", iss.status)
                app_reason = getattr(iss, "applied_reason", "")

                dec_badge = "Đã duyệt" if u_dec == "approved" else ("Từ chối" if u_dec == "rejected" else "Chờ duyệt")
                if app_st == "applied":
                    result_badge = "Đã sửa thành công"
                elif app_st == "skipped_conflict":
                    result_badge = f"Bỏ qua (Xung đột: {escape_md(app_reason)})"
                elif app_st == "skipped_mismatch":
                    result_badge = f"Bỏ qua (Không khớp: {escape_md(app_reason)})"
                elif app_st == "skipped_rejected":
                    result_badge = "Bỏ qua (Người dùng từ chối)"
                else:
                    result_badge = "Chờ duyệt"

                md.append(
                    f"| {idx} | {chap_name} | Đoạn {iss.paragraph_idx} | {iss.char_start}-{iss.char_end} | "
                    f"`{orig_disp}` | `{rep_disp}` | {cat_label} | {reason_disp} | {iss.source} | "
                    f"{dec_badge} | {result_badge} |"
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
        edited_paragraphs_map: Optional[Dict[int, List[str]]] = None,
        overwrite: bool = False,
        export_reports: bool = False,
    ) -> Dict[str, str]:
        """
        Xuất tệp cho tập vào thư mục output_dir thông qua file tạm an toàn:
        - Mặc định (export_reports=False): Chỉ xuất duy nhất 1 file TXT hoàn chỉnh: Tap_{vol}_Chuong_{start}_den_{end}.txt
        - Nếu bật export_reports=True: Xuất trọn bộ 4 tệp (RAW TXT, EDITED TXT, REPORT MD, CHANGELOG JSON) để audit.
        """
        os.makedirs(output_dir, exist_ok=True)
        base_name = volume.filename_base

        if not export_reports:
            # CHỈ XUẤT DUY NHẤT 1 FILE TXT HOÀN CHỈNH (không tạo file rác .md, .json hay _RAW)
            final_txt_path = os.path.join(output_dir, f"{base_name}.txt")
            if os.path.exists(final_txt_path) and not overwrite:
                raise FileExistsError(
                    f"Tệp '{os.path.basename(final_txt_path)}' đã tồn tại. Vui lòng bật cờ 'Ghi đè' (overwrite) nếu muốn ghi đè."
                )

            final_tmp = final_txt_path + ".tmp"
            try:
                # Render bản TXT hoàn chỉnh (áp dụng các đoạn đã hiệu đính nếu có)
                final_text = merger.render_volume_text(
                    volume, use_edited=True, chapter_paragraphs_map=edited_paragraphs_map
                )
                with open(final_tmp, "w", encoding="utf-8", newline="\n") as f:
                    f.write(final_text)

                os.replace(final_tmp, final_txt_path)
                return {
                    "txt": final_txt_path,
                    "edited": final_txt_path,
                    "raw": final_txt_path,
                    "report": "",
                    "changelog": "",
                }
            except Exception as e:
                if os.path.exists(final_tmp):
                    try:
                        os.remove(final_tmp)
                    except Exception:
                        pass
                raise e

        # Nếu bật export_reports=True: xuất trọn bộ 4 tệp phục vụ audit
        raw_path = os.path.join(output_dir, f"{base_name}_RAW.txt")
        edited_path = os.path.join(output_dir, f"{base_name}_EDITED.txt")
        report_path = os.path.join(output_dir, f"{base_name}_REPORT.md")
        json_path = os.path.join(output_dir, f"{base_name}_CHANGELOG.json")

        # Kiểm tra ghi đè trước khi thực hiện
        for p in [raw_path, edited_path, report_path, json_path]:
            if os.path.exists(p) and not overwrite:
                raise FileExistsError(
                    f"Tệp '{os.path.basename(p)}' đã tồn tại. Vui lòng bật cờ 'Ghi đè' (overwrite) nếu muốn ghi đè."
                )

        # Đường dẫn file tạm thời (.tmp)
        raw_tmp = raw_path + ".tmp"
        edited_tmp = edited_path + ".tmp"
        report_tmp = report_path + ".tmp"
        json_tmp = json_path + ".tmp"
        temp_files = [raw_tmp, edited_tmp, report_tmp, json_tmp]

        try:
            # 1. Render RAW TXT (UTF-8, LF)
            raw_text = merger.render_volume_text(volume, use_edited=False)
            with open(raw_tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(raw_text)

            # 2. Render EDITED TXT (UTF-8, LF)
            edited_text = merger.render_volume_text(
                volume, use_edited=True, chapter_paragraphs_map=edited_paragraphs_map
            )
            with open(edited_tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(edited_text)

            # 3. Tính toán thống kê & xuất Báo cáo Markdown
            stats = cls.calculate_statistics(issues)
            report_md = cls.generate_markdown_report(volume, issues, stats)
            with open(report_tmp, "w", encoding="utf-8", newline="\n") as f:
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
            with open(json_tmp, "w", encoding="utf-8") as f:
                json.dump(audit_data, f, ensure_ascii=False, indent=2)

            # Hoàn tất an toàn: hoán đổi nguyên tử các file tạm thành file chính thức
            os.replace(raw_tmp, raw_path)
            os.replace(edited_tmp, edited_path)
            os.replace(report_tmp, report_path)
            os.replace(json_tmp, json_path)

            return {
                "txt": edited_path,
                "raw": raw_path,
                "edited": edited_path,
                "report": report_path,
                "changelog": json_path,
            }

        except Exception as e:
            # Dọn dẹp file tạm nếu xảy ra lỗi giữa chừng
            for tmp in temp_files:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
            raise e
