from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def identity(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:24]


def atomic_json(target, value):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".write-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def file_lock(target, timeout=10):
    """跨进程互斥；崩溃遗留锁不自动删除，避免覆盖仍在运行的任务。"""
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"文件正被使用或存在遗留锁：{target}")
            time.sleep(0.05)
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        Path(target).unlink(missing_ok=True)



class MediaItem:
    """每份媒体的独立目录；运行状态位于 .corpus 中，用户无需创建项目。"""
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.file = self.root / ".corpus" / "state.json"
        self.read()

    def read(self):
        with self.file.open(encoding="utf-8") as handle:
            data = json.load(handle)
        if data.get("schema_version") != 3 or data.get("type") != "media":
            raise ValueError("此目录不是当前版本的媒体整理目录。")
        if not all(key in data for key in ("media", "sources", "segments", "hits", "search")):
            raise ValueError("媒体状态文件不完整。")
        return data

    @contextmanager
    def edit(self):
        with file_lock(self.path(".corpus/write.lock")):
            data = self.read()
            yield data
            data["revision"] += 1
            data["updated_at"] = now()
            atomic_json(self.path(".corpus/state.previous.json"), self.read())
            atomic_json(self.file, data)

    @contextmanager
    def job(self):
        with file_lock(self.path(".corpus/task.lock"), timeout=0):
            yield

    def path(self, relative):
        candidate = (self.root / relative).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError("媒体目录内路径越界。")
        return candidate

    @property
    def media_path(self):
        return self.path(self.read()["media"]["filename"])

    @property
    def id(self):
        return self.read()["media"]["id"]

    def rows(self, data=None):
        return (self.read() if data is None else data)["hits"]
