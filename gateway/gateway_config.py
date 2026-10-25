"""语音网关的持久化配置；浏览器读取时只返回密钥是否已配置。"""
import copy
import json
import math
import os
import re
from ipaddress import ip_address, ip_network
from pathlib import Path
from urllib.parse import urlsplit

DEFAULTS = {
    "asr_base_url": "https://api.siliconflow.cn/v1",
    "asr_model": "TeleAI/TeleSpeechASR",
    "asr_api_key": "",
    "asr_timeout_seconds": 4,
    "asr_fallback_model": "FunAudioLLM/SenseVoiceSmall",
    "asr_fallback_timeout_seconds": 2,
    "local_first": False,
    "suppress_noise_only": True,
    "max_compound_steps": 4,
    "local_max_chars": 12,
    "local_asr_url": "http://127.0.0.1:16066",
    "max_record_seconds": 18,
    "tts_base_url": "https://api.siliconflow.cn/v1",
    "tts_model": "FunAudioLLM/CosyVoice2-0.5B",
    "tts_voice": "FunAudioLLM/CosyVoice2-0.5B:anna",
    "tts_api_key": "",
    "tts_timeout_seconds": 15,
    "tts_first_chunk_timeout_seconds": 4,
    "tts_speed": 1.0,
    "tts_gain": 2.0,
    "ma_url": "http://127.0.0.1:8095",
    "ma_queue_id": "upbac50e55",
    "ma_token": "",
    "default_random_query": "国语流行",
    "default_random_providers": ["apple_music"],
    "r1_control_url": "http://192.168.1.3:8080",
    "allowed_clients": ["192.168.1.3", "192.168.1.88", "192.168.1.100", "127.0.0.1"],
    "bind_host": "192.168.1.88",
    "bind_port": 16068,
}
SECRETS = {"asr_api_key", "tts_api_key", "ma_token"}
RESTART_FIELDS = {"bind_host", "bind_port"}
NUMBERS = {
    "asr_timeout_seconds": (1, 30),
    "asr_fallback_timeout_seconds": (1, 20),
    "local_max_chars": (1, 32),
    "max_compound_steps": (2, 6),
    "max_record_seconds": (3, 30),
    "tts_timeout_seconds": (3, 60),
    "tts_first_chunk_timeout_seconds": (1, 15),
    "tts_speed": (0.5, 2),
    "tts_gain": (-10, 10),
    "bind_port": (1024, 65535),
}
INTEGERS = {"local_max_chars", "max_record_seconds", "bind_port", "max_compound_steps"}
URL_FIELDS = {"asr_base_url", "tts_base_url", "local_asr_url", "ma_url", "r1_control_url"}
ASR_PRESETS = ["TeleAI/TeleSpeechASR", "FunAudioLLM/SenseVoiceSmall", "XingChenAGI/XingChenGSR-V1.0"]


def client_allowed(remote, clients):
    """按真实连接地址匹配单个 IP 或 CIDR；不使用代理请求头授予权限。"""
    try:
        address = ip_address(remote)
    except (ValueError, TypeError):
        return False
    for entry in clients:
        try:
            network = ip_network(entry, strict=False)
        except (ValueError, TypeError):
            continue
        candidate = address
        if address.version == 6 and network.version == 4 and address.ipv4_mapped:
            candidate = address.ipv4_mapped
        if candidate in network:
            return True
    return False


def model_id(value, optional=False):
    if not isinstance(value, str) or len(value) > 160:
        raise ValueError("模型 ID 必须是最多 160 字符的文本")
    value = value.strip()
    if not value and optional:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*", value):
        raise ValueError("模型 ID 只能包含字母、数字和 _ . : / -")
    return value


