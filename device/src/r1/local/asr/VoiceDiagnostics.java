package r1.local.asr;

import java.io.*;
import java.net.*;
import java.text.SimpleDateFormat;
import java.util.*;
import java.util.concurrent.ArrayBlockingQueue;
import org.json.JSONArray;
import org.json.JSONObject;

/** 只发送明确选择的诊断字段；语音线程不等待网络或写盘。 */
public final class VoiceDiagnostics {
    private static final ArrayBlockingQueue<JSONObject> QUEUE = new ArrayBlockingQueue<JSONObject>(96);
    private static final Set<String> FIELDS = new HashSet<String>(Arrays.asList(
            "text","response","route","model","backend","operation","error_kind","status",
            "duration_ms","audio_seconds","accepted","executed","request_id"));
    private static volatile boolean enabled;
    private static volatile String level = "INFO";
    private static volatile long generation;
    private static boolean started;
    private static final ThreadLocal<HaCall> HA = new ThreadLocal<HaCall>();

    private VoiceDiagnostics() {}

    public static synchronized void initialize() {
        try {
            JSONObject settings = CloudVoiceSettings.read();
            enabled = settings.optBoolean("logs_enabled",false);
            level = settings.optString("logs_level","INFO");
            generation = settings.optLong("logs_generation",0);
        } catch (Exception ignored) { enabled = false; }
        startWorker();
    }

    private static int rank(String value) {
        if ("ERROR".equals(value)) return 40;
        if ("WARN".equals(value)) return 30;
        if ("INFO".equals(value)) return 20;
        return 10;
    }

    static String redact(String text) {
        if (text == null) return "";
        // 不接收请求头、地址或异常正文；文本内出现的常见凭据也去掉。
        String value=text.replaceAll("(?i)Bearer\\s+[^\\s,;\\\"']+","Bearer [已隐藏]")
                .replaceAll("\\beyJ[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+","[令牌已隐藏]")
                .replaceAll("\\bsk-[A-Za-z0-9_-]+","[密钥已隐藏]")
                .replaceAll("(?i)https?://[^\\s\\\"<>]+","[地址已隐藏]");
        return value.length()>2048 ? value.substring(0,2048)+"…" : value;
    }

    public static void record(String severity,String stage,int turn,Object... pairs) {
        if (!enabled || rank(severity)<rank(level)) return;
        try {
            JSONObject fields=new JSONObject();
            for (int i=0;i+1<pairs.length;i+=2) {
                String key=String.valueOf(pairs[i]);Object value=pairs[i+1];
                if (!FIELDS.contains(key) || value==null) continue;
                if (value instanceof Number || value instanceof Boolean) fields.put(key,value);
                else fields.put(key,redact(String.valueOf(value)));
            }
            JSONObject event=new JSONObject();
            SimpleDateFormat format=new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'",Locale.US);
            format.setTimeZone(TimeZone.getTimeZone("UTC"));
            event.put("timestamp",format.format(new Date()));event.put("level",severity);
            event.put("source","device");event.put("stage",stage);event.put("turn",turn);event.put("fields",fields);
            event.put("generation",generation);
            QUEUE.offer(event); // 队列满时丢诊断，不延迟语音控制。
        } catch (Exception ignored) {}
    }

    private static synchronized void startWorker() {
        if (started) return;
        started=true;
        Thread thread=new Thread(new Runnable() { @Override public void run() {
            while (true) {
                try {
                    JSONObject first=QUEUE.take();long epoch=first.optLong("generation",-1);
                    if (!enabled || epoch!=generation) continue;
                    first.remove("generation");JSONArray events=new JSONArray();events.put(first);
                    for (int i=1;i<8;i++) {
                        JSONObject next=QUEUE.poll();if (next==null) break;
                        if (next.optLong("generation",-1)==epoch) { next.remove("generation");events.put(next); }
                    }
                    JSONObject body=new JSONObject();body.put("generation",epoch);body.put("events",events);
                    JSONObject result=send(body);
                    if (result.optBoolean("stale",false)) {
                        apply(VoiceSettingsHttp.gateway("/logs/config",null));
                    }
                } catch (InterruptedException stopped) { Thread.currentThread().interrupt();return; }
                catch (Exception ignored) { /* 日志网络失败不重放，不影响业务。 */ }
            }
        }},"R1VoiceDiagnostics");
        thread.setDaemon(true);thread.start();
    }

