"""
Background Worker Threads for Video Production (QThread):
1. AudioMetadataWorker: Reads audio metadata (duration, audio stream validity) in background.
2. VideoExportWorker: Sequential batch encoding with snapshot isolation, accurate progress,
   and clean cancellation.
"""
import os
import time
import copy
from typing import List, Optional, Set, Dict, Any
from PySide6.QtCore import QThread, Signal

from core.video_models import AudioVideoItem, VideoConfig, parse_filename_metadata, EncodeResult
from core.video_renderer import save_frame_image
from core.ffmpeg_utils import encode_video_from_frame, probe_media


class ExportSummary(dict):
    """Lớp chứa kết quả tổng kết hàng đợi xuất video, hỗ trợ unpack và truy cập thuộc tính."""
    @property
    def success_count(self) -> int:
        return self.get("success", 0)

    @property
    def skipped_count(self) -> int:
        return self.get("skipped", 0)

    @property
    def error_count(self) -> int:
        return self.get("error", 0)

    @property
    def cancelled_count(self) -> int:
        return self.get("cancelled", 0)

    @property
    def status(self) -> str:
        return self.get("status", "hoàn tất")

    def __iter__(self):
        # Hỗ trợ unpack: success, error = summary
        return iter((self.get("success", 0), self.get("error", 0)))


class AudioMetadataWorker(QThread):
    """
    Worker nền đọc thông tin thời lượng và kiểm tra luồng audio của các file MP3.
    Tránh đơ giao diện khi thêm nhiều tệp âm thanh cùng lúc.
    """
    progress = Signal(int, int, str)  # current, total, filename
    item_probed = Signal(dict)  # kết quả đọc từng file
    all_finished = Signal(int, int, int)  # added_count, skipped_dup_count, error_count

    def __init__(
        self,
        filepaths: List[str],
        existing_paths: Optional[Set[str]] = None,
        ffprobe_path: str = "",
    ):
        super().__init__()
        self.filepaths = list(filepaths)
        self.existing_paths = set(existing_paths or set())
        self.ffprobe_path = ffprobe_path
        self._is_cancelled = False

    def cancel(self):
        """Yêu cầu dừng tiến trình đọc metadata."""
        self._is_cancelled = True

    def run(self):
        total = len(self.filepaths)
        added_count = 0
        skipped_dup = 0
        error_count = 0

        for idx, path in enumerate(self.filepaths, 1):
            if self._is_cancelled:
                break

            norm_path = os.path.abspath(path)
            fname = os.path.basename(norm_path)
            self.progress.emit(idx, total, fname)

            # Kiểm tra trùng lặp
            if norm_path in self.existing_paths:
                skipped_dup += 1
                self.item_probed.emit({
                    "status": "duplicate",
                    "path": norm_path,
                    "filename": fname,
                    "message": "Tệp đã có trong danh sách",
                })
                continue

            if not os.path.isfile(norm_path):
                error_count += 1
                self.item_probed.emit({
                    "status": "error",
                    "path": norm_path,
                    "filename": fname,
                    "error": "Tệp không tồn tại hoặc không thể đọc",
                })
                continue

            # Đọc metadata qua ffprobe
            try:
                probe = probe_media(norm_path, self.ffprobe_path)
                dur = probe.get("duration", 0.0)
                has_audio = probe.get("has_audio", False)

                if not has_audio or dur <= 0:
                    error_count += 1
                    self.item_probed.emit({
                        "status": "error",
                        "path": norm_path,
                        "filename": fname,
                        "error": "Tệp không chứa luồng audio hợp lệ hoặc thời lượng bằng 0",
                    })
                    continue

                # Phân tích metadata gợi ý từ tên file
                meta = parse_filename_metadata(fname)
                self.existing_paths.add(norm_path)
                added_count += 1

                self.item_probed.emit({
                    "status": "valid",
                    "path": norm_path,
                    "filename": fname,
                    "duration": dur,
                    "metadata": meta,
                })

            except Exception as e:
                error_count += 1
                self.item_probed.emit({
                    "status": "error",
                    "path": norm_path,
                    "filename": fname,
                    "error": f"Lỗi đọc metadata: {e}",
                })

        self.all_finished.emit(added_count, skipped_dup, error_count)


