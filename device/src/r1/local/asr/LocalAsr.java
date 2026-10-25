package r1.local.asr;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.media.AudioManager;
import android.util.Log;
import com.unisound.client.IAudioSource;
import com.unisound.vui.engine.NativeANTEngine;
import java.io.*;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.Arrays;
import okhttp3.*;
import okio.ByteString;
import org.json.JSONObject;
import nluparser.scheme.NLU;

/** 保留原生唤醒，只将唤醒后的音频交给局域网识别服务。 */
public final class LocalAsr {
    private static final String TAG = "R1LocalASR";
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final OkHttpClient HTTP = new OkHttpClient.Builder()
            .connectTimeout(2, TimeUnit.SECONDS).readTimeout(0, TimeUnit.SECONDS).build();
    private static volatile IAudioSource source;
    private static volatile Session active;
    private static final AsrRetryOnce RETRY = new AsrRetryOnce();
    private static volatile NativeANTEngine retryOwner;
    private static NativeANTEngine engine;
    private static Context deviceContext;
    private static boolean initialized;

    public static synchronized void initialize(NativeANTEngine value, Context context) {
        engine = value;
        deviceContext = context;
        SpeechRouteVolume.initialize(context);
        MusicListenMute.initialize(context);
        VoiceDiagnostics.initialize();
        if (initialized) return;
        if (context == null) { Log.e(TAG, "INITIALIZATION_CONTEXT_UNAVAILABLE"); return; }
        initialized = true;
        // DUMP 是发送者权限：仅系统或 ADB shell 可以触发诊断。
        context.registerReceiver(new BroadcastReceiver() {
            @Override public void onReceive(Context context, Intent intent) {
                String mode = intent.getStringExtra("mode");
                if ("state".equals(mode)) {
                    Log.i(TAG, "STATE enabled=" + enabled() + " source=" +
                            (source == null ? "none" : source.getClass().getName()) +
                            " active=" + (active != null));
                    AudioManager audio = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
                    Log.i(TAG, "AUDIO music=" + audio.getStreamVolume(3) + " tts=" + audio.getStreamVolume(9));
                    Log.i(TAG, "WAKEUP saved=" + VoiceSession.getWakeupWords(context));
                } else if ("volume".equals(mode)) {
                    AudioManager audio = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
                    int stream = intent.getIntExtra("stream", 9);
                    if (stream != 3 && stream != 9) return;
                    int level = Math.max(0, Math.min(audio.getStreamMaxVolume(stream), intent.getIntExtra("level", 9)));
                    audio.setStreamVolume(stream, level, 0);
                    Log.i(TAG, "VOLUME stream=" + stream + " level=" + audio.getStreamVolume(stream));
                } else if ("say".equals(mode)) {
                    testSpeech();
                } else if ("entry".equals(mode)) {
                    engine.doEnterASR();
                } else if ("legacy-check".equals(mode)) {
                    verifyLegacyGate();
                } else if ("probe".equals(mode) || "sample".equals(mode) || "voice".equals(mode) || "verify".equals(mode)) {
                    start(engine, mode);
                }
            }
        }, new IntentFilter("com.phicomm.speaker.device.LOCAL_ASR_TEST"),
                "android.permission.DUMP", MAIN);
        Log.i(TAG, "INITIALIZED version=1 enabled=" + enabled());
    }

    public static synchronized JSONObject adjustVolume(String target, String operation, int percent) throws Exception {
        if (deviceContext == null) throw new IOException("Audio context unavailable");
        int stream;
        if ("music".equals(target)) stream = 3;
        else if ("speech".equals(target)) stream = speechStream();
        else throw new IllegalArgumentException("Invalid volume target");
        AudioManager audio = (AudioManager)deviceContext.getSystemService(Context.AUDIO_SERVICE);
        int maximum = audio.getStreamMaxVolume(stream);
        int before = audio.getStreamVolume(stream);
        int level = before;
        android.content.SharedPreferences saved = deviceContext.getSharedPreferences("r1-cloud-audio",0);
        if ("up".equals(operation)) level++;
        else if ("down".equals(operation)) level--;
        else if ("set".equals(operation)) {
            if (percent < 0 || percent > 100) throw new IllegalArgumentException("Volume percent out of range");
            level = Math.round(percent * maximum / 100.0f);
        } else if ("mute".equals(operation)) {
            if (before > 0) saved.edit().putInt("before_mute_" + stream,before).apply();
            level = 0;
        } else if ("unmute".equals(operation)) {
            if (before == 0) level = saved.getInt("before_mute_" + stream,stream == 9 ? 9 : 4);
        } else if (!"get".equals(operation)) throw new IllegalArgumentException("Invalid volume operation");
        level = Math.max(0,Math.min(maximum,level));
        if (!"get".equals(operation)) {
            if (stream == 3) SpeechRouteVolume.setMusicVolume(audio,level);
            else audio.setStreamVolume(stream,level,0);
            if (stream == 3) com.unisound.vui.util.UserPerferenceUtil.setCurrentVolume(deviceContext,level);
            else saved.edit().putInt("speech_level",level).putInt("speech_maximum",maximum).apply();
        }
        JSONObject result = new JSONObject();
        result.put("target",target);result.put("level",audio.getStreamVolume(stream));
        result.put("maximum",maximum);result.put("percent",Math.round(audio.getStreamVolume(stream)*100.0f/maximum));
        return result;
    }

