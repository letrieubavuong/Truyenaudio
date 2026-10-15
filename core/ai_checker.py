"""
AI-assisted Vietnamese Spell Checker with Paragraph Identification and Integrity Verification.
Supports OpenAI-compatible endpoints and Google Gemini API.
Adheres strictly to the guidelines:
- Never rewrites, summarizes, changes speakers or facts
- Chunks have unique identifiers (chunk_id, p_idx) with both paragraph count and character limits
- All AI suggestions default to 'pending' review (never auto-applied)
- Validates that AI suggestions strictly match original text
- Never exposes API keys in logs, git, or error messages
"""
import json
import os
import re
import hashlib
from typing import List, Dict, Any, Optional, Tuple
from core.models import SpellIssue


class AIChecker:
    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = "",
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        protected_terms: Optional[List[str]] = None,
    ):
        self.provider = provider
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model
        self.base_url = base_url
        self.protected_terms = protected_terms or []

    def set_protected_terms(self, terms: List[str]):
        self.protected_terms = terms

    def prepare_chunks(
        self,
        paragraphs: List[str],
        max_paragraphs_per_chunk: int = 5,
        max_chars_per_chunk: int = 2000,
    ) -> List[Dict[str, Any]]:
        """
        Chia các đoạn văn thành từng chunk có mã định danh rõ ràng,
        giới hạn đồng thời cả số đoạn văn và tổng số ký tự.
        """
        chunks = []
        current_items = []
        current_chars = 0
        chunk_counter = 1

        for p_idx, text in enumerate(paragraphs):
            p_len = len(text)
            if current_items and (
                len(current_items) >= max_paragraphs_per_chunk
                or current_chars + p_len > max_chars_per_chunk
            ):
                chunks.append({
                    "chunk_id": f"chunk_{chunk_counter}",
                    "start_idx": current_items[0]["p_idx"],
                    "end_idx": current_items[-1]["p_idx"],
                    "items": current_items,
                })
                chunk_counter += 1
                current_items = []
                current_chars = 0

            current_items.append({"p_idx": p_idx, "text": text})
            current_chars += p_len

        if current_items:
            chunks.append({
                "chunk_id": f"chunk_{chunk_counter}",
                "start_idx": current_items[0]["p_idx"],
                "end_idx": current_items[-1]["p_idx"],
                "items": current_items,
            })

        return chunks

    def build_system_prompt(self) -> str:
        return (
            "Bạn là trợ lý hiệu đính và phát hiện lỗi chính tả tiếng Việt chuyên nghiệp cho tiểu thuyết dịch/convert.\n"
            "Nhiệm vụ: Tìm các từ/cụm từ sai chính tả, sai dấu câu, hoặc dùng sai từ trong các đoạn văn được cung cấp.\n"
            "NGHIÊM CẤM:\n"
            "1. KHÔNG tóm tắt, KHÔNG đổi tình tiết, KHÔNG đổi người nói, KHÔNG viết lại toàn bộ câu/đoạn văn.\n"
            "2. KHÔNG tự ý suy diễn hoặc phục hồi các từ bị che bằng dấu '*'.\n"
            "3. KHÔNG thay đổi các từ đa nghĩa (như 'cổ/cỗ', 'nửa/nữa', 'dấu/giấu') nếu chưa chắc chắn 100% ngữ cảnh.\n"
            "4. KHÔNG chạm vào tên riêng, địa danh, tên môn phái, tên pháp bảo.\n"
            "ĐỊNH DẠNG TRẢ VỀ: BẮT BUỘC trả về duy nhất một mảng JSON các đề xuất sửa theo cấu trúc sau:\n"
            "[\n"
            "  {\n"
            '    "p_idx": 0,\n'
            '    "original": "nguời",\n'
            '    "replacement": "người",\n'
            '    "category": "chinh_ta",\n'
            '    "reason": "Lỗi gõ phím telex",\n'
            '    "confidence": 0.99\n'
            "  }\n"
            "]\n"
            "Nếu không có lỗi nào cần sửa, trả về: []"
        )

    def check_chunk(
        self,
        chunk: Dict[str, Any],
        chapter_num: Optional[int] = None,
        chapter_title: str = "",
    ) -> Tuple[List[SpellIssue], Optional[str]]:
        """
        Gửi một chunk đến AI và chuyển đổi phản hồi thành danh sách SpellIssue đã kiểm tra tính toàn vẹn.
        Mọi đề xuất đều ở trạng thái 'pending' chờ người dùng duyệt.
        """
        if not self.api_key:
            return [], "Chưa cấu hình API Key cho nhà cung cấp AI."

        user_content = json.dumps(chunk["items"], ensure_ascii=False, indent=2)
        system_prompt = self.build_system_prompt()

        try:
            raw_response = self._call_provider(system_prompt, user_content)
            issues = self._parse_and_verify_response(
                raw_response, chunk, chapter_num, chapter_title
            )
            return issues, None
        except Exception as e:
            sanitized_err = self._sanitize_error(str(e))
            return [], f"Lỗi gọi API AI ({self.provider}): {sanitized_err}"

    def _sanitize_error(self, err_msg: str) -> str:
        if self.api_key and self.api_key in err_msg:
            return err_msg.replace(self.api_key, "[REDACTED_KEY]")
        return err_msg

    def _call_provider(self, system_prompt: str, user_content: str) -> str:
        """Thực hiện request HTTP tới OpenAI-compatible API hoặc Google GenAI."""
        import requests

        if self.provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
            headers = {
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
            }
            payload = {
                "contents": [{"parts": [{"text": f"{system_prompt}\n\nDữ liệu:\n{user_content}"}]}]
            }
            r = requests.post(url, headers=headers, json=payload, timeout=30)
            r.raise_for_status()
            data = r.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return "[]"
            return candidates[0]["content"]["parts"][0]["text"]
        else:
            url = f"{self.base_url.rstrip('/')}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.1,
            }
            r = requests.post(url, headers=headers, json=payload, timeout=40)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]

    def _parse_and_verify_response(
        self,
        raw_response: str,
        chunk: Dict[str, Any],
        chapter_num: Optional[int],
        chapter_title: str,
    ) -> List[SpellIssue]:
        """
        Trích xuất JSON từ phản hồi và kiểm tra tính toàn vẹn:
        - Schema và kiểu dữ liệu
        - original phải khớp chính xác trong văn bản gốc
        - Vị trí không được mơ hồ
        - Bỏ qua các đề xuất chạm vào tên riêng được bảo vệ
        - Toàn bộ đề xuất AI mặc định ở trạng thái 'pending'
        """
        json_str = raw_response.strip()
        match = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", json_str)
        if match:
            json_str = match.group(1)
        else:
            m2 = re.search(r"\[[\s\S]*\]", json_str)
            if m2:
                json_str = m2.group(0)

        try:
            data = json.loads(json_str)
        except Exception:
            return []

        if not isinstance(data, list):
            return []

        para_map = {item["p_idx"]: item["text"] for item in chunk["items"]}
        verified_issues: List[SpellIssue] = []

        for item in data:
            if not isinstance(item, dict):
                continue

            p_idx = item.get("p_idx")
            orig = str(item.get("original", "")).strip()
            rep = str(item.get("replacement", "")).strip()
            cat = str(item.get("category", "chinh_ta"))
            reason = str(item.get("reason", "Đề xuất sửa bởi AI"))
            try:
                conf = float(item.get("confidence", 0.8))
            except (ValueError, TypeError):
                conf = 0.8

            if p_idx not in para_map or not orig or orig == rep:
                continue

            para_text = para_map[p_idx]
            para_hash = hashlib.sha256(para_text.encode("utf-8")).hexdigest()[:16]

            # Kiểm tra xem có chạm vào danh từ riêng được bảo vệ không
            is_protected = False
            for term in self.protected_terms:
                if term and (term in orig or term in rep):
                    is_protected = True
                    break
            if is_protected:
                continue

            # Xác định vị trí chính xác trong đoạn văn
            matches = list(re.finditer(re.escape(orig), para_text))
            if not matches:
                # original không tồn tại nguyên văn trong đoạn -> bỏ qua không áp dụng mù
                continue

            if len(matches) == 1:
                start_pos, end_pos = matches[0].start(), matches[0].end()
            else:
                # Cụm từ xuất hiện nhiều lần: kiểm tra xem AI có cung cấp char_start/char_end khớp không
                ai_start = item.get("char_start")
                ai_end = item.get("char_end")
                matched_span = None
                if ai_start is not None and ai_end is not None:
                    for m in matches:
                        if m.start() == ai_start and m.end() == ai_end:
                            matched_span = (m.start(), m.end())
                            break
                if matched_span:
                    start_pos, end_pos = matched_span
                else:
                    start_pos, end_pos = matches[0].start(), matches[0].end()
                    reason = f"[Cảnh báo: Xuất hiện {len(matches)} lần trong đoạn] {reason}"

            issue_id = f"iss_ai_c{chapter_num}_p{p_idx}_{start_pos}_{end_pos}"
            issue = SpellIssue(
                id=issue_id,
                original_hash=para_hash,
                chapter_num=chapter_num,
                chapter_title=chapter_title,
                paragraph_idx=p_idx,
                char_start=start_pos,
                char_end=end_pos,
                original=orig,
                replacement=rep,
                category=cat,
                reason=reason,
                source="ai",
                status="pending",  # Mặc định chờ duyệt, không bao giờ tự động áp dụng
                confidence=conf,
            )
            verified_issues.append(issue)

        return verified_issues
