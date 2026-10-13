package r1.local.asr;

import android.content.Context;
import com.unisound.vui.util.SharedPreferencesHelper;
import com.unisound.vui.util.UserPerferenceUtil;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;

/** 新指令到来后丢弃旧聊天回复；页面优先显示保存的自定义唤醒词。 */
public final class VoiceSession {
    private static final AtomicInteger TURN = new AtomicInteger();

    public static boolean isUnmatched(org.json.JSONObject response) {
        if (response == null || !"error".equals(response.optString("response_type"))) return false;
        org.json.JSONObject data = response.optJSONObject("data");
        return data != null && "no_intent_match".equals(data.optString("code"));
    }

    public static boolean isExplanationQuestion(String text) {
        if (text == null) return false;
        String clean = text.trim().replaceAll("[，。！？、,.!?]+$", "");
        if (clean.matches(".*(温湿度|温度|湿度)(怎么样|什么情况)$")) return false;
        return clean.matches("^(解释|介绍|说说|为什么|什么是|怎么|怎样|如何|你知道|告诉我为什么|告诉我怎么|告诉我如何).*") ||
                clean.matches(".*(是什么意思|有什么好处|有什么区别)$") ||
                (!isControlPrefix(clean) && (clean.matches(".*(为什么|怎么|如何|怎样).+") || clean.matches(".*(是什么|是谁|怎么回事|怎么办)$")));
    }

    private static String stripRequestPrefix(String text) {
        return text.replaceFirst("^(麻烦帮我|请帮我|请给我|能不能帮我|可以帮我|能不能|帮我|给我|麻烦|请|帮忙|可以)", "");
    }

    private static boolean isControlPrefix(String text) {
        text = stripRequestPrefix(text);
        return text.matches("^(请|帮我|给我|麻烦|请帮我|请给我|能不能|可以帮我)?(打开|关闭|播放|放|来|先暂停|先停|先别放|先不听|别放|别播放|不要放|不要播放|暂停|继续|停止|切换|下一首|上一首|把|调|设置).*");
    }

    public static boolean isHomeRequest(String text) {
        if (text == null) return false;
        if (isExplanationQuestion(text)) { android.util.Log.i("R1VoiceRoute","AI_EXPLANATION"); return false; }
        boolean home = isControlRequest(text) ||
                text.matches(".*(温湿度|温度|湿度|多少度|几度|几点|时间|星期几|周几|几号|日期|电脑|播放器|音量).*");
        android.util.Log.i("R1VoiceRoute", home ? "HA_DIRECT" : "AI_CHAT");
        return home;
    }

    public static boolean isControlRequest(String text) {
        if (text == null || isExplanationQuestion(text)) return false;
        if (MusicRoute.isCandidate(text)) return true;
        String clean = text.replaceAll("^[，。！？、,.!?]+|[，。！？、,.!?]+$", "").trim();
        clean = stripRequestPrefix(clean);
        return clean.matches("^(打开|关闭|关掉|开启|启动|开机|关机|取消关机|播放|放(?!心|弃|假|学)|放首|放一首|放点|放些|放一些|放音乐|放歌|来首|来一首|来点|随便|随机|换个|换首|换一首|回到上一首|接着放|听歌|听音乐|我要听|我想听|听点|点歌|先暂停|先停|先别放|先不听|别放|别播放|不要放|不要播放|暂停|继续|继续播放|停止|停止播放|停止音乐|下一首|下一曲|上一首|上一曲|切换|音量|音乐音量|播报音量|助手音量|回答声音|说话声音|大声|小声|调高|调低|调大|调小|静音|取消静音|提醒我|设置闹钟|设个闹钟|定个闹钟|设定闹钟|把).*$") ||
                clean.matches("^[把]?(音乐|音箱|音响|声音|播报|助手|回答|说话|语音|你的声音|你说话)(音量|声音)?(调|设置|调整|大|小|提高|降低|静音|取消静音).*$") ||
                clean.matches("^音乐(暂停|停止|继续|播放|上一首|下一首).*$");

    }

    public static void newTurn() { TURN.incrementAndGet(); }
    public static int currentTurn() { return TURN.get(); }
    public static boolean isCurrent(int turn) { return turn == TURN.get(); }

    public static List<String> getWakeupWords(Context context) {
        Set<String> custom = SharedPreferencesHelper.getInstance(context, "unicar_user_settings")
                .getStringSetValue("main_wakeup_word");
        if (custom == null || custom.isEmpty()) return UserPerferenceUtil.getMainWakeupWord(context);
        List<String> words = new ArrayList<String>(custom);
        Collections.sort(words);
        return words;
    }
}
