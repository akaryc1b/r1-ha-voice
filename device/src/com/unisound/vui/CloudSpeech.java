package com.unisound.vui;

import android.media.MediaPlayer;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import java.net.URLEncoder;
import java.util.concurrent.atomic.AtomicInteger;
import org.json.JSONObject;
import r1.local.asr.CloudVoiceSettings;

/** 独立使用播报音量；设备 TTS 回退仅读出文字，不调用旧识别或问答。 */
public final class CloudSpeech {
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final AtomicInteger TOKEN = new AtomicInteger();
    private static final ThreadLocal<Boolean> BYPASS = new ThreadLocal<Boolean>();
    private static MediaPlayer player;
    private static d listener;
    private static Runnable watchdog;

    public static boolean play(final c owner, final String text) {
        if (Boolean.TRUE.equals(BYPASS.get()) || text == null || text.trim().length() == 0) return false;
        Log.i("R1SpeechTiming", "REQUEST characters=" + text.length());
        final String url;
        try {
            JSONObject settings = CloudVoiceSettings.read();
            if (!settings.optBoolean("cloud_tts", false) || text.length() > 1500 ||
                    text.startsWith("/") || text.startsWith("file:") || text.startsWith("http")) return false;
            url = CloudVoiceSettings.gatewayUrl(settings) + "/tts?text=" + URLEncoder.encode(text, "UTF-8");
        } catch (Exception error) { return false; }
        final int token = TOKEN.incrementAndGet();
        MAIN.post(new Runnable() { @Override public void run() {
            if (token != TOKEN.get()) return;
            release();
            final MediaPlayer current = new MediaPlayer();
            player = current;
            listener = c.a(owner);
            final d callback = listener;
            try {
                current.setAudioStreamType(9);
                current.setOnPreparedListener(new MediaPlayer.OnPreparedListener() {
                    @Override public void onPrepared(MediaPlayer mp) {
                        if (player != mp || token != TOKEN.get()) return;
                        MAIN.removeCallbacks(watchdog);
                        callback.onEvent(2105);
                        callback.onEvent(2106);
                        r1.local.asr.LocalAsr.restoreSpeechVolume();
                        mp.start();
                        Log.i("R1CloudTTS", "PLAYING duration_ms=" + mp.getDuration());
                    }
                });
                current.setOnCompletionListener(new MediaPlayer.OnCompletionListener() {
                    @Override public void onCompletion(MediaPlayer mp) {
                        if (player != mp || token != TOKEN.get()) return;
                        release();
                        callback.onEvent(2107);
                        Log.i("R1CloudTTS", "COMPLETED");
                    }
                });
                current.setOnErrorListener(new MediaPlayer.OnErrorListener() {
                    @Override public boolean onError(MediaPlayer mp, int what, int extra) {
                        if (player == mp && token == TOKEN.get()) fallback(owner, text);
                        return true;
                    }
                });
                watchdog = new Runnable() { @Override public void run() {
                    if (player == current && token == TOKEN.get()) fallback(owner, text);
                }};
                MAIN.postDelayed(watchdog, 5500);
                callback.onEvent(2104);
                current.setDataSource(url);
                current.prepareAsync();
                Log.i("R1CloudTTS", "REQUEST characters=" + text.length());
            } catch (Exception error) { fallback(owner, text); }
        }});
        return true;
    }

    private static void fallback(c owner, String text) {
        release();
        Log.w("R1CloudTTS", "FALLBACK device-speech-only");
        BYPASS.set(Boolean.TRUE);
        try { owner.b(text); }
        finally { BYPASS.remove(); }
    }

    private static void release() {
        if (watchdog != null) MAIN.removeCallbacks(watchdog);
        watchdog = null;
        MediaPlayer previous = player;
        player = null;
        listener = null;
        if (previous != null) {
            try { previous.reset(); previous.release(); }
            catch (Exception ignored) {}
        }
    }

    public static void cancel(c owner) {
        final int token = TOKEN.incrementAndGet();
        MAIN.post(new Runnable() { @Override public void run() {
            if (token != TOKEN.get()) return;
            d previous = listener;
            boolean playing = player != null;
            release();
            if (playing && previous != null) previous.onEvent(2111);
        }});
    }
}