    public static int speechStream() {
        try { return CloudVoiceSettings.getInt("speech_stream",9) == 2 ? 2 : 9; }
        catch (Exception ignored) { return 9; }
    }

    public static void restoreSpeechVolume() {
        if (deviceContext == null) return;
        android.content.SharedPreferences saved = deviceContext.getSharedPreferences("r1-cloud-audio",0);
        if (!saved.contains("speech_level")) return;
        AudioManager audio = (AudioManager)deviceContext.getSystemService(Context.AUDIO_SERVICE);
        int stream=speechStream(); int maximum=audio.getStreamMaxVolume(stream);
        int oldMaximum=Math.max(1,saved.getInt("speech_maximum",15));
        int level = Math.max(0,Math.min(maximum,Math.round(saved.getInt("speech_level",9)*maximum/(float)oldMaximum)));
        audio.setStreamVolume(stream,level,0);
    }

    public static void voiceTurnChanged(int turn) {
        RETRY.newTurn(turn);
        retryOwner = null;
    }

    public static void wakeupStarted() {
        VoiceFollowup.cancel();
        VoiceSession.newTurn();
        Session previous = active;
        active = null;
        if (previous != null) {
            previous.stop = true;
            previous.closeAudio();
            previous.opened.countDown(); previous.finished.countDown();
            if (previous.socket != null) previous.socket.close(1000,"new wakeup");
        }
    }

    public static void speechRequested(String text) {
        RETRY.speechRequested(text,SystemClock.elapsedRealtime());
        VoiceFollowup.speechRequested(text);
    }

    public static void speechError() { RETRY.cancel(); retryOwner = null; VoiceFollowup.cancel(); }

    private static void retryAfterSpeech(int event) {
        final long ticket = RETRY.speechEvent(event,VoiceSession.currentTurn(),SystemClock.elapsedRealtime());
        if (ticket == 0) return;
        final NativeANTEngine owner = retryOwner;
        MAIN.post(new Runnable() { @Override public void run() {
            if (owner == null) return;
            if (active != null) { RETRY.cancel(ticket); return; }
            try {
                if (!CloudVoiceSettings.getBoolean("asr_retry_once",true)) { RETRY.cancel(ticket); return; }
                if (!RETRY.take(ticket,VoiceSession.currentTurn(),SystemClock.elapsedRealtime())) return;
                retryOwner = null;
                Log.i(TAG,"RETRY_LISTEN turn=" + VoiceSession.currentTurn());
                start(owner,"voice",true);
            } catch (Exception error) { RETRY.cancel(ticket); }
        }});
    }

    private static void retryPrompt(final Session session) {
        long token = RETRY.arm(session.turn,session.retryEnabled && !session.retryContinuation,
                session.retryable,SystemClock.elapsedRealtime());
        if (token != 0) {
            retryOwner = session.owner;
            final long ticket = token;
            MAIN.postDelayed(new Runnable() { @Override public void run() {
                if (RETRY.expire(ticket,SystemClock.elapsedRealtime())) {
                    retryOwner = null;
                    Log.i(TAG,"RETRY_PROMPT_EXPIRED");
                }
            }},AsrRetryOnce.PROMPT_TIMEOUT_MS);
            Log.i(TAG,"RETRY_ARMED turn=" + session.turn);
        }
        session.owner.pipeline().playTTS(session.failure);
    }

