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
import queue
import threading
from core.video_models import AudioVideoItem, VideoConfig, EncodeResult


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


def get_subprocess_hidden_kwargs() -> Dict[str, Any]:
    """Tạo tham số ẩn hoàn toàn cửa sổ console/CMD khi chạy subprocess trên Windows."""
    kwargs: Dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        si = subprocess.STARTUPINFO()
        si.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 1)
        si.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = si
    return kwargs


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
        p1 = subprocess.run([ff_path, "-version"], capture_output=True, text=True, check=True, timeout=5, **get_subprocess_hidden_kwargs())
        ff_ver = p1.stdout.splitlines()[0] if p1.stdout else "FFmpeg OK"
    except Exception as e:
        return False, f"Không thể khởi chạy ffmpeg: {e}", ""

    try:
        p2 = subprocess.run([fp_path, "-version"], capture_output=True, text=True, check=True, timeout=5, **get_subprocess_hidden_kwargs())
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
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15, **get_subprocess_hidden_kwargs())
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


def _stop_process(p: Optional[subprocess.Popen], timeout: float = 2.5):
    """Dừng tiến trình có bảo đảm: terminate -> wait -> kill -> wait."""
    if p is None or p.poll() is not None:
        return
    try:
        p.terminate()
        try:
            p.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, Exception):
            p.kill()
            p.wait(timeout=timeout)
    except Exception:
        try:
            p.kill()
            p.wait(timeout=timeout)
        except Exception:
            pass


def _clean_temp_file(path: str):
    """Xóa file tạm an toàn sau khi tiến trình đã giải phóng handle."""
    if path and os.path.exists(path):
        for _ in range(5):
            try:
                os.remove(path)
                break
            except Exception:
                time.sleep(0.05)


def encode_video_from_frame(
    item: AudioVideoItem,
    frame_image_path: str,
    config: VideoConfig,
    on_progress: Optional[Callable[[float], None]] = None,
    check_cancel: Optional[Callable[[], bool]] = None,
) -> EncodeResult:
    """
    Mã hóa video MP4 từ ảnh khung hình tĩnh và file MP3 bằng FFmpeg.
    - Đảm bảo an toàn qua file tạm riêng .tmp.mp4 cùng thư mục đích.
    - Không xóa file cũ trước khi thay thế; bảo toàn file cũ khi thay thế thất bại.
    - Thu nhận stdout qua hàng đợi nền (non-blocking) và stderr tránh deadlock.
    - Phản ứng hủy tác vụ tức thì (trong vòng 100ms), terminate -> kill -> wait triệt để.
    - Dọn dẹp file tạm chỉ sau khi tiến trình đã hoàn toàn kết thúc.
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

    # Chế độ skip: nếu file đích đã tồn tại thì không mã hóa, trả về kết quả skipped
    if os.path.exists(final_output) and config.overwrite_mode == "skip":
        return EncodeResult(
            output_path=final_output,
            status="skipped",
            message=f"Tệp '{os.path.basename(final_output)}' đã tồn tại, bỏ qua theo cấu hình."
        )

    # Đặt file tạm độc nhất trong cùng thư mục đích để đảm bảo os.replace là atomic trên cùng volume
    temp_filename = f".tmp_{os.path.splitext(os.path.basename(final_output))[0]}_{os.getpid()}_{int(time.time()*1000)}.mp4"
    temp_output = os.path.join(out_dir, temp_filename)

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

    stdout_queue: queue.Queue = queue.Queue()
    stderr_lines: List[str] = []
    proc: Optional[subprocess.Popen] = None

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            **get_subprocess_hidden_kwargs(),
        )

        def _drain_stdout():
            try:
                if proc and proc.stdout:
                    for s_line in iter(proc.stdout.readline, ""):
                        stdout_queue.put(s_line)
            except Exception:
                pass
            finally:
                stdout_queue.put(None)

        def _drain_stderr():
            try:
                if proc and proc.stderr:
                    for s_line in iter(proc.stderr.readline, ""):
                        stderr_lines.append(s_line)
                        if len(stderr_lines) > 200:
                            stderr_lines.pop(0)
            except Exception:
                pass

        t_stdout = threading.Thread(target=_drain_stdout, daemon=True)
        t_stderr = threading.Thread(target=_drain_stderr, daemon=True)
        t_stdout.start()
        t_stderr.start()

        # Vòng lặp nhận dữ liệu không bị chặn vô hạn khi kiểm tra hủy
        while True:
            if check_cancel and check_cancel():
                _stop_process(proc)
                _clean_temp_file(temp_output)
                raise RuntimeError("Tác vụ xuất video đã bị người dùng hủy.")

            try:
                line = stdout_queue.get(timeout=0.1)
            except queue.Empty:
                if proc.poll() is not None:
                    break
                continue

            if line is None:
                # Kênh stdout đã kết thúc
                break

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
        t_stdout.join(timeout=1.0)
        t_stderr.join(timeout=1.0)

        if check_cancel and check_cancel():
            _clean_temp_file(temp_output)
            raise RuntimeError("Tác vụ xuất video đã bị người dùng hủy.")

        if ret != 0:
            err_details = "".join(stderr_lines)[-500:]
            _clean_temp_file(temp_output)
            raise RuntimeError(f"FFmpeg kết thúc với mã lỗi {ret}: {err_details}")

        # Xác minh chất lượng tệp MP4 qua ffprobe
        if not os.path.isfile(temp_output) or os.path.getsize(temp_output) == 0:
            _clean_temp_file(temp_output)
            raise RuntimeError("Tệp video xuất ra bị rỗng hoặc không tồn tại.")

        probe_res = probe_media(temp_output, fp_bin)
        if not probe_res.get("has_video"):
            _clean_temp_file(temp_output)
            raise RuntimeError("Tệp xuất ra không chứa luồng Video hợp lệ.")
        if not probe_res.get("has_audio"):
            _clean_temp_file(temp_output)
            raise RuntimeError("Tệp xuất ra không chứa luồng Audio hợp lệ.")

        # Cho phép sai số thời lượng nhỏ (< 2 giây do căn chỉnh khung hình)
        diff = abs(probe_res["duration"] - audio_dur)
        if diff > 2.0 and audio_dur > 5.0:
            _clean_temp_file(temp_output)
            raise RuntimeError(
                f"Thời lượng video ({probe_res['duration']:.2f}s) lệch quá nhiều so với audio ({audio_dur:.2f}s)."
            )

        # Thay thế nguyên tử: KHÔNG xóa file hoàn chỉnh cũ trước.
        # os.replace sẽ thay thế đích atomically. Nếu thất bại, file cũ vẫn còn nguyên.
        try:
            os.replace(temp_output, final_output)
        except PermissionError as e:
            _clean_temp_file(temp_output)
            raise PermissionError(
                f"Không thể ghi đè file đích '{final_output}'. File có thể đang được mở bởi ứng dụng khác hoặc thiếu quyền ghi: {e}"
            )
        except Exception as e:
            _clean_temp_file(temp_output)
            raise OSError(f"Lỗi khi thay thế file kết quả sang '{final_output}': {e}")

        if on_progress:
            on_progress(100.0)

        return EncodeResult(output_path=final_output, status="completed", message="Xuất thành công")

    except Exception:
        if proc and proc.poll() is None:
            _stop_process(proc)
        _clean_temp_file(temp_output)
        raise
    finally:
        if proc:
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
        _clean_temp_file(temp_output)
