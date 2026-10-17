"""
Command Line Interface (CLI) for story crawling, offline importing,
Vietnamese spellchecking, volume merging, and report generation.
"""
import sys
import os
import argparse

# Thiết lập encoding utf-8 cho console Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from core.storage import StorageManager
from core.crawler import NetworkCrawler
from core.importer import OfflineImporter
from core.spellchecker import VietnameseSpellChecker
from core.ai_checker import AIChecker
from core.merger import VolumeMerger
from core.reporter import ReportGenerator
from core.profiles import get_profile, list_profiles


def get_default_storage():
    return StorageManager("crawler_state.db")


def resolve_story_profile(args):
    target = getattr(args, "story", "") or getattr(args, "title", "") or getattr(args, "story_url", "")
    source = getattr(args, "source", "")
    return get_profile(target, source_id=source)


def resolve_story_id(storage: StorageManager, args) -> int:
    if getattr(args, "story_id", None):
        return args.story_id
    profile = resolve_story_profile(args)
    story_url = getattr(args, "story_url", "") or profile.story_url
    story_title = getattr(args, "title", "") or profile.title
    story_author = profile.author
    story = storage.get_or_create_story(story_url, story_title, story_author)
    return story.id or 1


def cmd_import(args):
    storage = get_default_storage()
    importer = OfflineImporter(storage)
    profile = resolve_story_profile(args)
    story_title = getattr(args, "title", "") or profile.title
    story_url = getattr(args, "story_url", "") or profile.story_url
    print(f"[*] Bắt đầu nạp các tệp từ thư mục: {args.dir}")
    chapters = importer.import_directory(
        directory_path=args.dir,
        story_url=story_url,
        story_title=story_title,
        on_log=lambda lvl, msg: print(f"[{lvl}] {msg}"),
    )
    print(f"[✓] Đã nạp thành công {len(chapters)} chương vào CSDL.")


def cmd_crawl(args):
    storage = get_default_storage()
    profile = resolve_story_profile(args)
    story_url = getattr(args, "story_url", "") or profile.story_url
    start_url = getattr(args, "start_url", "") or profile.start_chapter_url
    crawler = NetworkCrawler(
        storage=storage,
        delay_seconds=args.delay,
        timeout_seconds=args.timeout,
    )
    res = crawler.crawl_range(
        story_url=story_url,
        start_chapter_url=start_url,
        start_chap_num=args.start_chap,
        end_chap_num=args.end_chap,
        on_log=lambda lvl, msg: print(f"[{lvl}] {msg}"),
        on_progress=lambda curr, tot, msg: print(f"Tiến độ: {curr}/{tot} - {msg}"),
    )
    if res.get("success"):
        print(f"[✓] {res.get('status_message')}")
    else:
        print(f"[!] {res.get('status_message')}")
        if res.get("stop_reason"):
            print(f"[!] Nguyên nhân chi tiết: {res.get('stop_reason')}")
        sys.exit(1)


