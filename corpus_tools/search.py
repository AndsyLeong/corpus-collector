import re
from .storage import identity


def search(item, keywords, conversion="none", ignore_case=False):
    keywords = list(dict.fromkeys(word.strip() for word in keywords if word.strip()))
    if not keywords:
        raise ValueError("请输入至少一个关键词。")
    if conversion not in ("none", "t2s", "s2hk"):
        raise ValueError("未知文字转换方式。")
    convert = lambda text: text
    if conversion != "none":
        try:
            from opencc import OpenCC
        except ImportError:
            raise RuntimeError("简繁转换需要安装 opencc-python-reimplemented。") from None
        convert = OpenCC(conversion).convert
    hits = []
    with item.edit() as data:
        if not data["segments"]:
            raise ValueError("该媒体还没有转写文本，请转写或使用已有字幕/TXT。")
        for segment in data["segments"].values():
            text = convert(segment["text"])
            for keyword in keywords:
                term = convert(keyword)
                if not term:
                    continue
                flags = re.IGNORECASE if ignore_case else 0
                for occurrence, match in enumerate(re.finditer(re.escape(term), text, flags), 1):
                    start, end = match.span()
                    hit = {"id": identity(segment["id"], keyword, conversion, ignore_case, start, end),
                           "segment_id": segment["id"], "source_id": segment["source_id"],
                           "source_name": data["sources"][segment["source_id"]]["name"],
                           "cue": segment["cue"], "start_ms": segment["start_ms"], "end_ms": segment["end_ms"],
                           "keyword": keyword, "matched_term": match.group(), "occurrence": occurrence,
                           "left_context": text[:start], "right_context": text[end:],
                           "offset": start, "end_offset": end, "text": text,
                           "original_text": segment["text"], "conversion": conversion,
                           "imported_fields": segment.get("imported_fields", {})}
                    hits.append(hit)
        data["hits"] = hits
        data["search"] = {"keywords": keywords, "conversion": conversion,
                          "ignore_case": bool(ignore_case), "performed": True}
    return len(hits)
