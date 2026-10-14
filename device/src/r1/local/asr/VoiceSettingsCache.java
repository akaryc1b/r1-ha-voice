package r1.local.asr;

import java.io.*;
import org.json.JSONObject;

/** 持有不可变 JSON 快照；TTL 检查外部修改，成功落盘后才更新缓存。 */
final class VoiceSettingsCache {
    interface Clock { long millis(); }
    interface Writer { void write(String snapshot) throws Exception; }
    private final File file;
    private final Clock clock;
    private final long checkMillis;
    private final long reloadMillis;
    private String snapshot;
    private JSONObject parsed;
    private int parses;
    private int loads;
    private long checked;
    private long loaded;
    private long modified;
    private long length;
    private boolean failed;

    VoiceSettingsCache(File file) {
        this(file,new Clock(){public long millis(){return System.nanoTime()/1000000L;}},1000,30000);
    }

    VoiceSettingsCache(File file,Clock clock,long checkMillis,long reloadMillis) {
        this.file=file;this.clock=clock;this.checkMillis=checkMillis;this.reloadMillis=reloadMillis;
    }

    private void refresh() throws Exception {
        long now=clock.millis();
        if ((snapshot==null && !failed) || now-checked>=checkMillis) {
            checked=now;
            try {
                long currentModified=file.lastModified();
                long currentLength=file.isFile()?file.length():-1;
                if (snapshot==null || failed || currentModified!=modified || currentLength!=length ||
                        now-loaded>=reloadMillis) {
                    if (currentLength>16384) throw new IOException("Voice settings too large");
                    String candidate="{}";
                    if (currentLength>=0) {
                        FileInputStream input=new FileInputStream(file);
                        loads++;
                        try {
                            ByteArrayOutputStream data=new ByteArrayOutputStream();
                            byte[] block=new byte[1024];int count;
                            while((count=input.read(block))!=-1) {
                                if(data.size()+count>16384)throw new IOException("Voice settings too large");
                                data.write(block,0,count);
                            }
                            candidate=new String(data.toByteArray(),"UTF-8");
                        }finally{input.close();}
                    }
                    JSONObject candidateParsed=new JSONObject(candidate);parses++;
                    snapshot=candidate;modified=currentModified;length=currentLength;loaded=now;
                    parsed=candidateParsed;
                }
                failed=false;
            }catch(Exception error){failed=true;}
        }
        if (failed) throw new IOException("Voice settings reload failed");
    }

    synchronized JSONObject read() throws Exception {
        refresh();parses++;
        return new JSONObject(snapshot);
    }

    synchronized String getString(String key,String fallback) throws Exception {refresh();return parsed.optString(key,fallback);}
    synchronized boolean getBoolean(String key,boolean fallback) throws Exception {refresh();return parsed.optBoolean(key,fallback);}
    synchronized int getInt(String key,int fallback) throws Exception {refresh();return parsed.optInt(key,fallback);}
    synchronized long getLong(String key,long fallback) throws Exception {refresh();return parsed.optLong(key,fallback);}
    // 隔离性能测试使用计数，不暴露配置内容。
    synchronized int parseCount(){return parses;}
    synchronized int loadCount(){return loads;}

    synchronized void write(JSONObject settings,Writer writer) throws Exception {
        String candidate=settings.toString();
        JSONObject candidateParsed=new JSONObject(candidate);parses++;
        writer.write(candidate);
        // Writer 的原子提交成功以后才发布；不保留调用者的可变 JSONObject。
        snapshot=candidate;modified=file.lastModified();length=file.isFile()?file.length():-1;
        parsed=candidateParsed;
        checked=loaded=clock.millis();failed=false;
    }
}