def cmd_merge(args):
    storage = get_default_storage()
    profile = resolve_story_profile(args)
    checker = VietnameseSpellChecker()
    if profile.protected_terms_file:
        checker.set_protected_terms_path(profile.protected_terms_file)
    merger = VolumeMerger(
        chapters_per_volume=args.per_vol,
        allow_partial_last_volume=args.allow_partial,
        story_profile=profile,
    )

    story_id = resolve_story_id(storage, args)
    source = getattr(args, "source", "") or profile.active_source_id or ""
    chapters = storage.get_chapters_range(story_id, args.start_chap, args.end_chap, source=source)
    if not chapters:
        src_info = f", Nguồn: {source}" if source else ""
        print(f"[!] Không tìm thấy chương nào trong khoảng {args.start_chap} - {args.end_chap} (Story ID: {story_id}{src_info}) trong CSDL.")
        return

    do_spellcheck = not getattr(args, "no_spellcheck", False)
    use_ai = getattr(args, "use_ai", False)
    apply_ai = getattr(args, "apply_ai", False)

    ai_checker = None
    if use_ai:
        ai_checker = AIChecker(
            provider=getattr(args, "ai_provider", "openai_compatible"),
            api_key=getattr(args, "ai_api_key", ""),
            model=getattr(args, "ai_model", "gpt-4o-mini"),
            protected_terms=checker.protected_terms,
        )

    print(f"[*] Đang xử lý {len(chapters)} chương ({profile.title}, Story ID: {story_id}, Sửa chính tả: {do_spellcheck}, AI: {use_ai})...")

    all_issues = []
    edited_paragraphs_map = {}

    for ch in chapters:
        if do_spellcheck:
            # 1. Quy tắc & Từ điển
            _, rule_issues = checker.check_chapter(
                ch.paragraphs, chapter_num=ch.chapter_num, chapter_title=ch.chapter_title
            )

            # 2. AI tùy chọn
            ai_issues = []
            if use_ai and ai_checker and ai_checker.api_key:
                chunks = ai_checker.prepare_chunks(ch.paragraphs)
                for chunk in chunks:
                    chunk_issues, err = ai_checker.check_chunk(
                        chunk, chapter_num=ch.chapter_num, chapter_title=ch.chapter_title
                    )
                    if err:
                        print(f"[!] Lỗi AI tại Chương {ch.chapter_num}: {err}")
                    else:
                        for iss in chunk_issues:
                            iss.status = "applied" if apply_ai else "pending"
                        ai_issues.extend(chunk_issues)

            chap_issues = rule_issues + ai_issues
            all_issues.extend(chap_issues)

            # Dựng lại bản đã sửa dựa trên các đề xuất có status == 'applied'
            approved_issues = [i for i in chap_issues if i.status == "applied"]
            chap_edited_paras = []
            for p_idx, orig_text in enumerate(ch.paragraphs):
                p_issues = [i for i in approved_issues if i.paragraph_idx == p_idx]
                edited_p = VietnameseSpellChecker.apply_fixes(orig_text, p_issues, approved_only=True)
                chap_edited_paras.append(edited_p)

            edited_paragraphs_map[ch.chapter_num] = chap_edited_paras
        else:
            edited_paragraphs_map[ch.chapter_num] = ch.paragraphs

    volumes = merger.build_volumes(
        chapters=chapters,
        start_volume_num=args.start_vol,
        expected_start_chap=args.start_chap,
        expected_end_chap=args.end_chap,
        story_title=getattr(args, "title", "") or profile.title,
    )

    out_dir = args.out_dir if (args.out_dir and args.out_dir != "output_volumes") else profile.default_output_dir
    os.makedirs(out_dir, exist_ok=True)

    for vol in volumes:
        vol_issues = [
            i for i in all_issues if i.chapter_num is not None and vol.start_chapter <= i.chapter_num <= vol.end_chapter
        ]
        bundle = ReportGenerator.export_volume_bundle(
            volume=vol,
            output_dir=out_dir,
            merger=merger,
            issues=vol_issues,
            edited_paragraphs_map=edited_paragraphs_map,
            overwrite=args.overwrite,
            export_reports=getattr(args, "export_reports", False),
        )
        if getattr(args, "export_reports", False):
            print(f"[✓] Đã xuất Tập {vol.volume_num}:")
            print(f"    - RAW:       {bundle['raw']}")
            print(f"    - EDITED:    {bundle['edited']}")
            print(f"    - REPORT:    {bundle['report']}")
            print(f"    - CHANGELOG: {bundle['changelog']}")
        else:
            print(f"[✓] Đã xuất Tập {vol.volume_num}: {bundle['txt']}")


