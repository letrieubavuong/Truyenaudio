"""
Independent Worker Process for VieNeu-TTS Engine.
Runs in a dedicated Python environment, isolated from the main GUI/PyInstaller application.
Loads model once per queue, executes chunk inference, and reports structured progress via stdout JSON-lines.
Supports dual backends:
1. Native VieNeu-TTS (ONNX/PyTorch on Python 3.10-3.12)
2. Neural Cloud Fallback via Edge-TTS with 48kHz WAV conversion (Python 3.10-3.14+)
3. Synthetic harmonic tone generator for mock/testing
"""
import os
import sys
import re
import json
import time
import math
import wave
import struct
import shutil
import argparse
import traceback
import subprocess
from typing import Dict, Any, List, Optional, Tuple

# Đảm bảo stdout và stderr luôn là UTF-8 trên Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


# ==============================================================================
# BẢNG ÁNH XẠ GIỌNG ĐỌC CHO NEURAL CLOUD BACKEND (EDGE-TTS)
# ==============================================================================
VOICE_MAP: Dict[str, Tuple[str, str]] = {
    # Nữ (vi-VN-HoaiMyNeural) kèm cao độ tinh chỉnh
    "trúc ly": ("vi-VN-HoaiMyNeural", "+0Hz"),
    "mai anh": ("vi-VN-HoaiMyNeural", "+3Hz"),
    "thùy dung": ("vi-VN-HoaiMyNeural", "+2Hz"),
    "thu hà": ("vi-VN-HoaiMyNeural", "-2Hz"),
    "thanh trúc": ("vi-VN-HoaiMyNeural", "+4Hz"),
    "bảo ngọc": ("vi-VN-HoaiMyNeural", "+5Hz"),
    "hoài an": ("vi-VN-HoaiMyNeural", "-1Hz"),
    "ngọc huyền": ("vi-VN-HoaiMyNeural", "+1Hz"),
    "quỳnh nga": ("vi-VN-HoaiMyNeural", "+2Hz"),
    "phương linh": ("vi-VN-HoaiMyNeural", "+3Hz"),
    "hương giang": ("vi-VN-HoaiMyNeural", "-3Hz"),
    "diễm my": ("vi-VN-HoaiMyNeural", "+2Hz"),
    "kim ngân": ("vi-VN-HoaiMyNeural", "+6Hz"),

    # Nam (vi-VN-NamMinhNeural) kèm cao độ tinh chỉnh
    "hải đăng": ("vi-VN-NamMinhNeural", "+0Hz"),
    "adam bựa": ("vi-VN-NamMinhNeural", "-4Hz"),
    "thiện minh": ("vi-VN-NamMinhNeural", "-2Hz"),
    "minh quang": ("vi-VN-NamMinhNeural", "-3Hz"),
    "tuấn anh": ("vi-VN-NamMinhNeural", "+1Hz"),
    "mạnh cường": ("vi-VN-NamMinhNeural", "-5Hz"),
    "duy khang": ("vi-VN-NamMinhNeural", "+2Hz"),
    "minh hoàng": ("vi-VN-NamMinhNeural", "-1Hz"),
    "thanh tùng": ("vi-VN-NamMinhNeural", "-4Hz"),
    "bảo quốc": ("vi-VN-NamMinhNeural", "-2Hz"),
    "hùng dũng": ("vi-VN-NamMinhNeural", "-3Hz"),
    "đức thắng": ("vi-VN-NamMinhNeural", "-2Hz"),
}


def sanitize_tts_text(text: str) -> str:
    """Chuyển đổi hoặc loại bỏ emotion tags trước khi nạp vào TTS engine."""
    if not text:
        return ""
    # Chuyển tag nghỉ thành dấu chấm lửng
    t = re.sub(r"\[nghỉ\s*\d+s?\]", r" ... ", text, flags=re.IGNORECASE)
    # Loại bỏ hoặc làm mượt tag cảm xúc [cười], [thở dài], [hắng giọng]
    t = re.sub(r"\[(cười|thở dài|hắng giọng|khóc|ngạc nhiên|tức giận)\]", r" ... ", t, flags=re.IGNORECASE)
    # Chuẩn hóa khoảng trắng
    t = re.sub(r"[ \t]+", " ", t).strip()
    return t


