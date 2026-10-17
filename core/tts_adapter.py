"""
VieNeu-TTS Subprocess Adapter.
Manages communication with the isolated TTS runner process without importing heavy libraries
or conflicting with frozen PyInstaller binaries.
"""
import os
import sys
import json
import time
import shutil
import subprocess
from typing import Dict, Any, Optional, Tuple, Callable, List
from core.tts_models import TTSEnvStatus, TTSVoice, TTSItem, TTSConfig


class TTSAdapter:
    """Cầu nối thực thi VieNeu-TTS độc lập qua tiến trình con."""

    @classmethod
    def get_runner_script_path(cls) -> str:
        """Lấy đường dẫn tuyệt đối tới tệp core/tts_runner.py."""
        # 1. Nếu đang chạy đóng gói PyInstaller, ưu tiên tìm trong thư mục giải nén tạm _MEIPASS
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            cand = os.path.join(meipass, "core", "tts_runner.py")
            if os.path.isfile(cand):
                return os.path.abspath(cand)

        # 2. Nếu đang chạy từ mã nguồn dự án
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cand = os.path.join(base_dir, "core", "tts_runner.py")
        if os.path.isfile(cand):
            return os.path.abspath(cand)

        # 3. Khi đóng gói, runner có thể nằm cùng thư mục chứa tệp EXE
        exe_dir = os.path.dirname(sys.executable)
        cand = os.path.join(exe_dir, "core", "tts_runner.py")
        if os.path.isfile(cand):
            return os.path.abspath(cand)

        # 4. Tìm trong thư mục làm việc hiện tại
        cwd_cand = os.path.join(os.getcwd(), "core", "tts_runner.py")
        if os.path.isfile(cwd_cand):
            return os.path.abspath(cwd_cand)

        return os.path.abspath(cand)

    @classmethod
    def get_subprocess_kwargs(cls) -> Dict[str, Any]:
        """Tạo tham số ẩn hoàn toàn cửa sổ console/CMD khi chạy tiến trình TTS trên Windows."""
        kwargs: Dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            si = subprocess.STARTUPINFO()
            si.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 1)
            si.wShowWindow = 0  # SW_HIDE
            kwargs["startupinfo"] = si
        return kwargs

    @classmethod
    def find_python_tts(cls, custom_path: str = "") -> str:
        """
        Tìm trình thông dịch Python phù hợp cho TTS:
        1. custom_path nếu người dùng cấu hình và tệp tồn tại.
        2. Môi trường venv_tts hoặc .venv trong thư mục dự án, thư mục exe hoặc cwd.
        3. Python trong PATH hoặc launcher py.exe trên Windows.
        4. Các đường dẫn cài đặt tiêu chuẩn (C:\\Python312, C:\\Python311, v.v.).
        """
        if custom_path and os.path.isfile(custom_path):
            return os.path.abspath(custom_path)

        # Các thư mục gốc có thể chứa môi trường ảo
        search_roots = []
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if os.path.isdir(base_dir):
            search_roots.append(base_dir)

        exe_dir = os.path.dirname(sys.executable)
        if os.path.isdir(exe_dir):
            search_roots.append(exe_dir)
            parent_exe = os.path.dirname(exe_dir)
            if os.path.isdir(parent_exe):
                search_roots.append(parent_exe)

        cwd = os.getcwd()
        if os.path.isdir(cwd) and cwd not in search_roots:
            search_roots.append(cwd)

        # 1. Tìm venv_tts và .venv trong các thư mục gốc tiềm năng
        for r in search_roots:
            candidates = [
                os.path.join(r, "venv_tts", "Scripts", "python.exe"),
                os.path.join(r, "venv_tts", "bin", "python"),
                os.path.join(r, ".venv", "Scripts", "python.exe"),
                os.path.join(r, ".venv", "bin", "python"),
            ]
            for cand in candidates:
                if os.path.isfile(cand):
                    return os.path.abspath(cand)

        # 2. Nếu không frozen, có thể dùng sys.executable
        is_frozen = getattr(sys, "frozen", False)
        if not is_frozen and sys.executable and os.path.isfile(sys.executable):
            return os.path.abspath(sys.executable)

        # 3. Tìm python trong PATH
        py_in_path = shutil.which("python")
        if py_in_path and os.path.isfile(py_in_path):
            # Tránh Windows Store alias stub nếu kích thước 0 hoặc trỏ đến WindowsApps
            if "WindowsApps" not in py_in_path:
                return os.path.abspath(py_in_path)

        # 4. Kiểm tra Windows py launcher (py.exe)
        py_launcher = shutil.which("py")
        if py_launcher:
            try:
                out = subprocess.check_output(
                    [py_launcher, "-3", "-c", "import sys; print(sys.executable, end='')"],
                    text=True,
                    timeout=5,
                    **cls.get_subprocess_kwargs(),
                ).strip()
                if out and os.path.isfile(out):
                    return os.path.abspath(out)
            except Exception:
                pass

        # 5. Các đường dẫn cài đặt mặc định trên Windows
        for cand in [
            r"C:\Python312\python.exe",
            r"C:\Python311\python.exe",
            r"C:\Python310\python.exe",
            r"C:\Python314\python.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python312\python.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python311\python.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python314\python.exe"),
        ]:
            if os.path.isfile(cand):
                return os.path.abspath(cand)

        return ""

    @classmethod
    def check_environment(cls, python_path: str = "") -> TTSEnvStatus:
        """
        Gọi tts_runner.py --check-env để kiểm tra SDK, backend và lấy danh sách giọng đọc.
        Tuyệt đối không import thư viện trong tiến trình chính.
        """
        py_bin = cls.find_python_tts(python_path)
        from core.tts_models import get_default_voices
        if not py_bin or not os.path.isfile(py_bin):
            return TTSEnvStatus(
                available=False,
                voices=get_default_voices(),
                error_message="Không tìm thấy trình thông dịch Python cho TTS. Vui lòng thiết lập đường dẫn trong cấu hình.",
            )

        runner_script = cls.get_runner_script_path()
        if not os.path.isfile(runner_script):
            return TTSEnvStatus(
                available=False,
                python_path=py_bin,
                voices=get_default_voices(),
                error_message=f"Không tìm thấy kịch bản runner: {runner_script}",
            )

        cmd = [py_bin, runner_script, "--check-env"]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=25,
                **cls.get_subprocess_kwargs(),
            )
            # Thử phân tích JSON từ stdout
            stdout_text = proc.stdout.strip()
            if not stdout_text:
                return TTSEnvStatus(
                    available=False,
                    python_path=py_bin,
                    error_message=proc.stderr.strip() or "Runner không trả về dữ liệu.",
                )

            from core.tts_models import get_default_voices
            default_voices = get_default_voices()
            default_map = {v.voice_id.lower(): v for v in default_voices}

            data = json.loads(stdout_text)
            raw_voices = data.get("voices", [])
            voices = []
            if raw_voices:
                for v in raw_voices:
                    vid = v.get("voice_id", "")
                    if vid.lower() in default_map:
                        def_v = default_map[vid.lower()]
                        voices.append(TTSVoice(
                            voice_id=vid,
                            display_name=def_v.display_name,
                            gender=v.get("gender") or def_v.gender,
                            region=def_v.region,
                            style=def_v.style,
                            sample_rate=def_v.sample_rate,
                            starred=def_v.starred,
                            description=v.get("description") or def_v.description,
                        ))
                    else:
                        voices.append(TTSVoice(
                            voice_id=vid,
                            display_name=v.get("display_name", vid),
                            gender=v.get("gender", ""),
                            region="Bắc",
                            style="Phong cách tự nhiên",
                            sample_rate=48000,
                            starred=True,
                            description=v.get("description", f"{vid} · 48 kHz"),
                        ))
            if len(voices) < 10:
                existing_ids = {v.voice_id.lower() for v in voices}
                for def_v in default_voices:
                    if def_v.voice_id.lower() not in existing_ids:
                        voices.append(def_v)

            return TTSEnvStatus(
                available=data.get("available", False),
                python_path=data.get("python_path", py_bin),
                sdk_version=data.get("sdk_version", ""),
                backends=data.get("backends", ["onnx"]),
                current_backend=data.get("current_backend", "onnx"),
                cuda_available=data.get("cuda_available", False),
                device_name=data.get("device_name", "CPU"),
                voices=voices,
                models=data.get("models", ["v3_turbo", "v3nano"]),
                default_model=data.get("default_model", "v3_turbo"),
                error_message=data.get("error_message", ""),
            )

        except subprocess.TimeoutExpired:
            from core.tts_models import get_default_voices
            return TTSEnvStatus(
                available=False,
                python_path=py_bin,
                voices=get_default_voices(),
                error_message="Quá thời gian chờ khi kiểm tra môi trường TTS (timeout 25s).",
            )
        except Exception as e:
            from core.tts_models import get_default_voices
            return TTSEnvStatus(
                available=False,
                python_path=py_bin,
                voices=get_default_voices(),
                error_message=f"Lỗi khởi chạy kiểm tra môi trường: {e}",
            )

    @classmethod
    def synthesize_preview(
        cls,
        python_path: str,
        text: str,
        voice_id: str,
        out_wav: str,
        model_name: str = "v3_turbo",
        backend: str = "onnx",
        mock: bool = False,
    ) -> Tuple[bool, str, float]:
        """
        Tạo đoạn nghe thử ngắn.
        Trả về (success, out_wav_or_error, duration_sec).
        """
        py_bin = cls.find_python_tts(python_path)
        if not py_bin:
            return False, "Chưa cấu hình Python TTS", 0.0

        runner_script = cls.get_runner_script_path()
        cmd = [
            py_bin,
            runner_script,
            "--preview",
            "--text", text,
            "--voice", voice_id,
            "--out-wav", out_wav,
            "--model", model_name,
            "--backend", backend,
        ]
        if mock:
            cmd.append("--mock")

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=45,
                **cls.get_subprocess_kwargs(),
            )
            stdout_text = proc.stdout.strip()
            if proc.returncode != 0:
                err = proc.stderr.strip() or stdout_text
                return False, f"Lỗi tạo nghe thử: {err}", 0.0

            data = json.loads(stdout_text)
            if data.get("type") == "preview_done":
                return True, data.get("wav_path", out_wav), data.get("duration_sec", 0.0)
            else:
                return False, data.get("error", "Lỗi không xác định"), 0.0

        except Exception as e:
            return False, f"Lỗi thực thi nghe thử: {e}", 0.0

    @classmethod
    def create_batch_task_file(cls, item: TTSItem, config: TTSConfig) -> str:
        """Tạo tệp JSON tác vụ chứa danh sách các đoạn cần tổng hợp."""
        pending_chunks = [
            {"index": c.index, "text": c.text, "wav_path": c.wav_path}
            for c in item.chunks
            if c.status != "completed"
        ]

        task_data = {
            "item_id": item.item_id,
            "model_name": config.model_name,
            "backend": config.backend,
            "precision": config.precision,
            "voice_id": config.voice_id,
            "speed": getattr(config, "speed", 1.0),
            "sample_rate": getattr(config, "sample_rate", 48000),
            "chunks": pending_chunks,
        }

        task_file = os.path.join(item.manifest_dir, f"task_{item.item_id}_{int(time.time() * 1000)}.json")
        with open(task_file, "w", encoding="utf-8") as f:
            json.dump(task_data, f, ensure_ascii=False, indent=2)

        return task_file

    @classmethod
    def execute_batch_task(
        cls,
        python_path: str,
        task_file: str,
        event_callback: Callable[[Dict[str, Any]], None],
        cancel_check: Callable[[], bool],
        mock: bool = False,
    ) -> Tuple[bool, str]:
        """
        Chạy tiến trình batch inference cho một danh sách chunk.
        Gửi các sự kiện tiến độ qua event_callback.
        Hỗ trợ hủy tác vụ và giải phóng tiến trình con sạch sẽ.
        """
        py_bin = cls.find_python_tts(python_path)
        if not py_bin:
            return False, "Không tìm thấy trình thông dịch Python TTS."

        runner_script = cls.get_runner_script_path()
        cmd = [py_bin, runner_script, "--batch-task", task_file]
        if mock:
            cmd.append("--mock")

        proc = None
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
                **cls.get_subprocess_kwargs(),
            )

            # Đọc tiến độ theo từng dòng JSON từ stdout
            while True:
                if cancel_check():
                    # Hủy tiến trình con sạch sẽ
                    try:
                        proc.terminate()
                        proc.wait(timeout=3)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                    return False, "Đã hủy tác vụ tổng hợp theo yêu cầu."

                line = proc.stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.02)
                    continue

                line_str = line.strip()
                if not line_str:
                    continue

                try:
                    event = json.loads(line_str)
                    event_callback(event)
                except json.JSONDecodeError:
                    # Bỏ qua dòng không phải JSON (có thể là warning từ thư viện C)
                    pass

            ret_code = proc.wait()
            if ret_code != 0:
                err_output = proc.stderr.read().strip() if proc.stderr else ""
                return False, f"Tiến trình tổng hợp gặp lỗi (Mã thoát: {ret_code}): {err_output}"

            return True, "Hoàn tất tổng hợp các đoạn."

        except Exception as e:
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass
            return False, f"Lỗi trong quá trình chạy batch runner: {e}"

        finally:
            if proc:
                try:
                    if proc.stdout:
                        proc.stdout.close()
                    if proc.stderr:
                        proc.stderr.close()
                except Exception:
                    pass
            # Dọn dẹp tệp task tạm
            if os.path.exists(task_file):
                try:
                    os.remove(task_file)
                except Exception:
                    pass