def cmd_process(args):
    """Quy trình toàn diện: Nạp/Tải -> Phân tích -> Gộp tập -> Báo cáo."""
    storage = get_default_storage()
    profile = resolve_story_profile(args)

    # 1. Thu thập hoặc Nạp offline
    if getattr(args, "import_dir", None):
        importer = OfflineImporter(storage)
        print(f"[*] Đang nạp offline từ: {args.import_dir}")
        importer.import_directory(
            directory_path=args.import_dir,
            story_url=getattr(args, "story_url", "") or profile.story_url,
            story_title=getattr(args, "title", "") or profile.title,
            on_log=lambda lvl, msg: print(f"[{lvl}] {msg}"),
        )
    else:
        start_u = getattr(args, "start_url", "") or profile.start_chapter_url
        story_u = getattr(args, "story_url", "") or profile.story_url
        if start_u or story_u:
            crawler = NetworkCrawler(storage=storage)
            print(f"[*] Đang tải trực tiếp từ web: {start_u or story_u}")
            res = crawler.crawl_range(
                story_url=story_u,
                start_chapter_url=start_u,
                start_chap_num=args.start_chap,
                end_chap_num=args.end_chap,
                on_log=lambda lvl, msg: print(f"[{lvl}] {msg}"),
            )
            if not res.get("success"):
                print(f"[!] Cảnh báo thu thập: {res.get('status_message')}")
                if res.get("fetched_count", 0) == 0:
                    print("[X] Không có chương nào được tải thành công. Hủy bỏ bước gộp tập.")
                    return

    # 2. Gộp tập & xuất kết quả
    cmd_merge(args)


def cmd_tts(args):
    """Sản xuất tệp âm thanh MP3 từ tệp TXT bằng VieNeu-TTS."""
    from core.tts_models import TTSItem, TTSConfig
    from core.tts_chunker import TextChunker
    from core.tts_manifest import TTSManifestManager
    from core.tts_adapter import TTSAdapter
    from core.tts_assembler import TTSAudioAssembler
    from core.video_models import parse_filename_metadata

    input_file = os.path.abspath(args.file)
    if not os.path.isfile(input_file):
        print(f"[X] Không tìm thấy tệp văn bản: {input_file}")
        sys.exit(1)

    with open(input_file, "r", encoding="utf-8") as f:
        raw_text = f.read()

    if not raw_text.strip():
        print("[X] Tệp văn bản rỗng.")
        sys.exit(1)

    fname = os.path.basename(input_file)
    meta = parse_filename_metadata(fname)
    chunks = TextChunker.chunk_text(raw_text)

    config = TTSConfig(
        python_path=args.python_path or "",
        model_name=args.model or "v3_turbo",
        backend=args.backend or "onnx",
        voice_id=args.voice or "Hải Đăng",
        mp3_bitrate=args.bitrate or "192k",
    )

    item = TTSItem(
        item_id=f"cli_{int(time.time())}",
        story_title=meta.get("story_title") or "Truyen",
        author=meta.get("author") or "",
        volume_num=meta.get("volume_num", 1),
        start_chap=meta.get("start_chapter", 1),
        end_chap=meta.get("end_chapter", 1),
        source="cli",
        raw_text=raw_text,
        text_source_path=input_file,
        word_count=len(raw_text.split()),
        char_count=len(raw_text),
        chunks=chunks,
        chunks_total=len(chunks),
        status="waiting",
    )

    print(f"[*] Bắt đầu quy trình TTS: {item.story_title} - Tập {item.volume_num}")
    print(f"[*] Tổng số từ: {item.word_count:,} | Số ký tự: {item.char_count:,} | Số đoạn chia: {len(chunks)}")
    print(f"[*] Giọng đọc: {config.voice_id} | Model: {config.model_name} | Backend: {config.backend}")

    # Chuẩn bị manifest và kiểm tra cache
    manifest_path, is_reused = TTSManifestManager.prepare_item_manifest(item, config)
    if is_reused:
        print(f"[✓] Tận dụng cache: {item.chunks_done}/{len(chunks)} đoạn đã có sẵn.")

    pending = [c for c in item.chunks if c.status != "completed"]
    if pending:
        task_file = TTSAdapter.create_batch_task_file(item, config)
        print(f"[*] Đang thực thi tổng hợp {len(pending)} đoạn...")

        def on_event(ev):
            ev_type = ev.get("type")
            if ev_type == "chunk_done":
                idx = ev.get("index", 0)
                dur = ev.get("duration_sec", 0.0)
                print(f"    - Đoạn [{idx + 1:04d}/{len(chunks):04d}] hoàn thành ({dur:.1f}s)")
            elif ev_type == "chunk_error":
                print(f"    [!] Lỗi đoạn {ev.get('index')}: {ev.get('error')}")

        ok, msg = TTSAdapter.execute_batch_task(
            python_path=config.python_path,
            task_file=task_file,
            event_callback=on_event,
            cancel_check=lambda: False,
            mock=args.mock,
        )
        if not ok:
            print(f"[X] Quá trình infer gặp lỗi: {msg}")
            sys.exit(1)

    # Ghép MP3
    print("[*] Đang ghép các đoạn WAV và mã hóa MP3 với FFmpeg...")
    out_dir = args.out_dir if args.out_dir else None
    mp3_path = TTSAudioAssembler.assemble_and_encode_mp3(item, config, output_dir=out_dir)
    print(f"[✓] Xuất bản MP3 thành công: {mp3_path}")
    print(f"[✓] Thời lượng audio: {item.duration_sec:.1f} giây")


