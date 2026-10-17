"""
Background Worker Thread for Video Production (QThread).
Features:
- Sequential batch encoding to avoid overloading system resources.
- Takes config & item snapshot to ensure data consistency during run.
- Accurate progress: current item progress + queue progress + elapsed/ETA time.
- Graceful cancellation: stops running FFmpeg, waits for exit, and cleans temporary files.
- Resilient error handling: one failed item does not abort remaining items.
- Preserves input MP3 and image files untouched.
"""
import os
import time
import copy
from typing import List, Optional
from PySide6.QtCore import QThread, Signal

from core.video_models import AudioVideoItem, VideoConfig
from core.video_renderer import save_frame_image
from core.ffmpeg_utils import encode_video_from_frame, find_ffmpeg


class VideoExportWorker(QThread):
    item_started = Signal(str)  # item_id
    item_progress = Signal(str, float)  # item_id, percent (0-100)
    queue_progress = Signal(int, int, float, str)  # completed, total, queue_percent, eta_str
    item_finished = Signal(str, str)  # item_id, output_path
    item_failed = Signal(str, str)  # item_id, error_msg
    log_message = Signal(str, str)  # level, msg
    all_finished = Signal(int, int)  # success_count, error_count

    def __init__(
        self,
        items: List[AudioVideoItem],
        config: VideoConfig,
    ):
        super().__init__()
        # Tạo bản sao snapshot để tránh bị sửa đổi từ giao diện trong khi đang chạy
        self.items = [copy.deepcopy(it) for it in items]
        self.config = copy.deepcopy(config)
        self._is_cancelled = False
        self._start_time: float = 0.0

    def cancel(self):
        """Yêu cầu hủy tiến trình xuất video an toàn."""
        self._is_cancelled = True

    def is_cancelled(self) -> bool:
        return self._is_cancelled

    def run(self):
        self._start_time = time.time()
        total_items = len(self.items)
        success_count = 0
        error_count = 0

        self.log_message.emit("INFO", f"Bắt đầu hàng đợi xuất {total_items} video MP4 tuần tự...")

        # Tạo thư mục tạm lưu khung hình
        temp_frames_dir = os.path.join(self.config.output_dir or "output_videos", ".temp_frames")
        os.makedirs(temp_frames_dir, exist_ok=True)

        for idx, item in enumerate(self.items, 1):
            if self._is_cancelled:
                self.log_message.emit("WARNING", "Hàng đợi xuất video đã bị người dùng hủy.")
                item.status = "cancelled"
                self.item_failed.emit(item.id, "Đã bị hủy bởi người dùng.")
                break

            self.item_started.emit(item.id)
            self.log_message.emit("INFO", f"[{idx}/{total_items}] Đang kết xuất video: {item.filename} (Tập {item.volume_num})...")

            frame_img_path = os.path.join(temp_frames_dir, f"frame_{item.id}.png")

            try:
                # 1. Dựng ảnh khung hình chuẩn
                save_frame_image(item, self.config, frame_img_path)

                # 2. Callback tiến độ cho mục hiện tại
                def on_item_prog(pct: float):
                    if self._is_cancelled:
                        return
                    item.progress = pct
                    self.item_progress.emit(item.id, pct)

                    # Tính toán ETA cho toàn hàng đợi
                    elapsed = time.time() - self._start_time
                    done_fraction = (idx - 1 + (pct / 100.0)) / max(1, total_items)
                    queue_pct = min(100.0, done_fraction * 100.0)

                    eta_str = "--:--"
                    if done_fraction > 0.05 and elapsed > 2:
                        total_est = elapsed / done_fraction
                        remain = max(0, int(total_est - elapsed))
                        r_min = remain // 60
                        r_sec = remain % 60
                        eta_str = f"{r_min:02d}:{r_sec:02d}"

                    self.queue_progress.emit(success_count, total_items, queue_pct, eta_str)

                # 3. Mã hóa video bằng FFmpeg
                out_path = encode_video_from_frame(
                    item=item,
                    frame_image_path=frame_img_path,
                    config=self.config,
                    on_progress=on_item_prog,
                    check_cancel=self.is_cancelled,
                )

                item.status = "completed"
                item.output_path = out_path
                item.progress = 100.0
                success_count += 1
                self.item_finished.emit(item.id, out_path)
                self.log_message.emit("SUCCESS", f"[{idx}/{total_items}] Xuất thành công: {os.path.basename(out_path)}")

            except Exception as e:
                err_msg = str(e)
                if self._is_cancelled:
                    item.status = "cancelled"
                    item.error_message = "Đã bị hủy bởi người dùng."
                    self.item_failed.emit(item.id, item.error_message)
                    self.log_message.emit("WARNING", f"[{idx}/{total_items}] Bị hủy: {item.filename}")
                    break
                else:
                    item.status = "error"
                    item.error_message = err_msg
                    error_count += 1
                    self.item_failed.emit(item.id, err_msg)
                    self.log_message.emit("ERROR", f"[{idx}/{total_items}] Lỗi khi xuất {item.filename}: {err_msg}")

            finally:
                # Dọn tệp ảnh khung hình tạm thời
                if os.path.exists(frame_img_path):
                    try:
                        os.remove(frame_img_path)
                    except Exception:
                        pass

        # Dọn thư mục tạm nếu rỗng
        try:
            if os.path.exists(temp_frames_dir) and not os.listdir(temp_frames_dir):
                os.rmdir(temp_frames_dir)
        except Exception:
            pass

        self.all_finished.emit(success_count, error_count)
        self.log_message.emit(
            "SUCCESS" if error_count == 0 else "WARNING",
            f"Hoàn thành xuất video! Thành công: {success_count}/{total_items}, Lỗi: {error_count}."
        )
