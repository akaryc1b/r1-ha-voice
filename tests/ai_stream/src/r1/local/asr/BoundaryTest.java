package r1.local.asr;
public class BoundaryTest {
    public static class One {int count;public void playTTS(String text){count++;}}
    public static class Two {int count;public void playTTS(String text){count++;}}
    static void check(boolean ok){if(!ok)throw new AssertionError();}
    public static void main(String[] args){
        check(VoiceAiStream.sentenceEnd("可以的。后文")==4);
        check(VoiceAiStream.sentenceEnd("好的，我来解释一下。")==-1);
        check(VoiceAiStream.sentenceEnd("好的，我来解释一下。彩虹由折射形成。")>12);
        String clause="太阳光穿过空气中很小的水滴后，剩余回答";
        check(VoiceAiStream.sentenceEnd(clause)==clause.indexOf('，')+1);
        check(VoiceAiStream.sentenceEnd("太短，继续")==-1);
        One one=new One();Two two=new Two();VoiceSession.next();int turn=VoiceSession.currentTurn();
        VoiceAiStream.playReply(one,"一",turn);VoiceAiStream.playReply(two,"二",turn);
        VoiceAiStream.playReply(one,"三",turn);check(one.count==2&&two.count==1);
        System.out.println("6 sentence boundary and per-Class reflection tests passed");
    }
}
