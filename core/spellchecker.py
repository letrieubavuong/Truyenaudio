"""
Rule-based Vietnamese Spell Checker and Text Normalizer.
Features:
- Unicode NFC normalization (not counted as spelling error)
- Removal of stray underscores and spacing issues without damaging masked words
- Custom dictionary with regex and context rules
- Protected terms preservation (characters, artifacts, sects, locations)
- Strict duplicate sentence detection (marked as pending review by default)
- Precise character offset tracking for changelog audit trail and manual review
- Guaranteed exact idempotence: EDITED text is 100% reproducible from RAW text + changelog
"""
import re
import json
import hashlib
import unicodedata
from typing import List, Dict, Tuple, Optional
from core.models import SpellIssue


class VietnameseSpellChecker:
    def __init__(
        self,
        dictionary_path: str = "resources/default_dictionary.json",
        protected_terms_path: str = "resources/protected_terms.json",
    ):
        self.dictionary_path = dictionary_path
        self.protected_terms_path = protected_terms_path
        self.dictionary_map: Dict[str, str] = {}
        self.context_rules: List[Dict[str, str]] = []
        self.protected_terms: List[str] = []
        self.load_resources()

    def load_resources(self):
        """Tải từ điển và danh sách từ ngữ được bảo vệ từ các tệp JSON."""
        from core.utils import get_resource_path
        dict_real_path = get_resource_path(self.dictionary_path)
        try:
            with open(dict_real_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                raw_map = data.get("replacements", {})
                # Lọc bỏ các cặp từ không thay đổi nội dung (original == replacement)
                self.dictionary_map = {
                    k: v
                    for k, v in raw_map.items()
                    if k.strip().lower() != v.strip().lower()
                }
                self.context_rules = data.get("context_rules", [])
        except Exception:
            self.dictionary_map = {}
            self.context_rules = []

        terms_real_path = get_resource_path(self.protected_terms_path)
        try:
            with open(terms_real_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.protected_terms = data.get("terms", [])
        except Exception:
            self.protected_terms = []

    def set_protected_terms_path(self, protected_terms_path: str):
        """Cập nhật đường dẫn tệp thuật ngữ bảo vệ theo từng truyện và nạp lại."""
        self.protected_terms_path = protected_terms_path
        self.load_resources()

    def check_paragraph(
        self,
        paragraph: str,
        paragraph_idx: int = 0,
        chapter_num: Optional[int] = None,
        chapter_title: str = "",
    ) -> Tuple[str, List[SpellIssue]]:
        """
        Kiểm tra và sinh các đề xuất sửa lỗi cho một đoạn văn:
        Ghi nhận chính xác vị trí char_start, char_end và băm SHA-256 bản gốc.
        Mọi thay đổi đều được ghi lại trong danh sách issue, không sửa lén bằng regex bên ngoài.
        """
        norm_para = unicodedata.normalize("NFC", paragraph)
        para_hash = hashlib.sha256(norm_para.encode("utf-8")).hexdigest()[:16]
        issues: List[SpellIssue] = []

        # Danh sách vùng bảo vệ
        protected_spans: List[Tuple[int, int]] = []
        for term in self.protected_terms:
            if not term:
                continue
            for m in re.finditer(re.escape(term), norm_para):
                protected_spans.append((m.start(), m.end()))

        # BẢO VỆ TỪ BỊ CHE DẤU SAO: ví dụ c*m, v**, đ**, ***
        # Các từ chứa ký tự * nằm trong từ hoặc tạo thành từ bị che không bao giờ bị xóa dấu *
        masked_pat = r"(?<!\S)[a-zA-ZÀ-ỹ0-9]*\*+[a-zA-ZÀ-ỹ0-9*]*(?!\S)|\b[a-zA-ZÀ-ỹ0-9]+\*+[a-zA-ZÀ-ỹ0-9]+\b|\b[a-zA-ZÀ-ỹ0-9]{1,2}\*+"
        for m in re.finditer(masked_pat, norm_para):
            protected_spans.append((m.start(), m.end()))

        def is_in_protected(start: int, end: int) -> bool:
            for p_start, p_end in protected_spans:
                if max(start, p_start) < min(end, p_end):
                    return True
            return False

        # --- A. DỌN GẠCH DƯỚI THỪA & KÝ TỰ RÁC ---
        for m in re.finditer(r"(\s*)_+(?:\s*_+)*(\s*)", norm_para):
            start, end = m.start(), m.end()
            orig = norm_para[start:end]
            if is_in_protected(start, end) or not orig:
                continue

            has_leading = bool(m.group(1))
            has_trailing = bool(m.group(2))
            if has_leading and has_trailing:
                rep = " "
            elif has_leading and not has_trailing:
                rep = " "
            else:
                rep = ""

            if orig != rep:
                issues.append(
                    SpellIssue(
                        id=f"iss_c{chapter_num}_p{paragraph_idx}_{start}_{end}_undr",
                        original_hash=para_hash,
                        chapter_num=chapter_num,
                        chapter_title=chapter_title,
                        paragraph_idx=paragraph_idx,
                        char_start=start,
                        char_end=end,
                        original=orig,
                        replacement=rep,
                        category="gach_duoi_thua",
                        reason="Loại bỏ dấu gạch dưới thừa và chuẩn hóa khoảng trắng",
                        source="rule",
                        status="applied",
                    )
                )

        # Dấu sao ở cuối từ ngoài vùng được bảo vệ (nghi ngờ chú thích / footnote):
        # Mặc định chuyển sang chờ duyệt (pending), không tự xóa.
        for m in re.finditer(r"([a-zA-ZÀ-ỹ0-9])\*+(?=\s|[.,!?:;]|$)", norm_para):
            start, end = m.start(1), m.end()
            orig = norm_para[start:end]
            rep = m.group(1)
            if not is_in_protected(start, end) and orig != rep:
                issues.append(
                    SpellIssue(
                        id=f"iss_c{chapter_num}_p{paragraph_idx}_{start}_{end}_star",
                        original_hash=para_hash,
                        chapter_num=chapter_num,
                        chapter_title=chapter_title,
                        paragraph_idx=paragraph_idx,
                        char_start=start,
                        char_end=end,
                        original=orig,
                        replacement=rep,
                        category="dau_cau",
                        reason="Dấu hoa thị sau từ (nghi chú thích hoặc ký tự thừa, chờ duyệt)",
                        source="rule",
                        status="pending",
                    )
                )

        # --- B. KHOẢNG TRẮNG VÀ DẤU CÂU ---
        # 1. Khoảng trắng trước dấu câu VÀ thiếu khoảng trắng sau (ví dụ: " ,là" -> ", là")
        for m in re.finditer(r"\s+([.,!?:;])(?=[a-zA-ZÀ-ỹ0-9])", norm_para):
            start, end = m.start(), m.end()
            orig = norm_para[start:end]
            rep = f"{m.group(1)} "
            if not is_in_protected(start, end) and orig != rep:
                issues.append(
                    SpellIssue(
                        id=f"iss_c{chapter_num}_p{paragraph_idx}_{start}_{end}_pnc1",
                        original_hash=para_hash,
                        chapter_num=chapter_num,
                        chapter_title=chapter_title,
                        paragraph_idx=paragraph_idx,
                        char_start=start,
                        char_end=end,
                        original=orig,
                        replacement=rep,
                        category="dau_cau",
                        reason="Chuẩn hóa khoảng trắng trước và sau dấu câu",
                        source="rule",
                        status="applied",
                    )
                )

        # 2. Khoảng trắng trước dấu câu khi đã có khoảng trắng/kết thúc sau (ví dụ: " ," hoặc " .")
        for m in re.finditer(r"\s+([.,!?:;])(?=\s|$)", norm_para):
            start, end = m.start(), m.end()
            orig = norm_para[start:end]
            rep = m.group(1)
            if not is_in_protected(start, end) and orig != rep:
                issues.append(
                    SpellIssue(
                        id=f"iss_c{chapter_num}_p{paragraph_idx}_{start}_{end}_spcp",
                        original_hash=para_hash,
                        chapter_num=chapter_num,
                        chapter_title=chapter_title,
                        paragraph_idx=paragraph_idx,
                        char_start=start,
                        char_end=end,
                        original=orig,
                        replacement=rep,
                        category="khoang_trang",
                        reason="Xóa khoảng trắng thừa trước dấu câu",
                        source="rule",
                        status="applied",
                    )
                )

        # 3. Dấu câu dính liền chữ tiếp theo không có khoảng trắng (ví dụ: ",nói", ".Từ", nhưng bỏ qua số như 3.14)
        for m in re.finditer(r"(?<!\s)([.,!?:;])(?=[a-zA-ZÀ-ỹ])", norm_para):
            start, end = m.start(), m.end()
            orig = norm_para[start:end]
            rep = f"{m.group(1)} "
            if not is_in_protected(start, end) and orig != rep:
                issues.append(
                    SpellIssue(
                        id=f"iss_c{chapter_num}_p{paragraph_idx}_{start}_{end}_pnc2",
                        original_hash=para_hash,
                        chapter_num=chapter_num,
                        chapter_title=chapter_title,
                        paragraph_idx=paragraph_idx,
                        char_start=start,
                        char_end=end,
                        original=orig,
                        replacement=rep,
                        category="dau_cau",
                        reason="Thêm khoảng trắng sau dấu câu",
                        source="rule",
                        status="applied",
                    )
                )

        # 4. Khoảng trắng thừa bên trong dấu ngoặc đơn
        for m in re.finditer(r"\(\s+([a-zA-ZÀ-ỹ0-9])", norm_para):
            start, end = m.start(), m.end()
            orig = norm_para[start:end]
            rep = f"({m.group(1)}"
            if orig != rep:
                issues.append(
                    SpellIssue(
                        id=f"iss_c{chapter_num}_p{paragraph_idx}_{start}_{end}_brk1",
                        original_hash=para_hash,
                        chapter_num=chapter_num,
                        chapter_title=chapter_title,
                        paragraph_idx=paragraph_idx,
                        char_start=start,
                        char_end=end,
                        original=orig,
                        replacement=rep,
                        category="khoang_trang",
                        reason="Xóa khoảng trắng sau mở ngoặc đơn",
                        source="rule",
                        status="applied",
                    )
                )

        for m in re.finditer(r"([a-zA-ZÀ-ỹ0-9])\s+\)", norm_para):
            start, end = m.start(), m.end()
            orig = norm_para[start:end]
            rep = f"{m.group(1)})"
            if orig != rep:
                issues.append(
                    SpellIssue(
                        id=f"iss_c{chapter_num}_p{paragraph_idx}_{start}_{end}_brk2",
                        original_hash=para_hash,
                        chapter_num=chapter_num,
                        chapter_title=chapter_title,
                        paragraph_idx=paragraph_idx,
                        char_start=start,
                        char_end=end,
                        original=orig,
                        replacement=rep,
                        category="khoang_trang",
                        reason="Xóa khoảng trắng trước đóng ngoặc đơn",
                        source="rule",
                        status="applied",
                    )
                )

        # 5. Nhiều dấu cách liên tiếp
        for m in re.finditer(r"[^\S\r\n]{2,}", norm_para):
            start, end = m.start(), m.end()
            orig = norm_para[start:end]
            if orig != " ":
                issues.append(
                    SpellIssue(
                        id=f"iss_c{chapter_num}_p{paragraph_idx}_{start}_{end}_multispc",
                        original_hash=para_hash,
                        chapter_num=chapter_num,
                        chapter_title=chapter_title,
                        paragraph_idx=paragraph_idx,
                        char_start=start,
                        char_end=end,
                        original=orig,
                        replacement=" ",
                        category="khoang_trang",
                        reason="Thu gọn nhiều khoảng trắng liên tiếp",
                        source="rule",
                        status="applied",
                    )
                )

        # --- C. TỪ ĐIỂN VÀ QUY TẮC NGỮ CẢNH ---
        for wrong, correct in self.dictionary_map.items():
            if not wrong or not correct or wrong.strip().lower() == correct.strip().lower():
                continue
            pattern = rf"(?<!\w){re.escape(wrong)}(?!\w)"
            for m in re.finditer(pattern, norm_para, re.IGNORECASE):
                start, end = m.start(), m.end()
                orig = norm_para[start:end]
                if not is_in_protected(start, end):
                    rep = correct
                    if orig.isupper():
                        rep = correct.upper()
                    elif orig and orig[0].isupper():
                        rep = correct.capitalize()

                    if orig != rep:
                        issues.append(
                            SpellIssue(
                                id=f"iss_c{chapter_num}_p{paragraph_idx}_{start}_{end}_dict",
                                original_hash=para_hash,
                                chapter_num=chapter_num,
                                chapter_title=chapter_title,
                                paragraph_idx=paragraph_idx,
                                char_start=start,
                                char_end=end,
                                original=orig,
                                replacement=rep,
                                category="chinh_ta",
                                reason=f"Sửa lỗi từ điển: '{wrong}' -> '{correct}'",
                                source="dictionary",
                                status="applied",
                            )
                        )

        for rule in self.context_rules:
            pat = rule.get("pattern", "")
            rep_tpl = rule.get("replacement", "")
            reason = rule.get("reason", "Sửa theo quy tắc ngữ cảnh")
            cat = rule.get("category", "chinh_ta")
            if not pat:
                continue
            for m in re.finditer(pat, norm_para, re.IGNORECASE):
                start, end = m.start(), m.end()
                orig = norm_para[start:end]
                if not is_in_protected(start, end):
                    rep = m.expand(rep_tpl)
                    if orig != rep:
                        issues.append(
                            SpellIssue(
                                id=f"iss_c{chapter_num}_p{paragraph_idx}_{start}_{end}_ctx",
                                original_hash=para_hash,
                                chapter_num=chapter_num,
                                chapter_title=chapter_title,
                                paragraph_idx=paragraph_idx,
                                char_start=start,
                                char_end=end,
                                original=orig,
                                replacement=rep,
                                category=cat,
                                reason=reason,
                                source="rule",
                                status="applied",
                            )
                        )

        # --- D. PHÁT HIỆN CÂU TRÙNG NGUYÊN VĂN (MẶC ĐỊNH CHỜ DUYỆT - PENDING) ---
        sentences = re.split(r"(?<=[.!?])\s+", norm_para)
        if len(sentences) > 1:
            for i in range(len(sentences) - 1):
                s1 = sentences[i].strip()
                s2 = sentences[i + 1].strip()
                if s1 and s2 and len(s1) > 15 and s1 == s2:
                    pos_s1 = norm_para.find(s1)
                    if pos_s1 != -1:
                        pos_s2 = norm_para.find(s2, pos_s1 + len(s1))
                        if pos_s2 != -1:
                            start = pos_s2
                            end = pos_s2 + len(s2)
                            if start > 0 and norm_para[start - 1] == " ":
                                start -= 1
                            issues.append(
                                SpellIssue(
                                    id=f"iss_c{chapter_num}_p{paragraph_idx}_{start}_{end}_dup",
                                    original_hash=para_hash,
                                    chapter_num=chapter_num,
                                    chapter_title=chapter_title,
                                    paragraph_idx=paragraph_idx,
                                    char_start=start,
                                    char_end=end,
                                    original=norm_para[start:end],
                                    replacement="",
                                    category="lap_cau",
                                    reason="Đề xuất xóa câu trùng lặp nguyên văn liền kề (chờ duyệt)",
                                    source="rule",
                                    status="pending",
                                )
                            )

        # Lọc bỏ các issue vô nghĩa (orig == rep)
        valid_candidates = [
            i for i in issues if i.original != i.replacement and i.char_start < i.char_end
        ]
        # Áp dụng và giải quyết xung đột bằng apply_fixes_with_audit
        edited_para, resolved_issues = self.apply_fixes_with_audit(
            norm_para, valid_candidates, approved_only=True
        )

        return edited_para, resolved_issues

    def check_chapter(
        self,
        chapter_paragraphs: List[str],
        chapter_num: Optional[int] = None,
        chapter_title: str = "",
    ) -> Tuple[List[str], List[SpellIssue]]:
        """Kiểm tra toàn bộ các đoạn văn trong một chương."""
        all_issues: List[SpellIssue] = []
        edited_paragraphs: List[str] = []

        for idx, p in enumerate(chapter_paragraphs):
            edited_p, p_issues = self.check_paragraph(
                p, paragraph_idx=idx, chapter_num=chapter_num, chapter_title=chapter_title
            )
            edited_paragraphs.append(edited_p)
            all_issues.extend(p_issues)

        return edited_paragraphs, all_issues

    @classmethod
    def _resolve_overlapping_issues(cls, issues: List[SpellIssue]) -> List[SpellIssue]:
        """Lọc bỏ các issue chồng lấn một cách an toàn (ưu tiên dictionary > rule > ai)."""
        if not issues:
            return []

        source_priority = {"dictionary": 3, "rule": 2, "ai": 1}

        def sort_key(item: SpellIssue):
            s_prio = source_priority.get(item.source.lower(), 0)
            conf = item.confidence if item.confidence is not None else 0.0
            span_len = item.char_end - item.char_start
            return (s_prio, conf, span_len, -item.char_start)

        sorted_issues = sorted(issues, key=sort_key, reverse=True)
        resolved: List[SpellIssue] = []

        for cand in sorted_issues:
            conflict = False
            for acc in resolved:
                if max(cand.char_start, acc.char_start) < min(cand.char_end, acc.char_end):
                    conflict = True
                    break
            if not conflict:
                resolved.append(cand)

        return sorted(resolved, key=lambda x: (x.char_start, x.char_end))

    @classmethod
    def apply_fixes_with_audit(
        cls, original_text: str, issues: List[SpellIssue], approved_only: bool = True
    ) -> Tuple[str, List[SpellIssue]]:
        """
        Áp dụng các đề xuất sửa đổi và trả về:
        (chuỗi_sau_khi_sửa, danh_sách_issue_kèm_kết_quả_áp_dụng_và_nguyên_nhân).

        Yêu cầu kỹ thuật:
        - Xử lý nhất quán Unicode NFC trên cả bản gốc và nội dung đề xuất.
        - Kiểm tra original_hash (nếu có): hash không khớp -> skipped_mismatch.
        - Kiểm tra bounds [char_start:char_end] và lát cắt thực tế: không khớp -> skipped_mismatch.
        - Phân xử xung đột chồng lấn theo thứ tự ưu tiên: dictionary > rule > ai.
        - Đề xuất bị chồng lấn -> skipped_conflict kèm thông tin đề xuất ưu tiên hơn.
        - Đề xuất bị từ chối (user_decision == 'rejected') -> skipped_rejected.
        - Đề xuất chờ duyệt khi approved_only=True -> skipped_pending.
        - Đề xuất thỏa mãn: áp dụng từ cuối lên đầu (tránh lệch offset) -> applied.
        """
        if not issues:
            return unicodedata.normalize("NFC", original_text), []

        # 1. Chuẩn hóa NFC bản gốc
        text_nfc = unicodedata.normalize("NFC", original_text)
        current_hash = hashlib.sha256(text_nfc.encode("utf-8")).hexdigest()[:16]

        # 2. Phân loại theo quyết định của người dùng và tính hợp lệ ban đầu
        candidates_to_apply: List[SpellIssue] = []

        for iss in issues:
            if iss.status == "applied":
                u_dec = "approved"
            elif iss.status == "rejected":
                u_dec = "rejected"
            elif iss.status == "pending":
                u_dec = "pending"
            else:
                u_dec = getattr(iss, "user_decision", "approved")
            iss.user_decision = u_dec

            # Nếu người dùng từ chối
            if u_dec == "rejected":
                iss.applied_status = "skipped_rejected"
                iss.applied_reason = "Người dùng từ chối đề xuất"
                iss.status = "rejected"
                continue

            # Nếu đang chờ duyệt và chỉ áp dụng đề xuất đã duyệt
            if approved_only and u_dec == "pending":
                iss.applied_status = "skipped_pending"
                iss.applied_reason = "Đề xuất đang chờ người dùng duyệt"
                iss.status = "pending"
                continue

            # Chuẩn hóa NFC cho original & replacement của issue
            orig_nfc = unicodedata.normalize("NFC", iss.original)
            iss.original = orig_nfc
            iss.replacement = unicodedata.normalize("NFC", iss.replacement)

            # Kiểm tra hash nếu issue có lưu original_hash
            if iss.original_hash and iss.original_hash != current_hash:
                iss.applied_status = "skipped_mismatch"
                iss.applied_reason = f"Hash nội dung không khớp (gốc: {iss.original_hash}, hiện tại: {current_hash})"
                iss.status = "skipped_mismatch"
                continue

            # Kiểm tra giới hạn vị trí
            if not (0 <= iss.char_start <= iss.char_end <= len(text_nfc)):
                iss.applied_status = "skipped_mismatch"
                iss.applied_reason = f"Vị trí [{iss.char_start}:{iss.char_end}] ngoài độ dài văn bản ({len(text_nfc)})"
                iss.status = "skipped_mismatch"
                continue

            # Kiểm tra lát cắt văn bản thực tế
            actual_slice = text_nfc[iss.char_start:iss.char_end]
            if actual_slice != orig_nfc:
                iss.applied_status = "skipped_mismatch"
                iss.applied_reason = f"Nội dung tại [{iss.char_start}:{iss.char_end}] ('{actual_slice}') không khớp với '{orig_nfc}'"
                iss.status = "skipped_mismatch"
                continue

            candidates_to_apply.append(iss)

        # 3. Phân xử xung đột giữa các ứng viên được duyệt
        # Thứ tự ưu tiên nguồn: dictionary (3) > rule (2) > ai (1)
        source_priority = {"dictionary": 3, "rule": 2, "ai": 1}

        def sort_key(item: SpellIssue):
            s_prio = source_priority.get(item.source.lower(), 0)
            conf = item.confidence if item.confidence is not None else 0.0
            span_len = item.char_end - item.char_start
            return (s_prio, conf, span_len, -item.char_start)

        sorted_candidates = sorted(candidates_to_apply, key=sort_key, reverse=True)
        accepted_issues: List[SpellIssue] = []

        for cand in sorted_candidates:
            # Kiểm tra xem có chồng lấn với issue nào đã được chấp nhận trước đó không
            conflict_with: Optional[SpellIssue] = None
            for acc in accepted_issues:
                if max(cand.char_start, acc.char_start) < min(cand.char_end, acc.char_end):
                    conflict_with = acc
                    break

            if conflict_with:
                cand.applied_status = "skipped_conflict"
                cand.applied_reason = (
                    f"Xung đột vùng [{cand.char_start}:{cand.char_end}] với đề xuất ưu tiên hơn "
                    f"({conflict_with.source}: '{conflict_with.original}' -> '{conflict_with.replacement}')"
                )
                cand.status = "skipped_conflict"
            else:
                accepted_issues.append(cand)

        # 4. Áp dụng các thay đổi từ cuối lên đầu
        accepted_sorted = sorted(accepted_issues, key=lambda x: (x.char_start, x.char_end), reverse=True)
        last_applied_start = len(text_nfc) + 1

        for iss in accepted_sorted:
            start = iss.char_start
            end = iss.char_end
            if end > last_applied_start:
                iss.applied_status = "skipped_conflict"
                iss.applied_reason = "Xung đột vùng áp dụng với thay đổi khác"
                iss.status = "skipped_conflict"
                continue

            text_nfc = text_nfc[:start] + iss.replacement + text_nfc[end:]
            last_applied_start = start
            iss.applied_status = "applied"
            iss.applied_reason = "Đã áp dụng thành công"
            iss.status = "applied"

        return text_nfc, issues

    @classmethod
    def apply_fixes(
        cls, original_text: str, issues: List[SpellIssue], approved_only: bool = True
    ) -> str:
        """
        Áp dụng các thay đổi từ cuối lên đầu và trả về văn bản đã sửa.
        Đồng bộ hoàn toàn với apply_fixes_with_audit.
        """
        edited_text, _ = cls.apply_fixes_with_audit(original_text, issues, approved_only=approved_only)
        return edited_text
