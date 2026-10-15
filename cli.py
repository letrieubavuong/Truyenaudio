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


def get_default_storage():
    return StorageManager("crawler_state.db")


def cmd_import(args):
    storage = get_default_storage()
    importer = OfflineImporter(storage)
    print(f"[*] Bắt đầu nạp các tệp từ thư mục: {args.dir}")
    chapters = importer.import_directory(
        directory_path=args.dir,
        story_title=args.title or "Phàm Nhân Tu Tiên",
        on_log=lambda lvl, msg: print(f"[{lvl}] {msg}"),
    )
    print(f"[✓] Đã nạp thành công {len(chapters)} chương vào CSDL.")


def cmd_crawl(args):
    storage = get_default_storage()
    crawler = NetworkCrawler(
        storage=storage,
        delay_seconds=args.delay,
        timeout_seconds=args.timeout,
    )
    print(f"[*] Bắt đầu thu thập mạng từ Chương {args.start_chap} đến Chương {args.end_chap}")
    res = crawler.crawl_range(
        story_url=args.story_url,
        start_chapter_url=args.start_url,
        start_chap_num=args.start_chap,
        end_chap_num=args.end_chap,
        on_log=lambda lvl, msg: print(f"[{lvl}] {msg}"),
        on_progress=lambda curr, tot, msg: print(f"Tiến độ: {curr}/{tot} - {msg}"),
    )
    print(f"[✓] Hoàn thành: Đã xử lý {res['fetched_count']} chương.")


def cmd_merge(args):
    storage = get_default_storage()
    checker = VietnameseSpellChecker()
    merger = VolumeMerger(
        chapters_per_volume=args.per_vol,
        allow_partial_last_volume=args.allow_partial,
    )

    story_id = 1
    chapters = storage.get_chapters_range(story_id, args.start_chap, args.end_chap)
    if not chapters:
        print(f"[!] Không tìm thấy chương nào trong khoảng {args.start_chap} - {args.end_chap} trong CSDL.")
        return

    print(f"[*] Đang xử lý kiểm tra chính tả và gộp {len(chapters)} chương...")

    all_issues = []
    edited_paragraphs_map = {}

    for ch in chapters:
        edited_paras, issues = checker.check_chapter(
            ch.paragraphs, chapter_num=ch.chapter_num, chapter_title=ch.chapter_title
        )
        edited_paragraphs_map[ch.chapter_num] = edited_paras
        all_issues.extend(issues)

    volumes = merger.build_volumes(
        chapters=chapters,
        start_volume_num=args.start_vol,
        expected_start_chap=args.start_chap,
        expected_end_chap=args.end_chap,
        story_title="Phàm Nhân Tu Tiên",
    )

    out_dir = args.out_dir or "output_volumes"
    os.makedirs(out_dir, exist_ok=True)

    for vol in volumes:
        vol_issues = [
            i for i in all_issues if i.chapter_num and vol.start_chapter <= i.chapter_num <= vol.end_chapter
        ]
        bundle = ReportGenerator.export_volume_bundle(
            volume=vol,
            output_dir=out_dir,
            merger=merger,
            issues=vol_issues,
            edited_paragraphs_map=edited_paragraphs_map,
            overwrite=args.overwrite,
        )
        print(f"[✓] Đã xuất Tập {vol.volume_num}:")
        print(f"    - RAW:       {bundle['raw']}")
        print(f"    - EDITED:    {bundle['edited']}")
        print(f"    - REPORT:    {bundle['report']}")
        print(f"    - CHANGELOG: {bundle['changelog']}")


def cmd_process(args):
    """Quy trình toàn diện: Nạp/Tải -> Sửa lỗi -> Gộp tập -> Báo cáo."""
    storage = get_default_storage()

    # 1. Thu thập hoặc Nạp offline
    if args.import_dir:
        importer = OfflineImporter(storage)
        print(f"[*] Đang nạp offline từ: {args.import_dir}")
        importer.import_directory(
            directory_path=args.import_dir,
            story_title=args.title or "Phàm Nhân Tu Tiên",
            on_log=lambda lvl, msg: print(f"[{lvl}] {msg}"),
        )
    elif args.start_url:
        crawler = NetworkCrawler(storage=storage)
        print(f"[*] Đang tải trực tiếp từ web: {args.start_url}")
        crawler.crawl_range(
            story_url=args.story_url or "https://vivutruyen.com/truyen/pham-nhan-tu-tien",
            start_chapter_url=args.start_url,
            start_chap_num=args.start_chap,
            end_chap_num=args.end_chap,
            on_log=lambda lvl, msg: print(f"[{lvl}] {msg}"),
        )

    # 2. Gộp tập & sửa lỗi
    cmd_merge(args)