    private static JSONObject send(JSONObject body) throws Exception {
        String base=CloudVoiceSettings.gatewayUrl();
        HttpURLConnection connection=(HttpURLConnection)new URL(base+"/logs/events").openConnection();
        connection.setConnectTimeout(700);connection.setReadTimeout(1200);
        connection.setRequestMethod("POST");connection.setDoOutput(true);
        connection.setRequestProperty("Content-Type","application/json; charset=utf-8");
        byte[] bytes=body.toString().getBytes("UTF-8");connection.setFixedLengthStreamingMode(bytes.length);
        try {
            OutputStream output=connection.getOutputStream();output.write(bytes);output.close();
            if (connection.getResponseCode()!=200) throw new IOException("Log sink unavailable");
            InputStream input=connection.getInputStream();ByteArrayOutputStream result=new ByteArrayOutputStream();
            try { byte[] buffer=new byte[1024];int count;
                while ((count=input.read(buffer))!=-1) { if (result.size()+count>4096) throw new IOException();result.write(buffer,0,count); }
            } finally { input.close(); }
            return new JSONObject(new String(result.toByteArray(),"UTF-8"));
        } finally { connection.disconnect(); }
    }

    private static synchronized void apply(JSONObject settings) throws Exception {
        if (settings.has("error")) throw new IOException("Diagnostic configuration unavailable");
        boolean next=settings.optBoolean("enabled",false);
        String threshold=settings.optString("level","INFO");
        long epoch=settings.optLong("generation",0);
        if (epoch!=generation || !next) QUEUE.clear();
        enabled=next;level=threshold;generation=epoch;
        CloudVoiceSettings.saveLogState(next,threshold,epoch);
        startWorker();
    }

    public static boolean handle(Socket socket,String route,BufferedReader reader,String method) {
        if (!route.startsWith("/voice_logs")) return false;
        JSONObject result;int status=200;
        try {
            String path=route.split("\\?",2)[0];
            if ("GET".equals(method) && "/voice_logs".equals(path)) {
                int limit=50;
                if (route.contains("?")) for (String part:route.substring(route.indexOf('?')+1).split("&"))
                    if (part.startsWith("limit=")) limit=Integer.parseInt(part.substring(6));
                if (limit<1 || limit>100) throw new IllegalArgumentException("日志条数需为1～100");
                result=VoiceSettingsHttp.gateway("/logs?limit="+limit,null);
            } else if ("/voice_logs_config".equals(path) && ("GET".equals(method)||"POST".equals(method))) {
                JSONObject patch="POST".equals(method)?VoiceSettingsHttp.readJson(socket,reader):null;
                result=VoiceSettingsHttp.gateway("/logs/config",patch);if (!result.has("error")) apply(result);
            } else if ("/voice_logs_clear".equals(path) && "POST".equals(method)) {
                VoiceSettingsHttp.readJson(socket,reader);
                boolean before=enabled;enabled=false;QUEUE.clear();
                try { result=VoiceSettingsHttp.gateway("/logs/clear",new JSONObject());apply(result); }
                catch (Exception error) { enabled=before;throw error; }
            } else throw new IllegalArgumentException("不支持的日志请求");
            if (result.has("error")) status=400;
        } catch (Exception error) {
            status=error instanceof IllegalArgumentException?400:503;result=new JSONObject();
            try { result.put("error",error instanceof IllegalArgumentException?error.getMessage():"日志网关连接失败，请检查N1服务状态"); }
            catch (Exception ignored) {}
        }
        try {
            byte[] body=result.toString().getBytes("UTF-8");OutputStream output=socket.getOutputStream();
            String header="HTTP/1.1 "+status+(status==200?" OK":" Service Unavailable")+
                    "\r\nContent-Type: application/json; charset=utf-8\r\nCache-Control: no-store\r\nContent-Length: "+body.length+"\r\nConnection: close\r\n\r\n";
            output.write(header.getBytes("UTF-8"));output.write(body);output.flush();socket.close();
        } catch (Exception ignored) {}
        return true;
    }

    private static final class HaCall {
        final int turn=VoiceSession.currentTurn();final long started=System.currentTimeMillis();boolean logged;
    }

    public static void haStarted(String text) {
        if (!enabled) return;
        HA.set(new HaCall());
        record("INFO","ROUTE",VoiceSession.currentTurn(),"route","HA","text",text,"status","requested");
    }

    public static void haResponse(JSONObject response) {
        HaCall call=HA.get();if (call==null) return;
        try {
            String type=response==null?"empty_response":response.optString("response_type","");
            JSONObject speech=response==null?null:response.optJSONObject("speech");
            JSONObject plain=speech==null?null:speech.optJSONObject("plain");
            JSONObject data=response==null?null:response.optJSONObject("data");
            record("error".equals(type)?"WARN":"INFO","HA",call.turn,"status",type,
                    "response",plain==null?"":plain.optString("speech",""),
                    "error_kind",data==null?"":data.optString("code",""),"duration_ms",System.currentTimeMillis()-call.started);
            call.logged=true;
        } catch (Exception ignored) {}
    }

    public static void haReturned(String response) {
        HaCall call=HA.get();HA.remove();if (call==null || call.logged) return;
        record("WARN","HA",call.turn,"status","unconfirmed","response",response,
                "duration_ms",System.currentTimeMillis()-call.started);
    }
}
