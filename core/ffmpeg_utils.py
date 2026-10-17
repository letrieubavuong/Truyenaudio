"""
FFmpeg and ffprobe wrapper utilities for Video Production:
- Robust discovery on Windows and other OSes.
- Probing media via ffprobe without trusting file extensions.
- Video encoding via subprocess with argument list (shell=False).
- Machine-readable progress tracking via -progress pipe:1.
- Cancellation with resource cleanup and temporary file safety (.tmp.mp4).
- Verification of output video and audio streams before final atomic rename.
"""
import os
import sys
import shutil
import subprocess
import json
import re
import time
from typing import Dict, Any, Tuple, Optional, Callable, List
from core.video_models import AudioVideoItem, VideoConfig


def find_ffmpeg(custom_ffmpeg: str = "", custom_ffprobe: str = "") -> Tuple[str, str]:
    """
    Tìm vị trí thực thi của ffmpeg và ffprobe.
    Ưu tiên đường dẫn cấu hình -> PATH -> Các thư mục cài đặt thông dụng trên Windows.
    """
    ffmpeg_bin = ""
    ffprobe_bin = ""

    # 1. Kiểm tra custom path nếu được chỉ định
    if custom_ffmpeg and os.path.isfile(custom_ffmpeg):
        ffmpeg_bin = custom_ffmpeg
    if custom_ffprobe and os.path.isfile(custom_ffprobe):
        ffprobe_bin = custom_ffprobe

    # 2. Tìm trong PATH
    if not ffmpeg_bin:
        w_ff = shutil.which("ffmpeg")
        if w_ff:
            ffmpeg_bin = w_ff
    if not ffprobe_bin:
        w_fp = shutil.which("ffprobe")
        if w_fp:
            ffprobe_bin = w_fp

    # 3. Tìm các đường dẫn Windows thông dụng
    common_win_dirs = [
        r"C:\ffmpeg\bin",
        r"C:\Program Files\ffmpeg\bin",
        r"C:\Program Files (x86)\ffmpeg\bin",
        os.path.expanduser(r"~\ffmpeg\bin"),
        os.path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Links"),
    ]

    for d in common_win_dirs:
        if not ffmpeg_bin:
            cand = os.path.join(d, "ffmpeg.exe")
            if os.path.isfile(cand):
                ffmpeg_bin = cand
        if not ffprobe_bin:
            cand = os.path.join(d, "ffprobe.exe")
            if os.path.isfile(cand):
                ffprobe_bin = cand

    return ffmpeg_bin, ffprobe_bin


def check_ffmpeg_installed(custom_ffmpeg: str = "", custom_ffprobe: str = "") -> Tuple[bool, str, str]:
    """
    Kiểm tra ffmpeg và ffprobe có hoạt động không.
    Trả về: (is_ok, ffmpeg_version_or_err, ffprobe_version_or_err)
    """
    ff_path, fp_path = find_ffmpeg(custom_ffmpeg, custom_ffprobe)

    if not ff_path:
        return False, "Không tìm thấy ffmpeg trên hệ thống hoặc trong PATH.", ""
    if not fp_path:
        return False, f"Tìm thấy ffmpeg ({ff_path}) nhưng thiếu ffprobe.", ""

    try:
        p1 = subprocess.run([ff_path, "-version"], capture_output=True, text=True, check=True, timeout=5)
        ff_ver = p1.stdout.splitlines()[0] if p1.stdout else "FFmpeg OK"
    except Exception as e:
        return False, f"Không thể khởi chạy ffmpeg: {e}", ""

    try:
        p2 = subprocess.run([fp_path, "-version"], capture_output=True, text=True, check=True, timeout=5)
        fp_ver = p2.stdout.splitlines()[0] if p2.stdout else "ffprobe OK"
    except Exception as e:
        return False, ff_ver, f"Không thể khởi chạy ffprobe: {e}"

    return True, ff_ver, fp_ver


