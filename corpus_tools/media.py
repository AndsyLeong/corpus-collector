from pathlib import Path
import os
import shutil
import threading
import uuid

from .inputs import MEDIA, attach_text, media_fingerprint
from .storage import MediaItem, atomic_json, identity, now


class Cancelled(RuntimeError):
    pass


def _copy_media(source, destination, stop):
    """流式复制，保留时间属性；中断仅清理本次创建的临时副本。"""
    before = media_fingerprint(source)
    if shutil.disk_usage(destination.parent).free < source.stat().st_size:
        raise RuntimeError("输出位置空间不足，无法保存媒体副本。")
    temporary = destination.parent / (".copy-" + uuid.uuid4().hex + ".part")
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            while True:
                if stop.is_set():
                    raise Cancelled("已停止添加媒体。")
                block = reader.read(1024 * 1024)
                if not block:
                    break
                writer.write(block)
            writer.flush()
            os.fsync(writer.fileno())
        if before != media_fingerprint(source):
            raise ValueError("复制期间原媒体被修改，请重新添加。")
        shutil.copystat(source, temporary)
        if destination.exists():
            raise ValueError("整理目录已存在同名文件，无法覆盖。")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def add_media(file, output=None, stop=None, log=print):
    file = Path(file).resolve()
    if not file.is_file() or file.suffix.lower() not in MEDIA:
        raise ValueError(f"请选择视频或音频文件：{file.name}")
    stop = stop or threading.Event()
    if stop.is_set():
        raise Cancelled("已停止添加媒体。")
    state = file.parent / ".corpus/state.json"
    if state.is_file():
        item = MediaItem(file.parent)
        if item.media_path == file:
            return item
    fingerprint = media_fingerprint(file)
    sid = identity("media", str(file), fingerprint)
    parent = Path(output).resolve() if output else file.parent
    parent.mkdir(parents=True, exist_ok=True)
    counter = 1
    while True:
        folder = parent / (file.stem if counter == 1 else f"{file.stem} ({counter})")
        try:
            folder.mkdir()
        except FileExistsError:
            if (folder / ".corpus/state.json").is_file():
                existing = MediaItem(folder)
                if existing.id == sid:
                    item = existing
                    break
            counter += 1
            continue
        (folder / ".corpus").mkdir()
        atomic_json(folder / ".corpus/state.json", {
            "schema_version": 3, "type": "media", "name": file.name, "created_at": now(),
            "updated_at": now(), "revision": 0,
            "media": {"id": sid, "filename": file.name, "original_path": str(file),
                      "fingerprint": fingerprint, "copy_state": "pending"},
            "sources": {sid: {"id": sid, "name": file.name, "kind": "media",
                             "fingerprint": fingerprint, "transcribed": False, "error": ""}},
            "segments": {}, "hits": [],
            "search": {"keywords": [], "conversion": "none", "ignore_case": False, "performed": False},
        })
        item = MediaItem(folder)
        break
    with item.job():
        if item.media_path.exists():
            if media_fingerprint(item.media_path) != fingerprint:
                raise ValueError("整理目录中的媒体副本已改变，请添加到另一个输出位置。")
        else:
            log(f"{file.name}：复制媒体到 {item.root}")
            _copy_media(file, item.media_path, stop)
        with item.edit() as data:
            data["media"]["copy_state"] = "ready"
    if not item.read()["sources"][sid].get("transcribed"):
        for suffix in (".srt", ".txt"):
            text = file.with_suffix(suffix)
            if text.is_file():
                try:
                    attach_text(item, text)
                    log(f"{file.name}：已使用同名 {suffix} 文本。")
                    break
                except Exception as error:
                    log(f"{file.name}：同名文本读取失败（{error}），可改用转写。")
    return item


def media_files(folder):
    folder = Path(folder).resolve()
    for current, directories, filenames in os.walk(folder):
        root = Path(current)
        if (root / ".corpus/state.json").is_file():
            directories[:] = []
            item = MediaItem(root)
            yield item.media_path
            continue
        directories[:] = sorted(name for name in directories if name not in
                                {".corpus", ".venv", "venv", ".git", "node_modules", "__pycache__"})
        for name in sorted(filenames):
            if Path(name).suffix.lower() in MEDIA:
                yield root / name


def collect(paths, output=None, stop=None, log=print):
    stop = stop or threading.Event()
    files = []
    errors = []
    for path in paths:
        path = Path(path).resolve()
        try:
            files.extend(media_files(path) if path.is_dir() else [path])
        except Exception as error:
            errors.append({"file": str(path), "error": str(error)})
    items = {}
    duplicates = 0
    for file in files:
        if stop.is_set():
            break
        try:
            item = add_media(file, output, stop, log)
            if item.id in items:
                duplicates += 1
            items[item.id] = item
        except Cancelled:
            break
        except Exception as error:
            errors.append({"file": str(file), "error": str(error)})
            log(f"{file.name}：添加失败（{error}）。")
    return {"items": list(items.values()), "duplicates": duplicates,
            "errors": errors, "stopped": stop.is_set()}
