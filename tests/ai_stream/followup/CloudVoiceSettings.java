package r1.local.asr;
public final class CloudVoiceSettings {
    public static boolean enabled=true;
    public static boolean getBoolean(String key,boolean fallback){return enabled;}
    public static int getInt(String key,int fallback){return 3;}
}