def map_voice_profile(voice_id: str) -> Tuple[str, str]:
    """Ánh xạ voice_id sang voice engine và pitch tương ứng."""
    key = (voice_id or "").strip().lower()
    if key in VOICE_MAP:
        return VOICE_MAP[key]
    if any(w in key for w in ("nữ", "female", "gái", "bà", "cô", "chị")):
        return "vi-VN-HoaiMyNeural", "+0Hz"
    return "vi-VN-NamMinhNeural", "+0Hz"


def _find_ffmpeg_bin() -> str:
    """Tìm đường dẫn tệp thực thi FFmpeg trên hệ thống."""
    try:
        from core.ffmpeg_utils import find_ffmpeg
        ff, _ = find_ffmpeg()
        if ff and os.path.isfile(ff):
            return ff
    except Exception:
        pass

    for cand in [
        shutil.which("ffmpeg"),
        r"C:\ffmpeg\bin\ffmpeg.EXE",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    ]:
        if cand and os.path.isfile(cand):
            return cand
    return ""


def _generate_synthetic_wav(wav_path: str, duration_sec: float = 0.5, sample_rate: int = 48000):
    """Tạo tệp WAV PCM 16-bit phát ra chuỗi âm thanh hài hòa dịu êm cho chế độ mock/kiểm thử."""
    os.makedirs(os.path.dirname(os.path.abspath(wav_path)), exist_ok=True)
    num_samples = int(sample_rate * duration_sec)
    frames = bytearray()
    fade_len = int(0.04 * sample_rate)

    for i in range(num_samples):
        t = i / sample_rate
        # Phong bì âm lượng (fade-in / fade-out)
        env = 1.0
        if i < fade_len:
            env = i / fade_len
        elif i > num_samples - fade_len:
            env = (num_samples - i) / fade_len

        # Giao thoa sóng sine 330Hz (Mi) và 440Hz (La) tạo âm sắc dễ chịu
        val = 0.22 * (math.sin(2 * math.pi * 330 * t) + 0.5 * math.sin(2 * math.pi * 440 * t)) * env
        sample = int(val * 32767)
        frames.extend(struct.pack("<h", max(-32768, min(32767, sample))))

    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(frames)


def _synthesize_edge_tts(
    text: str,
    voice_id: str,
    speed: float,
    out_wav: str,
    sample_rate: int = 48000,
):
    """Tổng hợp giọng đọc tiếng Việt bằng Edge-TTS và xuất WAV 48kHz chuẩn."""
    clean_txt = sanitize_tts_text(text)
    if not clean_txt:
        _generate_synthetic_wav(out_wav, duration_sec=0.2, sample_rate=sample_rate)
        return

    import asyncio
    import edge_tts

    edge_voice, pitch_str = map_voice_profile(voice_id)
    pct = int(round((speed - 1.0) * 100))
    rate_str = f"{pct:+d}%" if pct != 0 else "+0%"

    os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
    tmp_mp3 = out_wav + f".tmp_{os.getpid()}_{int(time.time() * 1000)}.mp3"

    async def _async_gen():
        comm = edge_tts.Communicate(
            text=clean_txt,
            voice=edge_voice,
            rate=rate_str,
            pitch=pitch_str,
        )
        await comm.save(tmp_mp3)

    try:
        asyncio.run(_async_gen())
    except Exception as e:
        if os.path.exists(tmp_mp3):
            try:
                os.remove(tmp_mp3)
            except Exception:
                pass
        raise RuntimeError(f"Edge-TTS synthesis error: {e}")

    ff_bin = _find_ffmpeg_bin()
    if not ff_bin:
        if os.path.exists(tmp_mp3):
            try:
                os.remove(tmp_mp3)
            except Exception:
                pass
        raise RuntimeError("Không tìm thấy FFmpeg để chuyển đổi âm thanh sang định dạng WAV 48kHz.")

    cmd = [ff_bin, "-y", "-i", tmp_mp3, "-ar", str(sample_rate), "-ac", "1", out_wav]
    extra_kwargs: Dict[str, Any] = {}
    if sys.platform == "win32":
        extra_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        si = subprocess.STARTUPINFO()
        si.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 1)
        si.wShowWindow = 0  # SW_HIDE
        extra_kwargs["startupinfo"] = si

    proc = subprocess.run(cmd, capture_output=True, text=True, **extra_kwargs)

    if os.path.exists(tmp_mp3):
        try:
            os.remove(tmp_mp3)
        except Exception:
            pass

    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg chuyển đổi WAV thất bại: {proc.stderr.strip()}")


