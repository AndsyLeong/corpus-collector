import importlib.util
from pathlib import Path
import tempfile
import unittest

from corpus_tools.inputs import attach_text
from corpus_tools.media import add_media
from corpus_tools.search import search


class OptionalTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("opencc"), "OpenCC unavailable")
    def test_conversion_matches_queries_and_retains_original(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            media = root / "demo.mp4"
            media.write_bytes(b"fixture")
            file = root / "text.txt"
            file.write_text("這些資料來自訪談。", encoding="utf-8")
            item = add_media(media, log=lambda _: None)
            attach_text(item, file)
            self.assertEqual(search(item, ["这些资料"], "t2s"), 1)
            row = item.rows()[0]
            self.assertEqual(row["original_text"], "這些資料來自訪談。")
            self.assertEqual(row["text"][row["offset"]:row["end_offset"]], row["matched_term"])

    @unittest.skipUnless(importlib.util.find_spec("openpyxl"), "Openpyxl unavailable")
    def test_xlsx_multiple_sheets_and_custom_fields(self):
        from openpyxl import Workbook
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            media = root / "demo.mp4"
            media.write_bytes(b"fixture")
            file = root / "input.xlsx"
            book = Workbook()
            book.active.append(["文本", "speaker"])
            book.active.append(["数据来自访谈。", "Alice"])
            sheet = book.create_sheet("another")
            sheet.append(["text"])
            sheet.append(["数据来自视频。"])
            book.save(file)
            book.close()
            item = add_media(media, log=lambda _: None)
            self.assertEqual(attach_text(item, file), 2)
            self.assertEqual(search(item, ["数据"]), 2)
            self.assertEqual(item.rows()[0]["imported_fields"]["speaker"], "Alice")
            self.assertEqual(len({row["segment_id"] for row in item.rows()}), 2)
