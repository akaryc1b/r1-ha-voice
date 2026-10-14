import r1.local.asr.AsrAudio;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Arrays;
public class AsrAudioTest {
    static void check(boolean ok){if(!ok)throw new AssertionError();}
    public static void main(String[] args)throws Exception{
        check(AsrAudio.transportUrl("ws://speaker/asr").equals("ws://speaker/asr?audio_format=pcm_s16le"));
        check(AsrAudio.transportUrl("wss://speaker/asr?model=A%2FB").equals("wss://speaker/asr?model=A%2FB&audio_format=pcm_s16le"));
        check(AsrAudio.transportUrl("ws://speaker/asr?%61udio_format=float32&model=A").equals("ws://speaker/asr?model=A&audio_format=pcm_s16le"));
        check(AsrAudio.transportUrl("ws://speaker:16066").equals("ws://speaker:16066"));
        check(AsrAudio.transportUrl("ws://speaker/asr-other").equals("ws://speaker/asr-other"));
        byte[] stereo={0,(byte)128,1,0,(byte)255,127,2,0};
        byte[] mono=AsrAudio.mono(stereo,stereo.length,2);
        check(Arrays.equals(mono,new byte[]{0,(byte)128,(byte)255,127}));
        byte[] copied=AsrAudio.mono(mono,mono.length,1);check(copied!=mono&&Arrays.equals(copied,mono));
        ByteBuffer floats=ByteBuffer.wrap(AsrAudio.floats(mono)).order(ByteOrder.LITTLE_ENDIAN);
        check(floats.getFloat()==-1.0f&&floats.getFloat()==32767/32768.0f);
        for(int count:new int[]{-1,1,2,10}){
            boolean rejected=false;try{AsrAudio.mono(stereo,count,2);}catch(IllegalArgumentException e){rejected=true;}
            check(rejected);
        }
        System.out.println("9 PCM16/local-float transport cases passed");
    }
}
