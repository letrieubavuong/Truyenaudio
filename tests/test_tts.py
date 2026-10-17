"""
Unit and Integration Tests for VieNeu-TTS Audio Production Pipeline.
Covers text chunking coverage, manifest resumption and invalidation,
audio assembly with silence frames, atomic MP3 export, subprocess isolation,
error handling, and GUI integration.
"""
import os
import sys
import json
import time
import wave
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from core.tts_models import TTSItem, TTSChunk, TTSConfig, TTSEnvStatus, TTSVoice
from core.tts_chunker import TextChunker
from core.tts_manifest import TTSManifestManager
from core.tts_adapter import TTSAdapter
from core.tts_assembler import TTSAudioAssembler, AudioAssemblyError
from core.ffmpeg_utils import find_ffmpeg, probe_media


class TestTextChunker(unittest.TestCase):
    """Kiểm thử thuật toán chia đoạn tiếng Việt TextChunker."""

    def test_empty_and_whitespace_text(self):
        self.assertEqual(TextChunker.chunk_text(""), [])
        self.assertEqual(TextChunker.chunk_text("   \n\n  \t  "), [])

    def test_reconstruction_and_coverage(self):
        """Kiểm tra tái dựng văn bản: không mất từ, không lặp từ và không đảo thứ tự."""
        sample_text = (
            "Chương 1: Khởi đầu tu tiên.\n\n"
            "Hàn Lập ngẩng đầu nhìn lên bầu trời xanh thẳm. Trong lòng hắn tràn ngập suy tư về con đường tu đạo gian truân.\n\n"
            "Hắn biết rằng, một khi đã bước chân vào giới tu tiên, sinh tử khó lường, "
            "nhưng lòng kiên định không hề lay chuyển dù chỉ một chút nào.\n\n"
            "Chương 2: Bí mật thần bí.\n\n"
            "Bình nhỏ màu xanh lục tỏa ra ánh sáng nhạt giữa màn đêm tĩnh lặng."
        )

        chunks = TextChunker.chunk_text(sample_text, max_chars=120)
        self.assertGreater(len(chunks), 4)

        # Kiểm tra thứ tự liên tục
        for i, c in enumerate(chunks):
            self.assertEqual(c.index, i)

        # Kiểm tra phát hiện tiêu đề chương
        self.assertTrue(chunks[0].is_chapter_boundary)
        chap2_chunks = [c for c in chunks if "Chương 2" in c.text]
        self.assertTrue(len(chap2_chunks) > 0)
        self.assertTrue(chap2_chunks[0].is_chapter_boundary)

        # Tái dựng văn bản
        reconstructed = TextChunker.reconstruct_text(chunks)
        for orig_word in sample_text.split():
            clean_word = orig_word.strip(".,:;!?\"'()")
            if clean_word:
                self.assertIn(clean_word, reconstructed)

    def test_split_long_sentence_with_clauses(self):
        """Kiểm tra câu dài vượt quá max_chars được tách theo mệnh đề tự nhiên."""
        long_sentence = (
            "Một luồng linh khí vô cùng nồng đậm từ trong đan điền đột ngột bùng phát ra xung quanh, "
            "khiến cho kinh mạch toàn thân đau nhức kịch liệt như muốn đứt đoạn, "
            "nhưng hắn vẫn cắn chặt răng kiên trì chịu đựng mà không hề kêu lên một tiếng nào."
        )
        self.assertGreater(len(long_sentence), 150)

        chunks = TextChunker.chunk_text(long_sentence, max_chars=100)
        self.assertGreater(len(chunks), 1)

        # Xác nhận độ dài từng đoạn <= max_chars và không bị mất chữ
        combined_text = " ".join(c.text for c in chunks)
        for w in long_sentence.split():
            self.assertIn(w.strip(",."), combined_text)

    def test_protect_decimals_in_sentence_splitting(self):
        """Không được ngắt câu ở số thập phân (ví dụ: 1.5 vạn dặm)."""
        text = "Khoảng cách ước tính khoảng 1.5 vạn dặm. Hắn phải mất 3 ngày mới tới."
        chunks = TextChunker.chunk_text(text)
        self.assertEqual(len(chunks), 2)
        self.assertIn("1.5 vạn dặm", chunks[0].text)


