import r1.local.asr.*;

/** 用实际 Handler 调度器核对真实播报边界、旧轮取消和轮数，不连接设备。 */
public final class FollowupEventsTest {
    static void check(boolean value){if(!value)throw new AssertionError();}
    static void waitEnd()throws Exception{Thread.sleep(650);}
    static void begin(int turn,boolean continuation){VoiceSession.turn=turn;VoiceFollowup.begin(continuation?"followup":"voice",turn);VoiceFollowup.recognized(turn);}
    public static void main(String[]args)throws Exception {
        try {
            begin(1,false);VoiceFollowup.speechEvent(2106);waitEnd();check(LocalAsr.starts==0);
            VoiceFollowup.speechEvent(2107);waitEnd();check(LocalAsr.starts==1);
            VoiceFollowup.responseEnded(1);waitEnd();check(LocalAsr.starts==1);
            begin(2,true);VoiceFollowup.speechEvent(2107);waitEnd();check(LocalAsr.starts==2);
            begin(3,true);VoiceFollowup.speechEvent(2107);waitEnd();check(LocalAsr.starts==3);
            begin(4,true);VoiceFollowup.speechEvent(2107);waitEnd();check(LocalAsr.starts==3);
            begin(5,false);VoiceFollowup.speechEvent(2107);VoiceSession.turn=6;waitEnd();check(LocalAsr.starts==3);
            begin(7,false);VoiceAiStream.pending=true;VoiceFollowup.speechEvent(2107);waitEnd();check(LocalAsr.starts==3);
            VoiceAiStream.pending=false;VoiceFollowup.responseEnded(7);waitEnd();check(LocalAsr.starts==4);
            begin(8,false);VoiceFollowup.speechEvent(2111);VoiceFollowup.speechEvent(2107);waitEnd();check(LocalAsr.starts==4);
            begin(9,false);VoiceFollowup.speechRequested(AsrRetryOnce.PROMPT);VoiceFollowup.speechEvent(2107);waitEnd();check(LocalAsr.starts==4);
            CloudVoiceSettings.enabled=false;begin(10,false);VoiceFollowup.speechEvent(2107);waitEnd();check(LocalAsr.starts==4);
            System.out.println("TTS boundary, duplicate events, bounded followups, stale turn, AI tail and failures passed");
        }finally{android.os.Handler.LOOP.shutdownNow();}
    }
}
