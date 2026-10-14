package r1.local.asr;
import java.net.*;
import java.io.*;
import org.json.JSONObject;

/** 使用本地网关复用 MA 控制 API；未匹配的指令交回现有 HA。 */
public final class MusicRoute {
    public static boolean isCandidate(String text) {
        return SharedIntentRules.isMusicCandidate(text);
    }

    public static boolean isDirectMusic(String text) {
        try { return isCandidate(text) && "direct".equals(CloudVoiceSettings.getString("music_route","ha")); }
        catch (Exception error) { return false; }
    }

    public static String route(String text) {
        HttpURLConnection connection = null;
        try {
            if (!"direct".equals(CloudVoiceSettings.getString("music_route","ha")) ||
                    !isCandidate(text)) return null;
            connection = (HttpURLConnection)new URL(CloudVoiceSettings.gatewayUrl()+"/music/control").openConnection();
            connection.setConnectTimeout(1200);connection.setReadTimeout(17000);
            connection.setRequestMethod("POST");connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type","application/json; charset=utf-8");
            JSONObject payload = new JSONObject();payload.put("text",text);payload.put("turn",VoiceSession.currentTurn());
            VoiceDiagnostics.record("INFO","ROUTE",VoiceSession.currentTurn(),"route","MA","text",text,"status","requested");
            byte[] bytes=payload.toString().getBytes("UTF-8");connection.setFixedLengthStreamingMode(bytes.length);
            OutputStream output=connection.getOutputStream();output.write(bytes);output.close();
            if (connection.getResponseCode()!=200) throw new IOException("Music gateway unavailable");
            InputStream input=connection.getInputStream();
            ByteArrayOutputStream buffer=new ByteArrayOutputStream();byte[] chunk=new byte[1024];int count;
            while ((count=input.read(chunk))!=-1) {
                if (buffer.size()+count>16384) throw new IOException("Invalid music response");
                buffer.write(chunk,0,count);
            }
            input.close();JSONObject response=new JSONObject(new String(buffer.toByteArray(),"UTF-8"));
            VoiceDiagnostics.record(response.optBoolean("handled",false) && !response.optBoolean("accepted",false)?"WARN":"INFO",
                    "MA",VoiceSession.currentTurn(),"status",response.optBoolean("handled",false)?"acknowledged":"delegated_to_HA",
                    "accepted",response.optBoolean("accepted",false),"response",response.optString("message",""),
                    "operation",response.optString("operation",""));
            if (!response.optBoolean("handled",false)) return null;
            android.util.Log.i("R1VoiceRoute","MA_DIRECT");
            if (response.optBoolean("accepted",false) && !CloudVoiceSettings.getBoolean("music_ack",false)) return "";
            return response.optString("message","音乐通道未返回执行结果，请稍后再试。");
        } catch (Exception error) {
            VoiceDiagnostics.record("ERROR","MA",VoiceSession.currentTurn(),"status","failed","error_kind",error.getClass().getSimpleName());
            android.util.Log.w("R1VoiceRoute","MA_UNCONFIRMED");
            return "音乐通道暂时无法确认执行结果，请稍后再试。";
        } finally { if (connection!=null) connection.disconnect(); }
    }
}
