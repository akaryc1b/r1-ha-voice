package r1.local.asr;

import android.content.Context;
import android.media.AudioManager;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

/** RING 播报会切换输出设备；同步 MUSIC 的用户音量，不更改音乐的全局控制器。 */
public final class SpeechRouteVolume {
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final ThreadLocal<Snapshot> BEFORE = new ThreadLocal<Snapshot>();
    private static Context context;
    private static Snapshot active;
    private static long routeGeneration;
    private static long musicIntentGeneration;
    private static int musicIntent;
    private static boolean pendingIntentRestore;

    private SpeechRouteVolume() {}

    private static final class Snapshot {
        final Object track;
        final int musicLevel;
        final long intentGeneration;
        Snapshot(Object track, int level, long generation) {
            this.track = track; musicLevel = level; intentGeneration = generation;
        }
    }

    public static synchronized void initialize(Context value) {
        context = value == null ? null : value.getApplicationContext();
    }

    private static AudioManager audio() {
        return context == null ? null : (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
    }

    /** 仅显式音乐音量操作更新意图，避免被本类的路由补偿反向覆盖。 */
    public static synchronized void setMusicVolume(AudioManager audio, int level) {
        musicIntent = Math.max(0, Math.min(audio.getStreamMaxVolume(3), level));
        musicIntentGeneration++;
        audio.setStreamVolume(3, musicIntent, 0);
    }

    public static synchronized void beforePlay(Object track) {
        BEFORE.remove();
        if (LocalAsr.speechStream() != 2) return;
        AudioManager audio = audio();
        if (audio == null) return;
        try {
            routeGeneration++;
            if (pendingIntentRestore) {
                audio.setStreamVolume(3, musicIntent, 0);
                pendingIntentRestore = false;
            }
            BEFORE.set(new Snapshot(track, audio.getStreamVolume(3), musicIntentGeneration));
        } catch (RuntimeException error) { Log.w("R1SpeechRoute", "CAPTURE_FAILED " + error.getClass().getSimpleName()); }
    }

    /** AudioTrack.play 已激活新输出路由；在首次 write 之前同步该设备的 MUSIC 索引。 */
    public static synchronized void afterPlay(Object track) {
        Snapshot snapshot = BEFORE.get();
        BEFORE.remove();
        if (snapshot == null || snapshot.track != track || LocalAsr.speechStream() != 2) return;
        AudioManager audio = audio();
        if (audio == null) return;
        try {
            int target = musicIntentGeneration != snapshot.intentGeneration ? musicIntent : snapshot.musicLevel;
            int routed = audio.getStreamVolume(3);
            if (routed != target) audio.setStreamVolume(3, target, 0);
            active = snapshot;
            Log.i("R1SpeechRoute", "MUSIC_ROUTE level_before=" + snapshot.musicLevel + " routed=" + routed + " level=" + target);
        } catch (RuntimeException error) { Log.w("R1SpeechRoute", "SYNC_FAILED " + error.getClass().getSimpleName()); }
    }

    /** 只在播报期间发生过显式音乐调音时，有限同步回切后的输出设备。 */
    public static synchronized void afterStop(Object track) {
        final Snapshot snapshot = active;
        if (snapshot == null || snapshot.track != track) return;
        final long generation = ++routeGeneration;
        if (musicIntentGeneration == snapshot.intentGeneration) {
            active = null;
            pendingIntentRestore = false;
            return;
        }
        pendingIntentRestore = true;
        scheduleRestore(snapshot, generation, 50, false);
        scheduleRestore(snapshot, generation, 200, true);
    }

    private static void scheduleRestore(final Snapshot snapshot, final long generation, int delay, final boolean last) {
        MAIN.postDelayed(new Runnable() { @Override public void run() {
            synchronized (SpeechRouteVolume.class) {
                if (routeGeneration != generation || active != snapshot || LocalAsr.speechStream() != 2) return;
                AudioManager audio = audio();
                if (audio != null) {
                    try { audio.setStreamVolume(3, musicIntent, 0); }
                    catch (RuntimeException error) { Log.w("R1SpeechRoute", "END_SYNC_FAILED " + error.getClass().getSimpleName()); }
                }
                if (last) { active = null; pendingIntentRestore = false; }
            }
        }}, delay);
    }
}
