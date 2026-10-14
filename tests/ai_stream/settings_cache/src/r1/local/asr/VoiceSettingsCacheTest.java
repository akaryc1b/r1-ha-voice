package r1.local.asr;
import java.io.*;
import java.nio.file.*;
import org.json.JSONObject;

public class VoiceSettingsCacheTest {
    static class Clock implements VoiceSettingsCache.Clock {long now;public long millis(){return now;}}
    static class FileStats extends File {
        int stats;long stamp;
        FileStats(Path path){super(path.toString());}
        public long lastModified(){stats++;return stamp;}
    }
    static void check(boolean ok){if(!ok)throw new AssertionError();}
    public static void main(String[] args)throws Exception{
        Path dir=Files.createTempDirectory("r1-settings-test-");
        FileStats file=new FileStats(dir.resolve("config.json"));Clock clock=new Clock();
        Files.write(file.toPath(),new JSONObject().put("nested",new JSONObject().put("enabled",true)).put("value",1).toString().getBytes("UTF-8"));
        VoiceSettingsCache cache=new VoiceSettingsCache(file,clock,1000,30000);
        JSONObject first=cache.read();first.getJSONObject("nested").put("enabled",false);
        check(cache.read().getJSONObject("nested").getBoolean("enabled"));
        int stats=file.stats;cache.read();check(file.stats==stats);
        int parses=cache.parseCount(),loads=cache.loadCount();
        for(int i=0;i<100;i++){check(cache.getInt("value",0)==1);cache.getString("absent","fallback");cache.getBoolean("absent",false);}
        check(cache.parseCount()==parses&&cache.loadCount()==loads&&file.stats==stats);
        System.out.println("PASS defensive nested snapshot and no repeated stat within TTL");

        JSONObject next=cache.read().put("value",2);
        boolean rejected=false;
        try{cache.write(next,snapshot->{throw new IOException("test write failure");});}
        catch(IOException error){rejected=true;}
        check(rejected&&cache.read().getInt("value")==1);
        System.out.println("PASS failed atomic writer cannot publish new cache");

        cache.write(next,snapshot->Files.write(file.toPath(),snapshot.getBytes("UTF-8")));
        next.put("value",99);check(cache.read().getInt("value")==2);
        System.out.println("PASS successful writes publish immutable snapshot");

        Files.write(file.toPath(),new JSONObject().put("value",3).toString().getBytes("UTF-8"));file.stamp++;clock.now=1001;
        check(cache.read().getInt("value")==3);
        System.out.println("PASS ADB external edit reloads after metadata TTL");

        Files.write(file.toPath(),new JSONObject().put("value",4).toString().getBytes("UTF-8"));clock.now=2002;
        check(cache.read().getInt("value")==3);clock.now=31002;
        check(cache.read().getInt("value")==4);
        System.out.println("PASS same-size coarse-mtime edit eventually reloads");

        Files.write(file.toPath(),"{invalid".getBytes("UTF-8"));file.stamp++;clock.now=32003;
        check(cache.read().getInt("value")==4);stats=file.stats;loads=cache.loadCount();
        for(int i=0;i<100;i++)check(cache.getInt("value",0)==4);
        check(file.stats==stats&&cache.loadCount()==loads);
        Files.write(file.toPath(),new JSONObject().put("value",5).toString().getBytes("UTF-8"));file.stamp++;clock.now=33004;
        check(cache.read().getInt("value")==5);
        System.out.println("PASS invalid refresh retains valid snapshot, throttles retries and recovers");

        Files.delete(file.toPath());clock.now+=1001;
        check(cache.getInt("value",0)==5);
        Files.write(file.toPath(),new byte[16385]);clock.now+=1001;
        check(cache.getInt("value",0)==5);
        Files.write(file.toPath(),new JSONObject().put("value",7).toString().getBytes("UTF-8"));clock.now+=1001;
        check(cache.getInt("value",0)==7);
        System.out.println("PASS disappearing or oversized file cannot discard last valid settings");

        FileStats invalid=new FileStats(dir.resolve("invalid.json"));
        Files.write(invalid.toPath(),"{invalid".getBytes("UTF-8"));
        VoiceSettingsCache cold=new VoiceSettingsCache(invalid,clock,1000,30000);
        for(int i=0;i<2;i++){
            rejected=false;
            try{cold.read();}catch(IOException error){rejected=error.getCause()!=null;}
            check(rejected);
        }
        Files.write(invalid.toPath(),new JSONObject().put("value",8).toString().getBytes("UTF-8"));clock.now+=1001;
        check(cold.getInt("value",0)==8);
        System.out.println("PASS cold failure preserves original cause and subsequently recovers");

        FileStats missing=new FileStats(dir.resolve("missing.json"));
        VoiceSettingsCache absent=new VoiceSettingsCache(missing,clock,1000,30000);
        check(absent.read().length()==0);
        Files.write(missing.toPath(),new JSONObject().put("value",6).toString().getBytes("UTF-8"));missing.stamp++;clock.now+=1001;
        check(absent.read().getInt("value")==6);
        System.out.println("PASS initially missing file can appear later");

        Files.delete(file.toPath());Files.delete(missing.toPath());Files.delete(invalid.toPath());Files.delete(dir);
        System.out.println("9 settings cache lifecycle tests passed");
    }
}
