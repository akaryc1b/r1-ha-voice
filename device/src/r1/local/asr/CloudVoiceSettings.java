package r1.local.asr;

import android.util.AtomicFile;
import java.io.*;
import java.net.*;
import java.util.*;
import org.json.JSONObject;

/** 网页与音频通道共用一个持久化配置，不在网页传递供应商密钥。 */
public final class CloudVoiceSettings {
    private static final File FILE = new File("/sdcard/r1-local-asr.json");

    public static synchronized JSONObject read() throws Exception {
        if (!FILE.isFile() || FILE.length() > 16384) return new JSONObject();
        FileInputStream input = new FileInputStream(FILE);
        try {
            ByteArrayOutputStream buffer = new ByteArrayOutputStream();
            byte[] chunk = new byte[1024]; int count;
            while ((count = input.read(chunk)) != -1) buffer.write(chunk,0,count);
            return new JSONObject(new String(buffer.toByteArray(),"UTF-8"));
        } finally { input.close(); }
    }

    public static String gatewayUrl(JSONObject settings) throws Exception {
        return checkedUrl(settings.optString("gateway_url","http://192.168.1.88:16068"),false);
    }

    public static String asrServer(String value) throws Exception {
        return checkedUrl(value,true);
    }

    private static String checkedUrl(String value, boolean websocket) throws Exception {
        if (value == null || value.length() > 512) throw new IllegalArgumentException("服务地址无效");
        value = value.trim();
        URI uri = new URI(value);
        String scheme = uri.getScheme();
        boolean valid = websocket ? ("ws".equals(scheme) || "wss".equals(scheme)) :
                ("http".equals(scheme) || "https".equals(scheme));
        if (!valid || uri.getHost() == null || uri.getRawUserInfo() != null ||
                uri.getFragment() != null || (!websocket && uri.getQuery() != null))
            throw new IllegalArgumentException("请填写有效的服务地址，密钥不要放入地址");
        while (value.endsWith("/")) value = value.substring(0,value.length()-1);
        return value;
    }

    private static synchronized void write(JSONObject settings) throws Exception {
        AtomicFile atomic = new AtomicFile(FILE);
        FileOutputStream output = atomic.startWrite();
        try {
            output.write(settings.toString().getBytes("UTF-8"));
            atomic.finishWrite(output);
        } catch (Exception error) { atomic.failWrite(output); throw error; }
    }

    private static void connectionValues(JSONObject settings, Map<String,String> values) throws Exception {
        if (values.containsKey("gateway_url"))
            settings.put("gateway_url",checkedUrl(values.get("gateway_url"),false));
        if (values.containsKey("local_server"))
            settings.put("local_server",asrServer(values.get("local_server")));
        if (values.containsKey("session_timeout_seconds")) {
            int timeout = Integer.parseInt(values.get("session_timeout_seconds"));
            if (timeout < 20 || timeout > 120) throw new IllegalArgumentException("整轮识别超时需为 20～120 秒");
            settings.put("session_timeout_seconds",timeout);
        }
    }

    private static synchronized void save(Map<String,String> values) throws Exception {
        String asr = values.get("asr");
        String tts = values.get("tts");
        if (!("gateway".equals(asr) || "cloud".equals(asr) || "fast".equals(asr) ||
                "local".equals(asr) || "xingchen".equals(asr)) ||
                !("cosy".equals(tts) || "original".equals(tts)))
            throw new IllegalArgumentException("无效的语音设置");
        JSONObject settings = read();
        connectionValues(settings,values);
        settings.put("enabled",true);
        String server = "local".equals(asr) ?
                settings.optString("local_server","ws://192.168.1.88:16066") :
                gatewayUrl(settings).replaceFirst("^http","ws") + "/asr";
        // 旧接口仍可选择预设；新网页由网关配置决定模型，不在 URL 固定模型。
        if ("fast".equals(asr)) server += "?model=TeleAI%2FTeleSpeechASR";
        if ("xingchen".equals(asr)) server += "?model=XingChenAGI%2FXingChenGSR-V1.0";
        settings.put("server",asrServer(server));
        settings.put("cloud_tts","cosy".equals(tts));
        if (values.containsKey("voice")) settings.put("cloud_voice",values.get("voice"));
        settings.put("music_ack","true".equals(values.get("music_ack")));
        write(settings);
    }

    private static JSONObject publicSettings() throws Exception {
        JSONObject settings = read();
        JSONObject result = new JSONObject();
        String server = settings.optString("server","");
        result.put("asr",server.contains("/asr") ? "gateway" : "local");
        result.put("gateway_url",gatewayUrl(settings));
        result.put("local_server",settings.optString("local_server","ws://192.168.1.88:16066"));
        result.put("session_timeout_seconds",settings.optInt("session_timeout_seconds",45));
        result.put("tts",settings.optBoolean("cloud_tts",false) ? "cosy" : "original");
        result.put("voice",settings.optString("cloud_voice","anna"));
        result.put("music_route",settings.optString("music_route","ha"));
        result.put("music_ack",settings.optBoolean("music_ack",false));
        result.put("legacy_assistant",false);
        return result;
    }