    public static void speechEvent(int event) {
        VoiceFollowup.speechEvent(event);
        retryAfterSpeech(event);
        if (event==2106 || event==2107 || event==2111)
            VoiceDiagnostics.record(event==2111?"DEBUG":"INFO","TTS",VoiceSession.currentTurn(),
                    "status",event==2106?"playing":event==2107?"completed":"cancelled");
        if (event == 2106 || event == 2107) {
            // 自带 TTS 会重设系统音量；等 SDK 回调结束后恢复用户保存的播报音量。
            MAIN.post(new Runnable() { @Override public void run() { restoreSpeechVolume(); }});
            Log.i("R1SpeechEvents",event == 2106 ? "PLAYING" : "COMPLETED");
        }
    }

    public static void musicErrorSpeech(final int turn) {
        MAIN.post(new Runnable() { @Override public void run() {
            if (engine!=null && VoiceSession.isCurrent(turn))
                engine.pipeline().playTTS("音乐指令未能完成，请稍后再试。");
        }});
    }

    public static void testSpeech() {
        MAIN.post(new Runnable() { @Override public void run() {
            if (engine != null) engine.pipeline().playTTS("硅基流动语音通道测试成功，现在使用你选择的音色播报。");
        }});
    }

    // 这里只向现有 HA/AI 处理器投递文本，不调用旧云知声识别或问答。
    private static void dispatchAssistant(NativeANTEngine owner, String text) {
        NLU nlu = new NLU();
        nlu.setService("cn.yunzhisheng.chat");nlu.setText(text);
        owner.pipeline().fireUserEventTriggered(nlu);
    }

    private static void dispatch(final NativeANTEngine owner, final String text) {
        if (!MusicRoute.isDirectMusic(text)) { dispatchAssistant(owner,text);return; }
        final int turn=VoiceSession.currentTurn();
        new Thread(new Runnable() { @Override public void run() {
            final String reply=MusicRoute.route(text);
            MAIN.post(new Runnable() { @Override public void run() {
                if (!VoiceSession.isCurrent(turn)) return;
                if (reply==null) dispatchAssistant(owner,text);
                else if (reply.length()>0) owner.pipeline().playTTS(reply);
                else VoiceFollowup.responseEnded(turn);
            }});
        }}, "R1MusicControl").start();
    }

    public static void remember(IAudioSource value) { source = value; }

    public static void capture(IAudioSource value, byte[] data, int count) {
        Session session = active;
        if (session == null || session.stop || "sample".equals(session.mode) || count <= 0) return;
        byte[] frame = Arrays.copyOf(data, count);
        if (!session.frames.offer(frame)) {
            session.frames.poll();
            session.frames.offer(frame);
        }
    }

    public static boolean enabled() {
        return true;
    }

    public static boolean begin(NativeANTEngine value) {
        start(value, "voice");
        return true;
    }

    public static void startFollowup(int turn) {
        if(!VoiceSession.isCurrent(turn) || active!=null || engine==null)return;
        try {
            if(!AsrAudio.isGateway(CloudVoiceSettings.getString("server","")))return;
        }catch(Exception ignored){return;}
        start(engine,"followup");
    }

    public static boolean deferWakeup() { return active != null; }

    public static boolean keepMicrophoneOpen(IAudioSource value) {
        return false;
    }

    private static JSONObject config() throws Exception { return CloudVoiceSettings.read(); }

    private static void start(NativeANTEngine value, String mode) { start(value,mode,false); }

    private static synchronized void start(NativeANTEngine value, String mode, boolean continuation) {
        if (active != null) { Log.i(TAG, "ALREADY_LISTENING"); return; }
        Session session = null;
        try {
            JSONObject settings = config();
            if (!continuation && ("voice".equals(mode) || "followup".equals(mode) || "sample".equals(mode))) VoiceSession.newTurn();
            VoiceFollowup.begin(mode,VoiceSession.currentTurn());
            session = new Session(value, mode, settings,continuation);
            if (session.captureAudio) {
                CloudVoiceSettings.consumeCaptureNext();
            }
            active = session;
            if ("sample".equals(mode) || "verify".equals(mode)) {
                value.doCancelEngine();
                value.setEngineState(2);
            }
            if ("voice".equals(mode)||"followup".equals(mode)) value.pipeline().fireASREvent(1101);
            new Thread(session, "r1-local-asr").start();
            Log.i(TAG, "START mode=" + mode);
            VoiceDiagnostics.record("DEBUG","ASR",VoiceSession.currentTurn(),"status","started","operation",mode);
        } catch (Exception error) {
            if (session != null) session.closeAudio();
            active = null;
            Log.e(TAG, "START_FAILED", error);
            value.pipeline().fireASREvent(1102);
            value.pipeline().playTTS("语音通道配置无法读取，请在控制网页重新保存语音设置。");
            value.enterWakeup(false);
        }
    }

