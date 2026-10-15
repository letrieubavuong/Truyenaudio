"""
HTML Parser for vivutruyen.com and generic novel sites.
Extracts story title, chapter title, chapter number, paragraphs, prev/next links,
and computes SHA256 integrity hash without hallucinating selectors.
"""
import re
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from bs4 import BeautifulSoup
from urllib.parse import urljoin


class SourceParser:
    """Parser chuyên dụng cho HTML chương truyện vivutruyen.com và nguồn văn bản."""

    @staticmethod
    def extract_script_vars(html_text: str) -> Dict[str, str]:
        """Trích xuất các biến JavaScript trong thẻ script như bname, prevChap, nextChap, id, bid."""
        res = {}
        patterns = {
            "bname": r'var\s+bname\s*=\s*["\']([^"\']+)["\']',
            "bid": r'var\s+bid\s*=\s*["\']([^"\']+)["\']',
            "id": r'var\s+id\s*=\s*["\']([^"\']+)["\']',
            "prevChap": r'var\s+prevChap\s*=\s*["\']([^"\']+)["\']',
            "nextChap": r'var\s+nextChap\s*=\s*["\']([^"\']+)["\']',
        }
        for key, pat in patterns.items():
            match = re.search(pat, html_text)
            if match:
                res[key] = match.group(1).strip()
        return res

    @classmethod
    def parse_chapter_html(
        cls, html_text: str, current_url: str = ""
    ) -> Dict[str, Any]:
        """
        Phân tích mã nguồn HTML chương truyện thực tế của vivutruyen.com.
        Trả về dict với:
            - story_title: str
            - chapter_title: str
            - chapter_num: Optional[int]
            - raw_content: str
            - paragraphs: List[str]
            - prev_url: str
            - next_url: str
            - content_hash: str (SHA256)
            - warnings: List[str]
        """
        warnings = []
        soup = BeautifulSoup(html_text, "lxml" if "lxml" in BeautifulSoup.__dict__ else "html.parser")

        # 1. Kiểm tra dấu hiệu trang lỗi / chặn / CAPTCHA
        lower_html = html_text.lower()
        if "just a moment..." in lower_html or "cf-browser-verification" in lower_html:
            return {
                "error": "Phát hiện trang bảo vệ Cloudflare Challenge / CAPTCHA.",
                "is_blocked": True,
            }
        if "<title>403 forbidden" in lower_html or "<title>access denied" in lower_html:
            return {
                "error": "Truy cập bị từ chối (HTTP 403 / Access Denied).",
                "is_blocked": True,
            }

        # 2. Lấy biến JS có sẵn
        script_vars = cls.extract_script_vars(html_text)

        # 3. Trích xuất tên truyện (story_title)
        story_title = ""
        # Thử từ current-book
        current_book_tag = soup.select_one("h1.current-book a") or soup.select_one("h1.current-book")
        if current_book_tag:
            story_title = current_book_tag.get_text(strip=True)
        if not story_title and "bname" in script_vars:
            story_title = script_vars["bname"]
        if not story_title:
            # Thử từ breadcrumbs
            bc = soup.select(".breadcrumb a, .rdfa-breadcrumb a")
            if len(bc) >= 2:
                story_title = bc[1].get_text(strip=True)
        if not story_title:
            # Thử từ meta og:title hoặc title tag
            og_title = soup.select_one('meta[property="og:title"]')
            if og_title and og_title.get("content"):
                c = og_title["content"]
                if " - " in c:
                    story_title = c.split(" - ")[0].strip()
                else:
                    story_title = c.strip()

        # 4. Trích xuất tiêu đề chương (chapter_title) & số chương
        chapter_title = ""
        curr_chap_tag = soup.select_one("span.current-chapter")
        if curr_chap_tag:
            chapter_title = curr_chap_tag.get_text(strip=True)

        # 5. Trích xuất nội dung chương từ <div class="truyen">
        content_div = soup.select_one("div.truyen")
        paragraphs: List[str] = []

        if content_div:
            # Nếu chương chưa có tiêu đề, kiểm tra dòng text đầu tiên trong div.truyen
            first_text = ""
            for child in content_div.children:
                if isinstance(child, str):
                    t = child.strip()
                    if t:
                        first_text = t
                        break

            if not chapter_title and first_text and re.match(r"^Chương\s+\d+", first_text, re.IGNORECASE):
                chapter_title = first_text

            # Lấy tất cả thẻ p
            p_tags = content_div.find_all("p")
            if p_tags:
                for p in p_tags:
                    text = p.get_text().strip()
                    if text:
                        paragraphs.append(text)
            else:
                # Nếu không có thẻ p, lấy toàn bộ text và tách theo dòng
                full_text = content_div.get_text("\n")
                lines = [l.strip() for l in full_text.split("\n")]
                paragraphs = [l for l in lines if l]

            # Bỏ dòng đầu tiên nếu trùng khớp hoàn toàn với tiêu đề chương đã xác định từ metadata/HTML
            if paragraphs and chapter_title:
                first_clean = re.sub(r"\s+", " ", paragraphs[0]).strip().lower()
                title_clean = re.sub(r"\s+", " ", chapter_title).strip().lower()
                if first_clean == title_clean:
                    paragraphs = paragraphs[1:]
        else:
            warnings.append("Không tìm thấy vùng nội dung chuẩn (<div class='truyen'>).")

        # Fallback chapter title từ title của trang web nếu vẫn trống
        if not chapter_title:
            page_title = soup.title.string if soup.title else ""
            if page_title:
                match = re.search(r"Chương\s+\d+[^|\-]+", page_title, re.IGNORECASE)
                if match:
                    chapter_title = match.group(0).strip()
                else:
                    chapter_title = page_title.strip()

        # Trích xuất số chương từ chapter_title hoặc URL
        chapter_num = None
        if chapter_title:
            match_num = re.search(r"Chương\s+(\d+)", chapter_title, re.IGNORECASE)
            if match_num:
                chapter_num = int(match_num.group(1))

        if chapter_num is None and current_url:
            match_url = re.search(r"chuong-(\d+)", current_url, re.IGNORECASE)
            if match_url:
                chapter_num = int(match_url.group(1))

        # 6. Điều hướng Chương trước / Chương sau
        prev_url = ""
        next_url = ""

        # Ưu tiên từ script_vars
        if "prevChap" in script_vars:
            prev_cand = script_vars["prevChap"]
            # Không tính link về trang chủ truyện như /truyen/pham-nhan-tu-tien/ là chương trước của chương 1
            if prev_cand and not prev_cand.rstrip("/").endswith(script_vars.get("bid", "xxx")):
                prev_url = urljoin(current_url, prev_cand)

        if "nextChap" in script_vars:
            next_cand = script_vars["nextChap"]
            if next_cand:
                next_url = urljoin(current_url, next_cand)

        # Fallback từ HTML thẻ <a> điều hướng nếu script không có
        if not next_url:
            next_tag = soup.select_one(".chapter_control a.next, #gotochap a.next")
            if next_tag and next_tag.get("href"):
                next_cand = next_tag["href"]
                if next_cand and next_cand != "#" and not next_cand.startswith("javascript:"):
                    next_url = urljoin(current_url, next_cand)

        if not prev_url:
            prev_tag = soup.select_one(".chapter_control a.back:not(.disabled), #gotochap a.back:not(.disabled)")
            if prev_tag and prev_tag.get("href"):
                prev_cand = prev_tag["href"]
                if prev_cand and prev_cand != "#" and not prev_cand.startswith("javascript:"):
                    prev_url = urljoin(current_url, prev_cand)

        # 7. Ghép raw_content
        raw_content = "\n\n".join(paragraphs)

        # Tính băm nội dung SHA-256
        content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()

        # Kiểm tra cảnh báo bất thường
        word_count = len(raw_content.split())
        if word_count < 100:
            warnings.append(f"Cảnh báo: Nội dung chương rất ngắn ({word_count} từ), có thể bị cắt hoặc lỗi tải.")
        elif word_count < 300:
            warnings.append(f"Lưu ý: Độ dài chương thấp hơn bình thường ({word_count} từ).")

        return {
            "story_title": story_title,
            "chapter_title": chapter_title,
            "chapter_num": chapter_num,
            "raw_content": raw_content,
            "paragraphs": paragraphs,
            "prev_url": prev_url,
            "next_url": next_url,
            "content_hash": content_hash,
            "warnings": warnings,
        }

    @classmethod
    def parse_raw_text_file(
        cls, file_content: str, default_filename: str = ""
    ) -> Dict[str, Any]:
        """
        Trích xuất thông tin từ file văn bản thuần TXT do người dùng cung cấp.
        Phát hiện tiêu đề chương, số chương từ dòng đầu tiên hoặc tên file.
        """
        lines = [l.strip() for l in file_content.splitlines()]
        paragraphs = [l for l in lines if l]

        chapter_title = ""
        chapter_num = None
        warnings = []

        if paragraphs:
            first_line = paragraphs[0]
            if re.match(r"^Chương\s+\d+", first_line, re.IGNORECASE):
                chapter_title = first_line
                paragraphs = paragraphs[1:]
                m = re.search(r"Chương\s+(\d+)", chapter_title, re.IGNORECASE)
                if m:
                    chapter_num = int(m.group(1))

        if chapter_num is None and default_filename:
            m = re.search(r"(?:chuong|ch)[_\-\s]*(\d+)", default_filename, re.IGNORECASE)
            if m:
                chapter_num = int(m.group(1))
                if not chapter_title:
                    chapter_title = f"Chương {chapter_num}"

        raw_content = "\n\n".join(paragraphs)
        content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()

        word_count = len(raw_content.split())
        if word_count < 50:
            warnings.append(f"Cảnh báo: Tệp TXT có độ dài quá ngắn ({word_count} từ).")

        return {
            "story_title": "",
            "chapter_title": chapter_title or default_filename,
            "chapter_num": chapter_num,
            "raw_content": raw_content,
            "paragraphs": paragraphs,
            "prev_url": "",
            "next_url": "",
            "content_hash": content_hash,
            "warnings": warnings,
        }
