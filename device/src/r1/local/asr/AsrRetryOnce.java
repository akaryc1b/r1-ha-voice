package r1.local.asr;

/** 只允许同一语音轮次在未听清后续听一次；完成事件和轮次均需匹配。 */
public final class AsrRetryOnce {
    public static final String PROMPT = "没有听清，请再说一遍。";
    public static final long PROMPT_TIMEOUT_MS = 12000;
    private int turn;
    private boolean used;
    private long generation;
    private long deadline;
    private int phase; // 0 空闲，1 等待请求，2 等待播放，3 播放中，4 等待续听。

    public synchronized void newTurn(int value) {
        turn = value; used = false; cancel();
    }

    public synchronized long arm(int value, boolean enabled, boolean retryable, long now) {
        if (!enabled || !retryable || value != turn || used) return 0;
        used = true;
        generation++; phase = 1; deadline = now + PROMPT_TIMEOUT_MS;
        return generation;
    }

    public synchronized void speechRequested(String text, long now) {
        if (phase == 0) return;
        if (now >= deadline || phase != 1 || !PROMPT.equals(text)) { cancel(); return; }
        phase = 2;
    }

    public synchronized long speechEvent(int event, int value, long now) {
        if (phase == 0) return 0;
        if (value != turn || now >= deadline || event == 2111) { cancel(); return 0; }
        if (event == 2106 && phase == 2) phase = 3;
        else if (event == 2107 && phase == 3) { phase = 4; return generation; }
        return 0;
    }

    public synchronized boolean take(long ticket, int value, long now) {
        if (ticket == 0 || ticket != generation || phase != 4 || value != turn || now >= deadline)
            return false;
        phase = 0; generation++;
        return true;
    }

    public synchronized boolean expire(long ticket, long now) {
        if (ticket != generation || phase == 0 || now < deadline) return false;
        cancel(); return true;
    }

    public synchronized void cancel(long ticket) { if (ticket == generation) cancel(); }
    public synchronized void cancel() { phase = 0; generation++; }
}
