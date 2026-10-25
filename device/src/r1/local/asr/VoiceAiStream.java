package r1.local.asr;

import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayDeque;
import java.util.Arrays;
import java.util.concurrent.ConcurrentHashMap;
import java.util.Timer;
import java.util.TimerTask;
import org.json.JSONArray;
import org.json.JSONObject;

/** SSE 只朗读正文；句子按顺序播放，整次回答结束后才退出语音会话。 */
public final class VoiceAiStream {
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static volatile Reply active;
    private static final Timer DEADLINES = new Timer("R1-AI-deadlines", true);
    private static final String UNAVAILABLE = "问答服务响应较慢，请稍后再问一次。";

    private VoiceAiStream() {}

    private static final class Reply {
        final Object handler;
        final int turn;
        final long beganNanos = System.nanoTime();
        final int firstContentMs;
        final int firstReplyMs;
        final int answerMs;
        TimerTask deadline;
        boolean firstContent;
        boolean fallback;
        volatile boolean deadlineExceeded;
        int attempt;
        final ArrayDeque<String> pending = new ArrayDeque<String>();
        final StringBuilder answer = new StringBuilder();
        final StringBuilder fragment = new StringBuilder();
        HttpURLConnection connection;
        boolean generating = true;
        boolean playing;
        boolean waiting;
        boolean spoken;
        volatile boolean cancelled;
        boolean finished;
        Reply(Object handler, int turn, JSONObject settings) {
            this.handler = handler; this.turn = turn;
            firstContentMs = bounded(settings.optInt("ai_first_content_timeout_ms", 4500), 500, 30000);
            firstReplyMs = Math.max(firstContentMs, bounded(settings.optInt("ai_first_reply_timeout_ms", 8000), 500, 60000));
            answerMs = Math.max(firstReplyMs, bounded(settings.optInt("ai_answer_timeout_ms", 30000), 1000, 120000));
        }
    }

