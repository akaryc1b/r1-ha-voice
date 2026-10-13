package r1.local.asr;

import android.util.Log;
import java.net.URI;
import org.json.JSONArray;
import org.json.JSONObject;

/** 日常语音采用短答；深入问题保留用户配置的模型推理行为。 */
public final class VoiceAiOptions {
    private VoiceAiOptions() {}

    public static void apply(JSONObject body, String question, String baseUrl) {
        try {
            JSONArray messages = body.optJSONArray("messages");
            if (messages != null && messages.length() > 0) {
                JSONObject system = messages.optJSONObject(0);
                if (system != null && "system".equals(system.optString("role"))) {
                    system.put("content", system.optString("content")
                        + "\n\n语音回答要求：默认用一到两句、80字以内的自然中文回答。"
                        + "用户明确要求详细解释时再展开。不要使用Markdown。"
                        + "当前没有联网搜索工具。本轮未收到真实查询结果时，不得给出当前汇率、天气、新闻、价格或设备状态的具体值，"
                        + "应明确说明暂时无法获取。不能把历史知识或估计包装成实时信息。");
                }
            }
            String host = baseUrl == null ? null : new URI(baseUrl).getHost();
            String model = body.optString("model");
            boolean supported = ("api.siliconflow.cn".equalsIgnoreCase(host)
                    || "api.siliconflow.com".equalsIgnoreCase(host))
                && ("deepseek-ai/DeepSeek-V3.2".equals(model)
                    || "Pro/deepseek-ai/DeepSeek-V3.2".equals(model)
                    || model.startsWith("Qwen/Qwen3.5-"));
            boolean detailed = question != null
                && question.matches("(?s).*(详细|深入|推理|证明|逐步|一步一步|深度分析|仔细分析).*");
            if (supported && !detailed) body.put("enable_thinking", false);
            Log.i("R1AIOptions", "short_voice=true fast_reasoning=" + (supported && !detailed));
        } catch (Exception error) {
            Log.w("R1AIOptions", "options_preserved " + error.getClass().getSimpleName());
        }
    }
}
