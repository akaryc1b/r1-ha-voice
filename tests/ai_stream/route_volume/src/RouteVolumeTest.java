import android.content.Context;
import android.media.AudioManager;
import r1.local.asr.LocalAsr;
import r1.local.asr.SpeechRouteVolume;

public class RouteVolumeTest {
    static void require(boolean ok,String message){if(!ok)throw new AssertionError(message);}
    static Context context=new Context();
    static AudioManager audio=context.audio;
    static void fresh(){context=new Context();audio=context.audio;LocalAsr.stream=2;SpeechRouteVolume.initialize(context);}
    static void play(Object track){SpeechRouteVolume.beforePlay(track);audio.speaker=true;SpeechRouteVolume.afterPlay(track);}
    static void stop(Object track){audio.speaker=false;SpeechRouteVolume.afterStop(track);}
    public static void main(String[] args)throws Exception {
        Thread.setDefaultUncaughtExceptionHandler((thread,error)->{error.printStackTrace();System.exit(1);});
        fresh();Object one=new Object();play(one);
        require(audio.speakerLevel==4&&audio.spdifLevel==4&&audio.speechLevel==8,"route changes without raising music");stop(one);
        System.out.println("PASS active-route music level preserved; speech remains independent");
        fresh();audio.spdifLevel=0;one=new Object();play(one);require(audio.speakerLevel==0&&audio.speechLevel==8,"mute preserved");stop(one);
        System.out.println("PASS music mute stays zero");
        fresh();LocalAsr.stream=9;one=new Object();play(one);require(audio.speakerLevel==8&&audio.writes==0,"only stream2 guarded");
        System.out.println("PASS other speech stream remains untouched");
        fresh();one=new Object();SpeechRouteVolume.beforePlay(one);SpeechRouteVolume.setMusicVolume(audio,6);audio.speaker=true;SpeechRouteVolume.afterPlay(one);
        require(audio.speakerLevel==6,"explicit change between capture and play wins");stop(one);Thread.sleep(250);require(audio.spdifLevel==6,"explicit change survives return routing");
        System.out.println("PASS user music adjustment wins and follows end-route transition");
        fresh();one=new Object();play(one);SpeechRouteVolume.setMusicVolume(audio,6);stop(one);
        Object two=new Object();play(two);SpeechRouteVolume.setMusicVolume(audio,5);SpeechRouteVolume.afterStop(one);Thread.sleep(250);
        require(audio.speakerLevel==5,"old callbacks cannot overwrite new track adjustment");stop(two);Thread.sleep(250);require(audio.spdifLevel==5,"latest intent restored");
        System.out.println("PASS stale-track and delayed-generation callbacks are discarded");
        fresh();audio.spdifLevel=7;one=new Object();play(one);require(audio.speakerLevel==7,"capture actual music level rather than stale intent");stop(one);
        System.out.println("PASS current external music level respected before play");
        System.out.println("TESTS 6");System.exit(0);
    }
}