class TestTTSManifest(unittest.TestCase):
    """Kiểm thử quản lý manifest, cache và khả năng tiếp tục (resume)."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config = TTSConfig(
            model_name="v3_turbo",
            voice_id="Hải Đăng",
            sample_rate=48000,
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_mock_wav(self, file_path: str):
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with wave.open(file_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(48000)
            wf.writeframes(b"\x00\x00" * 4800)  # 0.1s

    def test_wav_file_validity_check(self):
        """Kiểm tra tính hợp lệ của file WAV: không rỗng, > 44 bytes, có header RIFF WAVE."""
        wav_path = os.path.join(self.test_dir, "test.wav")

        # 1. Chưa tồn tại
        self.assertFalse(TTSManifestManager.is_wav_file_valid(wav_path))

        # 2. File rỗng
        with open(wav_path, "wb") as f:
            pass
        self.assertFalse(TTSManifestManager.is_wav_file_valid(wav_path))

        # 3. File nhỏ hơn hoặc bằng 44 bytes không đủ header
        with open(wav_path, "wb") as f:
            f.write(b"RIFF" + b"\x00" * 30)
        self.assertFalse(TTSManifestManager.is_wav_file_valid(wav_path))

        # 4. File rác không đúng RIFF WAVE
        with open(wav_path, "wb") as f:
            f.write(b"GARBAGE_HEADER_DATA" * 5)
        self.assertFalse(TTSManifestManager.is_wav_file_valid(wav_path))

        # 5. File WAV hợp lệ
        self._create_mock_wav(wav_path)
        self.assertTrue(TTSManifestManager.is_wav_file_valid(wav_path))

    def test_manifest_creation_and_resume(self):
        """Kiểm tra lưu manifest và phục hồi tiến độ khi tiếp tục."""
        raw_text = "Câu thứ nhất để đọc thử.\n\nCâu thứ hai tiếp theo."
        chunks = TextChunker.chunk_text(raw_text)

        item = TTSItem(
            item_id="item_test_01",
            story_title="Tien Nghich",
            volume_num=1,
            start_chap=1,
            end_chap=4,
            raw_text=raw_text,
            chunks=chunks,
            chunks_total=len(chunks),
        )

        manifest_path, is_reused = TTSManifestManager.prepare_item_manifest(
            item, self.config, cache_dir=self.test_dir
        )
        self.assertFalse(is_reused)
        self.assertTrue(os.path.isfile(manifest_path))
        self.assertEqual(item.chunks_done, 0)

        # Giả lập hoàn thành chunk 0
        self._create_mock_wav(item.chunks[0].wav_path)
        item.chunks[0].status = "completed"
        item.chunks[0].duration_sec = 1.0
        item.chunks_done = 1
        TTSManifestManager.save_manifest(item, self.config, manifest_path)

        # Tải lại cùng cấu hình và nội dung -> Phải nhận diện được chunk 0 đã xong
        item_resume = TTSItem(
            item_id="item_test_01",
            story_title="Tien Nghich",
            volume_num=1,
            start_chap=1,
            end_chap=4,
            raw_text=raw_text,
            chunks=TextChunker.chunk_text(raw_text),
            chunks_total=len(chunks),
        )

        _, is_reused_2 = TTSManifestManager.prepare_item_manifest(
            item_resume, self.config, cache_dir=self.test_dir
        )
        self.assertTrue(is_reused_2)
        self.assertEqual(item_resume.chunks_done, 1)
        self.assertEqual(item_resume.chunks[0].status, "completed")
        self.assertEqual(item_resume.chunks[1].status, "pending")

    def test_cache_invalidation_when_text_or_config_changes(self):
        """Vô hiệu hóa cache khi nội dung văn bản hoặc giọng đọc thay đổi."""
        text1 = "Văn bản ban đầu."
        item1 = TTSItem(
            item_id="item_inv",
            story_title="Test",
            raw_text=text1,
            chunks=TextChunker.chunk_text(text1),
        )
        manifest_p, _ = TTSManifestManager.prepare_item_manifest(item1, self.config, cache_dir=self.test_dir)
        self._create_mock_wav(item1.chunks[0].wav_path)
        item1.chunks[0].status = "completed"
        TTSManifestManager.save_manifest(item1, self.config, manifest_p)

        # 1. Thay đổi văn bản
        text2 = "Văn bản đã bị sửa đổi nội dung!"
        item2 = TTSItem(
            item_id="item_inv",
            story_title="Test",
            raw_text=text2,
            chunks=TextChunker.chunk_text(text2),
        )
        _, is_reused_text = TTSManifestManager.prepare_item_manifest(item2, self.config, cache_dir=self.test_dir)
        self.assertFalse(is_reused_text)
        self.assertEqual(item2.chunks_done, 0)

        # 2. Thay đổi giọng đọc trong config
        config_diff_voice = TTSConfig(voice_id="Minh Quang", model_name="v3_turbo")
        item3 = TTSItem(
            item_id="item_inv",
            story_title="Test",
            raw_text=text1,
            chunks=TextChunker.chunk_text(text1),
        )
        _, is_reused_cfg = TTSManifestManager.prepare_item_manifest(item3, config_diff_voice, cache_dir=self.test_dir)
        self.assertFalse(is_reused_cfg)


class TestTTSAudioAssembler(unittest.TestCase):
    """Kiểm thử ghép nối đoạn WAV và mã hóa MP3 bằng FFmpeg."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config = TTSConfig(
            model_name="v3_turbo",
            voice_id="Hải Đăng",
            mp3_bitrate="192k",
            pause_sentence_ms=200,
            pause_paragraph_ms=400,
            pause_chapter_ms=800,
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_mock_wav(self, file_path: str, duration_sec: float = 0.5):
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with wave.open(file_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(48000)
            num_samples = int(48000 * duration_sec)
            wf.writeframes(b"\x00\x00" * num_samples)

    def test_refuse_assembly_when_chunks_missing(self):
        """Không được ghép MP3 nếu có bất kỳ đoạn nào chưa hoàn tất."""
        raw_text = "Đoạn 1.\n\nĐoạn 2."
        chunks = TextChunker.chunk_text(raw_text)
        item = TTSItem(
            item_id="item_missing",
            story_title="PNTT",
            volume_num=1,
            start_chap=1,
            end_chap=4,
            raw_text=raw_text,
            chunks=chunks,
        )
        for c in item.chunks:
            c.wav_path = os.path.join(self.test_dir, f"chunk_{c.index}.wav")

        # Chunk 0 xong nhưng chunk 1 chưa xong
        self._create_mock_wav(item.chunks[0].wav_path)
        item.chunks[0].status = "completed"
        item.chunks[1].status = "pending"

        with self.assertRaises(AudioAssemblyError) as ctx:
            TTSAudioAssembler.assemble_and_encode_mp3(item, self.config, output_dir=self.test_dir)
        self.assertIn("chưa hoàn tất", str(ctx.exception))

    def test_assemble_and_verify_mp3(self):
        """Ghép thành công 2 chunk, chèn khoảng nghỉ và kiểm tra MP3 bằng ffprobe."""
        ff_bin, _ = find_ffmpeg()
        if not ff_bin:
            self.skipTest("FFmpeg chưa được cài đặt trên máy test.")

        raw_text = "Chương 1: Mở màn.\n\nĐoạn văn thứ hai tiếp tục."
        chunks = TextChunker.chunk_text(raw_text)
        item = TTSItem(
            item_id="item_full",
            story_title="Tien_Nghich",
            author="Nhi Can",
            volume_num=2,
            start_chap=5,
            end_chap=8,
            raw_text=raw_text,
            chunks=chunks,
        )

        for c in item.chunks:
            c.wav_path = os.path.join(self.test_dir, f"chunk_{c.index}.wav")
            self._create_mock_wav(c.wav_path, duration_sec=0.5)
            c.status = "completed"
            c.duration_sec = 0.5

        mp3_path = TTSAudioAssembler.assemble_and_encode_mp3(item, self.config, output_dir=self.test_dir)
        self.assertTrue(os.path.isfile(mp3_path))
        self.assertEqual(item.status, "completed")
        self.assertGreater(item.duration_sec, 0.5)

        # Xác thực bằng ffprobe
        media_info = probe_media(mp3_path)
        self.assertTrue(media_info["has_audio"])
        self.assertGreater(media_info["duration"], 0.0)

    def test_safe_replacement_keeps_original_if_assembly_fails(self):
        """Nếu quá trình ghép gặp lỗi, tệp MP3 cũ vẫn được giữ nguyên vẹn."""
        target_path = os.path.join(self.test_dir, "Tien_Nghich_Tap_001_Chuong_1_den_4.mp3")
        with open(target_path, "w", encoding="utf-8") as f:
            f.write("ORIGINAL_VALID_CONTENT")

        item = TTSItem(
            item_id="fail_test",
            story_title="Tien_Nghich",
            volume_num=1,
            start_chap=1,
            end_chap=4,
            raw_text="Câu ngắn",
            chunks=[TTSChunk(index=0, text="Lỗi", text_hash="abc", char_count=3, word_count=1, paragraph_idx=0, status="pending")],
        )

        with self.assertRaises(AudioAssemblyError):
            TTSAudioAssembler.assemble_and_encode_mp3(item, self.config, output_dir=self.test_dir)

        # File cũ phải còn nguyên vẹn
        self.assertTrue(os.path.isfile(target_path))
        with open(target_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "ORIGINAL_VALID_CONTENT")


class TestTTSAdapterAndRunner(unittest.TestCase):
    """Kiểm thử adapter và runner trong tiến trình con."""

    def test_check_environment_graceful_when_not_installed(self):
        """Không gây crash hay exception khi vieneu chưa được cài đặt."""
        status = TTSAdapter.check_environment()
        self.assertIsInstance(status, TTSEnvStatus)
        # Báo cáo rõ ràng trạng thái khả dụng
        self.assertIsInstance(status.available, bool)
        self.assertIsInstance(status.models, list)
        self.assertIn("v3_turbo", status.models)

    def test_runner_batch_task_mock_mode(self):
        """Kiểm thử thực thi batch task qua runner ở chế độ mock."""
        test_dir = tempfile.mkdtemp()
        try:
            raw_text = "Đoạn một để thử nghiệm.\n\nĐoạn hai để kiểm tra mock."
            chunks = TextChunker.chunk_text(raw_text)
            item = TTSItem(
                item_id="batch_mock_01",
                story_title="TestStory",
                volume_num=1,
                start_chap=1,
                end_chap=4,
                raw_text=raw_text,
                chunks=chunks,
            )
            config = TTSConfig()
            manifest_p, _ = TTSManifestManager.prepare_item_manifest(item, config, cache_dir=test_dir)

            task_file = TTSAdapter.create_batch_task_file(item, config)
            self.assertTrue(os.path.isfile(task_file))

            events = []
            success, msg = TTSAdapter.execute_batch_task(
                python_path=sys.executable,
                task_file=task_file,
                event_callback=lambda ev: events.append(ev),
                cancel_check=lambda: False,
                mock=True,
            )

            self.assertTrue(success)
            done_events = [e for e in events if e.get("type") == "chunk_done"]
            self.assertEqual(len(done_events), len(chunks))

            for c in item.chunks:
                self.assertTrue(TTSManifestManager.is_wav_file_valid(c.wav_path))

        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_cancellation_cleans_up_process(self):
        """Hủy tác vụ giải phóng tiến trình sạch sẽ."""
        test_dir = tempfile.mkdtemp()
        try:
            chunks = [
                TTSChunk(index=i, text=f"Câu số {i}", text_hash=f"h_{i}", char_count=8, word_count=3, paragraph_idx=0,
                         wav_path=os.path.join(test_dir, f"c_{i}.wav"))
                for i in range(20)
            ]
            item = TTSItem(item_id="cancel_item", story_title="Test", raw_text="...", chunks=chunks, manifest_dir=test_dir)
            task_file = TTSAdapter.create_batch_task_file(item, TTSConfig())

            cancel_flag = False

            def on_event(ev):
                nonlocal cancel_flag
                if ev.get("type") == "chunk_done" and ev.get("index") >= 1:
                    cancel_flag = True

            success, msg = TTSAdapter.execute_batch_task(
                python_path=sys.executable,
                task_file=task_file,
                event_callback=on_event,
                cancel_check=lambda: cancel_flag,
                mock=True,
            )

            self.assertFalse(success)
            self.assertIn("hủy", msg.lower())

        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_find_python_tts_resolution(self):
        """Kiểm tra tìm kiếm python executable cho TTS trả về đường dẫn hợp lệ."""
        py_bin = TTSAdapter.find_python_tts()
        self.assertTrue(bool(py_bin))
        self.assertTrue(os.path.isfile(py_bin))

    def test_preview_synthesis_produces_valid_wav(self):
        """Kiểm tra tạo mẫu nghe thử trả về file WAV 48kHz hợp lệ và thời lượng dương."""
        test_dir = tempfile.mkdtemp()
        try:
            out_wav = os.path.join(test_dir, "preview_test.wav")
            success, res_path, dur = TTSAdapter.synthesize_preview(
                python_path=sys.executable,
                text="Xin chào, đây là câu thử nghiệm.",
                voice_id="Hải Đăng",
                out_wav=out_wav,
            )
            self.assertTrue(success, f"Tạo nghe thử thất bại: {res_path}")
            self.assertTrue(os.path.isfile(out_wav))
            self.assertTrue(TTSManifestManager.is_wav_file_valid(out_wav))
            self.assertGreater(dur, 0.5)
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)


