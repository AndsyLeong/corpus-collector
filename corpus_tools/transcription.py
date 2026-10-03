import hashlib
from pathlib import Path
import subprocess
import threading
import time
import wave

from .inputs import save_transcript, media_fingerprint
from .storage import atomic_json, identity


def transcribe(item, service, settings, stop=None, log=print, request_clock=None):
    """识别整理目录中的媒体副本，逐块持久化。"""
    if not 5 <= settings.chunk_seconds <= 120:
        raise ValueError("分段长度需为 5–120 秒。")
    if settings.rpm < 1:
        raise ValueError("RPM 必须为正整数。")
    stop = stop or threading.Event()
    complete, failed = 0, 0
    request_clock = [0.0] if request_clock is None else request_clock
    with item.job():
        for sid, source in item.read()["sources"].items():
            if source["kind"] != "media" or source.get("transcribed"):
                continue
            if stop.is_set():
                break
            media = item.media_path
            signature = identity(source["fingerprint"], settings.chunk_seconds,
                                 settings.qwen_model, settings.qwen_base, settings.language)
            work = item.path(f".corpus/jobs/asr-{signature}")
            work.mkdir(parents=True, exist_ok=True)
            checkpoint = work / "checkpoint.json"
            cache = {}
            if checkpoint.exists():
                import json
                cache = json.loads(checkpoint.read_text(encoding="utf-8"))
            try:
                if not media.is_file() or media_fingerprint(media) != source["fingerprint"]:
                    raise ValueError("整理目录中的媒体副本失效或已改变，请重新添加。")
                marker = work / "split.json"
                if not marker.exists():
                    # 重做未完成的切分，只清理此受控目录中的音频块。
                    for file in work.glob("chunk-*.wav"):
                        file.unlink()
                    command = [settings.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
                               "-i", str(media), "-vn", "-ac", "1", "-ar", "16000",
                               "-c:a", "pcm_s16le", "-f", "segment", "-segment_time",
                               str(settings.chunk_seconds), "-reset_timestamps", "1",
                               str(work / "chunk-%06d.wav")]
                    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, "CREATE_NO_WINDOW") else {}
                    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **options)
                    try:
                        while True:
                            try:
                                _, stderr = process.communicate(timeout=0.25)
                                break
                            except subprocess.TimeoutExpired:
                                if stop.is_set():
                                    process.terminate()
                                    process.communicate(timeout=10)
                                    return {"completed": complete, "failed": failed, "stopped": True}
                        if process.returncode:
                            raise RuntimeError("FFmpeg 音频切分失败：" + stderr.decode("utf-8", errors="replace")[-500:])
                    finally:
                        if process.poll() is None:
                            process.kill()
                            process.wait()
                    if not list(work.glob("chunk-*.wav")):
                        raise ValueError("FFmpeg 没有生成音频块。")
                    atomic_json(marker, {"signature": signature})
                blocks = sorted(work.glob("chunk-*.wav"))
                records, elapsed = [], 0
                for index, block in enumerate(blocks, 1):
                    if stop.is_set():
                        return {"completed": complete, "failed": failed, "stopped": True}
                    with wave.open(str(block), "rb") as handle:
                        duration = round(handle.getnframes() / handle.getframerate() * 1000)
                    checksum = hashlib.sha256(block.read_bytes()).hexdigest()
                    entry = cache.get(block.name)
                    if not entry or entry.get("sha256") != checksum:
                        if stop.wait(max(0, request_clock[0] - time.monotonic())):
                            return {"completed": complete, "failed": failed, "stopped": True}
                        request_clock[0] = time.monotonic() + 60 / settings.rpm
                        text = service.transcribe(block)
                        if not isinstance(text, str):
                            raise ValueError("转写服务必须返回字符串。")
                        entry = {"sha256": checksum, "text": text}
                        cache[block.name] = entry
                        atomic_json(checkpoint, cache)
                    if entry["text"].strip():
                        records.append({"cue": index, "text": entry["text"], "start_ms": elapsed,
                                        "end_ms": elapsed + duration})
                    elapsed += duration
                    log(f"{source['name']}：音频块 {index}/{len(blocks)}")
                if not records:
                    raise ValueError("全部音频块返回空文本，未标记转写完成。")
                save_transcript(item, records, "asr", {
                    "transcription_model": settings.qwen_model,
                    "chunk_seconds": settings.chunk_seconds, "language": settings.language})
                complete += 1
            except Exception as error:
                with item.edit() as data:
                    data["sources"][sid]["error"] = settings.safe_error(error)
                failed += 1
                log(f"{source['name']}：转写失败，已保留完成的块，可继续任务。")
    return {"completed": complete, "failed": failed, "stopped": stop.is_set()}


def transcribe_many(items, service, settings, stop=None, log=print):
    stop = stop or threading.Event()
    clock = [0.0]
    totals = {"completed": 0, "failed": 0, "stopped": False}
    for item in items:
        if stop.is_set():
            break
        result = transcribe(item, service, settings, stop, log, clock)
        totals["completed"] += result["completed"]
        totals["failed"] += result["failed"]
    totals["stopped"] = stop.is_set()
    return totals
