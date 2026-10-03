import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import wave

from corpus_tools.cli import search_items
from corpus_tools.exports import export, HEADERS
from corpus_tools.inputs import attach_text, parse_srt, decode, millis, timestamp
from corpus_tools.media import add_media, collect, Cancelled
from corpus_tools.providers import Qwen, Settings, https_url
from corpus_tools.search import search
from corpus_tools.storage import MediaItem
from corpus_tools.transcription import transcribe, transcribe_many

EXAMPLE = "1\n00:00:01,000 --> 00:00:03,000\n数据来自访谈，数据也来自视频。\n\n2\n00:00:04,000 --> 00:00:06,000\nApple and apple.\n"


def audio(file):
    file.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(file), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\0\0" * 16000 * 7)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "original" / "访谈.wav"
        audio(self.source)
        self.output = self.root / "collected"
        self.settings = Settings(rpm=1000000, chunk_seconds=5, qwen_key="fixture-secret")

    def tearDown(self):
        self.temp.cleanup()

    def item(self):
        return add_media(self.source, self.output, log=lambda _: None)

    def seed(self):
        self.source.with_suffix(".srt").write_text(EXAMPLE, encoding="utf-8-sig")
        item = self.item()
        search(item, ["数据"])
        return item

    def test_per_media_folder_contains_media_srt_txt_and_tables(self):
        before = self.source.read_bytes()
        item = self.seed()
        self.assertEqual(item.root, self.output / "访谈")
        self.assertEqual(item.media_path.name, "访谈.wav")
        self.assertEqual(item.media_path.read_bytes(), before)
        self.assertTrue((item.root / "访谈.srt").is_file())
        self.assertTrue((item.root / "访谈.txt").is_file())
        rows = item.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["source_name"], "访谈.wav")
        self.assertEqual(rows[1]["occurrence"], 2)
        self.assertEqual(rows[1]["offset"], 7)
        self.assertEqual(rows[1]["left_context"] + rows[1]["matched_term"] + rows[1]["right_context"], rows[1]["text"])
        result = export(item)
        self.assertEqual(Path(result["csv"]).parent, item.root)
        self.assertEqual(Path(result["xlsx"]).parent, item.root)
        with Path(result["csv"]).open(encoding="utf-8-sig", newline="") as handle:
            table = list(csv.reader(handle))
        self.assertEqual(table[0], HEADERS)
        self.assertEqual(len(table), 3)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse((item.root / "project.json").exists())
        self.assertEqual(json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))["state"], "complete")

    def test_default_output_is_next_to_source(self):
        item = add_media(self.source, log=lambda _: None)
        self.assertEqual(item.root, self.source.parent / self.source.stem)
        self.assertTrue(self.source.is_file())

    def test_readding_original_and_managed_media_resumes_without_duplicates(self):
        item = self.seed()
        original_again = self.item()
        copy_again = add_media(item.media_path, self.root / "unused", log=lambda _: None)
        self.assertEqual(item.root, original_again.root)
        self.assertEqual(item.root, copy_again.root)
        self.assertEqual(len(copy_again.rows()), 2)
        self.assertEqual(len(list(self.output.iterdir())), 1)
        self.assertFalse((self.root / "unused").exists())

    def test_same_names_from_different_sources_have_distinct_folders(self):
        first = self.seed()
        second_source = self.root / "another" / self.source.name
        audio(second_source)
        second_source.with_suffix(".txt").write_text("另一条数据", encoding="utf-8")
        second = add_media(second_source, self.output, log=lambda _: None)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(second.root.name, "访谈 (2)")
        self.assertEqual(search(second, ["数据"]), 1)
        self.assertEqual(first.rows()[0]["text"], "数据来自访谈，数据也来自视频。")
        self.assertEqual(add_media(second_source, self.output, log=lambda _: None).root, second.root)

    def test_existing_unrelated_folder_is_preserved(self):
        folder = self.output / "访谈"
        folder.mkdir(parents=True)
        (folder / "notes.txt").write_text("keep", encoding="utf-8")
        item = self.item()
        self.assertEqual(item.root.name, "访谈 (2)")
        self.assertEqual((folder / "notes.txt").read_text(encoding="utf-8"), "keep")

    def test_batch_search_exports_to_each_media_folder(self):
        first = self.seed()
        other = self.source.with_name("课堂.wav")
        audio(other)
        other.with_suffix(".txt").write_text("数据来自课堂。", encoding="utf-8")
        second = add_media(other, self.output, log=lambda _: None)
        report = search_items([first, second], ["数据"], log=lambda _: None)
        self.assertFalse(report["errors"])
        self.assertEqual([result["hits"] for result in report["results"]], [2, 1])
        for result, item in zip(report["results"], [first, second]):
            self.assertEqual(Path(result["csv"]).parent, item.root)
            self.assertEqual(Path(result["xlsx"]).parent, item.root)

    def test_existing_srt_preferred_to_txt_and_not_double_counted(self):
        self.source.with_suffix(".srt").write_text(EXAMPLE, encoding="utf-8")
        self.source.with_suffix(".txt").write_text("重复数据", encoding="utf-8")
        item = self.item()
        self.assertEqual(search(item, ["数据"]), 2)
        self.assertEqual(len(item.read()["segments"]), 2)

    def test_bad_sidecar_does_not_block_media_collection(self):
        self.source.with_suffix(".srt").write_text("bad subtitle", encoding="utf-8")
        item = self.item()
        self.assertTrue(item.media_path.is_file())
        self.assertFalse(item.read()["sources"][item.id]["transcribed"])

    def test_txt_replaces_srt_without_appending_and_invalidates_hits(self):
        item = self.seed()
        text = self.root / "new.txt"
        text.write_text("数据\n\n新的数据", encoding="utf-16")
        attach_text(item, text)
        self.assertFalse(item.rows())
        self.assertFalse(item.read()["search"]["performed"])
        self.assertFalse((item.root / "访谈.srt").exists())
        self.assertTrue(list((item.root / ".corpus/history").rglob("访谈.srt")))
        self.assertEqual(search(item, ["数据"]), 2)
        self.assertEqual([row["cue"] for row in item.rows()], [1, 3])
        self.assertTrue(all(row["start_ms"] is None for row in item.rows()))

    def test_malformed_text_preserves_previous_outputs_and_results(self):
        item = self.seed()
        subtitle = (item.root / "访谈.srt").read_bytes()
        malformed = self.root / "bad.srt"
        malformed.write_text("1\n00:00:04,000 --> 00:00:01,000\n文本\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            attach_text(item, malformed)
        self.assertEqual((item.root / "访谈.srt").read_bytes(), subtitle)
        self.assertEqual(len(item.rows()), 2)

    def test_bad_csv_header_preserves_state(self):
        item = self.item()
        text = self.root / "bad.csv"
        text.write_text("wrong\nsome text\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            attach_text(item, text)
        self.assertFalse(item.read()["segments"])

    def test_csv_custom_fields_and_missing_timestamps(self):
        item = self.item()
        text = self.root / "input.csv"
        text.write_text("text,speaker\n文本检索,Alice\n", encoding="utf-8-sig")
        attach_text(item, text)
        search(item, ["检索"])
        row = item.rows()[0]
        self.assertEqual(row["imported_fields"]["speaker"], "Alice")
        self.assertIsNone(row["start_ms"])
        self.assertEqual(row["source_name"], "访谈.wav")

    def test_literal_query_case_and_multiple_keywords(self):
        item = self.seed()
        self.assertEqual(search(item, ["apple"]), 1)
        self.assertEqual(search(item, ["apple"], ignore_case=True), 2)
        self.assertEqual([row["matched_term"] for row in item.rows()], ["Apple", "apple"])
        self.assertEqual(search(item, ["数据", "apple", "数据"], ignore_case=True), 4)
        self.assertEqual(search(item, ["."]), 1)
        self.assertEqual(search(item, ["missing"]), 0)
        result = export(item, False)
        with Path(result["csv"]).open(encoding="utf-8-sig", newline="") as handle:
            self.assertEqual(len(list(csv.reader(handle))), 1)

    def test_no_text_and_blank_keywords_do_not_create_false_results(self):
        item = self.item()
        with self.assertRaises(ValueError):
            search(item, ["数据"])
        with self.assertRaises(ValueError):
            export(item, False)
        item = self.seed()
        with self.assertRaises(ValueError):
            search(item, [" "])
        self.assertEqual(len(item.rows()), 2)

    def test_transaction_rollback_and_path_bounds(self):
        item = self.item()
        revision = item.read()["revision"]
        with self.assertRaises(RuntimeError):
            with item.edit() as state:
                state["name"] = "should not save"
                raise RuntimeError("fixture")
        self.assertEqual(item.read()["name"], self.source.name)
        self.assertEqual(item.read()["revision"], revision)
        with self.assertRaises(ValueError):
            item.path("../outside")
        with self.assertRaises(ValueError):
            item.path(str(self.source))

    def test_no_lost_updates_between_threads(self):
        item = self.item()
        revision = item.read()["revision"]
        failures = []
        def update(i):
            try:
                with item.edit() as state:
                    state.setdefault("notes", {})[str(i)] = i
            except Exception as error:
                failures.append(error)
        threads = [threading.Thread(target=update, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertFalse(failures)
        self.assertEqual(len(item.read()["notes"]), 8)
        self.assertEqual(item.read()["revision"], revision + 8)

    def test_task_lock_refuses_second_transcription(self):
        item = self.item()
        class Fake:
            def transcribe(self, file):
                raise AssertionError("must not send")
        with item.job():
            with self.assertRaises(RuntimeError):
                transcribe(item, Fake(), self.settings, log=lambda _: None)

    def test_export_unique_and_formula_literal(self):
        item = self.item()
        text = self.root / "formula.txt"
        text.write_text("=DATA()", encoding="utf-8")
        attach_text(item, text)
        search(item, ["DATA"])
        first, second = export(item), export(item)
        self.assertEqual(first["folder"], second["folder"])
        self.assertNotEqual(first["csv"], second["csv"])
        self.assertIn("'=DATA()", Path(first["csv"]).read_text(encoding="utf-8-sig"))
        from openpyxl import load_workbook
        book = load_workbook(first["xlsx"])
        self.assertEqual(book["检索结果"]["J2"].data_type, "s")
        self.assertEqual(book["检索结果"]["J2"].value, "=DATA()")
        book.close()

    def test_utf16_multiline_srt_and_time_validation(self):
        self.assertEqual(len(parse_srt(decode(EXAMPLE.rstrip().encode("utf-16")))), 2)
        self.assertEqual(parse_srt("00:00:01,000 --> 00:00:02,000\nhello\nworld")[0]["text"], "hello world")
        self.assertEqual(timestamp(millis("123:59:59,001")), "123:59:59,001")
        with self.assertRaises(ValueError):
            millis("01:99:00,000")

    def test_asr_auto_language_header_credentials_and_bad_response(self):
        with patch("corpus_tools.providers.request_json", return_value={"choices": [{"message": {"content": "文本"}}]}) as transport:
            self.settings.language = ""
            self.assertEqual(Qwen(self.settings).transcribe(self.source), "文本")
            url, body, headers, timeout = transport.call_args.args
            self.assertNotIn("language", body["asr_options"])
            self.assertNotIn("fixture-secret", url + json.dumps(body))
            self.assertEqual(headers["Authorization"], "Bearer fixture-secret")
            self.settings.language = "en"
            Qwen(self.settings).transcribe(self.source)
            self.assertEqual(transport.call_args.args[1]["asr_options"]["language"], "en")
        self.assertNotIn("fixture-secret", repr(self.settings))
        self.assertNotIn("fixture-secret", self.settings.safe_error(RuntimeError("fixture-secret")))
        for url in ["http://example.com", "https://example.com?token=abc", "https://user:pass@example.com"]:
            with self.assertRaises(ValueError):
                https_url(url)
        for payload in [{}, {"choices": [{"message": {"content": []}}]}]:
            with patch("corpus_tools.providers.request_json", return_value=payload):
                with self.assertRaises(ValueError):
                    Qwen(self.settings).transcribe(self.source)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg unavailable")
    def test_real_ffmpeg_uses_copy_and_resumes_failed_chunk(self):
        item = self.item()
        original = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.source.unlink()
        class Fake:
            def __init__(self):
                self.calls = []
                self.fail = True
            def transcribe(self, file):
                self.calls.append(file.name)
                if self.fail and file.name.endswith("000001.wav"):
                    raise RuntimeError("fixture-secret")
                return "收集数据。"
        service = Fake()
        first = transcribe(item, service, self.settings, log=lambda _: None)
        self.assertEqual(first["failed"], 1)
        self.assertFalse(item.read()["segments"])
        self.assertNotIn("fixture-secret", item.file.read_text(encoding="utf-8"))
        service.fail = False
        second = transcribe(item, service, self.settings, log=lambda _: None)
        self.assertEqual(second["completed"], 1)
        self.assertEqual(service.calls.count("chunk-000000.wav"), 1)
        self.assertEqual(service.calls.count("chunk-000001.wav"), 2)
        segments = list(item.read()["segments"].values())
        self.assertEqual(segments[0]["end_ms"], segments[1]["start_ms"])
        self.assertEqual(segments[-1]["end_ms"], 7000)
        self.assertEqual(hashlib.sha256(item.media_path.read_bytes()).hexdigest(), original)
        self.assertTrue((item.root / "访谈.srt").is_file())
        self.assertTrue((item.root / "访谈.txt").is_file())
        self.assertEqual(search(item, ["数据"]), 2)
        self.assertEqual(export(item)["rows"], 2)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg unavailable")
    def test_media_folder_can_move_and_transcribe_without_original(self):
        item = self.item()
        old_id = item.id
        destination = self.root / "moved"
        shutil.move(str(item.root), destination)
        self.source.unlink()
        moved = MediaItem(destination)
        self.assertEqual(moved.id, old_id)
        self.assertEqual(add_media(moved.media_path, log=lambda _: None).root, destination)
        class Fake:
            def transcribe(self, file):
                return "可移动的数据。"
        result = transcribe(moved, Fake(), self.settings, log=lambda _: None)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(search(moved, ["数据"]), 2)

    def test_copy_cancel_cleans_partial_file_and_can_resume(self):
        class StopDuringCopy:
            def __init__(self):
                self.calls = 0
            def is_set(self):
                self.calls += 1
                return self.calls >= 3
        with self.assertRaises(Cancelled):
            add_media(self.source, self.output, StopDuringCopy(), log=lambda _: None)
        folder = self.output / "访谈"
        self.assertFalse(list(folder.glob("*.part")))
        self.assertFalse((folder / "访谈.wav").exists())
        item = self.item()
        self.assertEqual(item.root, folder)
        self.assertEqual(item.media_path.read_bytes(), self.source.read_bytes())

    def test_batch_add_partial_failure_and_skip_internal_audio(self):
        item = self.seed()
        cache = item.root / ".corpus/jobs"
        cache.mkdir(parents=True)
        (cache / "chunk.wav").write_bytes(b"private temporary audio")
        report = collect([self.source, item.root, self.root / "missing.mp4"], self.output, log=lambda _: None)
        self.assertEqual(len(report["items"]), 1)
        self.assertEqual(report["duplicates"], 1)
        self.assertEqual(len(report["errors"]), 1)
        self.assertFalse((self.output / "chunk").exists())

    def test_stop_before_transcription_sends_nothing(self):
        item = self.item()
        event = threading.Event()
        event.set()
        class Fake:
            def transcribe(self, file):
                raise AssertionError("should not request")
        result = transcribe_many([item], Fake(), self.settings, event, log=lambda _: None)
        self.assertTrue(result["stopped"])
        self.assertFalse(result["completed"])

    def test_cli_pipeline_uses_media_paths_and_sidecar_offline(self):
        self.source.with_suffix(".srt").write_text(EXAMPLE, encoding="utf-8")
        environment = {**os.environ, "PYTHONUTF8": "1", "DASHSCOPE_API_KEY": ""}
        run = subprocess.run([sys.executable, "-m", "corpus_tools", "pipeline", str(self.source),
                              "--output", str(self.output), "--keywords", "数据", "apple",
                              "--ignore-case", "--csv-only"], capture_output=True, encoding="utf-8", env=environment)
        self.assertEqual(run.returncode, 0, run.stderr)
        report = json.loads(run.stdout)
        self.assertEqual(report["search"]["results"][0]["rows"], 4)
        self.assertEqual(Path(report["search"]["results"][0]["csv"]).parent, self.output / "访谈")
        self.assertEqual(report["transcribe"]["completed"], 0)

    def test_cli_reports_partial_failure_and_text_only_search(self):
        environment = {**os.environ, "PYTHONUTF8": "1"}
        added = subprocess.run([sys.executable, "-m", "corpus_tools", "add", str(self.source),
                                str(self.root / "missing.txt"), "--output", str(self.output)],
                               capture_output=True, encoding="utf-8", env=environment)
        self.assertEqual(added.returncode, 1)
        self.assertEqual(len(json.loads(added.stdout)["errors"]), 1)
        text = self.root / "existing.txt"
        text.write_text("数据来自文本", encoding="utf-8")
        searched = subprocess.run([sys.executable, "-m", "corpus_tools", "search", str(self.source),
                                   "--output", str(self.output), "--text", str(text), "--keywords", "数据",
                                   "--csv-only"], capture_output=True, encoding="utf-8", env=environment)
        self.assertEqual(searched.returncode, 0, searched.stderr)
        self.assertEqual(json.loads(searched.stdout)["search"]["results"][0]["rows"], 1)


if __name__ == "__main__":
    unittest.main()
