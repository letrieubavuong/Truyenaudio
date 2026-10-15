"""
AI-assisted Vietnamese Spell Checker with Paragraph Identification and Integrity Verification.
Supports OpenAI-compatible endpoints and Google Gemini API.
Adheres strictly to the guidelines:
- Never rewrites, summarizes, changes speakers or facts
- Chunks have unique identifiers (chunk_id, p_idx)
- Validates that AI suggestions strictly match original text
- Flags uncertain or meaning-altering changes for manual review
"""
import json
import os
import re
from typing import List, Dict, Any, Optional, Tuple
from core.models import SpellIssue


class AIChecker:
    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = "",
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
    ):
        self.provider = provider
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model
        self.base_url = base_url

    def prepare_chunks(
        self, paragraphs: List[str], max_paragraphs_per_chunk: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Chia các đoạn văn thành từng chunk có mã định danh rõ ràng.
        Dùng để người dùng xem trước chính xác nội dung sẽ gửi đến AI.
        """
        chunks = []
        total_p = len(paragraphs)
        for i in range(0, total_p, max_paragraphs_per_chunk):
            sub_paras = paragraphs[i : i + max_paragraphs_per_chunk]
            chunk_id = f"chunk_{i // max_paragraphs_per_chunk + 1}"
            items = []
            for offset, text in enumerate(sub_paras):
                p_idx = i + offset
                items.append({"p_idx": p_idx, "text": text})
            chunks.append({
                "chunk_id": chunk_id,
                "start_idx": i,
                "end_idx": min(i + max_paragraphs_per_chunk - 1, total_p - 1),
                "items": items,
            })
        return chunks

    def build_system_prompt(self) -> str:
        return (
            "Bạn là trợ lý hiệu đính và phát hiện lỗi chính tả tiếng Việt chuyên nghiệp cho tiểu thuyết dịch/convert.\n"
            "Nhiệm vụ: Tìm các từ/cụm từ sai chính tả, sai dấu câu, hoặc dùng sai từ trong các đoạn văn được cung cấp.\n"
            "NGHIÊM CẤM:\n"
            "1. KHÔNG tóm tắt, KHÔNG đổi tình tiết, KHÔNG đổi người nói, KHÔNG viết lại toàn bộ câu/đoạn văn.\n"
            "2. KHÔNG tự ý suy diễn hoặc phục hồi các từ bị che bằng dấu '*'.\n"
            "3. KHÔNG thay đổi các từ đa nghĩa (như 'cổ/cỗ', 'nửa/nữa') nếu chưa chắc chắn 100% ngữ cảnh.\n"
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
            return [], f"Lỗi gọi API AI ({self.provider}): {str(e)}"

    def _call_provider(self, system_prompt: str, user_content: str) -> str:
        """Thực hiện request HTTP tới OpenAI-compatible API hoặc Google GenAI."""
        import requests

        if self.provider == "gemini":
            # Nếu dùng google-genai
            try:
                from google import genai
                client = genai.Client(api_key=self.api_key)
                response = client.models.generate_content(
                    model=self.model or "gemini-2.5-flash",
                    contents=[system_prompt, f"Dữ liệu cần kiểm tra:\n{user_content}"],
                )
                return response.text or ""
            except Exception:
                # Fallback to direct HTTP REST for Gemini
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
                payload = {
                    "contents": [{"parts": [{"text": f"{system_prompt}\n\nDữ liệu:\n{user_content}"}]}]
                }
                r = requests.post(url, json=payload, timeout=30)
                r.raise_for_status()
                data = r.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            # OpenAI compatible endpoint
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
        - original phải xuất hiện trong đoạn p_idx
        - nếu không khớp hoặc confidence < 0.8 -> status='pending'
        """
        # Trích xuất JSON từ markdown block nếu có
        json_str = raw_response.strip()
        match = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", json_str)
        if match:
            json_str = match.group(1)
        else:
            m2 = re.search(r"\[[\s\S]*\]", json_str)
            if m2:
                json_str = m2.group(0)

        data = json.loads(json_str)
        if not isinstance(data, list):
            return []

        # Tạo map đoạn văn để tìm vị trí chính xác
        para_map = {item["p_idx"]: item["text"] for item in chunk["items"]}
        verified_issues: List[SpellIssue] = []

        for item in data:
            p_idx = item.get("p_idx")
            orig = item.get("original", "").strip()
            rep = item.get("replacement", "").strip()
            cat = item.get("category", "chinh_ta")
            reason = item.get("reason", "Đề xuất sửa bởi AI")
            conf = float(item.get("confidence", 0.9))

            if p_idx not in para_map or not orig:
                continue

            para_text = para_map[p_idx]
            pos = para_text.find(orig)

            status = "applied"
            if pos == -1:
                # Không khớp chính xác với bản gốc: chuyển sang pending để duyệt thủ công
                status = "pending"
                reason = f"[Cảnh báo: Không khớp nguyên văn] {reason}"
                pos = 0
                end_pos = len(orig)
            else:
                end_pos = pos + len(orig)

            if conf < 0.8:
                status = "pending"
                reason = f"[Độ tin cậy thấp {conf:.2f}] {reason}"

            issue = SpellIssue(
                chapter_num=chapter_num,
                chapter_title=chapter_title,
                paragraph_idx=p_idx,
                char_start=pos,
                char_end=end_pos,
                original=orig,
                replacement=rep,
                category=cat,
                reason=reason,
                source="ai",
                status=status,
            )
            verified_issues.append(issue)

        return verified_issues
