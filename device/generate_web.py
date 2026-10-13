"""将可直接编辑的 HTML、JS、CSS 编入 Android 5.1 可用的 Java 类。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
card = (WEB / "voice-card.html").read_text(encoding="utf-8")
script = "<style>" + (WEB / "voice-settings.css").read_text(encoding="utf-8") + "</style>\n"
script += "<script>" + (WEB / "voice-settings.js").read_text(encoding="utf-8") + "</script>\n"
for text in [card, script]:
    if len(text.encode("utf-8")) > 60000:
        raise ValueError("页面常量超过 Java 常量池长度，请拆分页面")
source = "package r1.local.asr;\n\n/** 从 web 目录生成，请编辑 HTML/JS/CSS 源文件。 */\n"
source += "public final class VoiceConfigPage {\n"
source += "    public static String card() { return " + json.dumps(card) + "; }\n"
source += "    public static String script() { return " + json.dumps(script) + "; }\n}\n"
(ROOT / "src/r1/local/asr/VoiceConfigPage.java").write_bytes(source.encode("utf-8"))
