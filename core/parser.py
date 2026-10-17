"""
HTML Parser for vivutruyen.com, webnovel.vn, and generic novel sites.
Extracts story title, chapter title, chapter number, paragraphs, prev/next links,
and computes SHA256 integrity hash without hallucinating selectors.
Preserves strict source separation and anti-bot/blocking detection.
"""
import re
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from core.profiles import normalize_hostname


class WebnovelParser:
    """Parser chuyên dụng cho nguồn webnovel.vn (Tiên Nghịch và các truyện trên webnovel.vn)."""

    @staticmethod
    def _resolve_url(cand: str, current_url: str = "", base_url: str = "https://webnovel.vn") -> str:
        if not cand:
            return ""
        cand = cand.strip()
        if cand.startswith("http://") or cand.startswith("https://"):
            return cand
        ref_url = current_url if (current_url and current_url.startswith("http")) else (base_url or "https://webnovel.vn")
        return urljoin(ref_url, cand)

    @classmethod
    def parse_toc_html(cls, html_text: str, current_url: str = "", base_url: str = "https://webnovel.vn") -> Dict[str, Any]:
        """
        Phân tích trang mục lục webnovel.vn.
        Trích xuất danh sách chương, tổng số trang, phân trang kế tiếp.
        """
        soup = BeautifulSoup(html_text, "lxml" if "lxml" in BeautifulSoup.__dict__ else "html.parser")
        
        # Kiểm tra trang bị chặn
        lower_html = html_text.lower()
        if "just a moment..." in lower_html or "cf-browser-verification" in lower_html or "challenge-running" in lower_html:
            return {"error": "Phát hiện màn hình bảo vệ Cloudflare Challenge / CAPTCHA.", "is_blocked": True, "chapters": []}
        if "<title>403 forbidden" in lower_html or "<title>access denied" in lower_html:
            return {"error": "Truy cập bị từ chối (HTTP 403 / Access Denied).", "is_blocked": True, "chapters": []}

        # Tiêu đề truyện
        story_title = ""
        h1 = soup.find("h1")
        if h1:
            story_title = h1.get_text(strip=True)

        # Tác giả
        author = ""
        author_link = soup.find("a", href=lambda h: h and "tac-gia" in h)
        if author_link:
            author = author_link.get_text(strip=True)

        # Danh sách chương trong <ol class="chapter-list" id="chapterList">
        chapters = []
        ol = soup.find("ol", id="chapterList") or soup.find("ol", class_="chapter-list")
        if ol:
            for a in ol.find_all("a", href=True):
                href = cls._resolve_url(a.get("href"), current_url, base_url)
                idx_span = a.find("span", class_="chapter-item__index")
                title_span = a.find("span", class_="chapter-item__title")
                
                num = None
                if idx_span:
                    try:
                        num = int(idx_span.get_text(strip=True))
                    except ValueError:
                        pass
                
                raw_title = title_span.get_text(strip=True) if title_span else a.get_text(strip=True)
                if num is None:
                    m_num = re.search(r"(\d+)", raw_title)
                    if m_num:
                        num = int(m_num.group(1))

                full_title = a.get("title", "") or f"Chương {num}: {raw_title}" if num else raw_title
                chapters.append({
                    "chapter_num": num,
                    "title": full_title,
                    "url": href,
                })

        # Phân trang
        total_pages = 1
        next_page_url = ""
        pagination = soup.find("div", class_="chapters-pagination")
        if pagination:
            # Tìm max page từ input hoặc pagination link
            btn_go = pagination.find("button", class_="pagination__go-btn")
            if btn_go and btn_go.get("data-max"):
                try:
                    total_pages = int(btn_go.get("data-max"))
                except ValueError:
                    pass
            inp = pagination.find("input", class_="pagination__input")
            if inp and inp.get("max") and total_pages <= 1:
                try:
                    total_pages = int(inp.get("max"))
                except ValueError:
                    pass

            # Link trang sau
            for li in pagination.find_all("li", class_="pagination__item"):
                arrow = li.find("span", class_=lambda c: c and "arrow-right" in c)
                if arrow:
                    a_arrow = li.find("a", href=True)
                    if a_arrow:
                        next_page_url = cls._resolve_url(a_arrow.get("href"), current_url, base_url)
                        break

        return {
            "story_title": story_title,
            "author": author,
            "chapters": chapters,
            "total_pages": total_pages,
            "next_page_url": next_page_url,
        }

    @classmethod
    def parse_chapter_html(
        cls, html_text: str, current_url: str = "", base_url: str = "https://webnovel.vn"
    ) -> Dict[str, Any]:
        """
        Phân tích HTML chương truyện từ webnovel.vn.
        """
        warnings = []
        soup = BeautifulSoup(html_text, "lxml" if "lxml" in BeautifulSoup.__dict__ else "html.parser")

        # 1. Kiểm tra dấu hiệu trang lỗi / chặn / CAPTCHA
        lower_html = html_text.lower()
        if "just a moment..." in lower_html or "cf-browser-verification" in lower_html or "challenge-running" in lower_html:
            return {"error": "Phát hiện màn hình bảo vệ Cloudflare Challenge / CAPTCHA.", "is_blocked": True}
        if "<title>403 forbidden" in lower_html or "<title>access denied" in lower_html:
            return {"error": "Truy cập bị từ chối (HTTP 403 / Access Denied).", "is_blocked": True}

        # 2. Tiêu đề truyện
        story_title = ""
        reader_title_tag = soup.find("h1", class_="reader__title")
        if reader_title_tag:
            story_title = reader_title_tag.get_text(strip=True)
        if not story_title:
            og_novel = soup.find("meta", property="og:novel:book_name")
            if og_novel and og_novel.get("content"):
                story_title = og_novel["content"].strip()
        if not story_title:
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                c = og_title["content"]
                if " - " in c:
                    story_title = c.split(" - ")[-1].replace("Webnovel.vn", "").strip(" |")

        # 3. Tiêu đề chương & số chương
        chapter_title = ""
        curr_chap_tag = soup.find("p", class_="reader__chapter")
        if curr_chap_tag:
            chapter_title = curr_chap_tag.get_text(strip=True)

        chapter_num = None
        if chapter_title:
            m = re.search(r"Chương\s+(\d+)", chapter_title, re.IGNORECASE)
            if m:
                chapter_num = int(m.group(1))

        if chapter_num is None and current_url:
            m_url = re.search(r"chuong-(\d+)", current_url, re.IGNORECASE)
            if m_url:
                chapter_num = int(m_url.group(1))
                if not chapter_title:
                    chapter_title = f"Chương {chapter_num}"

        # 4. Trích xuất nội dung chương từ div#chapter-c bên trong article.reader__content
        content_container = soup.find("div", id="chapter-c")
        if not content_container:
            content_container = soup.find("article", class_="reader__content")

        # Kiểm tra nội dung bị khóa / yêu cầu đăng nhập (paywall, VIP, login wall)
        unlock_box = soup.find(class_=lambda c: c and ("unlock__chapter" in c or "unlock__full" in c))
        if not unlock_box and content_container:
            unlock_box = content_container.find(class_=lambda c: c and ("unlock__chapter" in c or "unlock__full" in c))

        paragraphs: List[str] = []
        if content_container:
            # Loại bỏ các thành phần rác: quảng cáo bastorypush, script, iframe, styles
            for garbage in content_container.find_all(["div", "ins", "script", "style", "iframe"], class_=lambda c: c and "bastorypush" in c):
                garbage.decompose()
            for garbage in content_container.find_all(["script", "style", "noscript", "iframe"]):
                garbage.decompose()

            # Nếu có unlock_box, loại bỏ để kiểm tra xem có đoạn văn truyện thực sự không
            if unlock_box:
                unlock_box.decompose()

            # Chuẩn hóa thẻ <br> thành ký tự xuống dòng
            for br in content_container.find_all("br"):
                br.replace_with("\n")

            full_text = content_container.get_text()
            raw_lines = [line.strip() for line in full_text.split("\n")]
            paragraphs = [line for line in raw_lines if line]

            # Bỏ dòng đầu tiên nếu trùng với tiêu đề chương
            if paragraphs and chapter_title:
                first_clean = re.sub(r"\s+", " ", paragraphs[0]).strip().lower()
                title_clean = re.sub(r"\s+", " ", chapter_title).strip().lower()
                if first_clean == title_clean or first_clean.startswith(f"chương {chapter_num}:"):
                    paragraphs = paragraphs[1:]
        else:
            warnings.append("Không tìm thấy vùng nội dung chuẩn (<div id='chapter-c'> hoặc <article class='reader__content'>).")

        # Nếu phát hiện trang bị khóa / paywall và không có nội dung truyện thực tế:
        if unlock_box or (paragraphs and len("\n".join(paragraphs)) < 100 and "đăng nhập" in "\n".join(paragraphs).lower()):
            if not paragraphs or len(" ".join(paragraphs).split()) < 30:
                return {
                    "error": "Chương bị khóa: Yêu cầu đăng nhập tài khoản trên webnovel.vn ('unlock__chapter' / 'Đăng nhập để đọc ngay'). Website chặn truy cập nội dung đối với khách vãng lai.",
                    "is_blocked": True,
                    "status_category": "blocked",
                    "chapter_title": chapter_title,
                    "chapter_num": chapter_num,
                    "warnings": warnings,
                }

        # 5. Điều hướng Chương trước / Chương sau
        prev_url = ""
        next_url = ""
        next_source = "none"
        prev_source = "none"

        # Trong webnovel.vn, các nút điều hướng nằm trong .reader__actions
        nav_actions = soup.find_all("div", class_="reader__actions")
        candidate_links = []
        if nav_actions:
            for act in nav_actions:
                candidate_links.extend(act.find_all("a", href=True))
        else:
            candidate_links = soup.find_all("a", href=True)

        for a in candidate_links:
            href = a.get("href", "").strip()
            if not href or href == "#" or href.startswith("javascript:"):
                continue
            text = a.get_text().strip().lower()
            if "chương sau" in text or "tiếp" in text:
                if not next_url:
                    next_url = cls._resolve_url(href, current_url, base_url)
                    next_source = "webnovel_nav:chuong_sau"
            elif "chương trước" in text or "lùi" in text:
                if not prev_url:
                    prev_url = cls._resolve_url(href, current_url, base_url)
                    prev_source = "webnovel_nav:chuong_truoc"

        # 6. Ghép raw_content
        raw_content = "\n\n".join(paragraphs)
        content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()

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
            "next_source": next_source,
            "prev_source": prev_source,
            "content_hash": content_hash,
            "warnings": warnings,
        }