def main():
    parser = argparse.ArgumentParser(
        description="Công cụ thu thập, sửa lỗi chính tả tiếng Việt và gộp tập truyện Phàm Nhân Tu Tiên"
    )
    subparsers = parser.add_subparsers(dest="command", help="Lệnh chức năng")

    # Subcommand: import
    p_import = subparsers.add_parser("import", help="Nạp tệp HTML/TXT từ thư mục vào CSDL SQLite")
    p_import.add_argument("--dir", required=True, help="Đường dẫn thư mục chứa các tệp HTML/TXT")
    p_import.add_argument("--title", default="Phàm Nhân Tu Tiên", help="Tên tác phẩm")

    # Subcommand: crawl
    p_crawl = subparsers.add_parser("crawl", help="Thu thập chương truyện từ web theo liên kết kế tiếp")
    p_crawl.add_argument("--story-url", default="https://vivutruyen.com/truyen/pham-nhan-tu-tien", help="URL trang truyện")
    p_crawl.add_argument("--start-url", required=True, help="URL chương bắt đầu")
    p_crawl.add_argument("--start-chap", type=int, default=1, help="Số chương bắt đầu")
    p_crawl.add_argument("--end-chap", type=int, default=4, help="Số chương kết thúc")
    p_crawl.add_argument("--delay", type=float, default=1.5, help="Thời gian nghỉ giữa các yêu cầu (giây)")
    p_crawl.add_argument("--timeout", type=int, default=20, help="Thời gian chờ tối đa (giây)")

    # Subcommand: merge
    p_merge = subparsers.add_parser("merge", help="Gộp các chương thành tập TXT và xuất báo cáo")
    p_merge.add_argument("--start-chap", type=int, required=True, help="Chương bắt đầu")
    p_merge.add_argument("--end-chap", type=int, required=True, help="Chương kết thúc")
    p_merge.add_argument("--start-vol", type=int, required=True, help="Số tập bắt đầu (do người dùng chỉ định)")
    p_merge.add_argument("--per-vol", type=int, default=4, help="Số chương mỗi tập (mặc định: 4)")
    p_merge.add_argument("--out-dir", default="output_volumes", help="Thư mục xuất file")
    p_merge.add_argument("--overwrite", action="store_true", help="Ghi đè file nếu đã tồn tại")
    p_merge.add_argument("--allow-partial", action="store_true", help="Cho phép xuất nhóm cuối dưới 4 chương")

    # Subcommand: process
    p_proc = subparsers.add_parser("process", help="Thực hiện trọn gói pipeline từ nạp/tải đến xuất tập")
    p_proc.add_argument("--import-dir", help="Thư mục nạp tệp offline (nếu có)")
    p_proc.add_argument("--story-url", help="URL truyện")
    p_proc.add_argument("--start-url", help="URL chương bắt đầu (nếu tải mạng)")
    p_proc.add_argument("--title", default="Phàm Nhân Tu Tiên", help="Tên truyện")
    p_proc.add_argument("--start-chap", type=int, required=True, help="Chương bắt đầu")
    p_proc.add_argument("--end-chap", type=int, required=True, help="Chương kết thúc")
    p_proc.add_argument("--start-vol", type=int, required=True, help="Số tập bắt đầu")
    p_proc.add_argument("--per-vol", type=int, default=4, help="Số chương mỗi tập")
    p_proc.add_argument("--out-dir", default="output_volumes", help="Thư mục xuất file")
    p_proc.add_argument("--overwrite", action="store_true", help="Ghi đè file nếu đã tồn tại")
    p_proc.add_argument("--allow-partial", action="store_true", help="Cho phép xuất nhóm cuối dưới 4 chương")

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


if __name__ == "__main__":
    main()