    public static String chat(Object client, Object handler, String question, String history, int turn) {
        JSONObject settings;
        try { settings = CloudVoiceSettings.read(); }
        catch (Exception ignored) { settings = new JSONObject(); }
        if (!VoiceSession.isCurrent(turn)) return "";
        VoiceDiagnostics.record("INFO","ROUTE",turn,"route","AI","text",question,"status","requested");
        final Reply reply = new Reply(handler, turn, settings);
        synchronized (VoiceAiStream.class) { cancel(); active = reply; }
        scheduleDeadline(reply);
        final long began = System.currentTimeMillis();
        try {
            if (!settings.optBoolean("ai_streaming", true))
                return controlledFallback(client, question, history, reply, reply.firstReplyMs);
            Request request = request(client, question, history, true);
            HttpURLConnection connection = open(reply, request, reply.firstContentMs);
            if (connection.getResponseCode() != 200) throw new IllegalStateException("HTTP " + connection.getResponseCode());
            String contentType = connection.getContentType();
            BufferedReader reader = new BufferedReader(new InputStreamReader(connection.getInputStream(), "UTF-8"));
            try {
                if (contentType != null && contentType.toLowerCase(java.util.Locale.US).contains("application/json")) {
                    StringBuilder json = new StringBuilder();
                    String line;
                    while ((line = reader.readLine()) != null) {
                        if (json.length() > 262144) throw new IllegalStateException("response too large");
                        json.append(line);
                    }
                    JSONObject response = new JSONObject(json.toString());
                    append(reply, response.getJSONArray("choices").getJSONObject(0).getJSONObject("message").optString("content"), began);
                } else {
                    StringBuilder event = new StringBuilder();
                    String line;
                    boolean done = false;
                    while (current(reply) && (line = reader.readLine()) != null) {
                        if (reply.deadlineExceeded) throw new IllegalStateException("response deadline");
                        if (line.length() == 0) {
                            if (event.length() > 0) {
                                done = event(reply, event.toString(), began);
                                event.setLength(0);
                                if (done) break;
                            }
                        } else if (line.startsWith("data:")) {
                            if (event.length() > 262144) throw new IllegalStateException("event too large");
                            if (event.length() > 0) event.append('\n');
                            event.append(line.substring(5).trim());
                        }
                    }
                    if (!done && event.length() > 0) done = event(reply, event.toString(), began);
                    if (current(reply) && !done) throw new IllegalStateException("incomplete stream");
                }
            } finally { reader.close(); }
            synchronized (VoiceAiStream.class) {
                if (!current(reply)) return "";
                if (reply.deadlineExceeded) throw new IllegalStateException("response deadline");
                if (reply.answer.length() == 0) throw new IllegalStateException("empty content");
                finish(reply);
            }
            Log.i("R1AIStream", "COMPLETE elapsed_ms=" + (System.currentTimeMillis() - began) + " characters=" + reply.answer.length());
            VoiceDiagnostics.record("INFO","AI",turn,"status","completed","response",reply.answer.toString(),"duration_ms",System.currentTimeMillis()-began);
            return reply.answer.toString();
        } catch (Exception error) {
            synchronized (VoiceAiStream.class) {
                if (!current(reply)) return "";
                Log.w("R1AIStream", "FAILED " + error.getClass().getSimpleName() + " spoken=" + reply.spoken);
                VoiceDiagnostics.record("WARN","AI",turn,"status","stream_failed","error_kind",error.getClass().getSimpleName());
                if (reply.spoken) {
                    // 已开始播报时不重新请求、重复朗读前文；明确告知本次回答中断。
                    reply.deadlineExceeded = false;
                    reply.fragment.setLength(0);
                    reply.pending.add("回答中断了，请再问一次。");
                    finish(reply);
                    return reply.answer.toString();
                }
                reply.pending.clear();
                reply.fragment.setLength(0);
                reply.playing = false;
                reply.attempt++;
                reply.fallback = true;
                reply.deadlineExceeded = false;
            }
            return VoiceSession.isCurrent(turn) ? controlledFallback(client, question, history, reply, 4000) : "";
        } finally {
            if (reply.deadline != null) { reply.deadline.cancel(); DEADLINES.purge(); }
            HttpURLConnection completed;
            synchronized (VoiceAiStream.class) { completed = reply.connection; reply.connection = null; }
            // 非 200、解析异常和取消路径也必须释放连接；不打印接口错误正文。
            disconnectAsync(completed);
        }
    }

    private static int bounded(int value, int min, int max) { return Math.max(min, Math.min(max, value)); }

    private static final class Request {
        final String url;
        final String key;
        final JSONObject body;
        Request(String url, String key, JSONObject body) { this.url = url; this.key = key; this.body = body; }
    }

    private static Request request(Object client, String question, String history, boolean stream) throws Exception {
        Method builder = method(client.getClass(),"buildRequestBody",String.class,String.class,String.class);
        builder.setAccessible(true);
        JSONObject body = new JSONObject((String) builder.invoke(client, question, history, null));
        body.put("stream", stream);
        VoiceDiagnostics.record("DEBUG","AI",VoiceSession.currentTurn(),"status","request","model",body.optString("model",""));
        Field configField = field(client.getClass(),"config");
        configField.setAccessible(true);
        Object config = configField.get(client);
        String base = (String) method(config.getClass(),"getBaseUrl").invoke(config);
        String key = (String) method(config.getClass(),"getApiKey").invoke(config);
        String url = base.endsWith("/chat/completions") ? base : base.replaceAll("/+$", "") + "/chat/completions";
        return new Request(url, key, body);
    }