class VivutruyenParser:
    """Parser chuyên dụng cho HTML chương truyện vivutruyen.com."""

    @staticmethod
    def extract_script_vars(html_text: str) -> Dict[str, str]:
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

    @staticmethod
    def _resolve_url(cand: str, current_url: str = "", base_url: str = "https://vivutruyen.com") -> str:
        if not cand:
            return ""
        cand = cand.strip()
        if cand.startswith("http://") or cand.startswith("https://"):
            return cand
        if cand.startswith("file://"):
            m = re.search(r"(/truyen/.+)", cand)
            if m:
                cand = m.group(1)
            else:
                return cand
        ref_url = current_url if (current_url and current_url.startswith("http")) else (base_url or "https://vivutruyen.com")
        return urljoin(ref_url, cand)

    @classmethod
    def parse_chapter_html(
        cls, html_text: str, current_url: str = "", base_url: str = "https://vivutruyen.com"
    ) -> Dict[str, Any]:
        warnings = []
        soup = BeautifulSoup(html_text, "lxml" if "lxml" in BeautifulSoup.__dict__ else "html.parser")

        lower_html = html_text.lower()
        if "just a moment..." in lower_html or "cf-browser-verification" in lower_html:
            return {"error": "Phát hiện trang bảo vệ Cloudflare Challenge / CAPTCHA.", "is_blocked": True}
        if "<title>403 forbidden" in lower_html or "<title>access denied" in lower_html:
            return {"error": "Truy cập bị từ chối (HTTP 403 / Access Denied).", "is_blocked": True}

        script_vars = cls.extract_script_vars(html_text)

        story_title = ""
        current_book_tag = soup.select_one("h1.current-book a") or soup.select_one("h1.current-book")
        if current_book_tag:
            story_title = current_book_tag.get_text(strip=True)
        if not story_title and "bname" in script_vars:
            story_title = script_vars["bname"]
        if not story_title:
            bc = soup.select(".breadcrumb a, .rdfa-breadcrumb a")
            if len(bc) >= 2:
                story_title = bc[1].get_text(strip=True)
        if not story_title:
            og_title = soup.select_one('meta[property="og:title"]')
            if og_title and og_title.get("content"):
                c = og_title["content"]
                if " - " in c:
                    story_title = c.split(" - ")[0].strip()
                else:
                    story_title = c.strip()

        chapter_title = ""
        curr_chap_tag = soup.select_one("span.current-chapter")
        if curr_chap_tag:
            chapter_title = curr_chap_tag.get_text(strip=True)

        content_div = soup.select_one("div.truyen")
        paragraphs: List[str] = []

        if content_div:
            first_text = ""
            for child in content_div.children:
                if isinstance(child, str):
                    t = child.strip()
                    if t:
                        first_text = t
                        break

            if not chapter_title and first_text and re.match(r"^Chương\s+\d+", first_text, re.IGNORECASE):
                chapter_title = first_text

            p_tags = content_div.find_all("p")
            if p_tags:
                for p in p_tags:
                    text = p.get_text().strip()
                    if text:
                        paragraphs.append(text)
            else:
                full_text = content_div.get_text("\n")
                lines = [l.strip() for l in full_text.split("\n")]
                paragraphs = [l for l in lines if l]

            if paragraphs and chapter_title:
                first_clean = re.sub(r"\s+", " ", paragraphs[0]).strip().lower()
                title_clean = re.sub(r"\s+", " ", chapter_title).strip().lower()
                if first_clean == title_clean:
                    paragraphs = paragraphs[1:]
        else:
            warnings.append("Không tìm thấy vùng nội dung chuẩn (<div class='truyen'>).")

        if not chapter_title:
            page_title = soup.title.string if soup.title else ""
            if page_title:
                match = re.search(r"Chương\s+\d+[^|\-]+", page_title, re.IGNORECASE)
                if match:
                    chapter_title = match.group(0).strip()
                else:
                    chapter_title = page_title.strip()

        chapter_num = None
        if chapter_title:
            match_num = re.search(r"Chương\s+(\d+)", chapter_title, re.IGNORECASE)
            if match_num:
                chapter_num = int(match_num.group(1))

        if chapter_num is None and current_url:
            match_url = re.search(r"chuong-(\d+)", current_url, re.IGNORECASE)
            if match_url:
                chapter_num = int(match_url.group(1))

        prev_url = ""
        next_url = ""
        next_source = "none"
        prev_source = "none"

        bid = script_vars.get("bid", "pham-nhan-tu-tien")

        if "nextChap" in script_vars:
            next_cand = script_vars["nextChap"].strip()
            if next_cand and next_cand != "#" and not next_cand.startswith("javascript:"):
                if not next_cand.rstrip("/").endswith(bid):
                    next_url = cls._resolve_url(next_cand, current_url, base_url)
                    next_source = "script_var:nextChap"

        if "prevChap" in script_vars:
            prev_cand = script_vars["prevChap"].strip()
            if prev_cand and prev_cand != "#" and not prev_cand.startswith("javascript:"):
                if not prev_cand.rstrip("/").endswith(bid):
                    prev_url = cls._resolve_url(prev_cand, current_url, base_url)
                    prev_source = "script_var:prevChap"

        all_nav_links = soup.select(".chapter_control a, #gotochap a, .chapter_wrap a, div.control a, a.next, a.prev, a.back")

        if not next_url and all_nav_links:
            for a in all_nav_links:
                href = a.get("href", "").strip()
                if not href or href == "#" or href.startswith("javascript:"):
                    continue
                rel = a.get("rel", [])
                if isinstance(rel, list) and "next" in rel:
                    next_url = cls._resolve_url(href, current_url, base_url)
                    next_source = "html_nav:rel_next"
                    break

            if not next_url:
                for a in all_nav_links:
                    href = a.get("href", "").strip()
                    if not href or href == "#" or href.startswith("javascript:"):
                        continue
                    text = a.get_text().strip().lower()
                    if any(k in text for k in ["chương trước", "trước", "quay lại", "lùi", "«", "<<"]):
                        continue
                    if any(k in text for k in ["chương tiếp", "tiếp theo", "chap sau", "tiếp >>", "tiếp >", "chương sau", "tiếp"]):
                        next_url = cls._resolve_url(href, current_url, base_url)
                        next_source = "html_nav:text"
                        break

            if not next_url:
                for a in all_nav_links:
                    href = a.get("href", "").strip()
                    if not href or href == "#" or href.startswith("javascript:"):
                        continue
                    classes = a.get("class", [])
                    if "next" in classes:
                        text = a.get_text().strip().lower()
                        if not any(k in text for k in ["chương trước", "trước", "quay lại", "lùi", "«", "<<"]):
                            next_url = cls._resolve_url(href, current_url, base_url)
                            next_source = "html_nav:class_next"
                            break

        if not prev_url and all_nav_links:
            for a in all_nav_links:
                href = a.get("href", "").strip()
                if not href or href == "#" or href.startswith("javascript:") or href.rstrip("/").endswith(bid):
                    continue
                rel = a.get("rel", [])
                if isinstance(rel, list) and "prev" in rel:
                    prev_url = cls._resolve_url(href, current_url, base_url)
                    prev_source = "html_nav:rel_prev"
                    break

            if not prev_url:
                for a in all_nav_links:
                    href = a.get("href", "").strip()
                    if not href or href == "#" or href.startswith("javascript:") or href.rstrip("/").endswith(bid):
                        continue
                    text = a.get_text().strip().lower()
                    if any(k in text for k in ["tiếp theo", "chương tiếp", "chap sau", "tiếp"]):
                        continue
                    if any(k in text for k in ["chương trước", "trước", "quay lại", "lùi", "«", "<<"]):
                        prev_url = cls._resolve_url(href, current_url, base_url)
                        prev_source = "html_nav:text"
                        break

        raw_content = "\n\n".join(paragraphs)
        content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()

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
            "next_source": next_source,
            "prev_source": prev_source,
            "content_hash": content_hash,
            "warnings": warnings,
        }