def check_environment() -> Dict[str, Any]:
    """Kiểm tra môi trường Python TTS và khả năng của các động cơ khả dụng."""
    result: Dict[str, Any] = {
        "available": False,
        "engine_type": "none",
        "python_path": sys.executable,
        "sdk_version": "",
        "backends": [],
        "current_backend": "cpu",
        "cuda_available": False,
        "device_name": "CPU",
        "voices": [],
        "models": ["v3_turbo", "v3nano"],
        "default_model": "v3_turbo",
        "error_message": "",
    }

    # Danh sách 25 giọng chuẩn tiếng Việt
    default_preset = [
        {"voice_id": "Hải Đăng", "display_name": "Hải Đăng (Nam miền Bắc)", "gender": "Nam", "description": "Trầm ấm, truyền cảm"},
        {"voice_id": "Adam bựa", "display_name": "Adam bựa (Nam miền Bắc)", "gender": "Nam", "description": "Hài hước, tự nhiên"},
        {"voice_id": "Trúc Ly", "display_name": "Trúc Ly (Nữ miền Bắc)", "gender": "Nữ", "description": "Trong trẻo, chuẩn mực"},
        {"voice_id": "Thiện Minh", "display_name": "Thiện Minh (Nam miền Bắc)", "gender": "Nam", "description": "Phong cách kể chuyện"},
        {"voice_id": "Mai Anh", "display_name": "Mai Anh (Nữ miền Bắc)", "gender": "Nữ", "description": "Rõ ràng, tin tức"},
        {"voice_id": "Thùy Dung", "display_name": "Thùy Dung (Nữ miền Nam)", "gender": "Nữ", "description": "Ngọt ngào, truyền cảm"},
        {"voice_id": "Minh Quang", "display_name": "Minh Quang (Nam miền Bắc)", "gender": "Nam", "description": "Rõ ràng, dứt khoát"},
        {"voice_id": "Thu Hà", "display_name": "Thu Hà (Nữ miền Bắc)", "gender": "Nữ", "description": "Dịu dàng, chuẩn mực"},
        {"voice_id": "Thanh Trúc", "display_name": "Thanh Trúc (Nữ miền Nam)", "gender": "Nữ", "description": "Truyền cảm, ngọt ngào"},
        {"voice_id": "Bảo Ngọc", "display_name": "Bảo Ngọc (Nữ miền Nam)", "gender": "Nữ", "description": "Trong trẻo, tươi sáng"},
    ]

    # 1. Thử import vieneu SDK (chạy offline nội bộ)
    has_vieneu = False
    try:
        import vieneu
        result["sdk_version"] = getattr(vieneu, "__version__", "3.x")
        result["engine_type"] = "vieneu"
        result["available"] = True
        has_vieneu = True

        # Kiểm tra ONNX
        try:
            import onnxruntime
            result["backends"].append("onnx")
            result["current_backend"] = "onnx"
        except ImportError:
            pass

        # Kiểm tra PyTorch / CUDA
        try:
            import torch
            result["backends"].append("pytorch")
            if torch.cuda.is_available():
                result["cuda_available"] = True
                result["device_name"] = torch.cuda.get_device_name(0)
                result["current_backend"] = "pytorch"
            else:
                result["device_name"] = "CPU"
        except ImportError:
            pass

        # Lấy danh sách preset voices nếu có
        try:
            raw_v = None
            if hasattr(vieneu, "list_preset_voices"):
                raw_v = vieneu.list_preset_voices()
            if isinstance(raw_v, list) and raw_v:
                voices = []
                for v in raw_v:
                    if isinstance(v, str):
                        voices.append({"voice_id": v, "display_name": v, "gender": "", "description": ""})
                    elif isinstance(v, dict):
                        voices.append({
                            "voice_id": v.get("id", v.get("voice_id", "")),
                            "display_name": v.get("name", v.get("voice_id", "")),
                            "gender": v.get("gender", ""),
                            "description": v.get("description", ""),
                        })
                if voices:
                    result["voices"] = voices
        except Exception:
            pass

    except Exception:
        has_vieneu = False

    # 2. Nếu vieneu chưa có, kiểm tra Neural Engine (Edge-TTS)
    if not has_vieneu:
        try:
            import edge_tts
            result["available"] = True
            result["engine_type"] = "edge_tts"
            result["sdk_version"] = f"Neural {getattr(edge_tts, '__version__', '7.x')}"
            result["backends"] = ["neural_cloud"]
            result["current_backend"] = "neural_cloud"
            result["device_name"] = "Neural Engine"
            result["error_message"] = ""
        except ImportError:
            result["available"] = False
            result["error_message"] = (
                f"Chưa cài đặt engine TTS trong môi trường Python ({sys.executable}).\n"
                "Vui lòng cài đặt: pip install edge-tts hoặc pip install vieneu"
            )

    if not result["voices"]:
        result["voices"] = default_preset

    return result


