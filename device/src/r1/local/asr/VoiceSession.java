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
        return SharedIntentRules.isExplanationQuestion(text);
    }

    public static boolean isHomeRequest(String text) {
        if (SharedIntentRules.isExplanationQuestion(text)) {
            android.util.Log.i("R1VoiceRoute","AI_EXPLANATION");return false;
        }
        boolean home=SharedIntentRules.isHomeRequest(text);
        android.util.Log.i("R1VoiceRoute",home?"HA_DIRECT":"AI_CHAT");return home;
    }

    public static boolean isControlRequest(String text) {
        return SharedIntentRules.isControlRequest(text);
    }

    public static void newTurn() { int turn = TURN.incrementAndGet(); LocalAsr.voiceTurnChanged(turn); VoiceAiStream.cancel(); }
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
