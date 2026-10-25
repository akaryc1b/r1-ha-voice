package r1.local.asr;
public final class VoiceSession {
    public static int turn=1;
    public static int currentTurn(){return turn;}
    public static boolean isCurrent(int value){return value==turn;}
}
