"""
Background Workers for Audio Production Tab.
Manages asynchronous execution of queue synthesis, single chunk retries,
previews, speed tracking, ETA estimation, and thread-safe UI updates.
"""
import os
import time
from typing import List, Optional, Dict, Any
from PySide6.QtCore import QThread, Signal

from core.tts_models import TTSItem, TTSConfig
from core.tts_manifest import TTSManifestManager
from core.tts_adapter import TTSAdapter
from core.tts_assembler import TTSAudioAssembler, AudioAssemblyError


class TTSQueueWorker(QThread):
    """Worker luồng nền xử lý hàng đợi sản xuất âm thanh."""

    # Tín hiệu cập nhật UI
    item_started = Signal(str)                                         # item_id
    item_progress = Signal(str, int, int, float, str)                 # item_id, done, total, chars_per_sec, eta_str
    item_status_changed = Signal(str, str, str)                       # item_id, status, error_msg
    item_finished = Signal(str, str, float)                           # item_id, mp3_path, duration_sec
    queue_progress = Signal(int, int)                                 # current_item_idx, total_items
    queue_finished = Signal(int, int, int)                            # completed, skipped, error
    log_message = Signal(str, str)                                    # level, message

    def __init__(
        self,
        items: List[TTSItem],
        config: TTSConfig,
        output_dir: Optional[str] = None,
        mock: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.items = items
        self.config = config
        self.output_dir = output_dir
        self.mock = mock

        self._cancel_requested = False
        self._stop_after_current = False
        self._is_paused = False

    def request_cancel(self):
        """Hủy ngay lập tức."""
        self._cancel_requested = True

    def request_stop_after_current(self):
        """Dừng sau khi hoàn tất tập đang xử lý."""
        self._stop_after_current = True

    def run(self):
        total_items = len(self.items)
        completed_count = 0
        skipped_count = 0
        error_count = 0

        self.log_message.emit("INFO", f"Bắt đầu xử lý hàng đợi TTS ({total_items} tập)...")

        for idx, item in enumerate(self.items):
            if self._cancel_requested:
                self.log_message.emit("WARNING", "Hàng đợi đã bị hủy bởi người dùng.")
                item.status = "cancelled"
                self.item_status_changed.emit(item.item_id, "cancelled", "Người dùng hủy tác vụ")
                break

            self.queue_progress.emit(idx + 1, total_items)
            self.item_started.emit(item.item_id)

            try:
                # 1. Chuẩn bị manifest và kiểm tra cache
                manifest_path, is_reused = TTSManifestManager.prepare_item_manifest(
                    item, self.config
                )

                if is_reused:
                    self.log_message.emit(
                        "INFO",
                        f"Tập {item.volume_num}: Tận dụng lại {item.chunks_done}/{len(item.chunks)} đoạn đã có từ cache."
                    )

                # 2. Kiểm tra xem có cần tổng hợp đoạn nào không
                pending_chunks = [c for c in item.chunks if c.status != "completed"]

                if pending_chunks:
                    item.status = "loading_model"
                    self.item_status_changed.emit(item.item_id, "loading_model", "")

                    task_file = TTSAdapter.create_batch_task_file(item, self.config)

                    start_time = time.time()
                    synthesized_chars = 0

                    def on_event(ev: Dict[str, Any]):
                        nonlocal synthesized_chars
                        ev_type = ev.get("type")

                        if ev_type == "model_loaded":
                            item.status = "synthesizing"
                            self.item_status_changed.emit(item.item_id, "synthesizing", "")

                        elif ev_type == "chunk_started":
                            c_idx = ev.get("index", 0)
                            if 0 <= c_idx < len(item.chunks):
                                item.chunks[c_idx].status = "synthesizing"

                        elif ev_type == "chunk_done":
                            c_idx = ev.get("index", 0)
                            if 0 <= c_idx < len(item.chunks):
                                chunk = item.chunks[c_idx]
                                chunk.status = "completed"
                                chunk.wav_path = ev.get("wav_path", chunk.wav_path)
                                chunk.duration_sec = ev.get("duration_sec", 0.0)
                                chunk.sample_count = ev.get("sample_count", 0)
                                chunk.error_msg = ""

                                item.chunks_done = sum(1 for c in item.chunks if c.status == "completed")
                                synthesized_chars += chunk.char_count

                                # Tính toán tốc độ đọc và ETA thực tế
                                elapsed = time.time() - start_time
                                chars_per_sec = (synthesized_chars / elapsed) if elapsed > 0.5 else 0.0
                                item.chars_per_sec = chars_per_sec

                                rem_chunks = [c for c in item.chunks if c.status != "completed"]
                                rem_chars = sum(c.char_count for c in rem_chunks)
                                if chars_per_sec > 0:
                                    eta_sec = rem_chars / chars_per_sec
                                    item.eta_seconds = eta_sec
                                    mins = int(eta_sec // 60)
                                    secs = int(eta_sec % 60)
                                    eta_str = f"{mins:02d}:{secs:02d}"
                                else:
                                    item.eta_seconds = None
                                    eta_str = "--:--"

                                # Lưu manifest
                                TTSManifestManager.save_manifest(item, self.config, manifest_path)

                                # Bắn tín hiệu tiến độ
                                self.item_progress.emit(
                                    item.item_id,
                                    item.chunks_done,
                                    len(item.chunks),
                                    chars_per_sec,
                                    eta_str,
                                )

                        elif ev_type == "chunk_error":
                            c_idx = ev.get("index", 0)
                            err = ev.get("error", "Lỗi tổng hợp đoạn")
                            if 0 <= c_idx < len(item.chunks):
                                chunk = item.chunks[c_idx]
                                chunk.status = "error"
                                chunk.error_msg = err
                            TTSManifestManager.save_manifest(item, self.config, manifest_path)
                            self.log_message.emit("WARNING", f"Lỗi đoạn {c_idx}: {err}")

                    # Thực thi batch task
                    success, msg = TTSAdapter.execute_batch_task(
                        python_path=self.config.python_path,
                        task_file=task_file,
                        event_callback=on_event,
                        cancel_check=lambda: self._cancel_requested,
                        mock=self.mock,
                    )

                    if self._cancel_requested:
                        item.status = "cancelled"
                        item.error_msg = "Người dùng đã hủy tác vụ."
                        TTSManifestManager.save_manifest(item, self.config, manifest_path)
                        self.item_status_changed.emit(item.item_id, "cancelled", item.error_msg)
                        break

                    if not success:
                        item.status = "error"
                        item.error_msg = msg
                        TTSManifestManager.save_manifest(item, self.config, manifest_path)
                        self.item_status_changed.emit(item.item_id, "error", msg)
                        self.log_message.emit("ERROR", f"Tập {item.volume_num} thất bại: {msg}")
                        error_count += 1
                        continue

                # 3. Ghép nối WAV và chuyển đổi sang MP3
                item.status = "assembling"
                self.item_status_changed.emit(item.item_id, "assembling", "")
                self.log_message.emit("INFO", f"Đang ghép {len(item.chunks)} đoạn và mã hóa MP3 cho Tập {item.volume_num}...")

                mp3_path = TTSAudioAssembler.assemble_and_encode_mp3(
                    item=item,
                    config=self.config,
                    output_dir=self.output_dir,
                )

                if item.status == "skipped":
                    skipped_count += 1
                    self.log_message.emit("INFO", f"Tập {item.volume_num} đã có tệp MP3 hợp lệ, bỏ qua theo cấu hình.")
                else:
                    completed_count += 1
                    self.log_message.emit(
                        "INFO",
                        f"Đã hoàn thành Tập {item.volume_num}: {os.path.basename(mp3_path)} (Thời lượng: {item.duration_sec:.1f}s)"
                    )

                # Lưu manifest trạng thái cuối
                TTSManifestManager.save_manifest(item, self.config, manifest_path)
                self.item_status_changed.emit(item.item_id, item.status, "")
                self.item_finished.emit(item.item_id, item.output_mp3_path, item.duration_sec)

            except AudioAssemblyError as ae:
                item.status = "error"
                item.error_msg = str(ae)
                error_count += 1
                TTSManifestManager.save_manifest(item, self.config)
                self.item_status_changed.emit(item.item_id, "error", str(ae))
                self.log_message.emit("ERROR", f"Lỗi ghép MP3 Tập {item.volume_num}: {ae}")

            except Exception as e:
                item.status = "error"
                item.error_msg = str(e)
                error_count += 1
                TTSManifestManager.save_manifest(item, self.config)
                self.item_status_changed.emit(item.item_id, "error", str(e))
                self.log_message.emit("ERROR", f"Lỗi không mong muốn Tập {item.volume_num}: {e}")

            if self._stop_after_current:
                self.log_message.emit("WARNING", "Đã dừng hàng đợi sau tập hiện tại theo yêu cầu.")
                break

        self.queue_finished.emit(completed_count, skipped_count, error_count)


class TTSPreviewWorker(QThread):
    """Worker luồng riêng cho thao tác nghe thử câu ngắn."""

    preview_finished = Signal(bool, str, float)  # success, wav_path_or_err, duration_sec

    def __init__(
        self,
        python_path: str,
        text: str,
        voice_id: str,
        out_wav: str,
        model_name: str = "v3_turbo",
        backend: str = "onnx",
        mock: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.python_path = python_path
        self.text = text
        self.voice_id = voice_id
        self.out_wav = out_wav
        self.model_name = model_name
        self.backend = backend
        self.mock = mock

    def run(self):
        success, res, dur = TTSAdapter.synthesize_preview(
            python_path=self.python_path,
            text=self.text,
            voice_id=self.voice_id,
            out_wav=self.out_wav,
            model_name=self.model_name,
            backend=self.backend,
            mock=self.mock,
        )
        self.preview_finished.emit(success, res, dur)
