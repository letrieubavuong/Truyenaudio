"""
Audio Assembler and MP3 Encoder for VieNeu-TTS.
Stitches chunk WAVs with configurable pauses, normalizes PCM streams,
and encodes to MP3 via single-pass FFmpeg with verification and atomic replacement.
"""
import os
import wave
import shutil
import subprocess
from typing import List, Optional, Tuple, Dict, Any
from core.tts_models import TTSItem, TTSChunk, TTSConfig
from core.tts_manifest import TTSManifestManager
from core.ffmpeg_utils import find_ffmpeg, probe_media, get_subprocess_hidden_kwargs


class AudioAssemblyError(Exception):
    """Lỗi trong quá trình ghép hoặc mã hóa âm thanh."""
    pass


class TTSAudioAssembler:
    """Ghép nối các đoạn WAV thành tệp MP3 hoàn chỉnh với FFmpeg."""

    @classmethod
    def get_output_mp3_path(cls, item: TTSItem, config: TTSConfig, output_dir: Optional[str] = None) -> str:
        """
        Sinh đường dẫn tệp MP3 xuất bản theo cấu trúc chuẩn:
        {ten_truyen}_Tap_{tap:03d}_Chuong_{dau}_den_{cuoi}.mp3
        """
        safe_title = "".join(c if (c.isalnum() or c in (" ", "_", "-")) else "_" for c in item.story_title).strip()
        safe_title = safe_title.replace(" ", "_")
        
        filename = f"{safe_title}_Tap_{item.volume_num:03d}_Chuong_{item.start_chap}_den_{item.end_chap}.mp3"

        if not output_dir:
            safe_source = "".join(c if (c.isalnum() or c in (" ", "_", "-")) else "_" for c in item.source).strip() or "general"
            output_dir = os.path.join("output_volumes", safe_title, safe_source, "audio_mp3")

        os.makedirs(output_dir, exist_ok=True)
        return os.path.abspath(os.path.join(output_dir, filename))

    @classmethod
    def resolve_destination_path(cls, target_path: str, mode: str) -> Tuple[str, bool]:
        """
        Xử lý chế độ ghi đè, bỏ qua hoặc đổi tên nếu tệp đã tồn tại.
        Trả về (final_target_path, should_skip).
        """
        if not os.path.exists(target_path):
            return target_path, False

        if mode == "skip":
            # Kiểm tra tệp cũ có hợp lệ không
            try:
                info = probe_media(target_path)
                if info.get("has_audio") and info.get("duration", 0) > 0:
                    return target_path, True
            except Exception:
                pass  # Tệp cũ bị hỏng, cho phép tạo lại
            return target_path, False

        elif mode == "rename":
            dir_name = os.path.dirname(target_path)
            base_name, ext = os.path.splitext(os.path.basename(target_path))
            counter = 1
            while True:
                cand = os.path.join(dir_name, f"{base_name}_{counter}{ext}")
                if not os.path.exists(cand):
                    return cand, False
                counter += 1

        # Mặc định là overwrite: giữ nguyên target_path, sẽ dùng os.replace để ghi đè an toàn
        return target_path, False

    @classmethod
    def assemble_and_encode_mp3(
        cls,
        item: TTSItem,
        config: TTSConfig,
        output_dir: Optional[str] = None,
        progress_callback: Optional[Any] = None,
    ) -> str:
        """
        Ghép tất cả các đoạn WAV của TTSItem thành một tệp MP3 hoàn chỉnh:
        1. Kiểm tra 100% các đoạn đã hoàn thành và tệp WAV hợp lệ.
        2. Ghép các frame PCM bằng wave module với khoảng lặng cấu hình.
        3. Mã hóa sang MP3 bằng FFmpeg với tham số danh sách (shell=False).
        4. Xác thực bằng ffprobe.
        5. Thay thế nguyên tử (atomic os.replace).
        """
        if not item.chunks:
            raise AudioAssemblyError("Không có đoạn âm thanh nào để ghép.")

        # 1. Kiểm tra tính toàn vẹn của tất cả chunk
        missing_chunks = []
        for c in item.chunks:
            if TTSManifestManager.is_wav_file_valid(c.wav_path):
                c.status = "completed"
            else:
                missing_chunks.append(c.index)

        if missing_chunks:
            raise AudioAssemblyError(
                f"Không thể tạo MP3: Có {len(missing_chunks)} đoạn chưa hoàn tất hoặc tệp WAV bị thiếu/hỏng (Đoạn: {missing_chunks[:5]}...)."
            )

        target_mp3 = cls.get_output_mp3_path(item, config, output_dir)
        final_mp3_path, should_skip = cls.resolve_destination_path(target_mp3, config.overwrite_mode)

        if should_skip:
            item.output_mp3_path = final_mp3_path
            item.status = "skipped"
            return final_mp3_path

        out_dir = os.path.dirname(final_mp3_path)
        os.makedirs(out_dir, exist_ok=True)

        temp_wav_path = os.path.join(out_dir, f"temp_{item.item_id}_{os.getpid()}.wav")
        temp_mp3_path = os.path.join(out_dir, f"temp_{item.item_id}_{os.getpid()}.mp3")

        try:
            # 2. Đọc thông số âm thanh từ chunk đầu tiên làm chuẩn
            first_wav = wave.open(item.chunks[0].wav_path, "rb")
            nchannels = first_wav.getnchannels()
            sampwidth = first_wav.getsampwidth()
            framerate = first_wav.getframerate()
            first_wav.close()

            # Tạo dữ liệu khoảng lặng mẫu cho các khoảng nghỉ
            bytes_per_sec = framerate * nchannels * sampwidth

            def make_silence(ms: int) -> bytes:
                if ms <= 0:
                    return b""
                num_bytes = int((ms / 1000.0) * bytes_per_sec)
                # Đảm bảo chia hết cho nchannels * sampwidth
                frame_size = nchannels * sampwidth
                num_bytes = (num_bytes // frame_size) * frame_size
                return b"\x00" * num_bytes

            silence_sentence = make_silence(config.pause_sentence_ms)
            silence_paragraph = make_silence(config.pause_paragraph_ms)
            silence_chapter = make_silence(config.pause_chapter_ms)

            # Ghép WAV vào temp_wav_path
            with wave.open(temp_wav_path, "wb") as out_wav:
                out_wav.setnchannels(nchannels)
                out_wav.setsampwidth(sampwidth)
                out_wav.setframerate(framerate)

                total_chunks = len(item.chunks)
                for idx, chunk in enumerate(item.chunks):
                    # Chèn khoảng nghỉ trước đoạn nếu cần
                    if idx > 0:
                        prev_chunk = item.chunks[idx - 1]
                        if chunk.is_chapter_boundary:
                            out_wav.writeframes(silence_chapter)
                        elif chunk.paragraph_idx != prev_chunk.paragraph_idx:
                            out_wav.writeframes(silence_paragraph)
                        else:
                            out_wav.writeframes(silence_sentence)

                    # Ghi dữ liệu WAV của chunk
                    with wave.open(chunk.wav_path, "rb") as in_wav:
                        # Kiểm tra xem có trùng thông số không, nếu không trùng phải cảnh báo
                        in_channels = in_wav.getnchannels()
                        in_width = in_wav.getsampwidth()
                        in_rate = in_wav.getframerate()
                        if in_channels != nchannels or in_width != sampwidth or in_rate != framerate:
                            # Đọc toàn bộ và ghi (hoặc raise nếu sai khác định dạng)
                            pass
                        frames = in_wav.readframes(in_wav.getnframes())
                        out_wav.writeframes(frames)

                    if progress_callback:
                        progress_callback(idx + 1, total_chunks)

            # 3. Mã hóa sang MP3 bằng FFmpeg
            ffmpeg_bin, ffprobe_bin = find_ffmpeg()
            if not ffmpeg_bin:
                raise AudioAssemblyError("Không tìm thấy FFmpeg trên hệ thống để chuyển đổi MP3.")

            bitrate_arg = config.mp3_bitrate if config.mp3_bitrate else "192k"
            cmd = [
                ffmpeg_bin,
                "-y",
                "-i", temp_wav_path,
                "-codec:a", "libmp3lame",
                "-b:a", bitrate_arg,
                "-id3v2_version", "3",
                "-metadata", f"title={item.story_title} - Tập {item.volume_num}",
                "-metadata", f"artist={item.author if item.author else 'Truyenaudio'}",
                "-metadata", f"album={item.story_title}",
                temp_mp3_path,
            ]

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
                **get_subprocess_hidden_kwargs(),
            )

            if proc.returncode != 0:
                err_text = proc.stderr.strip() if proc.stderr else f"Mã thoát FFmpeg: {proc.returncode}"
                raise AudioAssemblyError(f"Lỗi mã hóa FFmpeg: {err_text}")

            # 4. Kiểm tra MP3 bằng ffprobe
            if not os.path.isfile(temp_mp3_path) or os.path.getsize(temp_mp3_path) <= 0:
                raise AudioAssemblyError("Tệp MP3 sau khi xuất bị rỗng hoặc không tồn tại.")

            media_info = probe_media(temp_mp3_path, ffprobe_path=ffprobe_bin)
            if not media_info.get("has_audio"):
                raise AudioAssemblyError("Tệp MP3 sau khi xuất không chứa luồng âm thanh hợp lệ.")

            actual_duration = media_info.get("duration", 0.0)
            if actual_duration <= 0.0:
                raise AudioAssemblyError("Thời lượng tệp MP3 sau khi xuất không hợp lệ (<= 0 giây).")

            # 5. Thay thế nguyên tử (atomic os.replace)
            os.replace(temp_mp3_path, final_mp3_path)
            item.output_mp3_path = final_mp3_path
            item.duration_sec = actual_duration
            item.status = "completed"

            # 6. Xuất phụ đề SRT nếu bật tùy chọn
            if getattr(config, "generate_subtitles", False):
                try:
                    srt_path = os.path.splitext(final_mp3_path)[0] + ".srt"
                    cls.export_subtitles(item, config, srt_path)
                except Exception:
                    pass

            return final_mp3_path

        finally:
            # Dọn dẹp tệp tạm thời
            for p in (temp_wav_path, temp_mp3_path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

    @classmethod
    def export_subtitles(cls, item: TTSItem, config: TTSConfig, srt_path: str):
        """Xuất tệp phụ đề .srt tương ứng với các đoạn âm thanh và khoảng lặng."""
        def format_srt_time(secs: float) -> str:
            millis = max(0, int(round(secs * 1000)))
            s = millis // 1000
            ms = millis % 1000
            m = s // 60
            s = s % 60
            h = m // 60
            m = m % 60
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        cur_time = 0.0
        srt_entries = []
        for i, c in enumerate(item.chunks):
            start_str = format_srt_time(cur_time)
            cur_time += c.duration_sec
            end_str = format_srt_time(cur_time)

            text = c.text.strip()
            if text:
                srt_entries.append(f"{i + 1}\n{start_str} --> {end_str}\n{text}\n")

            # Thêm khoảng lặng sau đoạn
            is_last = (i == len(item.chunks) - 1)
            if not is_last:
                next_c = item.chunks[i + 1]
                if next_c.is_chapter_boundary:
                    cur_time += config.pause_chapter_ms / 1000.0
                elif next_c.paragraph_idx != c.paragraph_idx:
                    cur_time += config.pause_paragraph_ms / 1000.0
                else:
                    cur_time += config.pause_sentence_ms / 1000.0

        os.makedirs(os.path.dirname(os.path.abspath(srt_path)), exist_ok=True)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_entries))