def main():
    parser = argparse.ArgumentParser(
        description="Công cụ thu thập, sửa lỗi chính tả tiếng Việt và gộp tập truyện (Phàm Nhân Tu Tiên, Tiên Nghịch)"
    )
    subparsers = parser.add_subparsers(dest="command", help="Lệnh chức năng")

    # Subcommand: import
    p_import = subparsers.add_parser("import", help="Nạp tệp HTML/TXT từ thư mục vào CSDL SQLite")
    p_import.add_argument("--story", default="", help="Hồ sơ truyện: 'pham-nhan-tu-tien', 'tien-nghich'")
    p_import.add_argument("--source", default="", help="Nguồn truyện: 'tamhoan', 'webnovel', 'vivutruyen' (hoặc tên miền)")
    p_import.add_argument("--dir", required=True, help="Đường dẫn thư mục chứa các tệp HTML/TXT")
    p_import.add_argument("--story-url", default="", help="URL truyện")
    p_import.add_argument("--title", default="", help="Tên tác phẩm")

    # Subcommand: crawl
    p_crawl = subparsers.add_parser("crawl", help="Thu thập chương truyện từ web theo liên kết kế tiếp")
    p_crawl.add_argument("--story", default="", help="Hồ sơ truyện: 'pham-nhan-tu-tien', 'tien-nghich'")
    p_crawl.add_argument("--source", default="", help="Nguồn truyện: 'tamhoan', 'webnovel', 'vivutruyen' (hoặc tên miền)")
    p_crawl.add_argument("--story-url", default="", help="URL trang truyện")
    p_crawl.add_argument("--start-url", default="", help="URL chương bắt đầu")
    p_crawl.add_argument("--start-chap", type=int, default=1, help="Số chương bắt đầu")
    p_crawl.add_argument("--end-chap", type=int, default=12, help="Số chương kết thúc (khoảng tải: start-chap đến end-chap)")
    p_crawl.add_argument("--delay", type=float, default=1.5, help="Thời gian nghỉ giữa các yêu cầu (giây)")
    p_crawl.add_argument("--timeout", type=int, default=20, help="Thời gian chờ tối đa (giây)")

    # Subcommand: merge
    p_merge = subparsers.add_parser("merge", help="Gộp các chương thành tập TXT và xuất báo cáo")
    p_merge.add_argument("--story", default="", help="Hồ sơ truyện: 'pham-nhan-tu-tien', 'tien-nghich'")
    p_merge.add_argument("--source", default="", help="Nguồn truyện: 'tamhoan', 'webnovel', 'vivutruyen' (hoặc tên miền)")
    p_merge.add_argument("--story-id", type=int, help="ID truyện trong CSDL (mặc định tự phân giải)")
    p_merge.add_argument("--title", default="", help="Tên truyện")
    p_merge.add_argument("--start-chap", type=int, required=True, help="Chương bắt đầu")
    p_merge.add_argument("--end-chap", type=int, required=True, help="Chương kết thúc")
    p_merge.add_argument("--start-vol", type=int, required=True, help="Số tập bắt đầu (do người dùng chỉ định)")
    p_merge.add_argument("--per-vol", type=int, default=4, help="Số chương mỗi tập (mặc định: 4, chỉ dùng cho bước gộp tập)")
    p_merge.add_argument("--out-dir", default="", help="Thư mục xuất file")
    p_merge.add_argument("--overwrite", action="store_true", help="Ghi đè file nếu đã tồn tại")
    p_merge.add_argument("--allow-partial", action="store_true", help="Cho phép xuất nhóm cuối dưới 4 chương")
    p_merge.add_argument("--no-spellcheck", action="store_true", help="Tắt tính năng sửa chính tả")
    p_merge.add_argument("--use-ai", action="store_true", help="Bật phân tích lỗi bằng AI")
    p_merge.add_argument("--apply-ai", action="store_true", help="Tự động áp dụng cả các đề xuất của AI vào bản EDITED")
    p_merge.add_argument("--export-reports", action="store_true", help="Xuất kèm báo cáo audit (.md, .json). Mặc định chỉ xuất duy nhất file TXT hoàn chỉnh.")

    # Subcommand: process
    p_proc = subparsers.add_parser("process", help="Thực hiện trọn gói pipeline từ nạp/tải đến xuất tập")
    p_proc.add_argument("--story", default="", help="Hồ sơ truyện: 'pham-nhan-tu-tien', 'tien-nghich'")
    p_proc.add_argument("--source", default="", help="Nguồn truyện: 'tamhoan', 'webnovel', 'vivutruyen' (hoặc tên miền)")
    p_proc.add_argument("--import-dir", help="Thư mục nạp tệp offline (nếu có)")
    p_proc.add_argument("--story-id", type=int, help="ID truyện trong CSDL")
    p_proc.add_argument("--story-url", help="URL truyện")
    p_proc.add_argument("--start-url", help="URL chương bắt đầu (nếu tải mạng)")
    p_proc.add_argument("--title", default="", help="Tên truyện")
    p_proc.add_argument("--start-chap", type=int, required=True, help="Khoảng tải: Chương bắt đầu")
    p_proc.add_argument("--end-chap", type=int, required=True, help="Khoảng tải: Chương kết thúc")
    p_proc.add_argument("--start-vol", type=int, required=True, help="Số tập bắt đầu")
    p_proc.add_argument("--per-vol", type=int, default=4, help="Số chương mỗi tập (chỉ phục vụ gộp tập, không giới hạn tải)")
    p_proc.add_argument("--out-dir", default="", help="Thư mục xuất file")
    p_proc.add_argument("--overwrite", action="store_true", help="Ghi đè file nếu đã tồn tại")
    p_proc.add_argument("--allow-partial", action="store_true", help="Cho phép xuất nhóm cuối dưới 4 chương")
    p_proc.add_argument("--no-spellcheck", action="store_true", help="Tắt tính năng sửa chính tả")
    p_proc.add_argument("--use-ai", action="store_true", help="Bật phân tích lỗi bằng AI")
    p_proc.add_argument("--apply-ai", action="store_true", help="Tự động áp dụng cả các đề xuất của AI vào bản EDITED")
    p_proc.add_argument("--export-reports", action="store_true", help="Xuất kèm báo cáo audit (.md, .json). Mặc định chỉ xuất duy nhất file TXT hoàn chỉnh.")

    # Subcommand: tts
    p_tts = subparsers.add_parser("tts", help="Sản xuất tệp âm thanh MP3 từ tệp TXT bằng VieNeu-TTS")
    p_tts.add_argument("--file", required=True, help="Đường dẫn tệp TXT cần đọc")
    p_tts.add_argument("--voice", default="Hải Đăng", help="Tên giọng đọc (mặc định: 'Hải Đăng')")
    p_tts.add_argument("--model", default="v3_turbo", help="Tên model ('v3_turbo', 'v3nano')")
    p_tts.add_argument("--backend", default="onnx", help="Backend ('onnx', 'pytorch')")
    p_tts.add_argument("--bitrate", default="192k", help="Bitrate MP3 (mặc định: '192k')")
    p_tts.add_argument("--out-dir", default="", help="Thư mục xuất file MP3")
    p_tts.add_argument("--python-path", default="", help="Đường dẫn Python TTS riêng")
    p_tts.add_argument("--mock", action="store_true", help="Chế độ giả lập phục vụ kiểm thử")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "import":
        cmd_import(args)
    elif args.command == "crawl":
        cmd_crawl(args)
    elif args.command == "merge":
        cmd_merge(args)
    elif args.command == "process":
        cmd_process(args)
    elif args.command == "tts":
        cmd_tts(args)


if __name__ == "__main__":
    main()