    /** 仅由系统/ADB 诊断入口调用，不采集音频，也不执行设备控制。 */
    private static void verifyLegacyGate() {
        try {
            Class<?> type = Class.forName("com.unisound.vui.handler.filter.NLUDispatcher");
            Class<?> processor = Class.forName("nluparser.MixtureProcessor");
            Class<?> context = Class.forName("com.unisound.vui.engine.ANTHandlerContext");
            Object instance = type.getConstructor(processor).newInstance(new Object[]{null});
            for (String method : new String[]{"onASRResultLocal", "onASRResultNet", "onASRError"}) {
                Object blocked = type.getMethod(method,context,String.class)
                        .invoke(instance,new Object[]{null,"synthetic legacy response"});
                if (!Boolean.TRUE.equals(blocked)) throw new IllegalStateException(method);
            }
            Log.i(TAG,"LEGACY_GATE_VERIFIED callbacks_blocked=3");
        } catch (Exception error) { Log.e(TAG,"LEGACY_GATE_FAILED",error); }
    }

    /** 只修正完整的音乐控制短句，避免改写歌名或普通聊天。 */
    public static String normalize(String text) {
        return SharedIntentRules.normalize(text);
    }

    private static final class Session implements Runnable {
        final NativeANTEngine owner;
        final String mode;
        final String url;
        final boolean pcm16;
        final int channels;
        final String channelMix;
        final boolean captureAudio;
        final int followupWindowMilliseconds;
        volatile boolean ignoredResult;
        final MusicListenMute.Lease musicMute;
        final int turn;
        final boolean retryEnabled;
        final boolean retryContinuation;
        volatile boolean retryable;
        final CountDownLatch opened = new CountDownLatch(1);
        final CountDownLatch finished = new CountDownLatch(1);
        final ArrayBlockingQueue<byte[]> frames = new ArrayBlockingQueue<byte[]>(64);
        volatile WebSocket socket;
        volatile boolean stop;
        volatile String recognized = "";
        volatile String failure = "";
        volatile String recognizedBackend = "";
        volatile boolean finalResult;
        long started;
        long bytes;
        long squares;
        long samples;
        int peak;
        int watchdogMilliseconds;

        Session(NativeANTEngine owner, String mode, JSONObject settings, boolean continuation) throws Exception {
            this.owner = owner; this.mode = mode;
            turn = VoiceSession.currentTurn();
            retryEnabled = settings.optBoolean("asr_retry_once",true);
            retryContinuation = continuation;
            String configured = settings.optString("server", "ws://192.168.1.88:16066");
            CloudVoiceSettings.asrServer(configured);
            if("followup".equals(mode) && AsrAudio.isGateway(configured))
                configured+=(configured.indexOf('?')<0?"?":"&")+"followup=1";
            url = AsrAudio.transportUrl(configured);
            pcm16 = AsrAudio.isGateway(url);
            channels = settings.optInt("channels", 1) == 2 ? 2 : 1;
            // 旧固件的第二轨可能是参考音频；已有配置保持主麦，平均由网页显式选择。
            channelMix = settings.optString("asr_channel_mix","left");
            captureAudio = "voice".equals(mode) && settings.optBoolean("capture_next", false);
            followupWindowMilliseconds=Math.max(3,Math.min(10,settings.optInt("followup_window_seconds",6)))*1000;
            CloudVoiceSettings.asrServer(url);
            watchdogMilliseconds = Math.max(20,Math.min(120,settings.optInt("session_timeout_seconds",45)))*1000;
            if (continuation) watchdogMilliseconds = Math.min(watchdogMilliseconds,15000);
            musicMute = MusicListenMute.acquire("voice".equals(mode) && settings.optBoolean("listen_music_mute",true));
        }

