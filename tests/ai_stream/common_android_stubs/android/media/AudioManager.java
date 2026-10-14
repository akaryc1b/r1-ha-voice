package android.media;
/** 只声明测试所需 Android 边界；行为由每个 suite 的子类提供。 */
public class AudioManager {
    public static final int STREAM_MUSIC=3;
    public int getStreamMaxVolume(int stream){throw new AssertionError("Audio backend not configured");}
    public int getStreamVolume(int stream){throw new AssertionError("Audio backend not configured");}
    public void setStreamVolume(int stream,int level,int flags){throw new AssertionError("Audio backend not configured");}
    public void setStreamMute(int stream,boolean state){throw new AssertionError("Audio backend not configured");}
}