class TamHoanParser:
    """Parser chuyên dụng cho nguồn tamhoan.com (Tiên Nghịch và các truyện trên tamhoan.com)."""

    BASE_URL = "https://tamhoan.com"

    @classmethod
    def _resolve_url(cls, cand: str, current_url: str = "", base_url: str = "") -> str:
        if not cand:
            return ""
        cand = cand.strip()
        if "#" in cand:
            cand = cand.split("#")[0].strip()
        if not cand or cand.startswith("javascript:"):
            return ""
        if cand.startswith("http://") or cand.startswith("https://"):
            return cand
        ref_url = current_url if (current_url and current_url.startswith("http")) else (base_url or cls.BASE_URL)
        return urljoin(ref_url, cand)

    @classmethod
    def parse_toc_html(cls, html_text: str, current_url: str = "", base_url: str = "") -> Dict[str, Any]:
        soup = BeautifulSoup(html_text, "lxml" if "lxml" in BeautifulSoup.__dict__ else "html.parser")
        base = base_url or cls.BASE_URL

        lower_html = html_text.lower()
        if "just a moment..." in lower_html or "cf-browser-verification" in lower_html or "challenge-running" in lower_html:
            return {"error": "Phát hiện màn hình bảo vệ Cloudflare Challenge / CAPTCHA.", "is_blocked": True, "chapters": []}
        if "<title>403 forbidden" in lower_html or "<title>access denied" in lower_html:
            return {"error": "Truy cập bị từ chối (HTTP 403 / Access Denied).", "is_blocked": True, "chapters": []}

        # 1. Tiêu đề truyện
        story_title = ""
        info_div = soup.find("div", class_="stories-infomation")
        if info_div:
            h_tag = info_div.find(["h1", "h2", "h3"])
            if h_tag:
                story_title = h_tag.get_text(strip=True)
        if not story_title:
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                c = og_title["content"]
                if "–" in c:
                    story_title = c.split("–")[0].strip()
                elif "-" in c:
                    story_title = c.split("-")[0].strip()
                else:
                    story_title = c.strip()

        # 2. Tác giả
        author = ""
        if info_div:
            author_link = info_div.find("a", href=lambda h: h and "tac-gia" in h)
            if author_link:
                author = author_link.get_text(strip=True)
            if not author:
                m_auth = re.search(r"Tác\s*giả\s*:\s*([^<\n\r]+)", info_div.get_text())
                if m_auth:
                    author = m_auth.group(1).split("Nguồn")[0].strip()

        # 3. Danh sách chương
        chapters = []
        chap_container = soup.find("div", class_=lambda c: c and "dschuong" in c) or soup.find("div", id="latest-chap-list")
        if not chap_container:
            chap_container = soup

        for a in chap_container.find_all("a", href=True):
            href = a.get("href", "").strip()
            if not re.search(r"/[a-z0-9\-]+/\d+$", href):
                continue
            full_url = cls._resolve_url(href, current_url, base)
            raw_title = a.get("title", "") or a.get_text(strip=True)
            if not raw_title or raw_title.lower() in ["đọc từ đầu", "đọc truyện"]:
                continue

            num = None
            m_num = re.search(r"Chương\s+(\d+)", raw_title, re.IGNORECASE)
            if m_num:
                num = int(m_num.group(1))

            chapters.append({
                "chapter_num": num,
                "title": raw_title,
                "url": full_url,
            })

        # 4. Phân trang
        total_pages = 1
        next_page_url = ""
        pag_div = soup.find("div", class_="storyPagination")
        if pag_div:
            for a in pag_div.find_all("a", href=True):
                m_p = re.search(r"[?&]page=(\d+)", a["href"])
                if m_p:
                    p_val = int(m_p.group(1))
                    if p_val > total_pages:
                        total_pages = p_val
                if a.get("aria-label") == "Next" or "fa-angle-right" in str(a):
                    next_page_url = cls._resolve_url(a["href"], current_url, base)

        return {
            "story_title": story_title,
            "author": author,
            "chapters": chapters,
            "total_pages": total_pages,
            "next_page_url": next_page_url,
        }

    @classmethod
    def parse_chapter_html(
        cls, html_text: str, current_url: str = "", base_url: str = ""
    ) -> Dict[str, Any]:
        warnings = []
        soup = BeautifulSoup(html_text, "lxml" if "lxml" in BeautifulSoup.__dict__ else "html.parser")
        base = base_url or cls.BASE_URL

        # 1. Kiểm tra dấu hiệu trang lỗi / chặn / CAPTCHA
        lower_html = html_text.lower()
        if "just a moment..." in lower_html or "cf-browser-verification" in lower_html or "challenge-running" in lower_html:
            return {"error": "Phát hiện màn hình bảo vệ Cloudflare Challenge / CAPTCHA.", "is_blocked": True, "status_category": "blocked"}
        if "<title>403 forbidden" in lower_html or "<title>access denied" in lower_html:
            return {"error": "Truy cập bị từ chối (HTTP 403 / Access Denied).", "is_blocked": True, "status_category": "blocked"}

        # 2. Tiêu đề truyện
        story_title = ""
        bc_link = soup.find("a", href=lambda h: h and "/truyen/" in h)
        if bc_link:
            story_title = bc_link.get_text(strip=True)
        if not story_title:
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                c = og_title["content"]
                if "–" in c:
                    parts = c.split("–")
                    if len(parts) > 1:
                        story_title = parts[1].split("|")[0].strip()

        # 3. Tiêu đề chương & Số chương
        chapter_title = ""
        chap_content = soup.find("div", class_="chapContent")
        if chap_content:
            h2 = chap_content.find("h2", class_=lambda c: c and "text-center" in c)
            if not h2:
                h2 = chap_content.find("h2")
            if h2:
                chapter_title = h2.get_text(strip=True)

        if not chapter_title:
            if soup.title and soup.title.string:
                t_str = soup.title.string.strip()
                if "–" in t_str:
                    chapter_title = t_str.split("–")[0].strip()
                elif "-" in t_str:
                    chapter_title = t_str.split("-")[0].strip()

        chapter_num = None
        if chapter_title:
            m = re.search(r"Chương\s+(\d+)", chapter_title, re.IGNORECASE)
            if m:
                chapter_num = int(m.group(1))

        # Lưu ý: 205299 là ID bài viết trên URL tamhoan, tuyệt đối KHÔNG coi đó là số chương!

        # 4. Trích xuất nội dung chương từ div.content bên trong div.chapContent
        content_container = None
        if chap_content:
            content_container = chap_content.find("div", class_="content")
        if not content_container:
            content_container = soup.find("div", class_="content")

        paragraphs: List[str] = []
        if content_container:
            # Loại bỏ quảng cáo Google Ads (<ins class="adsbygoogle">, script, iframe, style)
            for garbage in content_container.find_all(["ins", "script", "style", "iframe", "noscript"]):
                garbage.decompose()
            for h in content_container.find_all(["h1", "h2", "h3"]):
                h.decompose()

            p_tags = content_container.find_all("p")
            if p_tags:
                for p in p_tags:
                    for br in p.find_all("br"):
                        br.replace_with("\n")
                    text = p.get_text().strip()
                    if text:
                        for line in text.split("\n"):
                            line_str = line.strip()
                            if line_str:
                                paragraphs.append(line_str)
            else:
                for br in content_container.find_all("br"):
                    br.replace_with("\n")
                full_text = content_container.get_text()
                raw_lines = [l.strip() for l in full_text.split("\n")]
                paragraphs = [l for l in raw_lines if l]

            if paragraphs and chapter_title:
                first_clean = re.sub(r"\s+", " ", paragraphs[0]).strip().lower()
                title_clean = re.sub(r"\s+", " ", chapter_title).strip().lower()
                if first_clean == title_clean or (chapter_num and first_clean.startswith(f"chương {chapter_num}:")):
                    paragraphs = paragraphs[1:]
        else:
            warnings.append("Không tìm thấy vùng nội dung chuẩn (<div class='content'> bên trong <div class='chapContent'>).")

        # 5. Điều hướng Chương trước / Chương sau qua id="next_chap" và id="prev_chap"
        prev_url = ""
        next_url = ""
        next_source = "none"
        prev_source = "none"

        next_tag = soup.find("a", id="next_chap")
        if next_tag and next_tag.get("href"):
            nhref = next_tag["href"].strip()
            if nhref and nhref != "#" and "disabled" not in next_tag.get("class", []):
                next_url = cls._resolve_url(nhref, current_url, base)
                next_source = "tamhoan_id:next_chap"

        prev_tag = soup.find("a", id="prev_chap")
        if prev_tag and prev_tag.get("href"):
            phref = prev_tag["href"].strip()
            if phref and phref != "#" and "disabled" not in prev_tag.get("class", []):
                prev_url = cls._resolve_url(phref, current_url, base)
                prev_source = "tamhoan_id:prev_chap"

        # 6. Ghép raw_content và tính SHA256
        raw_content = "\n\n".join(paragraphs)
        content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()

        word_count = len(raw_content.split())
        res_data = {
            "story_title": story_title,
            "chapter_title": chapter_title,
            "chapter_num": chapter_num,
            "raw_content": raw_content,
            "paragraphs": paragraphs,
            "prev_url": prev_url,
            "next_url": next_url,
            "next_source": next_source,
            "prev_source": prev_source,
            "content_hash": content_hash,
            "warnings": warnings,
        }

        if not paragraphs:
            res_data["error"] = "Không tìm thấy nội dung chương truyện hợp lệ trong trang HTML."
            return res_data

        if word_count < 100:
            warnings.append(f"Cảnh báo: Nội dung chương rất ngắn ({word_count} từ), có thể bị cắt hoặc lỗi tải.")
        elif word_count < 300:
            warnings.append(f"Lưu ý: Độ dài chương thấp hơn bình thường ({word_count} từ).")

        return res_data