def probe_media(filepath: str, ffprobe_path: str = "") -> Dict[str, Any]:
    """
    Dùng ffprobe trích xuất thông tin media thực tế (không chỉ tin vào đuôi mở rộng).
    Trả về dict gồm:
        - duration: float
        - size: int
        - bit_rate: int
        - has_audio: bool
        - has_video: bool
        - video_codec: str
        - audio_codec: str
        - width: int
        - height: int
        - sample_rate: int
        - channels: int
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Tệp không tồn tại: {filepath}")

    _, fp_bin = find_ffmpeg("", ffprobe_path)
    if not fp_bin:
        raise RuntimeError("Không tìm thấy công cụ ffprobe để kiểm tra tệp tin.")

    cmd = [
        fp_bin,
        "-v", "error",
        "-show_entries", "format=duration,size,bit_rate:stream=codec_type,codec_name,width,height,channels,sample_rate",
        "-print_format", "json",
        filepath,
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15)
        data = json.loads(proc.stdout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ffprobe quá thời gian chờ khi đọc tệp: {filepath}")
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr.strip() if e.stderr else str(e)
        raise RuntimeError(f"ffprobe báo lỗi khi đọc tệp '{filepath}': {err_msg}")
    except json.JSONDecodeError:
        raise RuntimeError(f"Không thể phân tích dữ liệu JSON từ ffprobe cho tệp: {filepath}")

    fmt = data.get("format", {})
    streams = data.get("streams", [])

    duration = float(fmt.get("duration", 0.0) or 0.0)
    size = int(fmt.get("size", 0) or 0)
    bit_rate = int(fmt.get("bit_rate", 0) or 0)

    has_video = False
    has_audio = False
    video_codec = ""
    audio_codec = ""
    width = 0
    height = 0
    channels = 0
    sample_rate = 0

    for s in streams:
        c_type = s.get("codec_type")
        if c_type == "video" and not has_video:
            # Bỏ qua stream đính kèm thumbnail ảnh trong MP3 (attached_pic)
            if s.get("disposition", {}).get("attached_pic") != 1:
                has_video = True
                video_codec = s.get("codec_name", "")
                width = int(s.get("width", 0) or 0)
                height = int(s.get("height", 0) or 0)
        elif c_type == "audio" and not has_audio:
            has_audio = True
            audio_codec = s.get("codec_name", "")
            channels = int(s.get("channels", 0) or 0)
            sample_rate = int(s.get("sample_rate", 0) or 0)

    return {
        "duration": duration,
        "size": size,
        "bit_rate": bit_rate,
        "has_audio": has_audio,
        "has_video": has_video,
        "video_codec": video_codec,
        "audio_codec": audio_codec,
        "width": width,
        "height": height,
        "channels": channels,
        "sample_rate": sample_rate,
    }


def resolve_output_filename(dest_dir: str, base_filename: str, overwrite_mode: str) -> str:
    """
    Xác định tên tệp đích theo chính sách ghi đè: 'overwrite', 'skip', 'rename'.
    """
    os.makedirs(dest_dir, exist_ok=True)
    target = os.path.join(dest_dir, base_filename)
    if not os.path.exists(target) or overwrite_mode == "overwrite":
        return target

    if overwrite_mode == "skip":
        return target

    # Mode: rename
    name, ext = os.path.splitext(base_filename)
    idx = 1
    while True:
        cand = os.path.join(dest_dir, f"{name}_{idx}{ext}")
        if not os.path.exists(cand):
            return cand
        idx += 1


def encode_video_from_frame(
    item: AudioVideoItem,
    frame_image_path: str,
    config: VideoConfig,
    on_progress: Optional[Callable[[float], None]] = None,
    check_cancel: Optional[Callable[[], bool]] = None,
) -> str:
    """
    Mã hóa video MP4 từ ảnh khung hình tĩnh và file MP3 bằng FFmpeg.
    - Đảm bảo an toàn qua file tạm .tmp.mp4.
    - Kiểm tra tiến độ machine-readable (-progress pipe:1).
    - Hỗ trợ dừng / hủy tác vụ và dọn file tạm.
    - Xác minh video/audio stream và thời lượng bằng ffprobe trước khi hoàn tất.
    """
    ff_bin, fp_bin = find_ffmpeg(config.ffmpeg_path, config.ffprobe_path)
    if not ff_bin:
        raise RuntimeError("Không tìm thấy công cụ FFmpeg để xuất video. Vui lòng kiểm tra cấu hình.")

    if not os.path.isfile(item.audio_path):
        raise FileNotFoundError(f"Tệp audio nguồn không tồn tại: {item.audio_path}")
    if not os.path.isfile(frame_image_path):
        raise FileNotFoundError(f"Tệp khung hình kết xuất không tồn tại: {frame_image_path}")

    # Xác định thư mục và tên tệp đầu ra
    out_dir = config.output_dir or "output_videos"
    os.makedirs(out_dir, exist_ok=True)

    base_name = item.suggested_output_filename()
    final_output = resolve_output_filename(out_dir, base_name, config.overwrite_mode)

    if os.path.exists(final_output) and config.overwrite_mode == "skip":
        if on_progress:
            on_progress(100.0)
        return final_output

    temp_output = final_output + ".tmp.mp4"

    # Xóa file tạm cũ nếu còn sót lại từ lần chạy trước
    if os.path.exists(temp_output):
        try:
            os.remove(temp_output)
        except Exception:
            pass

    # Lấy thời lượng audio chuẩn xác
    audio_dur = item.duration
    if audio_dur <= 0:
        info = probe_media(item.audio_path, fp_bin)
        audio_dur = info["duration"]
        item.duration = audio_dur

    if audio_dur <= 0:
        audio_dur = 1.0  # Fallback tối thiểu

    cmd = [
        ff_bin,
        "-y",
        "-loop", "1",
        "-framerate", "1",
        "-i", frame_image_path,
        "-i", item.audio_path,
        "-c:v", "libx264",
        "-tune", "stillimage",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", config.audio_bitrate or "192k",
        "-shortest",
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        temp_output,
    ]

    import threading

    stderr_lines: List[str] = []

    def _drain_stderr():
        try:
            for s_line in proc.stderr:
                stderr_lines.append(s_line)
                if len(stderr_lines) > 200:
                    stderr_lines.pop(0)
        except Exception:
            pass

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )

    t_err = threading.Thread(target=_drain_stderr, daemon=True)
    t_err.start()

    try:
        while True:
            if check_cancel and check_cancel():
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                if os.path.exists(temp_output):
                    try:
                        os.remove(temp_output)
                    except Exception:
                        pass
                raise RuntimeError("Tác vụ xuất video đã bị người dùng hủy.")

            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                time.sleep(0.02)
                continue

            line = line.strip()
            # Bắt tiến độ máy đọc: out_time_us=... hoặc out_time_ms=... hoặc out_time=00:01:23.456
            if line.startswith("out_time_us="):
                try:
                    us = int(line.split("=")[1])
                    curr_sec = us / 1_000_000.0
                    pct = min(99.0, (curr_sec / audio_dur) * 100.0)
                    if on_progress:
                        on_progress(pct)
                except Exception:
                    pass
            elif line.startswith("out_time_ms="):
                try:
                    ms = int(line.split("=")[1])
                    curr_sec = ms / 1_000_000.0 if ms > 1000000 else ms / 1000.0
                    pct = min(99.0, (curr_sec / audio_dur) * 100.0)
                    if on_progress:
                        on_progress(pct)
                except Exception:
                    pass
            elif line.startswith("progress=end"):
                if on_progress:
                    on_progress(99.0)

        ret = proc.wait()
        t_err.join(timeout=1.0)
        if ret != 0:
            err_details = "".join(stderr_lines)[-500:]
            if os.path.exists(temp_output):
                try:
                    os.remove(temp_output)
                except Exception:
                    pass
            raise RuntimeError(f"FFmpeg kết thúc với mã lỗi {ret}: {err_details}")

    except Exception:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
        if os.path.exists(temp_output):
            try:
                os.remove(temp_output)
            except Exception:
                pass
        raise
    finally:
        try:
            if proc.stdout:
                proc.stdout.close()
        except Exception:
            pass
        try:
            if proc.stderr:
                proc.stderr.close()
        except Exception:
            pass

    # 4. Xác minh chất lượng tệp MP4 qua ffprobe
    if not os.path.isfile(temp_output) or os.path.getsize(temp_output) == 0:
        raise RuntimeError("Tệp video xuất ra bị rỗng hoặc không tồn tại.")

    probe_res = probe_media(temp_output, fp_bin)
    if not probe_res["has_video"]:
        os.remove(temp_output)
        raise RuntimeError("Tệp xuất ra không chứa luồng Video hợp lệ.")
    if not probe_res["has_audio"]:
        os.remove(temp_output)
        raise RuntimeError("Tệp xuất ra không chứa luồng Audio hợp lệ.")

    # Cho phép sai số thời lượng nhỏ (< 1.5 giây do căn chỉnh khung hình)
    diff = abs(probe_res["duration"] - audio_dur)
    if diff > 2.0 and audio_dur > 5.0:
        os.remove(temp_output)
        raise RuntimeError(
            f"Thời lượng video ({probe_res['duration']:.2f}s) lệch quá nhiều so với audio ({audio_dur:.2f}s)."
        )

    # 5. Đổi tên nguyên tử sang tệp chính thức
    if os.path.exists(final_output):
        try:
            os.remove(final_output)
        except Exception as e:
            pass

    os.replace(temp_output, final_output)

    if on_progress:
        on_progress(100.0)

    return final_output