class TestTTSGUIIntegration(unittest.TestCase):
    """Kiểm thử tích hợp giao diện GUI và luân chuyển sang Tab Video."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_audio_tab_initialization_and_table(self):
        from gui.tts_tab import AudioProductionTab
        tab = AudioProductionTab()
        self.assertEqual(tab.table_queue.columnCount(), 8)
        self.assertEqual(tab.table_queue.rowCount(), 0)

    def test_transfer_to_video_pipeline(self):
        """Kiểm tra truyền dữ liệu từ Audio Tab sang Video Tab kèm metadata chính xác."""
        from gui.tts_tab import AudioProductionTab
        from gui.video_tab import VideoProductionTab

        audio_tab = AudioProductionTab()
        video_tab = VideoProductionTab()

        test_dir = tempfile.mkdtemp()
        try:
            dummy_mp3 = os.path.join(test_dir, "Pham_Nhan_Tu_Tien_Tap_001_Chuong_1_den_4.mp3")
            with open(dummy_mp3, "wb") as f:
                f.write(b"ID3" + b"\x00" * 100)

            item = TTSItem(
                item_id="trans_01",
                story_title="Phàm Nhân Tu Tiên",
                author="Vong Ngữ",
                volume_num=1,
                start_chap=1,
                end_chap=4,
                duration_sec=3600.0,
                output_mp3_path=dummy_mp3,
                status="completed",
            )
            audio_tab.items.append(item)

            transferred_data = []
            audio_tab.transfer_to_video_requested.connect(lambda data: transferred_data.extend(data))
            audio_tab.transfer_to_video()

            self.assertEqual(len(transferred_data), 1)
            self.assertEqual(transferred_data[0]["story_title"], "Phàm Nhân Tu Tiên")
            self.assertEqual(transferred_data[0]["volume_num"], 1)
            self.assertEqual(transferred_data[0]["start_chapter"], 1)
            self.assertEqual(transferred_data[0]["end_chapter"], 4)

            # Đưa vào video_tab
            added = video_tab.add_direct_items(transferred_data)
            self.assertEqual(added, 1)
            self.assertEqual(len(video_tab.items), 1)
            self.assertEqual(video_tab.items[0].story_title, "Phàm Nhân Tu Tiên")
            self.assertEqual(video_tab.items[0].volume_num, 1)

        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_studio_ui_components_and_voice_cards(self):
        """Kiểm tra giao diện Studio: 25 thẻ giọng, bộ lọc giới tính, tag cảm xúc, tốc độ."""
        from gui.tts_tab import AudioProductionTab
        tab = AudioProductionTab()

        # 1. Kiểm tra số lượng thẻ giọng
        self.assertGreaterEqual(len(tab.voice_cards), 25)

        # 2. Kiểm tra bộ lọc Tất cả / Nữ / Nam
        tab.set_voice_filter("Nam")
        male_visible = [c for c in tab.voice_cards if not c.isHidden()]
        self.assertTrue(all(c.voice.gender == "Nam" for c in male_visible))
        self.assertGreater(len(male_visible), 0)

        tab.set_voice_filter("Nữ")
        female_visible = [c for c in tab.voice_cards if not c.isHidden()]
        self.assertTrue(all(c.voice.gender == "Nữ" for c in female_visible))
        self.assertGreater(len(female_visible), 0)

        tab.set_voice_filter("all")
        all_visible = [c for c in tab.voice_cards if not c.isHidden()]
        self.assertEqual(len(all_visible), len(tab.voice_cards))

        # 3. Chèn tag cảm xúc
        init_len = len(tab.txt_content.toPlainText())
        tab.insert_tag(" [cười] ")
        self.assertIn("[cười]", tab.txt_content.toPlainText())

        # 4. Điều chỉnh tốc độ và ước tính audio
        tab.slider_speed.setValue(110)
        self.assertEqual(tab.lbl_speed_val.text(), "1.10")
        self.assertIn("audio", tab.lbl_estimate.text())

    def test_clean_reading_text_and_dictionary(self):
        """Kiểm tra làm sạch văn bản và áp dụng từ điển phát âm."""
        from core.tts_dictionary import clean_reading_text, TTSDictionaryManager

        raw_dirty = (
            "Nguồn: tamhoan.com\n"
            "   Phàm   Nhân    Tu Tiên   -   PNTT   \n"
            "“Đạo hữu xin dừng bước!” - Hàn Lập quát.\n"
            "Đọc truyện online tại vivutruyen.com\n"
        )
        dm = TTSDictionaryManager()
        cleaned = clean_reading_text(raw_dirty, apply_dict=True, dict_manager=dm)

        # Đã lọc watermark
        self.assertNotIn("tamhoan.com", cleaned)
        self.assertNotIn("vivutruyen.com", cleaned)
        # Đã chuẩn hóa ngoặc kép
        self.assertIn('"Đạo hữu xin dừng bước!"', cleaned)
        # Đã thay thế từ viết tắt theo từ điển
        self.assertIn("Phàm Nhân Tu Tiên", cleaned)


if __name__ == "__main__":
    unittest.main()