class SourceParser:
    """
    Parser thống nhất phân phối cho các nguồn tamhoan.com, webnovel.vn, vivutruyen.com và tệp offline.
    Nhận diện nguồn từ hostname đã chuẩn hóa, không dùng kiểm tra chuỗi lỏng lẻo.
    """

    @staticmethod
    def extract_script_vars(html_text: str) -> Dict[str, str]:
        return VivutruyenParser.extract_script_vars(html_text)

    @classmethod
    def detect_source(cls, html_text: str = "", current_url: str = "", base_url: str = "") -> str:
        """
        Nhận diện nguồn chính xác dựa trên normalized hostname,
        hoặc nhận diện cấu trúc đặc trưng nếu URL là file offline (file://).
        Trả về: 'tamhoan', 'webnovel', hoặc 'vivutruyen'.
        """
        for u in [current_url, base_url]:
            if u:
                host = normalize_hostname(u)
                if host == "tamhoan.com":
                    return "tamhoan"
                if host == "webnovel.vn":
                    return "webnovel"
                if host == "vivutruyen.com":
                    return "vivutruyen"

        # Nếu không có hostname web hợp lệ (ví dụ tệp offline file://), kiểm tra cấu trúc DOM đặc trưng
        if html_text:
            if 'id="next_chap"' in html_text or 'class="chapContent"' in html_text or 'class="dschuong"' in html_text:
                return "tamhoan"
            if 'id="chapter-c"' in html_text or 'class="reader__content"' in html_text or 'class="chapter-item__link"' in html_text or 'class="reader__chapter"' in html_text:
                return "webnovel"

        return "vivutruyen"

    @classmethod
    def is_webnovel_source(cls, html_text: str, current_url: str = "", base_url: str = "") -> bool:
        """Tương thích ngược: kiểm tra nguồn webnovel.vn."""
        return cls.detect_source(html_text, current_url, base_url) == "webnovel"

    @classmethod
    def is_tamhoan_source(cls, html_text: str, current_url: str = "", base_url: str = "") -> bool:
        """Kiểm tra nguồn tamhoan.com."""
        return cls.detect_source(html_text, current_url, base_url) == "tamhoan"

    @classmethod
    def _resolve_url(cls, cand: str, current_url: str = "", base_url: str = "") -> str:
        src = cls.detect_source("", current_url, base_url)
        if src == "tamhoan":
            return TamHoanParser._resolve_url(cand, current_url, base_url or "https://tamhoan.com")
        elif src == "webnovel":
            return WebnovelParser._resolve_url(cand, current_url, base_url or "https://webnovel.vn")
        return VivutruyenParser._resolve_url(cand, current_url, base_url or "https://vivutruyen.com")

    @classmethod
    def parse_chapter_html(
        cls, html_text: str, current_url: str = "", base_url: str = ""
    ) -> Dict[str, Any]:
        """Phân tích HTML chương theo nguồn tương ứng."""
        src = cls.detect_source(html_text, current_url, base_url)
        if src == "tamhoan":
            return TamHoanParser.parse_chapter_html(
                html_text, current_url=current_url, base_url=base_url or "https://tamhoan.com"
            )
        elif src == "webnovel":
            return WebnovelParser.parse_chapter_html(
                html_text, current_url=current_url, base_url=base_url or "https://webnovel.vn"
            )
        return VivutruyenParser.parse_chapter_html(
            html_text, current_url=current_url, base_url=base_url or "https://vivutruyen.com"
        )

    @classmethod
    def parse_toc_html(
        cls, html_text: str, current_url: str = "", base_url: str = ""
    ) -> Dict[str, Any]:
        """Phân tích HTML trang mục lục."""
        src = cls.detect_source(html_text, current_url, base_url)
        if src == "tamhoan":
            return TamHoanParser.parse_toc_html(
                html_text, current_url=current_url, base_url=base_url or "https://tamhoan.com"
            )
        elif src == "webnovel":
            return WebnovelParser.parse_toc_html(
                html_text, current_url=current_url, base_url=base_url or "https://webnovel.vn"
            )
        return {"error": "Nguồn chưa hỗ trợ phân tích mục lục trực tiếp.", "chapters": []}

    @classmethod
    def parse_raw_text_file(
        cls, file_content: str, default_filename: str = ""
    ) -> Dict[str, Any]:
        """
        Trích xuất thông tin từ file văn bản thuần TXT do người dùng cung cấp.
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