def validate(values):
    result = copy.deepcopy(values)
    if set(result) != set(DEFAULTS):
        raise ValueError("配置项不完整或包含未知字段")
    for field in ["asr_model", "tts_model"]:
        result[field] = model_id(result[field])
    result["asr_fallback_model"] = model_id(result["asr_fallback_model"], optional=True)
    for field in URL_FIELDS:
        value = result[field]
        if not isinstance(value, str) or len(value) > 512:
            raise ValueError(field + " 地址无效")
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https", "ws", "wss"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError(field + " 需填写不含账号、查询参数的服务基础地址")
        if field != "local_asr_url" and parsed.scheme not in {"http", "https"}:
            raise ValueError(field + " 需使用 HTTP 或 HTTPS")
        try:
            parsed.port
        except ValueError as error:
            raise ValueError(field + " 端口无效") from error
        result[field] = value
    for field, (lower, upper) in NUMBERS.items():
        value = result[field]
        if isinstance(value, bool) or not isinstance(value, (float, int)):
            raise ValueError(field + " 必须是数字")
        if not math.isfinite(value) or not lower <= value <= upper:
            raise ValueError(f"{field} 需在 {lower}～{upper} 之间")
        if field in INTEGERS and int(value) != value:
            raise ValueError(field + " 必须是整数")
        result[field] = int(value) if field in INTEGERS else value
    if type(result["local_first"]) is not bool:
        raise ValueError("local_first 必须是布尔值")
    if type(result["suppress_noise_only"]) is not bool:
        raise ValueError("suppress_noise_only 必须是布尔值")
    for field in SECRETS:
        value = result[field]
        if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value):
            raise ValueError(field + " 格式无效")
        result[field] = value.strip()
    for field in ["tts_voice", "ma_queue_id", "bind_host", "default_random_query"]:
        value = result[field]
        if not isinstance(value, str) or not value.strip() or len(value) > 256 or any(ord(c) < 32 for c in value):
            raise ValueError(field + " 格式无效")
        result[field] = value.strip()
    providers = result["default_random_providers"]
    if (not isinstance(providers, list) or len(providers) > 32 or
            any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", v) for v in providers)):
        raise ValueError("default_random_providers 必须是音乐来源 ID 列表；空列表表示不限来源")
    clients = result["allowed_clients"]
    if (not isinstance(clients, list) or not clients or len(clients) > 32
            or any(not isinstance(v, str) or not v or len(v) > 128 for v in clients)):
        raise ValueError("allowed_clients 必须是非空地址列表")
    for client in clients:
        try:
            ip_network(client, strict=False)
        except ValueError:
            raise ValueError("allowed_clients 需填写 IP 地址或 CIDR 网段") from None
    if "127.0.0.1" not in clients:
        raise ValueError("allowed_clients 需要保留 127.0.0.1")
    if result["tts_first_chunk_timeout_seconds"] > result["tts_timeout_seconds"]:
        raise ValueError("TTS 首块等待不能大于 TTS 总超时")
    return result


class GatewayConfig:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / "gateway.private.json"
        values = copy.deepcopy(DEFAULTS)
        legacy = self.root / "provider.private.json"
        if legacy.exists():
            provider = json.loads(legacy.read_text(encoding="utf-8"))
            for prefix in ["asr", "tts"]:
                values[prefix + "_base_url"] = provider["base_url"]
                values[prefix + "_api_key"] = provider["api_key"]
        auth = self.root / "ma-authorization.private"
        if auth.exists():
            values["ma_token"] = auth.read_text(encoding="utf-8").strip().strip("'\"")
        if self.path.exists():
            values.update(json.loads(self.path.read_text(encoding="utf-8")))
        self._values = validate(values)
        self._startup_bind = {k: self._values[k] for k in RESTART_FIELDS}

    def snapshot(self):
        return copy.deepcopy(self._values)

    def public(self):
        values = self.snapshot()
        for field in SECRETS:
            values[field + "_configured"] = bool(values.pop(field))
        values["asr_presets"] = ASR_PRESETS
        values["restart_required"] = any(self._values[k] != v for k, v in self._startup_bind.items())
        return values

    def update(self, patch):
        if not isinstance(patch, dict):
            raise ValueError("配置必须是 JSON 对象")
        allowed = set(DEFAULTS) | {"clear_" + k for k in SECRETS}
        if set(patch) - allowed:
            raise ValueError("包含未知配置项")
        values = self.snapshot()
        for field in SECRETS:
            if "clear_" + field in patch and type(patch["clear_" + field]) is not bool:
                raise ValueError("清除密钥选项必须是布尔值")
        for key, value in patch.items():
            if key.startswith("clear_"):
                continue
            # 空白密钥表示保留；清除需要单独明确指定。
            if key in SECRETS and value == "":
                continue
            values[key] = value
        for field in SECRETS:
            if patch.get("clear_" + field):
                values[field] = ""
        values = validate(values)
        encoded = (json.dumps(values, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if self.path.exists():
            previous = self.root / "gateway.previous.private.json"
            self._atomic_write(previous, self.path.read_bytes())
        self._atomic_write(self.path, encoded)
        self._values = values
        return self.public()

    @staticmethod
    def _atomic_write(path, data):
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
