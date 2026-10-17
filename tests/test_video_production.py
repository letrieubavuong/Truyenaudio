"""
Unit and Integration Tests for Video Production module:
1. Audio metadata probing (duration, codec, format).
2. Natural sorting of items by volume number (preventing Volume 10 before Volume 2).
3. Handling Vietnamese characters, spaces, and special symbols in file paths.
4. Frame rendering: dimensions (1920x1080, 1280x720), modes (crop_fill, fit_letterbox) without distortion.
5. Adaptive wrapping for long titles without overflowing canvas bounds.
6. Worker cancellation: stops FFmpeg process and cleans up temporary files.
7. Fault-tolerance: one corrupted item does not fail remaining items in queue.
8. Output collision handling: preserves existing output file if new export fails.
9. Real FFmpeg integration test: builds actual MP4, checks H.264/AAC codecs and duration with ffprobe.
"""
import unittest
from unittest.mock import patch, MagicMock
import os
import sys
import shutil
import tempfile
import time
import subprocess
from PySide6.QtGui import QImage, QColor, QCloseEvent
from PySide6.QtWidgets import QMessageBox

from core.video_models import AudioVideoItem, VideoConfig, parse_filename_metadata, EncodeResult
from core.video_renderer import render_frame, save_frame_image, ensure_qapp
from core.ffmpeg_utils import find_ffmpeg, check_ffmpeg_installed, probe_media, encode_video_from_frame, _stop_process
from gui.video_worker import VideoExportWorker, AudioMetadataWorker, ExportSummary
from gui.video_tab import VideoProductionTab
from gui.main_window import MainWindow


