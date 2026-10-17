"""
Manifest and Cache Manager for VieNeu-TTS Audio Production.
Ensures immutability of text snapshots, tracks chunk-level progress,
validates WAV integrity, and enables safe resumption after errors/cancellation.
"""
import os
import json
import hashlib
from typing import Dict, Any, Optional, Tuple, List
from core.tts_models import TTSItem, TTSChunk, TTSConfig


class TTSManifestManager:
    """Quản lý tệp manifest.json nội bộ và kiểm tra tính hợp lệ của cache audio."""

    MANIFEST_FILENAME = "manifest.json"
    CHUNKING_VERSION = "v1"

    @classmethod
    def get_default_cache_dir(cls, story_title: str, source: str, volume_num: int, config_hash: str) -> str:
        """
        Tạo đường dẫn thư mục cache nội bộ nằm ẩn trong output_volumes.
        Ví dụ: output_volumes/Tien_Nghich/tamhoan_com/.tts_cache/Tap_001_a1b2c3d4/
        """
        safe_title = "".join(c if (c.isalnum() or c in (" ", "_", "-")) else "_" for c in story_title).strip()
        safe_source = "".join(c if (c.isalnum() or c in (" ", "_", "-")) else "_" for c in source).strip() or "general"
        
        base_dir = os.path.join("output_volumes", safe_title, safe_source, ".tts_cache", f"Tap_{volume_num:03d}_{config_hash}")
        return os.path.abspath(base_dir)

    @classmethod
    def is_wav_file_valid(cls, wav_path: str) -> bool:
        """
        Kiểm tra tính hợp lệ của tệp WAV đã tạo:
        1. Tệp phải tồn tại và đọc được.
        2. Kích thước phải > 44 bytes (kích thước tối thiểu của header chuẩn RIFF WAVE).
        3. 4 byte đầu phải là b'RIFF' và byte 8-12 phải là b'WAVE'.
        """
        if not wav_path or not os.path.isfile(wav_path):
            return False
        try:
            sz = os.path.getsize(wav_path)
            if sz <= 44:
                return False
            with open(wav_path, "rb") as f:
                header = f.read(12)
                if len(header) < 12:
                    return False
                if header[:4] != b"RIFF" or header[8:12] != b"WAVE":
                    return False
            return True
        except Exception:
            return False

    @classmethod
    def prepare_item_manifest(
        cls,
        item: TTSItem,
        config: TTSConfig,
        cache_dir: Optional[str] = None,
    ) -> Tuple[str, bool]:
        """
        Khởi tạo hoặc nạp manifest cho một TTSItem.
        Trả về (manifest_path, is_reused).
        Nếu nội dung text hoặc cấu hình âm thanh thay đổi, đánh dấu cache không tương thích.
        """
        cfg_hash = config.compute_hash()
        text_hash = hashlib.sha256(item.raw_text.encode("utf-8")).hexdigest()

        if not cache_dir:
            cache_dir = cls.get_default_cache_dir(
                story_title=item.story_title,
                source=item.source,
                volume_num=item.volume_num,
                config_hash=cfg_hash,
            )

        os.makedirs(cache_dir, exist_ok=True)
        item.manifest_dir = cache_dir
        manifest_path = os.path.join(cache_dir, cls.MANIFEST_FILENAME)

        is_reused = False
        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Kiểm tra tương thích: hash văn bản, thuật toán chia đoạn và hash cấu hình
                if (
                    data.get("raw_text_hash") == text_hash
                    and data.get("config_hash") == cfg_hash
                    and data.get("chunking_version") == cls.CHUNKING_VERSION
                ):
                    is_reused = True
                    # Phục hồi trạng thái các chunk đã hoàn thành
                    saved_chunks = {c["index"]: c for c in data.get("chunks", [])}
                    chunks_done = 0

                    for chunk in item.chunks:
                        if chunk.index in saved_chunks:
                            sc = saved_chunks[chunk.index]
                            wav_path = sc.get("wav_path", "")
                            # Kiểm tra file WAV thực tế trên đĩa (nếu WAV hợp lệ thì tái sử dụng được)
                            if cls.is_wav_file_valid(wav_path):
                                chunk.status = "completed"
                                chunk.wav_path = wav_path
                                chunk.duration_sec = sc.get("duration_sec", 0.0)
                                chunk.sample_count = sc.get("sample_count", 0)
                                chunk.error_msg = ""
                                chunks_done += 1
                            else:
                                chunk.status = "pending"
                                chunk.wav_path = os.path.join(cache_dir, f"chunk_{chunk.index:05d}.wav")
                                chunk.error_msg = sc.get("error_msg", "")
                        else:
                            chunk.status = "pending"
                            chunk.wav_path = os.path.join(cache_dir, f"chunk_{chunk.index:05d}.wav")

                    item.chunks_done = chunks_done
            except Exception:
                is_reused = False

        if not is_reused:
            # Gán đường dẫn file WAV mục tiêu cho từng chunk
            for chunk in item.chunks:
                chunk.wav_path = os.path.join(cache_dir, f"chunk_{chunk.index:05d}.wav")
                chunk.status = "pending"
                chunk.error_msg = ""
            item.chunks_done = 0

        # Lưu manifest cập nhật
        cls.save_manifest(item, config, manifest_path)
        return manifest_path, is_reused

    @classmethod
    def save_manifest(cls, item: TTSItem, config: TTSConfig, manifest_path: Optional[str] = None):
        """Lưu toàn bộ metadata và trạng thái hiện tại của item vào manifest.json."""
        if not manifest_path:
            if not item.manifest_dir:
                return
            manifest_path = os.path.join(item.manifest_dir, cls.MANIFEST_FILENAME)

        text_hash = hashlib.sha256(item.raw_text.encode("utf-8")).hexdigest()
        data = {
            "version": "1.0",
            "item_id": item.item_id,
            "story_title": item.story_title,
            "author": item.author,
            "volume_num": item.volume_num,
            "start_chap": item.start_chap,
            "end_chap": item.end_chap,
            "source": item.source,
            "raw_text_hash": text_hash,
            "chunking_version": cls.CHUNKING_VERSION,
            "config_hash": config.compute_hash(),
            "config": {
                "model_name": config.model_name,
                "backend": config.backend,
                "precision": config.precision,
                "voice_id": config.voice_id,
                "sample_rate": config.sample_rate,
                "pause_sentence_ms": config.pause_sentence_ms,
                "pause_paragraph_ms": config.pause_paragraph_ms,
                "pause_chapter_ms": config.pause_chapter_ms,
                "mp3_bitrate": config.mp3_bitrate,
            },
            "status": item.status,
            "chunks_total": len(item.chunks),
            "chunks_done": item.chunks_done,
            "duration_sec": item.duration_sec,
            "output_mp3_path": item.output_mp3_path,
            "error_msg": item.error_msg,
            "chunks": [
                {
                    "index": c.index,
                    "text": c.text,
                    "text_hash": c.text_hash,
                    "char_count": c.char_count,
                    "word_count": c.word_count,
                    "paragraph_idx": c.paragraph_idx,
                    "is_chapter_boundary": c.is_chapter_boundary,
                    "wav_path": c.wav_path,
                    "duration_sec": c.duration_sec,
                    "sample_count": c.sample_count,
                    "status": c.status,
                    "error_msg": c.error_msg,
                }
                for c in item.chunks
            ],
        }

        tmp_path = manifest_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, manifest_path)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