        @Override public void run() {
            started = SystemClock.elapsedRealtime();
            final Runnable watchdog = new Runnable() {
                @Override public void run() {
                    if (active != Session.this) return;
                    failure = "本地语音识别超时";
                    stop = true;
                    closeAudio();
                    if (socket != null) socket.close(1000, "timeout");
                    opened.countDown(); finished.countDown();
                }
            };
            MAIN.postDelayed(watchdog, "probe".equals(mode) ? 10000 : watchdogMilliseconds);
            try {
                if (!"probe".equals(mode)) connect();
                if ("sample".equals(mode) || "verify".equals(mode)) sample();
                else microphone();
            } catch (Exception error) {
                if (failure.length() == 0) failure = "本地语音识别连接失败";
                Log.e(TAG, "SESSION_FAILED mode=" + mode, error);
            } finally {
                stop = true;
                closeAudio();
                if (socket != null) socket.close(1000, "complete");
                MAIN.removeCallbacks(watchdog);
                final String result = normalize(recognized);
                VoiceDiagnostics.record(failure.length()>0?"WARN":"INFO","ASR",turn,
                        "text",finalResult && failure.length()==0?result:"", "response",failure,
                        "backend",recognizedBackend,"operation",mode,
                        "status",ignoredResult?"ignored":failure.length()>0?"failed":"recognized",
                        "duration_ms",SystemClock.elapsedRealtime()-started);
                Log.i(TAG, "FINISH mode=" + mode + " bytes=" + bytes +
                        " rms=" + (samples == 0 ? 0 : (int)Math.sqrt((double)squares / samples)) +
                        " peak=" + peak + " elapsed_ms=" +
                        (SystemClock.elapsedRealtime() - started) +
                        " text=" + result + " error=" + failure);
                MAIN.post(new Runnable() {
                    @Override public void run() {
                        if (active != Session.this) return;
                        active = null;
                        if (!VoiceSession.isCurrent(turn)) return;
                        if ("sample".equals(mode) || "verify".equals(mode)) owner.setEngineState(0);
                        owner.pipeline().fireASREvent(1102);
                        if (result.length() > 0 && finalResult && failure.length() == 0 && !"probe".equals(mode) && !"verify".equals(mode)) {
                            VoiceFollowup.recognized(turn);
                            Log.i(TAG, "DISPATCH text=" + result);
                            dispatch(owner,result);
                        } else if ("voice".equals(mode) && failure.length() > 0) {
                            retryPrompt(Session.this);
                        }
                        if(ignoredResult || "followup".equals(mode) && failure.length()>0)
                            VoiceFollowup.cancelTurn(turn);
                        owner.enterWakeup(false);
                    }
                });
            }
        }

        private void connect() throws Exception {
            socket = HTTP.newWebSocket(new Request.Builder().url(url).build(), new WebSocketListener() {
                @Override public void onOpen(WebSocket ws, Response response) {
                    Log.i(TAG, "CONNECTED");
                    opened.countDown();
                }
                @Override public void onMessage(WebSocket ws, String message) {
                    if ("Done!".equals(message)) { finalResult = true; stop = true; finished.countDown(); return; }
                    try {
                        JSONObject reply = new JSONObject(message);
                        if (reply.has("backend")) recognizedBackend=reply.optString("backend","");
                        if(reply.optBoolean("ignored",false)) {
                            recognized="";ignoredResult=true;finalResult=true;stop=true;
                            finished.countDown();return;
                        }
                        if (reply.optString("error", "").length() > 0) {
                            failure = AsrRetryOnce.PROMPT.equals(reply.optString("error","")) ?
                                    AsrRetryOnce.PROMPT : "语音识别服务暂时没有响应，请稍后再试。";
                            retryable = reply.optBoolean("retryable",false);
                            stop = true;
                            finished.countDown();
                            return;
                        }
                        String text = reply.optString("text", "").trim();
                        if (text.length() > 0) recognized = text;
                        if (reply.optBoolean("is_final", false) && text.length() > 0) {
                            VoiceCommands.offer(turn,normalize(text),reply.optJSONObject("command_plan"));
                            finalResult = true;
                            stop = true;
                            finished.countDown();
                        }
                    } catch (Exception error) { Log.w(TAG, "INVALID_REPLY", error); }
                }
                @Override public void onFailure(WebSocket ws, Throwable error, Response response) {
                    if (!stop) failure = "本地语音识别连接失败";
                    stop = true; opened.countDown(); finished.countDown();
                    Log.w(TAG, "SOCKET_FAILED " + error.getClass().getSimpleName());
                }
                @Override public void onClosed(WebSocket ws, int code, String reason) {
                    stop = true; opened.countDown(); finished.countDown();
                }
            });
            if (!opened.await(3, TimeUnit.SECONDS) || stop)
                throw new IOException("ASR connection unavailable");
        }

