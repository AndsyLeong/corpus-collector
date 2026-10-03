import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sys

from .exports import export
from .inputs import attach_text
from .media import collect
from .providers import Qwen, Settings
from .search import search
from .transcription import transcribe_many


def doctor():
    settings = Settings()
    return {"python": sys.version.split()[0], "ffmpeg": shutil.which(settings.ffmpeg),
            "openpyxl": bool(importlib.util.find_spec("openpyxl")),
            "opencc": bool(importlib.util.find_spec("opencc")),
            "tkinter": bool(importlib.util.find_spec("tkinter")),
            "tkinterdnd2": bool(importlib.util.find_spec("tkinterdnd2")),
            "aliyun_key_configured": bool(settings.qwen_key),
            "asr_model": settings.qwen_model, "asr_language": settings.language or "auto"}


def search_items(items, keywords, conversion="none", ignore_case=False, xlsx=True, save=True, log=print):
    report = {"results": [], "errors": []}
    for item in items:
        try:
            hits = search(item, keywords, conversion, ignore_case)
            result = {"media": item.media_path.name, "folder": str(item.root), "hits": hits}
            if save:
                result.update(export(item, xlsx))
            report["results"].append(result)
            log(f"{item.media_path.name}：{hits} 次命中" + (f"，表格保存于 {item.root}" if save else "。"))
        except Exception as error:
            report["errors"].append({"media": item.media_path.name, "error": str(error)})
            log(f"{item.media_path.name}：{error}")
    return report


def parser():
    root = argparse.ArgumentParser(description="以媒体为单位：添加视频/音频 → 转写 → 词汇检索导出")
    subs = root.add_subparsers(dest="command")
    subs.add_parser("gui", help="打开图形界面")
    subs.add_parser("doctor", help="检查本地依赖与配置")
    for command, help_text in (("add", "为每个媒体建立独立文件夹并复制文件"),
                               ("transcribe", "添加媒体并转写未完成文件"),
                               ("search", "检索对应媒体的文本并逐文件导出表格"),
                               ("pipeline", "添加媒体、转写、检索与逐文件导出")):
        sub = subs.add_parser(command, help=help_text)
        sub.add_argument("media", nargs="+", type=Path, help="媒体文件或包含媒体的文件夹")
        sub.add_argument("--output", type=Path, help="整理目录的上级文件夹；默认在原媒体旁创建")
        if command in ("search", "pipeline"):
            sub.add_argument("--keywords", nargs="+", required=True)
            sub.add_argument("--conversion", choices=["none", "t2s", "s2hk"], default="none")
            sub.add_argument("--ignore-case", action="store_true")
            sub.add_argument("--csv-only", action="store_true")
            if command == "search":
                sub.add_argument("--text", type=Path, help="为单个媒体使用指定 SRT/TXT/CSV/XLSX")
        if command in ("transcribe", "pipeline"):
            sub.add_argument("--chunk-seconds", type=int, default=60)
            sub.add_argument("--rpm", type=int, default=30)
            sub.add_argument("--timeout", type=int, default=120)
            sub.add_argument("--language", default=Settings().language, help="留空自动识别；例如 zh/en/yue")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command in (None, "gui"):
        from .gui import main as gui_main
        gui_main()
        return 0
    settings = Settings()
    log = lambda text: print(text, file=sys.stderr)
    try:
        if args.command == "doctor":
            report = doctor()
            failed = False
        else:
            collected = collect(args.media, args.output, log=log)
            items = collected.pop("items")
            report = {"media": [{"file": str(item.media_path), "folder": str(item.root)} for item in items],
                      **collected}
            if getattr(args, "text", None):
                if len(items) != 1:
                    raise ValueError("--text 只能与一个媒体文件一起使用。")
                attach_text(items[0], args.text)
            if args.command in ("transcribe", "pipeline"):
                settings.chunk_seconds = args.chunk_seconds
                settings.rpm = args.rpm
                settings.timeout = args.timeout
                settings.language = args.language
                pending = [item for item in items if not item.read()["sources"][item.id]["transcribed"]]
                report["transcribe"] = transcribe_many(pending, Qwen(settings), settings, log=log) if pending else {
                    "completed": 0, "failed": 0, "stopped": False}
            if args.command in ("search", "pipeline"):
                report["search"] = search_items(items, args.keywords, args.conversion,
                                                args.ignore_case, not args.csv_only, log=log)
            failed = (not items or bool(report["errors"])
                      or bool(report.get("transcribe", {}).get("failed"))
                      or bool(report.get("search", {}).get("errors")))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if failed else 0
    except Exception as error:
        print(settings.safe_error(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
