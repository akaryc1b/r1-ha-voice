package r1.local.asr;

import android.content.Context;
import android.media.AudioManager;
import android.util.Log;

/** API22 静音请求成对计数；只借用音乐静音，不改变任何音量索引。 */
public final class MusicListenMute {
    private static AudioManager audio;

    public static synchronized void initialize(Context context) {
        if (audio == null && context != null)
            audio = (AudioManager)context.getSystemService(Context.AUDIO_SERVICE);
    }

    public static synchronized Lease acquire(boolean enabled) {
        AudioManager owner = audio;
        if (!enabled || owner == null) return new Lease(null,false);
        try {
            owner.setStreamMute(AudioManager.STREAM_MUSIC,true);
            Log.i("R1ListenMute","ACQUIRED stream=3");
            return new Lease(owner,true);
        } catch (RuntimeException error) {
            Log.w("R1ListenMute","ACQUIRE_FAILED type=" + error.getClass().getSimpleName());
            return new Lease(null,false);
        }
    }

    public static final class Lease {
        private final AudioManager owner;
        private boolean held;

        private Lease(AudioManager owner, boolean held) { this.owner=owner;this.held=held; }

        public synchronized void close() {
            if (!held) return;
            try {
                owner.setStreamMute(AudioManager.STREAM_MUSIC,false);
                held=false;
                Log.i("R1ListenMute","RELEASED stream=3");
            } catch (RuntimeException error) {
                // 保留借用状态，后续 finally 可再次释放；进程退出由 API22 Binder 清理。
                Log.w("R1ListenMute","RELEASE_FAILED type=" + error.getClass().getSimpleName());
            }
        }
    }
}