def run_batch_task(task_path: str, mock: bool = False):
    """
    Xử lý danh sách các chunk từ tệp JSON cấu hình tác vụ.
    Tự động kích hoạt backend phù hợp: VieNeu, Neural Cloud (Edge-TTS) hoặc Mock.
    Giao tiếp tiến độ bằng JSON-lines trên stdout.
    """
    if not os.path.isfile(task_path):
        print(json.dumps({"type": "fatal_error", "error": f"Không tìm thấy tệp tác vụ: {task_path}"}), flush=True)
        sys.exit(1)

    try:
        with open(task_path, "r", encoding="utf-8") as f:
            task_data = json.load(f)
    except Exception as e:
        print(json.dumps({"type": "fatal_error", "error": f"Lỗi đọc tệp tác vụ: {e}"}), flush=True)
        sys.exit(1)

    model_name = task_data.get("model_name", "v3_turbo")
    backend = task_data.get("backend", "onnx")
    precision = task_data.get("precision", "fp32")
    voice_id = task_data.get("voice_id", "Hải Đăng")
    speed = float(task_data.get("speed", 1.0))
    sample_rate = int(task_data.get("sample_rate", 48000))
    chunks = task_data.get("chunks", [])

    print(json.dumps({
        "type": "model_loading",
        "model_name": model_name,
        "backend": backend,
        "precision": precision,
        "voice_id": voice_id,
        "speed": speed,
        "total_chunks": len(chunks),
    }), flush=True)

    engine_mode = "mock"
    tts_engine = None

    if not mock:
        # Thử khởi tạo VieNeu trước
        try:
            from vieneu import Vieneu
            tts_engine = Vieneu(mode=model_name, backend=backend, precision=precision)
            engine_mode = "vieneu"
            print(json.dumps({"type": "model_loaded", "engine": "vieneu"}), flush=True)
        except Exception:
            # Chuyển sang Neural Cloud Engine (Edge-TTS)
            try:
                import edge_tts
                engine_mode = "edge_tts"
                print(json.dumps({"type": "model_loaded", "engine": "edge_tts"}), flush=True)
            except Exception as e:
                err_tb = traceback.format_exc()
                print(json.dumps({
                    "type": "fatal_error",
                    "error": f"Không có động cơ TTS khả dụng: Cần vieneu hoặc edge-tts.\n{e}\n{err_tb}"
                }), flush=True)
                sys.exit(1)
    else:
        engine_mode = "mock"
        time.sleep(0.05)
        print(json.dumps({"type": "model_loaded", "mock": True}), flush=True)

    # Xử lý tuần tự từng đoạn
    for c in chunks:
        idx = c.get("index", 0)
        text = c.get("text", "")
        wav_path = c.get("wav_path", "")

        print(json.dumps({"type": "chunk_started", "index": idx}), flush=True)

        try:
            start_t = time.time()
            clean_txt = sanitize_tts_text(text)

            if engine_mode == "mock":
                time.sleep(0.05)
                _generate_synthetic_wav(wav_path, duration_sec=0.4, sample_rate=sample_rate)
                dur = 0.4
                sc = int(sample_rate * 0.4)

            elif engine_mode == "vieneu":
                audio = tts_engine.infer(clean_txt, voice=voice_id)
                os.makedirs(os.path.dirname(os.path.abspath(wav_path)), exist_ok=True)
                tts_engine.save(audio, wav_path)

                with wave.open(wav_path, "rb") as wf:
                    sc = wf.getnframes()
                    fr = wf.getframerate()
                    dur = sc / fr if fr > 0 else 0.0

            elif engine_mode == "edge_tts":
                _synthesize_edge_tts(
                    text=clean_txt,
                    voice_id=voice_id,
                    speed=speed,
                    out_wav=wav_path,
                    sample_rate=sample_rate,
                )
                with wave.open(wav_path, "rb") as wf:
                    sc = wf.getnframes()
                    fr = wf.getframerate()
                    dur = sc / fr if fr > 0 else 0.0

            elapsed = time.time() - start_t
            print(json.dumps({
                "type": "chunk_done",
                "index": idx,
                "wav_path": wav_path,
                "duration_sec": dur,
                "sample_count": sc,
                "elapsed_sec": round(elapsed, 3),
            }), flush=True)

        except Exception as e:
            err_msg = str(e)
            print(json.dumps({
                "type": "chunk_error",
                "index": idx,
                "error": err_msg,
            }), flush=True)

    print(json.dumps({"type": "task_completed"}), flush=True)


