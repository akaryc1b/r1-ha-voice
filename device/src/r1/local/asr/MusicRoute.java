package r1.local.asr;
import java.net.*;
import java.io.*;
import org.json.JSONObject;

/** 使用本地网关复用 MA 控制 API；未匹配的指令交回现有 HA。 */
public final class MusicRoute {
    public static boolean isCandidate(String text) {
        if (text==null || VoiceSession.isExplanationQuestion(text)) return false;
        String clean=text.trim().replaceFirst("^(麻烦帮我|请帮我|请给我|能不能帮我|可以帮我|能不能|帮我|给我|麻烦|请|帮忙|可以)","");
        return clean.matches("^(播放|放(?!心|弃|假|学)|来首|来一首|来点|来个音乐|来些|来一些|听歌|听音乐|听点|我想听|我要听|给点音乐|随便|随机|先暂停|先停|先别放|先不听|暂停|继续|接着放|接着播放|停止|别放|别播放|不要放|不要播放|下一首|下一曲|上一首|上一曲|换个歌|换首歌|换一首|换下一|再来一首|切歌|切换|回到上一首|音乐(暂停|停止|继续|播放)|打开.*播放器|启动.*播放器|关闭.*(音乐|播放器)|关掉.*(音乐|播放器)|把音乐关了).*$");
    }

    public static boolean isDirectMusic(String text) {
        try { return isCandidate(text) && "direct".equals(CloudVoiceSettings.read().optString("music_route","ha")); }
        catch (Exception error) { return false; }
    }

    public static String route(String text) {
        HttpURLConnection connection = null;
        try {
            if (!"direct".equals(CloudVoiceSettings.read().optString("music_route","ha")) ||
                    !isCandidate(text)) return null;
            connection = (HttpURLConnection)new URL(CloudVoiceSettings.gatewayUrl(CloudVoiceSettings.read())+"/music/control").openConnection();
            connection.setConnectTimeout(1200);connection.setReadTimeout(17000);
            connection.setRequestMethod("POST");connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type","application/json; charset=utf-8");
            JSONObject payload = new JSONObject();payload.put("text",text);payload.put("turn",VoiceSession.currentTurn());
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
            if (!response.optBoolean("handled",false)) return null;
            android.util.Log.i("R1VoiceRoute","MA_DIRECT");
            if (response.optBoolean("accepted",false) && !CloudVoiceSettings.read().optBoolean("music_ack",false)) return "";
            return response.optString("message","音乐通道未返回执行结果，请稍后再试。");
        } catch (Exception error) {
            android.util.Log.w("R1VoiceRoute","MA_UNCONFIRMED");
            return "音乐通道暂时无法确认执行结果，请稍后再试。";
        } finally { if (connection!=null) connection.disconnect(); }
    }
}