class VideoExportWorker(QThread):
    item_started = Signal(str)  # item_id
    item_progress = Signal(str, float)  # item_id, percent (0-100)
    queue_progress = Signal(int, int, float, str)  # processed_count, total, queue_percent, eta_str
    item_finished = Signal(str, str)  # item_id, output_path
    item_skipped = Signal(str, str)  # item_id, reason
    item_failed = Signal(str, str)  # item_id, error_msg
    item_cancelled = Signal(str)  # item_id
    log_message = Signal(str, str)  # level, msg
    all_finished = Signal(object)  # ExportSummary dict

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
        skipped_count = 0
        error_count = 0
        cancelled_count = 0

        self.log_message.emit("INFO", f"Bắt đầu hàng đợi xuất {total_items} video MP4 tuần tự...")

        # Tạo thư mục tạm lưu khung hình
        temp_frames_dir = os.path.join(self.config.output_dir or "output_videos", ".temp_frames")
        try:
            os.makedirs(temp_frames_dir, exist_ok=True)
        except Exception as e:
            self.log_message.emit("ERROR", f"Không thể tạo thư mục tạm: {e}")

        for idx, item in enumerate(self.items, 1):
            if self._is_cancelled:
                # Đánh dấu mục hiện tại và tất cả các mục còn lại là cancelled
                item.status = "cancelled"
                item.error_message = "Đã bị hủy bởi người dùng."
                cancelled_count += 1
                self.item_cancelled.emit(item.id)

                for rem_item in self.items[idx:]:
                    rem_item.status = "cancelled"
                    rem_item.error_message = "Đã bị hủy do dừng hàng đợi."
                    cancelled_count += 1
                    self.item_cancelled.emit(rem_item.id)

                self.log_message.emit("WARNING", "Hàng đợi xuất video đã dừng theo yêu cầu hủy.")
                break

            self.item_started.emit(item.id)
            self.log_message.emit("INFO", f"[{idx}/{total_items}] Đang kết xuất video: {item.filename} (Tập {item.volume_num})...")

            if not os.path.isfile(item.audio_path):
                item.status = "error"
                item.error_message = "Tệp audio không tồn tại."
                error_count += 1
                self.item_failed.emit(item.id, item.error_message)
                self.log_message.emit("ERROR", f"[{idx}/{total_items}] Tệp audio không tồn tại: {item.filename}")
                continue

            if item.duration <= 0:
                try:
                    probe = probe_media(item.audio_path, self.config.ffprobe_path)
                    item.duration = probe.get("duration", 0.0)
                except Exception:
                    pass

            if item.duration <= 0:
                item.status = "error"
                item.error_message = "Tệp audio không có luồng âm thanh hoặc thời lượng bằng 0."
                error_count += 1
                self.item_failed.emit(item.id, item.error_message)
                self.log_message.emit("ERROR", f"[{idx}/{total_items}] Thời lượng audio không hợp lệ: {item.filename}")
                continue

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
                    queue_pct = min(99.0, done_fraction * 100.0)

                    eta_str = "--:--"
                    if done_fraction > 0.05 and elapsed > 2:
                        total_est = elapsed / done_fraction
                        remain = max(0, int(total_est - elapsed))
                        r_min = remain // 60
                        r_sec = remain % 60
                        eta_str = f"{r_min:02d}:{r_sec:02d}"

                    processed = success_count + skipped_count
                    self.queue_progress.emit(processed, total_items, queue_pct, eta_str)

                # 3. Mã hóa video bằng FFmpeg
                res = encode_video_from_frame(
                    item=item,
                    frame_image_path=frame_img_path,
                    config=self.config,
                    on_progress=on_item_prog,
                    check_cancel=self.is_cancelled,
                )

                if res.status == "skipped":
                    item.status = "skipped"
                    item.output_path = str(res)
                    item.progress = 100.0
                    skipped_count += 1
                    self.item_skipped.emit(item.id, res.message)
                    self.log_message.emit("INFO", f"[{idx}/{total_items}] Bỏ qua: {os.path.basename(str(res))} ({res.message})")
                else:
                    item.status = "completed"
                    item.output_path = str(res)
                    item.progress = 100.0
                    success_count += 1
                    self.item_finished.emit(item.id, str(res))
                    self.log_message.emit("SUCCESS", f"[{idx}/{total_items}] Xuất thành công: {os.path.basename(str(res))}")

            except Exception as e:
                err_msg = str(e)
                if self._is_cancelled or "hủy" in err_msg.lower():
                    item.status = "cancelled"
                    item.error_message = "Đã bị hủy bởi người dùng."
                    cancelled_count += 1
                    self.item_cancelled.emit(item.id)

                    for rem_item in self.items[idx:]:
                        rem_item.status = "cancelled"
                        rem_item.error_message = "Đã bị hủy do dừng hàng đợi."
                        cancelled_count += 1
                        self.item_cancelled.emit(rem_item.id)

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

        # Xác định trạng thái tổng thể
        if self._is_cancelled:
            overall_status = "đã hủy"
        elif error_count > 0:
            overall_status = "hoàn tất có lỗi"
        else:
            overall_status = "hoàn tất"

        summary = ExportSummary({
            "success": success_count,
            "skipped": skipped_count,
            "error": error_count,
            "cancelled": cancelled_count,
            "total": total_items,
            "status": overall_status,
        })

        self.all_finished.emit(summary)
        self.log_message.emit(
            "SUCCESS" if overall_status == "hoàn tất" else ("WARNING" if overall_status == "đã hủy" else "ERROR"),
            f"Kết thúc hàng đợi ({overall_status}): {success_count} thành công, {skipped_count} bỏ qua, {error_count} lỗi, {cancelled_count} đã hủy."
        )
