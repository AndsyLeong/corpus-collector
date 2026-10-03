from dataclasses import dataclass, field
import base64
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def resource(name):
    return Path(__file__).resolve().parent / "resources" / Path(name).name


@dataclass
class Settings:
    qwen_key: str = field(default_factory=lambda: os.getenv("DASHSCOPE_API_KEY", ""), repr=False)
    qwen_model: str = field(default_factory=lambda: os.getenv("QWEN_ASR_MODEL", "qwen3-asr-flash"))
    qwen_base: str = field(default_factory=lambda: os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
    language: str = field(default_factory=lambda: os.getenv("ASR_LANGUAGE", ""))
    ffmpeg: str = field(default_factory=lambda: os.getenv("FFMPEG_PATH", "ffmpeg"))
    chunk_seconds: int = 60
    rpm: int = 30
    timeout: int = 120

    def safe_error(self, error):
        text = f"{type(error).__name__}: {error}"
        if self.qwen_key:
            text = text.replace(self.qwen_key, "[密钥已隐藏]")
        return text[:1000]


def https_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("服务地址需为不带账号、查询参数或片段的 HTTPS URL。")
    return url.rstrip("/")


def request_json(url, payload, headers=None, timeout=120):
    """密钥只放请求头；错误不记录可能含凭据的响应正文。"""
    request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode(),
                      headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"阿里云 HTTP {error.code}；请检查模型、权限、配额与地域。") from None
    except URLError:
        raise RuntimeError("网络连接失败；检查网络和代理后可继续任务。") from None


class Qwen:
    """阿里云百炼 Qwen-ASR，使用 OpenAI 兼容的 HTTP 接口。"""
    def __init__(self, settings):
        if not settings.qwen_key.strip():
            raise ValueError("请填写 DashScope API Key。")
        if not settings.qwen_model.strip():
            raise ValueError("请填写阿里云 ASR 模型名。")
        if settings.timeout <= 0:
            raise ValueError("请求超时需大于零。")
        self.settings = settings
        self.base = https_url(settings.qwen_base)

    def transcribe(self, wav):
        audio = base64.b64encode(Path(wav).read_bytes()).decode("ascii")
        options = {"enable_itn": False}
        language = self.settings.language.strip()
        if language:
            options["language"] = language
        response = request_json(self.base + "/chat/completions", {
            "model": self.settings.qwen_model, "stream": False,
            "messages": [{"role": "user", "content": [{"type": "input_audio",
                          "input_audio": {"data": "data:audio/wav;base64," + audio}}]}],
            "asr_options": options,
        }, {"Authorization": "Bearer " + self.settings.qwen_key}, self.settings.timeout)
        choices = response.get("choices", [])
        if not choices:
            raise ValueError("阿里云没有返回识别结果。")
        text = choices[0].get("message", {}).get("content")
        if not isinstance(text, str):
            raise ValueError("阿里云返回的转写内容格式不正确。")
        return text.strip()