        private void microphone() throws Exception {
            if (stop) return;
            // 只保留显式开启诊断后的下一句，正常语音不写录音文件。
            FileOutputStream diagnostic = captureAudio ? new FileOutputStream("/sdcard/r1-asr-diagnostic.pcm") : null;
            int captured = 0;
            try {
            final long micStarted = SystemClock.elapsedRealtime();
            Log.i(TAG, "MIC_OPEN source=existing-recording-stream channels=" + channels + " setup_ms=" +
                    (micStarted - started));
            while (!stop) {
                // 窗口限制等人开口的时间；已有中间文字后让端点服务判断句尾，避免截断长指令。
                if("followup".equals(mode) && FollowupWindow.listeningExpired(
                        SystemClock.elapsedRealtime()-micStarted,followupWindowMilliseconds,recognized.length()>0))break;
                byte[] pcm = frames.poll(250, TimeUnit.MILLISECONDS);
                if (pcm == null) {
                    if (SystemClock.elapsedRealtime() - micStarted > 5000 && bytes == 0)
                        throw new IOException("Existing microphone stream unavailable");
                    continue;
                }
                int count = pcm.length;
                if (diagnostic != null && captured + count <= 1024 * 1024) {
                    diagnostic.write(pcm);
                    captured += count;
                }
                bytes += count;
                byte[] converted = encode(pcm, count, channels);
                if (!"probe".equals(mode)) {
                    if (!socket.send(new ByteString(converted)))
                        throw new IOException("ASR sender stalled");
                }
                long elapsed = SystemClock.elapsedRealtime() - micStarted;
                if ("probe".equals(mode) && SystemClock.elapsedRealtime() - micStarted >= 3000) break;
                if (!"probe".equals(mode) && !"followup".equals(mode) && recognized.length() == 0 && elapsed > 6500) {
                    stop = true; break;
                }
            }
            if (socket != null && failure.length() == 0) {
                socket.send("Done");
                if (!finalResult) finished.await(14, TimeUnit.SECONDS);
            }
            } finally {
                if (diagnostic != null) {
                    diagnostic.close();
                    Log.i(TAG, "PCM_CAPTURED bytes=" + captured + " channels=" + channels);
                }
            }
        }

        private void sample() throws Exception {
            File file = new File("/sdcard/r1-local-asr-test.wav");
            if (!file.isFile() || file.length() > 1024 * 1024)
                throw new IOException("Diagnostic sample unavailable");
            DataInputStream input = new DataInputStream(new FileInputStream(file));
            try {
                byte[] header = new byte[44]; input.readFully(header);
                ByteBuffer wav = ByteBuffer.wrap(header).order(ByteOrder.LITTLE_ENDIAN);
                if (wav.getInt(0) != 0x46464952 || wav.getInt(8) != 0x45564157 ||
                        wav.getShort(20) != 1 || wav.getShort(22) != 1 ||
                        wav.getInt(24) != 16000 || wav.getShort(34) != 16 ||
                        wav.getInt(36) != 0x61746164)
                    throw new IOException("Expected PCM mono 16 kHz sample");
                byte[] pcm = new byte[3200]; int count;
                while (!stop && (count = input.read(pcm)) > 0) {
                    bytes += count;
                    if (!socket.send(new ByteString(encode(pcm, count, 1))))
                        throw new IOException("Sample send failed");
                    Thread.sleep(count * 1000L / 32000L);
                }
                if (!stop) socket.send("Done");
                if (!finished.await(14, TimeUnit.SECONDS)) throw new IOException("No final ASR result");
            } finally { input.close(); }
        }

        private byte[] encode(byte[] pcm, int count, int channels) {
            byte[] mono = AsrAudio.mono(pcm,count,channels,channelMix);
            for (int at=0;at<mono.length;at+=2) {
                short sample = (short)((mono[at] & 255) | (mono[at + 1] << 8));
                peak = Math.max(peak,Math.abs((int)sample));
                squares += (long)sample * sample; samples++;
            }
            return pcm16 ? mono : AsrAudio.floats(mono);
        }

        private synchronized void closeAudio() {
            musicMute.close();
        }
    }
}
