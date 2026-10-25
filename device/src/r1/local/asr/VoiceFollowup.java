package r1.local.asr;

import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;

/** 等真实播报结束后续听；静音或无有效指令即退出，不保持常开麦克风。 */
public final class VoiceFollowup {
    private static final Handler MAIN=new Handler(Looper.getMainLooper());
    private static final FollowupWindow WINDOW=new FollowupWindow();
    private static volatile boolean speechPlaying;

    private VoiceFollowup() {}

    public static void begin(String mode,int turn) {
        boolean continuation="followup".equals(mode);
        if (!(continuation||"voice".equals(mode))) {WINDOW.cancel();return;}
        int maximum=0;
        try {
            if(CloudVoiceSettings.getBoolean("followup_enabled",false))
                maximum=Math.max(1,Math.min(5,CloudVoiceSettings.getInt("followup_max_turns",3)));
        }catch(Exception ignored){}
        WINDOW.begin(turn,maximum,continuation);
        if(maximum==0)WINDOW.cancel();
    }

    public static void recognized(int turn) {
        WINDOW.recognized(turn,SystemClock.elapsedRealtime(),122000);
    }

    public static void cancel() {WINDOW.cancel();}
    public static void cancelTurn(int turn) {WINDOW.cancelTurn(turn);}

    public static void speechRequested(String text) {
        if(text==null)return;
        if(AsrRetryOnce.PROMPT.equals(text) || text.startsWith("语音识别服务暂时") ||
                text.startsWith("问答服务响应较慢") || text.startsWith("回答中断了") ||
                text.startsWith("HA 错误") || text.startsWith("连接HA失败") || text.startsWith("HA未配置"))
            WINDOW.cancelTurn(VoiceSession.currentTurn());
    }

    public static void speechEvent(int event) {
        if(event==2106)speechPlaying=true;
        else if(event==2107){speechPlaying=false;responseEnded(VoiceSession.currentTurn());}
        else if(event==2111){speechPlaying=false;WINDOW.cancelTurn(VoiceSession.currentTurn());}
    }

    public static void responseEnded(final int turn) {
        MAIN.postDelayed(new Runnable(){public void run(){
            if(!VoiceSession.isCurrent(turn) || speechPlaying || VoiceAiStream.hasPendingSpeech())return;
            long ticket=WINDOW.responseEnded(turn,SystemClock.elapsedRealtime());
            if(!WINDOW.take(ticket,turn,SystemClock.elapsedRealtime()))return;
            try{
                if(!CloudVoiceSettings.getBoolean("followup_enabled",false))return;
                LocalAsr.startFollowup(turn);
            }catch(Exception ignored){WINDOW.cancel();}
        }},500);
    }
}