def run_preview(
    text: str,
    voice_id: str,
    out_wav: str,
    model_name: str = "v3_turbo",
    backend: str = "onnx",
    speed: float = 1.0,
    mock: bool = False,
):
    """Tổng hợp một đoạn nghe thử ngắn chất lượng cao."""
    try:
        clean_txt = sanitize_tts_text(text)
        if not clean_txt:
            clean_txt = "Xin chào, đây là giọng đọc thử nghiệm của hệ thống Truyenaudio."

        if mock:
            _generate_synthetic_wav(out_wav, duration_sec=1.5, sample_rate=48000)
            print(json.dumps({"type": "preview_done", "wav_path": out_wav, "duration_sec": 1.5}), flush=True)
            return

        # 1. Thử VieNeu
        try:
            from vieneu import Vieneu
            tts = Vieneu(mode=model_name, backend=backend)
            audio = tts.infer(clean_txt, voice=voice_id)
            os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
            tts.save(audio, out_wav)

            with wave.open(out_wav, "rb") as wf:
                dur = wf.getnframes() / wf.getframerate()

            print(json.dumps({"type": "preview_done", "wav_path": out_wav, "duration_sec": dur}), flush=True)
            return
        except Exception:
            pass

        # 2. Thử Neural Cloud Engine (Edge-TTS)
        try:
            import edge_tts
            _synthesize_edge_tts(
                text=clean_txt,
                voice_id=voice_id,
                speed=speed,
                out_wav=out_wav,
                sample_rate=48000,
            )
            with wave.open(out_wav, "rb") as wf:
                dur = wf.getnframes() / wf.getframerate()

            print(json.dumps({"type": "preview_done", "wav_path": out_wav, "duration_sec": dur}), flush=True)
            return
        except Exception as e:
            # Fallback sang âm thanh mẫu nhẹ nhàng nếu mất mạng
            _generate_synthetic_wav(out_wav, duration_sec=1.2, sample_rate=48000)
            print(json.dumps({
                "type": "preview_done",
                "wav_path": out_wav,
                "duration_sec": 1.2,
                "note": f"Sử dụng âm mẫu do lỗi: {e}"
            }), flush=True)

    except Exception as e:
        print(json.dumps({"type": "preview_error", "error": str(e)}), flush=True)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="VieNeu-TTS Independent Runner")
    parser.add_argument("--check-env", action="store_true", help="Kiểm tra môi trường và thông tin model/SDK")
    parser.add_argument("--batch-task", type=str, help="Đường dẫn tệp JSON tác vụ cần xử lý")
    parser.add_argument("--preview", action="store_true", help="Chế độ nghe thử một câu ngắn")
    parser.add_argument("--text", type=str, default="", help="Nội dung câu nghe thử")
    parser.add_argument("--voice", type=str, default="Hải Đăng", help="Tên giọng đọc")
    parser.add_argument("--out-wav", type=str, default="preview.wav", help="Đường dẫn file WAV nghe thử")
    parser.add_argument("--model", type=str, default="v3_turbo", help="Tên model")
    parser.add_argument("--backend", type=str, default="onnx", help="Backend onnx hoặc pytorch")
    parser.add_argument("--speed", type=float, default=1.0, help="Tốc độ đọc")
    parser.add_argument("--mock", action="store_true", help="Chạy ở chế độ giả lập cho kiểm thử")

    args = parser.parse_args()

    if args.check_env:
        status = check_environment()
        print(json.dumps(status, ensure_ascii=False, indent=2))
        sys.exit(0 if status["available"] else 2)

    elif args.preview:
        run_preview(
            text=args.text or "Xin chào, đây là giọng đọc thử nghiệm của hệ thống Truyenaudio.",
            voice_id=args.voice,
            out_wav=args.out_wav,
            model_name=args.model,
            backend=args.backend,
            speed=args.speed,
            mock=args.mock,
        )

    elif args.batch_task:
        run_batch_task(args.batch_task, mock=args.mock)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