    private static HttpURLConnection open(Reply reply, Request request, int timeout) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(request.url).openConnection();
        HttpURLConnection previous;
        synchronized (VoiceAiStream.class) {
            if (!current(reply)) throw new IllegalStateException("stale turn");
            previous = reply.connection;
            reply.connection = connection;
        }
        disconnectAsync(previous);
        connection.setRequestMethod("POST");
        connection.setConnectTimeout(Math.min(5000, timeout));
        connection.setReadTimeout(timeout);
        connection.setDoOutput(true);
        connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        connection.setRequestProperty("Accept", request.body.optBoolean("stream") ? "text/event-stream" : "application/json");
        connection.setRequestProperty("Authorization", "Bearer " + request.key);
        byte[] bytes = request.body.toString().getBytes("UTF-8");
        connection.setFixedLengthStreamingMode(bytes.length);
        OutputStream output = connection.getOutputStream();
        try { output.write(bytes); } finally { output.close(); }
        return connection;
    }

    private static String controlledFallback(Object client, String question, String history, Reply reply, int maxBudget) {
        try {
            synchronized (VoiceAiStream.class) {
                if (!current(reply)) return "";
                reply.fallback = true;
                reply.deadlineExceeded = false;
            }
            int remaining = reply.firstReplyMs - (int)((System.nanoTime() - reply.beganNanos) / 1000000L);
            if (remaining < 100) return UNAVAILABLE;
            HttpURLConnection connection = open(reply, request(client, question, history, false), Math.min(maxBudget, remaining));
            if (connection.getResponseCode() != 200) return UNAVAILABLE;
            BufferedReader reader = new BufferedReader(new InputStreamReader(connection.getInputStream(), "UTF-8"));
            StringBuilder data = new StringBuilder();
            try {
                String line;
                while ((line = reader.readLine()) != null) {
                    if (!current(reply)) return "";
                    if (reply.deadlineExceeded || data.length() > 262144) return UNAVAILABLE;
                    data.append(line);
                }
            } finally { reader.close(); }
            if (!current(reply)) return "";
            if (reply.deadlineExceeded) return UNAVAILABLE;
            JSONObject response = new JSONObject(data.toString());
            String answer = response.getJSONArray("choices").getJSONObject(0).getJSONObject("message").optString("content");
            Log.i("R1AIStream", "SYNC_COMPLETE elapsed_ms=" + ((System.nanoTime() - reply.beganNanos) / 1000000L));
            VoiceDiagnostics.record("INFO","AI",reply.turn,"status","completed","response",answer,
                    "duration_ms",(System.nanoTime()-reply.beganNanos)/1000000L);
            return answer.trim().length() > 0 ? answer : UNAVAILABLE;
        } catch (Exception error) {
            Log.w("R1AIStream", "SYNC_FAILED " + error.getClass().getSimpleName());
            VoiceDiagnostics.record("ERROR","AI",reply.turn,"status","failed","error_kind",error.getClass().getSimpleName());
            return current(reply) ? UNAVAILABLE : "";
        } finally {
            synchronized (VoiceAiStream.class) { reply.generating = false; reply.finished = true; }
        }
    }

    private static void scheduleDeadline(final Reply reply) {
        reply.deadline = new TimerTask() { @Override public void run() {
            HttpURLConnection connection = null;
            String reason = null;
            synchronized (VoiceAiStream.class) {
                if (!current(reply) || !reply.generating || reply.deadlineExceeded) return;
                long elapsed = (System.nanoTime() - reply.beganNanos) / 1000000L;
                if (!reply.spoken && elapsed >= reply.firstReplyMs) reason = "first_reply";
                else if (!reply.fallback && !reply.firstContent && elapsed >= reply.firstContentMs) reason = "first_content";
                else if (elapsed >= reply.answerMs) reason = "answer";
                if (reason == null) return;
                reply.deadlineExceeded = true;
                connection = reply.connection;
            }
            Log.w("R1AIStream", "DEADLINE phase=" + reason);
            VoiceDiagnostics.record("WARN","AI",reply.turn,"status","timeout","error_kind",reason);
            disconnectAsync(connection);
        }};
        DEADLINES.schedule(reply.deadline, 50, 50);
    }

    private static void disconnectAsync(final HttpURLConnection connection) {
        if (connection != null) new Thread(new Runnable() { @Override public void run() { connection.disconnect(); }}, "R1-AI-cancel").start();
    }

    private static boolean event(Reply reply, String data, long began) throws Exception {
        if ("[DONE]".equals(data)) return true;
        JSONObject object = new JSONObject(data);
        if (object.has("error")) throw new IllegalStateException("provider error");
        JSONArray choices = object.optJSONArray("choices");
        if (choices == null || choices.length() == 0) return false;
        JSONObject delta = choices.getJSONObject(0).optJSONObject("delta");
        // 不读取 reasoning_content、tool_calls 或其它非正文输出。
        if (delta != null && delta.opt("content") instanceof String)
            append(reply, delta.optString("content"), began);
        return false;
    }

    private static synchronized void append(Reply reply, String text, long began) {
        if (!current(reply) || text == null || text.length() == 0) return;
        if (reply.deadlineExceeded) throw new IllegalStateException("response deadline");
        reply.firstContent = true;
        if (reply.answer.length() == 0) Log.i("R1AIStream", "FIRST_CONTENT elapsed_ms=" + (System.currentTimeMillis() - began));
        if (reply.answer.length() + text.length() > 20000) throw new IllegalStateException("answer too large");
        reply.answer.append(text);
        reply.fragment.append(text);
        int end;
        while ((end = sentenceEnd(reply.fragment)) > 0) {
            String sentence = reply.fragment.substring(0, end).trim();
            reply.fragment.delete(0, end);
            if (sentence.length() > 0) reply.pending.add(sentence);
        }
        startNext(reply);
    }

    static int sentenceEnd(CharSequence text) {
        for (int i=0;i<text.length();i++) {
            char c=text.charAt(i);
            boolean sentence="。！？!?；;\n".indexOf(c)>=0 && i+1>=4;
            boolean clause="，,、".indexOf(c)>=0 && i+1>=15;
            if ((sentence || clause) && !filler(text.subSequence(0,i+1).toString())) return i+1;
        }
        return -1;
    }

    private static boolean filler(String text) {
        String clean=text.replaceAll("[\\s，。！？、,.!?；;]","");
        return clean.matches("(好的|好|可以|没问题|当然可以)?(我来|让我|下面我来|这就)?"+
                "(为你|为您|帮你|帮您)?(解释|介绍|说明|回答|解答)?(一下|这个问题)?");
    }

    private static boolean current(Reply reply) {
        return active == reply && !reply.cancelled && VoiceSession.isCurrent(reply.turn);
    }

    private static void finish(final Reply reply) {
        reply.generating = false;
        if (reply.fragment.length() > 0) { reply.pending.add(reply.fragment.toString()); reply.fragment.setLength(0); }
        startNext(reply);
        if (!reply.playing && reply.pending.isEmpty() && reply.waiting && !reply.finished) {
            reply.finished = true;
            VoiceFollowup.responseEnded(reply.turn);
            MAIN.post(new Runnable() { @Override public void run() {
                if (!current(reply)) return;
                try {
                    Field field = field(reply.handler.getClass(), "ctx");
                    Object context = field.get(reply.handler);
                    method(reply.handler.getClass(),"onTTSEventPlayingEnd",Class.forName("com.unisound.vui.engine.ANTHandlerContext"))
                            .invoke(reply.handler, context);
                } catch (Exception error) { Log.w("R1AIStream", "END_FAILED " + error.getClass().getSimpleName()); }
            }});
        }
    }

    private static void startNext(final Reply reply) {
        if (!current(reply) || reply.playing || reply.pending.isEmpty()) return;
        final int attempt = reply.attempt;
        final String text = reply.pending.remove();
        reply.playing = true;
        reply.waiting = false;
        MAIN.post(new Runnable() { @Override public void run() {
            synchronized (VoiceAiStream.class) {
                if (!current(reply) || reply.deadlineExceeded || reply.attempt != attempt) return;
                reply.spoken = true;
            }
            try {
                Log.i("R1AIStream", "SPEAK characters=" + text.length());
                method(reply.handler.getClass(),"playTTS",String.class).invoke(reply.handler, text);
            } catch (Exception error) {
                synchronized (VoiceAiStream.class) { reply.playing = false; reply.cancelled = true; }
                Log.w("R1AIStream", "SPEAK_FAILED " + error.getClass().getSimpleName());
            }
        }});
    }

    /** 中间句结束时消费事件；最后一句仍交给原处理器结束会话。 */
    public static synchronized boolean onSpeechEnd(Object handler) {
        Reply reply = active;
        if (reply == null || handler != reply.handler || !current(reply) || reply.finished) return false;
        if (!reply.playing) return reply.generating;
        reply.playing = false;
        if (!reply.pending.isEmpty()) { startNext(reply); return true; }
        if (reply.generating) { reply.waiting = true; return true; }
        reply.finished = true;
        VoiceFollowup.responseEnded(reply.turn);
        return false;
    }

    public static void playReply(Object handler, String text, int turn) {
        synchronized (VoiceAiStream.class) {
            if (!VoiceSession.isCurrent(turn)) return;
            if (active != null && active.handler == handler && active.turn == turn && !active.cancelled && (active.spoken || active.playing || !active.pending.isEmpty())) return;
        }
        try { method(handler.getClass(),"playTTS",String.class).invoke(handler, text); }
        catch (Exception error) { Log.w("R1AIStream", "REPLY_FAILED " + error.getClass().getSimpleName()); }
    }

    public static synchronized void cancel() {
        Reply reply = active;
        active = null;
        if (reply == null) return;
        reply.cancelled = true;
        reply.pending.clear();
        if (reply.deadline != null) reply.deadline.cancel();
        disconnectAsync(reply.connection);
    }

    public static synchronized boolean hasPendingSpeech() {
        Reply reply=active;
        return reply!=null && current(reply) && !reply.fallback && !reply.finished &&
                (reply.generating || reply.playing || !reply.pending.isEmpty());
    }

    private static final ConcurrentHashMap<Class<?>,ConcurrentHashMap<MethodKey,Method>> METHODS =
            new ConcurrentHashMap<Class<?>,ConcurrentHashMap<MethodKey,Method>>();
    private static final ConcurrentHashMap<Class<?>,ConcurrentHashMap<String,Field>> FIELDS =
            new ConcurrentHashMap<Class<?>,ConcurrentHashMap<String,Field>>();

    private static final class MethodKey {
        final String name;
        final Class<?>[] parameters;
        MethodKey(String name,Class<?>[] parameters){this.name=name;this.parameters=parameters.clone();}
        public int hashCode(){return 31*name.hashCode()+Arrays.hashCode(parameters);}
        public boolean equals(Object other){
            if(!(other instanceof MethodKey))return false;
            MethodKey key=(MethodKey)other;
            return name.equals(key.name)&&Arrays.equals(parameters,key.parameters);
        }
    }

    private static Method method(Class<?> type,String name,Class<?>... parameters) throws Exception {
        ConcurrentHashMap<MethodKey,Method> cache=METHODS.get(type);
        if(cache==null){
            ConcurrentHashMap<MethodKey,Method> created=new ConcurrentHashMap<MethodKey,Method>();
            ConcurrentHashMap<MethodKey,Method> previous=METHODS.putIfAbsent(type,created);
            cache=previous==null?created:previous;
        }
        MethodKey key=new MethodKey(name,parameters);Method found=cache.get(key);
        if(found!=null)return found;
        for(Class<?> current=type;current!=null;current=current.getSuperclass()){
            try{
                found=current.getDeclaredMethod(name,parameters);found.setAccessible(true);
                Method previous=cache.putIfAbsent(key,found);return previous==null?found:previous;
            }catch(NoSuchMethodException ignored){}
        }
        found=type.getMethod(name,parameters);found.setAccessible(true);
        Method previous=cache.putIfAbsent(key,found);return previous==null?found:previous;
    }

    private static Field field(Class<?> type,String name) throws Exception {
        ConcurrentHashMap<String,Field> cache=FIELDS.get(type);
        if(cache==null){
            ConcurrentHashMap<String,Field> created=new ConcurrentHashMap<String,Field>();
            ConcurrentHashMap<String,Field> previous=FIELDS.putIfAbsent(type,created);
            cache=previous==null?created:previous;
        }
        Field found=cache.get(name);if(found!=null)return found;
        for(Class<?> current=type;current!=null;current=current.getSuperclass()){
            try{
                found=current.getDeclaredField(name);found.setAccessible(true);
                Field previous=cache.putIfAbsent(name,found);return previous==null?found:previous;
            }catch(NoSuchFieldException ignored){}
        }
        throw new NoSuchFieldException(name);
    }
}
