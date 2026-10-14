package android.content;
import android.media.AudioManager;
public class Context {
    public static final String AUDIO_SERVICE="audio";
    public final AudioManager audio;
    public Context(AudioManager value){audio=value;}
    public Context getApplicationContext(){return this;}
    public Object getSystemService(String name){
        if(!AUDIO_SERVICE.equals(name))throw new AssertionError("Unknown service");
        return audio;
    }
}
