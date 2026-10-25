package r1.local.asr;

/** 有界续听状态；回复结束和当前轮次必须同时匹配。 */
public final class FollowupWindow {
    private int turn;
    private int remaining;
    private long deadline;
    private long generation;
    private boolean waiting;
    private boolean pending;

    public static boolean listeningExpired(long elapsed,long limit,boolean heardSpeech) {
        return !heardSpeech && elapsed>=limit;
    }

    public synchronized void begin(int value, int maximum, boolean continuation) {
        if (!continuation) remaining=maximum;
        turn=value;waiting=false;pending=false;generation++;
    }

    public synchronized void recognized(int value,long now,long budget) {
        if (value!=turn || remaining<=0) return;
        waiting=true;pending=false;deadline=now+budget;generation++;
    }

    public synchronized long responseEnded(int value,long now) {
        if (!waiting || value!=turn || remaining<=0 || now>=deadline) return 0;
        waiting=false;pending=true;remaining--;return ++generation;
    }

    public synchronized boolean take(long ticket,int value,long now) {
        if (!pending || ticket==0 || ticket!=generation || value!=turn || now>=deadline) return false;
        pending=false;generation++;return true;
    }

    public synchronized void cancel() {
        waiting=false;pending=false;remaining=0;generation++;
    }

    public synchronized void cancelTurn(int value) {if(value==turn)cancel();}
}