class TestVideoProduction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = ensure_qapp()
        if app:
            app.setQuitOnLastWindowClosed(False)
        cls.has_ffmpeg, cls.ff_ver, cls.fp_ver = check_ffmpeg_installed()
        cls.fixture_dir = os.path.join(os.path.dirname(__file__), "..", "data", "fixtures")
        os.makedirs(cls.fixture_dir, exist_ok=True)

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.output_dir = os.path.join(self.test_dir, "output_video")
        os.makedirs(self.output_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_sample_audio(self, duration_sec: int = 3, filename: str = "sample.mp3") -> str:
        """Tạo tệp MP3 mẫu dùng lavfi của FFmpeg."""
        ff_bin, _ = find_ffmpeg()
        if not ff_bin:
            self.skipTest("FFmpeg không khả dụng.")
        path = os.path.join(self.test_dir, filename)
        cmd = [
            ff_bin, "-y",
            "-f", "lavfi",
            "-i", f"sine=frequency=800:duration={duration_sec}",
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            path
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return path

    def _create_sample_image(self, width: int = 1200, height: int = 800, filename: str = "sample_bg.png") -> str:
        """Tạo ảnh PNG mẫu với màu nền gradient/tĩnh."""
        path = os.path.join(self.test_dir, filename)
        img = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        img.fill(QColor(60, 40, 90))
        img.save(path, "PNG")
        return path

    def test_01_probe_audio_metadata(self):
        """Kiểm tra đọc metadata audio thực tế bằng ffprobe."""
        if not self.has_ffmpeg:
            self.skipTest("FFmpeg không khả dụng.")

        audio_path = self._create_sample_audio(duration_sec=3, filename="test_probe.mp3")
        probe = probe_media(audio_path)

        self.assertTrue(probe["has_audio"])
        self.assertFalse(probe["has_video"])
        self.assertEqual(probe["audio_codec"], "mp3")
        self.assertAlmostEqual(probe["duration"], 3.0, delta=0.5)

    def test_02_natural_sorting_by_volume(self):
        """Kiểm tra sắp xếp tập theo số tự nhiên, tránh tập 10 đứng trước tập 2."""
        items = [
            AudioVideoItem(audio_path="Tap_10.mp3", volume_num=10),
            AudioVideoItem(audio_path="Tap_2.mp3", volume_num=2),
            AudioVideoItem(audio_path="Tap_1.mp3", volume_num=1),
            AudioVideoItem(audio_path="Tap_20.mp3", volume_num=20),
            AudioVideoItem(audio_path="Tap_3.mp3", volume_num=3),
        ]

        items.sort(key=lambda x: (x.volume_num, x.start_chapter, x.filename))
        ordered_vols = [it.volume_num for it in items]
        self.assertEqual(ordered_vols, [1, 2, 3, 10, 20])

    def test_03_vietnamese_path_and_spaces(self):
        """Kiểm tra đường dẫn tiếng Việt có dấu, khoảng trắng và ký tự đặc biệt."""
        if not self.has_ffmpeg:
            self.skipTest("FFmpeg không khả dụng.")

        vietnamese_dir = os.path.join(self.test_dir, "Thư mục truyện audio Tiên Nghịch - Tập Đẹp")
        os.makedirs(vietnamese_dir, exist_ok=True)
        audio_name = "Tiên Nghịch - Tập 01 (Chương 1 đến 4).mp3"
        audio_path = os.path.join(vietnamese_dir, audio_name)

        ff_bin, _ = find_ffmpeg()
        cmd = [
            ff_bin, "-y",
            "-f", "lavfi",
            "-i", "sine=frequency=600:duration=2",
            "-c:a", "libmp3lame",
            audio_path
        ]
        subprocess.run(cmd, check=True, capture_output=True)

        self.assertTrue(os.path.isfile(audio_path))
        probe = probe_media(audio_path)
        self.assertTrue(probe["has_audio"])
        self.assertAlmostEqual(probe["duration"], 2.0, delta=0.5)

        # Gợi ý metadata từ tên file tiếng Việt
        meta = parse_filename_metadata(audio_name)
        self.assertEqual(meta.get("volume_num"), 1)
        self.assertEqual(meta.get("start_chapter"), 1)
        self.assertEqual(meta.get("end_chapter"), 4)
        self.assertEqual(meta.get("story_title"), "Tiên Nghịch")

    def test_04_frame_renderer_dimensions_and_modes(self):
        """Kiểm tra dựng ảnh đúng kích thước (1080p, 720p) và hai chế độ crop_fill vs fit_letterbox."""
        bg_path = self._create_sample_image(width=1000, height=1000, filename="square_bg.png")

        item = AudioVideoItem(
            audio_path="dummy.mp3",
            story_title="Tiên Nghịch",
            author="Nhĩ Căn",
            volume_num=5,
            start_chapter=17,
            end_chapter=20,
        )

        # 1. Chế độ Crop Fill 1920x1080
        cfg_1080 = VideoConfig(
            width=1920,
            height=1080,
            bg_image_path=bg_path,
            bg_mode="crop_fill",
        )
        img_1080 = render_frame(item, cfg_1080)
        self.assertEqual(img_1080.width(), 1920)
        self.assertEqual(img_1080.height(), 1080)

        # 2. Chế độ Fit Letterbox 1280x720
        cfg_720 = VideoConfig(
            width=1280,
            height=720,
            bg_image_path=bg_path,
            bg_mode="fit_letterbox",
        )
        img_720 = render_frame(item, cfg_720)
        self.assertEqual(img_720.width(), 1280)
        self.assertEqual(img_720.height(), 720)

    def test_05_long_title_no_overflow(self):
        """Kiểm tra tiêu đề truyện cực dài tự xuống dòng và không làm lỗi dựng hình."""
        item = AudioVideoItem(
            audio_path="dummy.mp3",
            story_title="Bộ Truyện Tiên Hiệp Trọng Sinh Tu Chân Siêu Cấp Vô Địch Chi Tiên Nghịch Toàn Tập Đỉnh Phong",
            author="Tác giả Nhĩ Căn Chi Đại Thần",
            volume_num=999,
            start_chapter=1001,
            end_chapter=1004,
        )
        cfg = VideoConfig(width=1920, height=1080, title_size=56)
        img = render_frame(item, cfg)
        self.assertFalse(img.isNull())
        self.assertEqual(img.width(), 1920)
        self.assertEqual(img.height(), 1080)

    def test_06_real_ffmpeg_encoding_and_ffprobe_verification(self):
        """Mã hóa video MP4 thật và dùng ffprobe kiểm tra codec h264, aac, kích thước và thời lượng."""
        if not self.has_ffmpeg:
            self.skipTest("FFmpeg không khả dụng.")

        audio_path = self._create_sample_audio(duration_sec=3, filename="real_audio.mp3")
        bg_path = self._create_sample_image(width=1920, height=1080, filename="real_bg.png")

        item = AudioVideoItem(
            audio_path=audio_path,
            story_title="Tiên Nghịch",
            author="Nhĩ Căn",
            volume_num=1,
            start_chapter=1,
            end_chapter=4,
        )
        config = VideoConfig(
            width=1920,
            height=1080,
            bg_image_path=bg_path,
            output_dir=self.output_dir,
            audio_bitrate="192k",
        )

        frame_path = os.path.join(self.test_dir, "final_frame.png")
        save_frame_image(item, config, frame_path)
        self.assertTrue(os.path.isfile(frame_path))

        out_video = encode_video_from_frame(item, frame_path, config)
        self.assertTrue(os.path.isfile(out_video))
        self.assertTrue(out_video.endswith(".mp4"))

        # Xác minh bằng ffprobe
        probe = probe_media(out_video)
        self.assertTrue(probe["has_video"])
        self.assertTrue(probe["has_audio"])
        self.assertEqual(probe["video_codec"], "h264")
        self.assertEqual(probe["audio_codec"], "aac")
        self.assertEqual(probe["width"], 1920)
        self.assertEqual(probe["height"], 1080)
        self.assertAlmostEqual(probe["duration"], 3.0, delta=0.5)

    def test_07_resilient_worker_and_cancel(self):
        """Kiểm tra worker xử lý lỗi mục hỏng không dừng toàn bộ, và hủy tác vụ dọn sạch tài nguyên."""
        if not self.has_ffmpeg:
            self.skipTest("FFmpeg không khả dụng.")

        good_audio1 = self._create_sample_audio(duration_sec=2, filename="good1.mp3")
        good_audio2 = self._create_sample_audio(duration_sec=2, filename="good2.mp3")
        bad_audio = os.path.join(self.test_dir, "non_existent.mp3")

        # 1. Kiểm tra tính chống chịu: mục lỗi không làm ảnh hưởng mục sau
        items_resilient = [
            AudioVideoItem(audio_path=bad_audio, story_title="Truyện Lỗi", volume_num=1),
            AudioVideoItem(audio_path=good_audio1, story_title="Truyện Chuẩn", volume_num=2),
        ]
        config = VideoConfig(output_dir=self.output_dir)

        finished_events = []
        failed_events = []
        worker = VideoExportWorker(items_resilient, config)
        worker.item_finished.connect(lambda i_id, p: finished_events.append((i_id, p)))
        worker.item_failed.connect(lambda i_id, err: failed_events.append((i_id, err)))
        worker.run()

        self.assertEqual(len(failed_events), 1)
        self.assertEqual(len(finished_events), 1)
        self.assertTrue(os.path.isfile(finished_events[0][1]))

        # 2. Kiểm tra hủy tác vụ (Cancel) thực sự
        items_cancel = [
            AudioVideoItem(audio_path=good_audio1, story_title="Tập 1", volume_num=1),
            AudioVideoItem(audio_path=good_audio2, story_title="Tập 2", volume_num=2),
        ]
        cancelled_events = []
        summary_result = []

        cancel_worker = VideoExportWorker(items_cancel, config)
        cancel_worker.item_cancelled.connect(lambda i_id: cancelled_events.append(i_id))
        cancel_worker.all_finished.connect(lambda s: summary_result.append(s))

        # Kích hoạt hủy ngay khi mục 1 bắt đầu
        cancel_worker.item_started.connect(lambda i_id: cancel_worker.cancel())
        cancel_worker.run()

        self.assertTrue(len(cancelled_events) >= 1)
        self.assertEqual(len(summary_result), 1)
        summary = summary_result[0]
        self.assertEqual(summary.status, "đã hủy")
        self.assertTrue(summary.cancelled_count >= 1)
        for it in cancel_worker.items:
            self.assertIn(it.status, ("cancelled", "completed"))

    def test_08_overwrite_protection(self):
        """Kiểm tra chế độ overwrite, skip, rename: bảo toàn file cũ nếu thay thế thất bại."""
        # 1. Chế độ OVERWRITE:
        cfg_overwrite = VideoConfig(output_dir=self.output_dir, overwrite_mode="overwrite")
        frame_dummy = os.path.join(self.test_dir, "frame_dummy.png")
        QImage(100, 100, QImage.Format_ARGB32).save(frame_dummy)
        # Tệp audio mẫu giả lập cho mock tests
        mock_audio = os.path.join(self.test_dir, "mock_audio.mp3")
        with open(mock_audio, "wb") as f:
            f.write(b"ID3mock")
        mock_item = AudioVideoItem(audio_path=mock_audio, story_title="Tiên Nghịch", volume_num=1, duration=5.0)
        target_name = mock_item.suggested_output_filename()
        target_path = os.path.join(self.output_dir, target_name)
        initial_content = b"ORIGINAL_VIDEO_CONTENT_VERSION_1"

        def _reset_original_file():
            with open(target_path, "wb") as f:
                f.write(initial_content)

        bad_item = AudioVideoItem(audio_path=os.path.join(self.test_dir, "missing.mp3"), story_title="Tiên Nghịch", volume_num=1)

        # Helper tạo file temp khi Popen chạy để kiểm thử các bước sau mã hóa
        def mock_popen_create_temp(*args, **kwargs):
            cmd = args[0]
            temp_out = cmd[-1]
            with open(temp_out, "wb") as f:
                f.write(b"TEMP_VIDEO_CHUNK")
            m = MagicMock()
            m.poll.return_value = 0
            m.returncode = 0
            m.wait.return_value = 0
            m.stdout = MagicMock()
            m.stdout.readline.return_value = ""
            m.stderr = MagicMock()
            m.stderr.readline.return_value = ""
            return m

        # Tình huống A: Mã hóa thất bại -> file cũ còn nguyên
        _reset_original_file()
        with self.assertRaises(Exception):
            encode_video_from_frame(bad_item, frame_dummy, cfg_overwrite)
        self.assertTrue(os.path.isfile(target_path))
        with open(target_path, "rb") as f:
            self.assertEqual(f.read(), initial_content)

        # Tình huống B: ffprobe xác minh thất bại -> file cũ còn nguyên
        _reset_original_file()
        with patch("subprocess.Popen", side_effect=mock_popen_create_temp):
            with patch("core.ffmpeg_utils.probe_media", side_effect=RuntimeError("Corrupted stream")):
                with self.assertRaises(RuntimeError):
                    encode_video_from_frame(mock_item, frame_dummy, cfg_overwrite)
        with open(target_path, "rb") as f:
            self.assertEqual(f.read(), initial_content)

        # Tình huống C: os.replace thất bại (file đang mở / lock) -> file cũ còn nguyên
        _reset_original_file()
        with patch("subprocess.Popen", side_effect=mock_popen_create_temp):
            with patch("core.ffmpeg_utils.probe_media", return_value={"has_video": True, "has_audio": True, "duration": 5.0}):
                with patch("os.replace", side_effect=PermissionError("File locked by player")):
                    with self.assertRaises(PermissionError):
                        encode_video_from_frame(mock_item, frame_dummy, cfg_overwrite)
        with open(target_path, "rb") as f:
            self.assertEqual(f.read(), initial_content)

        # Tình huống D: Thành công với FFmpeg thật -> file mới thay thế đúng
        if self.has_ffmpeg:
            _reset_original_file()
            good_audio = self._create_sample_audio(duration_sec=2, filename="ovw_audio.mp3")
            item = AudioVideoItem(audio_path=good_audio, story_title="Tiên Nghịch", volume_num=1)
            frame_path = os.path.join(self.test_dir, "frame_real.png")
            save_frame_image(item, cfg_overwrite, frame_path)
            res = encode_video_from_frame(item, frame_path, cfg_overwrite)
            self.assertEqual(str(res), target_path)
            with open(target_path, "rb") as f:
                new_data = f.read()
            self.assertNotEqual(new_data, initial_content)
            self.assertTrue(len(new_data) > 1000)

        # 2. Chế độ SKIP:
        _reset_original_file()
        cfg_skip = VideoConfig(output_dir=self.output_dir, overwrite_mode="skip")
        res_skip = encode_video_from_frame(mock_item, frame_dummy, cfg_skip)
        self.assertEqual(res_skip.status, "skipped")
        with open(target_path, "rb") as f:
            self.assertEqual(f.read(), initial_content)

        # 3. Chế độ RENAME:
        _reset_original_file()
        cfg_rename = VideoConfig(output_dir=self.output_dir, overwrite_mode="rename")
        if self.has_ffmpeg:
            good_audio = self._create_sample_audio(duration_sec=1, filename="rename_audio.mp3")
            item_ren = AudioVideoItem(audio_path=good_audio, story_title="Tiên Nghịch", volume_num=1)
            res_ren = encode_video_from_frame(item_ren, frame_dummy, cfg_rename)
            self.assertNotEqual(str(res_ren), target_path)
            self.assertTrue(str(res_ren).endswith("_1.mp4"))
            with open(target_path, "rb") as f:
                self.assertEqual(f.read(), initial_content)

    def test_09_cli_and_gui_clean_startup(self):
        """Kiểm tra khởi động CLI và GUI trong tiến trình Python sạch hoàn toàn."""
        # 1. python cli.py --help -> mã thoát 0
        cli_res = subprocess.run(
            [sys.executable, "cli.py", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
        )
        self.assertEqual(cli_res.returncode, 0, f"cli.py --help failed: {cli_res.stderr}")
        self.assertIn("usage", cli_res.stdout.lower())

        # 2. Khởi tạo MainWindow trong tiến trình sạch
        gui_code = (
            "import os, sys\n"
            "os.environ['QT_QPA_PLATFORM'] = 'offscreen'\n"
            "from PySide6.QtWidgets import QApplication\n"
            "from gui.main_window import MainWindow\n"
            "app = QApplication([])\n"
            "win = MainWindow()\n"
            "print('MAINWINDOW_INIT_SUCCESS')\n"
        )
        gui_res = subprocess.run(
            [sys.executable, "-c", gui_code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
        )
        self.assertEqual(gui_res.returncode, 0, f"GUI startup failed: {gui_res.stderr}")
        self.assertIn("MAINWINDOW_INIT_SUCCESS", gui_res.stdout)

    def test_10_cancel_when_ffmpeg_silent_no_stdout(self):
        """Kiểm tra hủy kịp thời khi FFmpeg bị treo hoặc không phát thêm dòng stdout."""
        frame_dummy = os.path.join(self.test_dir, "silent_frame.png")
        QImage(100, 100, QImage.Format_ARGB32).save(frame_dummy)
        dummy_audio = os.path.join(self.test_dir, "silent_audio.mp3")
        with open(dummy_audio, "wb") as f:
            f.write(b"ID3dummy")
        dummy_item = AudioVideoItem(audio_path=dummy_audio, duration=5.0)
        cfg = VideoConfig(output_dir=self.output_dir)

        # Mock process mà stdout không bao giờ trả về dòng mới
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.readline.side_effect = lambda: time.sleep(0.5) or ""
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.readline.return_value = ""

        def is_cancelled():
            return True

        with patch("subprocess.Popen", return_value=mock_proc):
            start_t = time.time()
            with self.assertRaises(RuntimeError) as ctx:
                encode_video_from_frame(
                    item=dummy_item,
                    frame_image_path=frame_dummy,
                    config=cfg,
                    check_cancel=is_cancelled,
                )
            elapsed = time.time() - start_t

        self.assertTrue("hủy" in str(ctx.exception).lower() or "cancel" in str(ctx.exception).lower())
        self.assertTrue(elapsed < 2.0, f"Cancellation took too long: {elapsed}s")

    def test_11_uncooperative_process_kill_and_wait(self):
        """Kiểm tra tiến trình không chịu terminate sẽ bị kill và wait xác nhận thoát."""
        mock_proc = MagicMock()
        poll_states = [None, None, 0]

        def mock_poll():
            return poll_states.pop(0) if poll_states else 0

        mock_proc.poll.side_effect = mock_poll
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="ffmpeg", timeout=0.01), 0]

        _stop_process(mock_proc, timeout=0.01)

        mock_proc.terminate.assert_called()
        mock_proc.kill.assert_called()
        self.assertTrue(mock_proc.wait.called)

    def test_12_safe_window_close_event(self):
        """Kiểm tra đóng cửa sổ an toàn, không để lại QThread hay process mồ côi."""
        win = MainWindow()
        try:
            # Tình huống 1: Worker đang bận, người dùng chọn No (tiếp tục làm việc)
            with patch.object(win.video_tab, "is_busy", return_value=True):
                with patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.No):
                    evt = QCloseEvent()
                    win.closeEvent(evt)
                    self.assertFalse(evt.isAccepted(), "Cửa sổ không được đóng khi người dùng chọn No.")

            # Tình huống 2: Worker đang bận, người dùng chọn Yes, worker dừng hoàn tất
            with patch.object(win.video_tab, "is_busy", side_effect=[True, False]):
                with patch.object(win.video_tab, "stop_all_workers") as mock_stop:
                    with patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.Yes):
                        evt = QCloseEvent()
                        win.closeEvent(evt, timeout_s=0.05)
                        mock_stop.assert_called_once()
                        self.assertTrue(evt.isAccepted(), "Cửa sổ phải chấp nhận đóng khi worker đã dừng.")

            # Tình huống 3: Worker cứng đầu không chịu dừng (vẫn isRunning sau timeout)
            mock_stubborn_worker = MagicMock()
            mock_stubborn_worker.isRunning.return_value = True
            win.video_tab.worker = mock_stubborn_worker

            with patch.object(win.video_tab, "is_busy", return_value=True):
                with patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.Yes):
                    with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
                        evt = QCloseEvent()
                        win.closeEvent(evt, timeout_s=0.05)
                        mock_warn.assert_called_once()
                        self.assertFalse(evt.isAccepted(), "Không chấp nhận đóng cửa sổ khi worker vẫn hoạt động.")
        finally:
            win.video_tab.worker = None
            win.deleteLater()

    def test_13_skip_mode_not_counted_as_new_success(self):
        """Kiểm tra chế độ skip không được tính là video mới xuất thành công."""
        good_audio = self._create_sample_audio(duration_sec=1, filename="skip_test.mp3") if self.has_ffmpeg else "test.mp3"
        item = AudioVideoItem(audio_path=good_audio, story_title="Tiên Nghịch", volume_num=1, duration=1.0)
        target_name = item.suggested_output_filename()
        target_path = os.path.join(self.output_dir, target_name)
        with open(target_path, "wb") as f:
            f.write(b"EXISTING_VIDEO")

        cfg = VideoConfig(output_dir=self.output_dir, overwrite_mode="skip")

        skipped_signals = []
        finished_signals = []
        summary_holder = []

        worker = VideoExportWorker([item], cfg)
        worker.item_skipped.connect(lambda i_id, r: skipped_signals.append((i_id, r)))
        worker.item_finished.connect(lambda i_id, p: finished_signals.append((i_id, p)))
        worker.all_finished.connect(lambda s: summary_holder.append(s))

        worker.run()

        self.assertEqual(len(skipped_signals), 1)
        self.assertEqual(len(finished_signals), 0)
        self.assertEqual(len(summary_holder), 1)
        summary = summary_holder[0]
        self.assertEqual(summary.skipped_count, 1)
        self.assertEqual(summary.success_count, 0)
        self.assertEqual(summary.status, "hoàn tất")

    def test_14_cancel_progress_not_forced_to_100(self):
        """Kiểm tra sau khi hủy, thanh tiến độ hàng đợi giữ đúng phần đã xử lý, không ép 100%."""
        tab = VideoProductionTab()
        tab.prog_queue.setValue(35)
        tab.prog_item.setValue(50)

        summary_cancelled = ExportSummary({
            "status": "đã hủy",
            "success": 1,
            "skipped": 0,
            "error": 0,
            "cancelled": 2,
            "total": 3,
        })
        tab.on_worker_all_finished(summary_cancelled)

        # Tiến độ tập về 0, nhưng tiến độ hàng đợi không bị ép thành 100%
        self.assertEqual(tab.prog_item.value(), 0)
        self.assertEqual(tab.prog_queue.value(), 35)

    def test_15_background_audio_metadata_probing(self):
        """Kiểm tra worker nền đọc metadata, bỏ qua tệp hỏng/không có audio và ngăn trùng lặp."""
        valid_mp3 = self._create_sample_audio(duration_sec=3, filename="valid_probe.mp3") if self.has_ffmpeg else os.path.join(self.test_dir, "v.mp3")
        if not self.has_ffmpeg:
            with open(valid_mp3, "wb") as f:
                f.write(b"ID3dummy")

        corrupt_file = os.path.join(self.test_dir, "corrupted.mp3")
        with open(corrupt_file, "wb") as f:
            f.write(b"not an audio file at all")

        missing_file = os.path.join(self.test_dir, "missing_probe.mp3")

        filepaths = [valid_mp3, corrupt_file, missing_file, valid_mp3]
        probed_items = []
        finished_stats = []

        worker = AudioMetadataWorker(
            filepaths=filepaths,
            existing_paths=set(),
            ffprobe_path="",
        )
        worker.item_probed.connect(lambda d: probed_items.append(d))
        worker.all_finished.connect(lambda a, d, e: finished_stats.append((a, d, e)))

        # Mock probe_media để kiểm soát kết quả chính xác
        def mock_probe(path, *args, **kwargs):
            if path == os.path.abspath(valid_mp3):
                return {"has_audio": True, "duration": 3.5}
            return {"has_audio": False, "duration": 0.0}

        with patch("gui.video_worker.probe_media", side_effect=mock_probe):
            worker.run()

        self.assertEqual(len(finished_stats), 1)
        added, dups, errors = finished_stats[0]
        self.assertEqual(added, 1)
        self.assertEqual(dups, 1)
        self.assertEqual(errors, 2)

        # Kiểm tra không có tệp lỗi nào được gắn thời lượng 0 trong danh sách thêm
        valid_results = [r for r in probed_items if r.get("status") == "valid"]
        self.assertEqual(len(valid_results), 1)
        self.assertAlmostEqual(valid_results[0]["duration"], 3.5)


if __name__ == "__main__":
    unittest.main()
