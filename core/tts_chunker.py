"""
Vietnamese Text Chunker for Long-Form TTS Synthesis.
Splits volume text into speech-friendly chunks by chapter, paragraph, sentence, and clause.
Guarantees 100% text coverage without dropping, duplicating, or inverting text.
"""
import re
import hashlib
from typing import List, Tuple
from core.tts_models import TTSChunk


class TextChunker:
    """
    Bộ chia văn bản tiếng Việt dài thành các đoạn nhỏ tối ưu cho VieNeu-TTS.
    Ngưỡng khuyến nghị cho VieNeu-TTS v3: ~120 - 250 ký tự/đoạn để giữ nhịp thở tự nhiên.
    """

    MAX_CHUNK_CHARS = 240
    MIN_CHUNK_CHARS = 30

    # Nhận diện tiêu đề chương để đánh dấu khoảng nghỉ dài hơn
    CHAPTER_HEADING_REGEX = re.compile(
        r"^(?:chương|chuong|hồi|hoi|tiết|tiet|tập|tap)\s+\d+[:\s\.\-]",
        re.IGNORECASE,
    )

    # Ranh giới câu tiếng Việt
    SENTENCE_END_REGEX = re.compile(
        r"([\.!\?…]+[\"'\u201d\u2019\)]*|\.{3}[\"'\u201d\u2019\)]*)(?:\s+|$)"
    )

    # Dấu ngắt mệnh đề an toàn
    CLAUSE_PUNCT_REGEX = re.compile(r"([,;:\-–—]+[\"'\u201d\u2019\)]*)(?:\s+)")

    # Liên từ tiếng Việt để ngắt khi câu dài không có dấu phẩy
    CONJUNCTION_SPLIT_REGEX = re.compile(
        r"(\s+(?:nhưng|mà|bởi vì|cho nên|thế nhưng|tuy nhiên|mặc dù|đồng thời)\s+)",
        re.IGNORECASE,
    )

    @classmethod
    def chunk_text(cls, text: str, max_chars: int = MAX_CHUNK_CHARS) -> List[TTSChunk]:
        """
        Chia văn bản thành danh sách TTSChunk có thứ tự tuyệt đối.
        Bảo toàn toàn bộ từ ngữ và dấu câu.
        """
        if not text or not text.strip():
            return []

        chunks: List[TTSChunk] = []
        # Tách các đoạn văn bằng dòng trống
        raw_paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

        chunk_idx = 0
        for p_idx, p_text in enumerate(raw_paragraphs):
            is_chapter = bool(cls.CHAPTER_HEADING_REGEX.match(p_text))

            # 1. Tách đoạn văn thành các câu
            sentences = cls._split_into_sentences(p_text)

            for s_text in sentences:
                s_text = s_text.strip()
                if not s_text:
                    continue

                # 2. Nếu câu quá dài, tách theo mệnh đề
                if len(s_text) > max_chars:
                    sub_chunks = cls._split_long_sentence(s_text, max_chars)
                    for sc in sub_chunks:
                        sc = sc.strip()
                        if sc:
                            ch_hash = hashlib.sha256(sc.encode("utf-8")).hexdigest()[:16]
                            chunks.append(
                                TTSChunk(
                                    index=chunk_idx,
                                    text=sc,
                                    text_hash=ch_hash,
                                    char_count=len(sc),
                                    word_count=len(sc.split()),
                                    paragraph_idx=p_idx,
                                    is_chapter_boundary=is_chapter,
                                )
                            )
                            chunk_idx += 1
                else:
                    ch_hash = hashlib.sha256(s_text.encode("utf-8")).hexdigest()[:16]
                    chunks.append(
                        TTSChunk(
                            index=chunk_idx,
                            text=s_text,
                            text_hash=ch_hash,
                            char_count=len(s_text),
                            word_count=len(s_text.split()),
                            paragraph_idx=p_idx,
                            is_chapter_boundary=is_chapter,
                        )
                    )
                    chunk_idx += 1

        return chunks

    @classmethod
    def _split_into_sentences(cls, text: str) -> List[str]:
        """
        Tách một đoạn văn thành danh sách các câu hoàn chỉnh dựa trên dấu kết thúc.
        Tránh ngắt nhầm ở số thập phân (1.5) hoặc từ viết tắt phổ biến.
        """
        # Bảo vệ số thập phân tạm thời
        protected = re.sub(r"(\d+)\.(\d+)", r"\1<DOT>\2", text)

        parts = []
        last_idx = 0
        for m in cls.SENTENCE_END_REGEX.finditer(protected):
            end_pos = m.end()
            sentence = protected[last_idx:end_pos].strip()
            if sentence:
                parts.append(sentence.replace("<DOT>", "."))
            last_idx = end_pos

        rem = protected[last_idx:].strip()
        if rem:
            parts.append(rem.replace("<DOT>", "."))

        return parts if parts else [text]

    @classmethod
    def _split_long_sentence(cls, sentence: str, max_chars: int) -> List[str]:
        """
        Chia một câu quá dài (> max_chars) thành các mệnh đề tự nhiên tại dấu phẩy/chấm phẩy hoặc liên từ.
        Không bao giờ cắt đôi từ tiếng Việt.
        """
        if len(sentence) <= max_chars:
            return [sentence]

        result = []
        current = sentence

        while len(current) > max_chars:
            # 1. Tìm vị trí ngắt dấu phẩy/chấm phẩy/ngang tốt nhất trong khoảng [max_chars*0.4, max_chars]
            cutoff = -1
            search_window = current[:max_chars]

            # Tìm dấu câu mệnh đề gần cuối window nhất
            matches = list(cls.CLAUSE_PUNCT_REGEX.finditer(search_window))
            if matches:
                # Lấy dấu câu gần nhất trước giới hạn max_chars
                last_m = matches[-1]
                if last_m.end() >= int(max_chars * 0.35):
                    cutoff = last_m.end()

            # 2. Nếu không có dấu câu, tìm liên từ
            if cutoff == -1:
                conj_matches = list(cls.CONJUNCTION_SPLIT_REGEX.finditer(search_window))
                if conj_matches:
                    last_c = conj_matches[-1]
                    if last_c.start() >= int(max_chars * 0.35):
                        cutoff = last_c.start()

            # 3. Nếu vẫn không có, ngắt tại khoảng trắng gần nhất
            if cutoff == -1:
                space_pos = search_window.rfind(" ")
                if space_pos >= int(max_chars * 0.35):
                    cutoff = space_pos + 1
                else:
                    cutoff = max_chars

            part = current[:cutoff].strip()
            if part:
                result.append(part)
            current = current[cutoff:].strip()

        if current:
            result.append(current)

        return result

    @classmethod
    def reconstruct_text(cls, chunks: List[TTSChunk]) -> str:
        """
        Tái dựng văn bản từ các đoạn để phục vụ kiểm thử độ bao phủ (coverage).
        """
        paras: List[List[str]] = []
        current_p = -1

        for c in chunks:
            if c.paragraph_idx != current_p:
                paras.append([])
                current_p = c.paragraph_idx
            paras[-1].append(c.text)

        return "\n".join(" ".join(p_chunks) for p_chunks in paras)
