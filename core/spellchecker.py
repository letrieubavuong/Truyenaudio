"""
Rule-based Vietnamese Spell Checker and Text Normalizer.
Features:
- Unicode NFC normalization (not counted as spelling error)
- Removal of stray underscores, stars, duplicate punctuation, and spacing issues
- Custom dictionary with regex and context rules
- Protected terms preservation (characters, artifacts, sects, locations)
- Strict duplicate sentence detection
- Precise character offset tracking for audit trail and manual review
"""
import re
import json
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
        try:
            with open(self.dictionary_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.dictionary_map = data.get("replacements", {})
                self.context_rules = data.get("context_rules", [])
        except Exception:
            self.dictionary_map = {}
            self.context_rules = []

        try:
            with open(self.protected_terms_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.protected_terms = data.get("terms", [])
        except Exception:
            self.protected_terms = []

    def check_paragraph(
        self,
        paragraph: str,
        paragraph_idx: int = 0,
        chapter_num: Optional[int] = None,
        chapter_title: str = "",
    ) -> Tuple[str, List[SpellIssue]]:
        """
        Kiểm tra và sửa lỗi một đoạn văn:
        Ghi nhận các issue và sinh văn bản đã sửa.
        """
        norm_para = unicodedata.normalize("NFC", paragraph)
        issues: List[SpellIssue] = []

        # Danh sách vùng bảo vệ
        protected_spans: List[Tuple[int, int]] = []
        for term in self.protected_terms:
            if not term:
                continue
            for m in re.finditer(re.escape(term), norm_para):
                protected_spans.append((m.start(), m.end()))

        def is_in_protected(start: int, end: int) -> bool:
            for p_start, p_end in protected_spans:
                if max(start, p_start) < min(end, p_end):
                    return True
            return False

        # --- A. DỌN GẠCH DƯỚI THỪA & KÝ TỰ RÁC ---
        # Bắt tất cả các chuỗi gạch dưới lặp hoặc đơn lẻ (ví dụ: _ hoặc _ _ _ _ hoặc dính sát ")
        for m in re.finditer(r"_+(?:\s*_+)*", norm_para):
            start, end = m.start(), m.end()
            orig = norm_para[start:end]
            if not is_in_protected(start, end):
                issues.append(
                    SpellIssue(
                        chapter_num=chapter_num,
                        chapter_title=chapter_title,
                        paragraph_idx=paragraph_idx,
                        char_start=start,
                        char_end=end,
                        original=orig,
                        replacement="",
                        category="gach_duoi_thua",
                        reason="Loại bỏ dấu gạch dưới thừa",
                        source="rule",
                        status="applied",
                    )
                )

        # 3. Dấu sao thừa sau chữ
        for m in re.finditer(r"([a-zA-ZÀ-ỹ0-9])\*(?!\*)", norm_para):
            start = m.start(1)
            end = m.end()
            orig = norm_para[start:end]
            rep = m.group(1)
            if not is_in_protected(start, end):
                issues.append(
                    SpellIssue(
                        chapter_num=chapter_num,
                        chapter_title=chapter_title,
                        paragraph_idx=paragraph_idx,
                        char_start=start,
                        char_end=end,
                        original=orig,
                        replacement=rep,
                        category="dau_cau",
                        reason="Loại bỏ dấu hoa thị (*) thừa dính sau từ",
                        source="rule",
                        status="applied",
                    )
                )

        # --- B. KHOẢNG TRẮNG VÀ DẤU CÂU ---
        # 1. Khoảng trắng trước dấu câu: " ," hoặc " ."
        for m in re.finditer(r"\s+([.,!?:;])", norm_para):
            start, end = m.start(), m.end()
            orig = norm_para[start:end]
            rep = m.group(1)
            if not is_in_protected(start, end):
                issues.append(
                    SpellIssue(
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

        # 2. Dấu câu dính liền chữ tiếp theo không có khoảng trắng: ".Từ" hoặc ",nói"
        for m in re.finditer(r"([.,!?:;])([a-zA-ZÀ-ỹ])", norm_para):
            start, end = m.start(), m.end()
            orig = norm_para[start:end]
            rep = f"{m.group(1)} {m.group(2)}"
            if not is_in_protected(start, end):
                issues.append(
                    SpellIssue(
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

        # 3. Dấu ngoặc đơn có khoảng trắng thừa
        for m in re.finditer(r"\(\s+([a-zA-ZÀ-ỹ0-9])", norm_para):
            start, end = m.start(), m.end()
            orig = norm_para[start:end]
            rep = f"({m.group(1)}"
            issues.append(
                SpellIssue(
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
            issues.append(
                SpellIssue(
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

        # 4. Nhiều dấu cách liên tiếp
        for m in re.finditer(r"[^\S\r\n]{2,}", norm_para):
            start, end = m.start(), m.end()
            orig = norm_para[start:end]
            issues.append(
                SpellIssue(
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

                    issues.append(
                        SpellIssue(
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
                    issues.append(
                        SpellIssue(
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

        # --- D. PHÁT HIỆN CÂU TRÙNG NGUYÊN VĂN ---
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
                                    chapter_num=chapter_num,
                                    chapter_title=chapter_title,
                                    paragraph_idx=paragraph_idx,
                                    char_start=start,
                                    char_end=end,
                                    original=norm_para[start:end],
                                    replacement="",
                                    category="lap_cau",
                                    reason="Xóa câu trùng lặp nguyên văn liền kề",
                                    source="rule",
                                    status="applied",
                                )
                            )

        # Giải quyết chồng lấn
        non_overlapping_issues = self._resolve_overlapping_issues(issues)

        # Áp dụng
        edited_para = self.apply_fixes(norm_para, non_overlapping_issues, approved_only=True)
        # Làm sạch khoảng trắng thừa cuối cùng
        edited_para = re.sub(r"\s+", " ", edited_para).strip()
        edited_para = re.sub(r'\s+([.,!?:;])', r'\1', edited_para)
        edited_para = re.sub(r'([.,!?:;])([a-zA-ZÀ-ỹ])', r'\1 \2', edited_para)

        return edited_para, non_overlapping_issues

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

    @staticmethod
    def _resolve_overlapping_issues(issues: List[SpellIssue]) -> List[SpellIssue]:
        """Lọc bỏ các issue chồng lấn."""
        if not issues:
            return []

        sorted_issues = sorted(issues, key=lambda x: (x.char_start, -(x.char_end - x.char_start)))
        resolved: List[SpellIssue] = []

        last_end = -1
        for issue in sorted_issues:
            if issue.char_start >= last_end:
                resolved.append(issue)
                last_end = issue.char_end

        return resolved

    @staticmethod
    def apply_fixes(
        original_text: str, issues: List[SpellIssue], approved_only: bool = True
    ) -> str:
        """Áp dụng các thay đổi từ cuối lên đầu."""
        if not issues:
            return original_text

        valid_issues = [
            i for i in issues if (not approved_only or i.status == "applied")
        ]
        valid_issues = sorted(valid_issues, key=lambda x: x.char_start, reverse=True)

        res = original_text
        for issue in valid_issues:
            start = issue.char_start
            end = issue.char_end
            if 0 <= start <= end <= len(res):
                res = res[:start] + issue.replacement + res[end:]

        return res.strip()
