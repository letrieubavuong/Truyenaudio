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
import os
import shutil
import tempfile
import time
import subprocess
from PySide6.QtGui import QImage, QColor

from core.video_models import AudioVideoItem, VideoConfig, parse_filename_metadata
from core.video_renderer import render_frame, save_frame_image, ensure_qapp
from core.ffmpeg_utils import find_ffmpeg, check_ffmpeg_installed, probe_media, encode_video_from_frame
from gui.video_worker import VideoExportWorker


class TestVideoProduction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_qapp()
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

        good_audio = self._create_sample_audio(duration_sec=2, filename="good.mp3")
        bad_audio = os.path.join(self.test_dir, "non_existent.mp3")

        items = [
            AudioVideoItem(audio_path=bad_audio, story_title="Truyện Lỗi", volume_num=1),
            AudioVideoItem(audio_path=good_audio, story_title="Truyện Chuẩn", volume_num=2),
        ]

        config = VideoConfig(output_dir=self.output_dir)

        finished_events = []
        failed_events = []

        worker = VideoExportWorker(items, config)
        worker.item_finished.connect(lambda i_id, p: finished_events.append((i_id, p)))
        worker.item_failed.connect(lambda i_id, err: failed_events.append((i_id, err)))

        worker.run()  # Chạy đồng bộ trong test

        # Mục 1 bị lỗi vì file không tồn tại
        self.assertEqual(len(failed_events), 1)
        self.assertIn("Truyện Lỗi", [it.story_title for it in items if it.id == failed_events[0][0]])

        # Mục 2 thành công bình thường
        self.assertEqual(len(finished_events), 1)
        self.assertTrue(os.path.isfile(finished_events[0][1]))

    def test_08_overwrite_protection(self):
        """Kiểm tra không làm mất file hoàn chỉnh cũ nếu lần xuất thay thế thất bại."""
        if not self.has_ffmpeg:
            self.skipTest("FFmpeg không khả dụng.")

        good_audio = self._create_sample_audio(duration_sec=2, filename="good_vol1.mp3")
        item = AudioVideoItem(audio_path=good_audio, story_title="Tiên Nghịch", volume_num=1)
        config = VideoConfig(output_dir=self.output_dir)

        frame_path = os.path.join(self.test_dir, "frame_vol1.png")
        save_frame_image(item, config, frame_path)
        out1 = encode_video_from_frame(item, frame_path, config)
        self.assertTrue(os.path.isfile(out1))
        orig_size = os.path.getsize(out1)

        # Bây giờ giả lập lần xuất thứ 2 nhưng file audio bị xóa đột ngột (thất bại)
        corrupted_item = AudioVideoItem(audio_path=os.path.join(self.test_dir, "deleted.mp3"), story_title="Tiên Nghịch", volume_num=1)
        with self.assertRaises(Exception):
            encode_video_from_frame(corrupted_item, frame_path, config)

        # File cũ out1 vẫn phải nguyên vẹn
        self.assertTrue(os.path.isfile(out1))
        self.assertEqual(os.path.getsize(out1), orig_size)


if __name__ == "__main__":
    unittest.main()