    public static boolean handle(Socket socket, String route, BufferedReader reader, String method) {
        if (!route.startsWith("/voice_config") && !route.equals("/voice_health") && !route.equals("/voice_test") && !route.startsWith("/voice_volume") && !route.startsWith("/music_config") && !route.startsWith("/voice_gateway_config") && !route.startsWith("/voice_connection") && !route.startsWith("/voice_models") && !route.startsWith("/voice_asr_test")) return false;
        JSONObject result; int status = 200;
        try {
            Map<String,String> values = new HashMap<String,String>();
            int query = route.indexOf('?');
            String path = query < 0 ? route : route.substring(0,query);
            if (query >= 0) for (String part : route.substring(query+1).split("&")) {
                String[] pair = part.split("=",2);
                values.put(URLDecoder.decode(pair[0],"UTF-8"),pair.length == 2 ? URLDecoder.decode(pair[1],"UTF-8") : "");
            }
            if ("POST".equals(method)) {
                JSONObject body = VoiceSettingsHttp.readJson(socket,reader);
                if ("/voice_gateway_config".equals(path)) {
                    result = VoiceSettingsHttp.gateway("/config",body);
                } else if ("/voice_asr_test".equals(path)) {
                    result = VoiceSettingsHttp.gateway("/asr/test",body);
                } else if ("/voice_config".equals(path) || "/voice_connection".equals(path)) {
                    Iterator<String> keys = body.keys();
                    while (keys.hasNext()) { String key = keys.next(); values.put(key,body.optString(key,"")); }
                    if ("/voice_config".equals(path)) save(values);
                    else {
                        JSONObject settings = read(); connectionValues(settings,values);
                        String old = settings.optString("server","");
                        if (old.contains("/asr")) settings.put("server",gatewayUrl(settings).replaceFirst("^http","ws")+"/asr");
                        else settings.put("server",settings.optString("local_server","ws://192.168.1.88:16066"));
                        write(settings);
                    }
                    result = publicSettings();
                } else { throw new IllegalArgumentException("不支持此设置请求"); }
                if (result.has("error")) status = 400;
            } else if ("/voice_gateway_config".equals(path)) {
                result = VoiceSettingsHttp.gateway("/config",null);
            } else if ("/voice_models".equals(path)) {
                result = VoiceSettingsHttp.gateway("/models",null);
                if (result.has("error")) status = 503;
            } else if ("/music_config".equals(path)) {
                JSONObject settings=read();
                if ("save".equals(values.get("action"))) {
                    String mode=values.get("route");
                    if (!("ha".equals(mode)||"direct".equals(mode))) throw new IllegalArgumentException("Invalid music route");
                    settings.put("music_route",mode);
                    AtomicFile atomic=new AtomicFile(FILE);FileOutputStream output=atomic.startWrite();
                    try {output.write(settings.toString().getBytes("UTF-8"));atomic.finishWrite(output);}
                    catch (Exception error) {atomic.failWrite(output);throw error;}
                }
                result=new JSONObject();result.put("route",settings.optString("music_route","ha"));
            } else if ("/voice_volume".equals(path)) {
                result = LocalAsr.adjustVolume(values.containsKey("target") ? values.get("target") : "music",
                        values.containsKey("operation") ? values.get("operation") : "get",
                        values.containsKey("percent") ? Integer.parseInt(values.get("percent")) : 0);
            } else if ("/voice_config".equals(path)) {
                if ("save".equals(values.get("action"))) save(values);
                result = publicSettings();
            } else if ("/voice_health".equals(path)) {
                result = VoiceSettingsHttp.gateway("/health",null);
            } else if ("/voice_test".equals(path)) {
                if ("1".equals(values.get("music_error"))) LocalAsr.musicErrorSpeech(Integer.parseInt(values.get("turn")));
                else LocalAsr.testSpeech();
                result = new JSONObject(); result.put("queued",true);
            } else { throw new IllegalArgumentException("Unknown voice endpoint"); }
        } catch (Exception error) {
            result = new JSONObject(); status = error instanceof IllegalArgumentException ? 400 : 503;
            try { result.put("error",error instanceof IllegalArgumentException ? error.getMessage() : "语音设置或网关连接失败，请检查网关地址与服务状态"); } catch (Exception ignored) {}
        }
        try {
            byte[] body = result.toString().getBytes("UTF-8");
            OutputStream output = socket.getOutputStream();
            String header = "HTTP/1.1 " + status + (status == 200 ? " OK" : " Service Unavailable") +
                    "\r\nContent-Type: application/json; charset=utf-8\r\nCache-Control: no-store\r\nContent-Length: " +
                    body.length + "\r\nConnection: close\r\n\r\n";
            output.write(header.getBytes("UTF-8"));output.write(body);output.flush();socket.close();
        } catch (Exception ignored) {}
        return true;
    }

    public static String decorate(String html) {
        String card = VoiceConfigPage.card();
        java.util.regex.Pattern pattern = java.util.regex.Pattern.compile("(<div[^>]*id=['\"]tab-r1['\"][^>]*>)");
        java.util.regex.Matcher matcher = pattern.matcher(html);
        if (matcher.find()) html = html.substring(0,matcher.end()) + card + html.substring(matcher.end());
        else html = html.replace("<body>","<body>"+card);
        String script = VoiceConfigPage.script();
        return html.replace("</body>",script+"</body>");
    }
}
