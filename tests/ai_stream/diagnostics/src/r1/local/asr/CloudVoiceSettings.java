package r1.local.asr;
import org.json.JSONObject;
public final class CloudVoiceSettings {
 static JSONObject config=new JSONObject();
 public static String base;
 public static JSONObject read(){return config;}
 public static String gatewayUrl(JSONObject data){return base;}
 static void saveLogState(boolean enabled,String level,long generation) throws Exception {
  config.put("logs_enabled",enabled);config.put("logs_level",level);config.put("logs_generation",generation);
 }
}
