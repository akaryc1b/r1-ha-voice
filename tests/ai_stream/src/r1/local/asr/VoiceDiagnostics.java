package r1.local.asr;
/** 日志传输在独立测试覆盖；SSE 回归只验证问答行为。 */
public final class VoiceDiagnostics {
    public static void record(String level,String stage,int turn,Object... pairs) {}
}
