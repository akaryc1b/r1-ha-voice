import com.sun.net.httpserver.HttpServer;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import org.json.*;
import r1.local.asr.*;

public class StreamTest {
    static HttpServer server;
    static volatile int mode;
    static volatile boolean done;
    static final java.util.concurrent.atomic.AtomicInteger requests=new java.util.concurrent.atomic.AtomicInteger();
    static final List<String> results = new ArrayList<String>();
    public static class Config {
        public String getBaseUrl(){return "http://127.0.0.1:"+server.getAddress().getPort();}
        public String getApiKey(){return "test-key-only";}
    }
    public static class Client {
        private final Config config=new Config();
        int fallback;
        private String buildRequestBody(String q,String h,String p){return new JSONObject().put("messages",new JSONArray()).toString();}
        public String chatWithHistory(String q,String h,String p){fallback++;return "同步回退回答。";}
    }
    public static class Chat {
        public com.unisound.vui.engine.ANTHandlerContext ctx;
        public final List<String> spoken=Collections.synchronizedList(new ArrayList<String>());
        public int ends;
        public boolean early;
        public void playTTS(String s){spoken.add(s);if(!done)early=true;android.os.Handler.LOOP.schedule(new Runnable(){public void run(){onTTSEventPlayingEnd(ctx);}},40,TimeUnit.MILLISECONDS);}
        public boolean onTTSEventPlayingEnd(com.unisound.vui.engine.ANTHandlerContext c){if(VoiceAiStream.onSpeechEnd(this))return true;ends++;return true;}
    }
    static void require(boolean b,String s){if(!b)throw new AssertionError(s);}
    static void sleep(long ms){try{Thread.sleep(ms);}catch(Exception e){throw new RuntimeException(e);}}
    static String event(String text){return "data: "+new JSONObject().put("choices",new JSONArray().put(new JSONObject().put("delta",new JSONObject().put("content",text)))).toString()+"\n\n";}
    static void send(OutputStream out,String s)throws Exception{for(byte b:s.getBytes(StandardCharsets.UTF_8)){out.write(new byte[]{b});out.flush();}}
    static void test(String name,Runnable test){VoiceSession.next();done=false;CloudVoiceSettings.enabled=true;CloudVoiceSettings.first=4500;CloudVoiceSettings.reply=8000;CloudVoiceSettings.answer=30000;requests.set(0);test.run();sleep(120);results.add(name);System.out.println("PASS "+name);}
    public static void main(String[] args)throws Exception{
        Thread.setDefaultUncaughtExceptionHandler((thread,error)->{error.printStackTrace();System.exit(1);});
        server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/chat/completions",exchange->{
            int selected=mode;
            try{
                JSONObject body=new JSONObject(new String(exchange.getRequestBody().readAllBytes(),StandardCharsets.UTF_8));
                requests.incrementAndGet();
                if(selected==2 && body.optBoolean("stream")){exchange.sendResponseHeaders(503,-1);return;}
                if(selected==3 || !body.optBoolean("stream")){exchange.getResponseHeaders().set("Content-Type","application/json");byte[] json="{\"choices\":[{\"message\":{\"content\":\"接口返回普通 JSON 也能正常播放。\"}}]}".getBytes(StandardCharsets.UTF_8);exchange.sendResponseHeaders(200,json.length);exchange.getResponseBody().write(json);done=true;return;}
                exchange.getResponseHeaders().set("Content-Type","text/event-stream");exchange.sendResponseHeaders(200,0);
                OutputStream out=exchange.getResponseBody();
                send(out,"data: {\"choices\":[{\"delta\":{\"reasoning_content\":\"不可朗读的思考内容\"}}]}\n\n");
                if(selected==5){sleep(1400);}
                if(selected==6){send(out,event("这是还没有完整句末的回答"));for(int i=0;i<16;i++){sleep(100);send(out,event("仍在继续"));}}
                if(selected==7){send(out,event("这是一句足够长且可以先播放的完整回答。"));for(int i=0;i<30;i++){sleep(100);send(out,event("还有正文"));}}
                send(out,event("彩虹是太阳光经过水滴折射和反射形成的。"));
                sleep(selected==4?500:180);
                if(selected==1){send(out,"data: {\"error\":{\"message\":\"private error\"}}\n\n");return;}
                send(out,event("不同颜色的光分散开来，就形成了彩色的圆弧。"));
                done=true;send(out,"data: [DONE]\n\n");
            }catch(Exception ignored){}finally{exchange.close();}
        });
        server.setExecutor(Executors.newCachedThreadPool());server.start();
        test("fragmented UTF-8 SSE, first sentence before DONE, ordered queue, reasoning excluded, single final completion",()->{
            mode=0;Client c=new Client();Chat h=new Chat();String answer=VoiceAiStream.chat(c,h,"question","",VoiceSession.turn);
            VoiceAiStream.playReply(h,answer,VoiceSession.turn);sleep(220);
            require(h.early,"first sentence streamed");require(c.fallback==0,"no fallback");require(h.spoken.size()==2,"no duplicate full reply "+h.spoken);
            require(answer.equals(String.join("",h.spoken)),"full answer preserved");require(!answer.contains("思考"),"reasoning ignored");require(h.ends==1,"session ends once "+h.ends);
        });
        test("failure before speech falls back once",()->{mode=2;Client c=new Client();Chat h=new Chat();String a=VoiceAiStream.chat(c,h,"q","",VoiceSession.turn);VoiceAiStream.playReply(h,a,VoiceSession.turn);sleep(100);require(c.fallback==0&&requests.get()==2,"one bounded fallback request");require(h.spoken.size()==1,"one synchronous reply");});
        test("failure after speech does not replay prefix",()->{mode=1;Client c=new Client();Chat h=new Chat();String a=VoiceAiStream.chat(c,h,"q","",VoiceSession.turn);VoiceAiStream.playReply(h,a,VoiceSession.turn);sleep(200);require(c.fallback==0,"no replay request");require(h.spoken.size()==2&&h.spoken.get(1).contains("中断"),"clear failure prompt");require(h.ends==1,"completion once");});
        test("provider JSON response is accepted without second request",()->{mode=3;Client c=new Client();Chat h=new Chat();String a=VoiceAiStream.chat(c,h,"q","",VoiceSession.turn);VoiceAiStream.playReply(h,a,VoiceSession.turn);sleep(100);require(c.fallback==0&&h.spoken.size()==1,"JSON handled once");});
        test("new voice turn cancels stale remainder and stale full reply",()->{mode=4;Client c=new Client();Chat h=new Chat();int turn=VoiceSession.turn;FutureTask<String> task=new FutureTask<String>(()->VoiceAiStream.chat(c,h,"q","",turn));new Thread(task).start();while(h.spoken.isEmpty())sleep(5);VoiceSession.next();try{String a=task.get(3,TimeUnit.SECONDS);require("".equals(a),"stale cancellation is non-failure and bypasses HA fallback");VoiceAiStream.playReply(h,a,turn);}catch(Exception e){throw new RuntimeException(e);}sleep(550);require(h.spoken.size()==1&&c.fallback==0,"stale continuation discarded");});
        test("disabled streaming preserves original synchronous path",()->{CloudVoiceSettings.enabled=false;Client c=new Client();Chat h=new Chat();String a=VoiceAiStream.chat(c,h,"q","",VoiceSession.turn);VoiceAiStream.playReply(h,a,VoiceSession.turn);sleep(100);require(c.fallback==0&&requests.get()==1&&h.spoken.size()==1,"off switch sends one bounded synchronous request");});
        test("first content absolute deadline and bounded synchronous fallback",()->{mode=5;CloudVoiceSettings.first=500;CloudVoiceSettings.reply=1800;CloudVoiceSettings.answer=3000;Client c=new Client();Chat h=new Chat();long st=System.nanoTime();String a=VoiceAiStream.chat(c,h,"q","",VoiceSession.turn);VoiceAiStream.playReply(h,a,VoiceSession.turn);sleep(120);require((System.nanoTime()-st)/1e6<1800,"first content bounded");require(requests.get()==2&&h.spoken.size()==1,"single fallback after deadline");});
        test("first content without a sentence remains bounded by first reply deadline",()->{mode=6;CloudVoiceSettings.first=500;CloudVoiceSettings.reply=900;CloudVoiceSettings.answer=3000;Client c=new Client();Chat h=new Chat();long st=System.nanoTime();String a=VoiceAiStream.chat(c,h,"q","",VoiceSession.turn);VoiceAiStream.playReply(h,a,VoiceSession.turn);sleep(120);require((System.nanoTime()-st)/1e6<1600,"first sentence bounded");require(h.spoken.size()==1&&h.spoken.get(0).contains("响应较慢"),"clear timeout prompt, no HA fallback");});
        test("answer total deadline after speech never restarts the request",()->{mode=7;CloudVoiceSettings.first=500;CloudVoiceSettings.reply=800;CloudVoiceSettings.answer=1000;Client c=new Client();Chat h=new Chat();long st=System.nanoTime();String a=VoiceAiStream.chat(c,h,"q","",VoiceSession.turn);VoiceAiStream.playReply(h,a,VoiceSession.turn);sleep(200);require((System.nanoTime()-st)/1e6<1700,"whole answer bounded");require(requests.get()==1&&h.spoken.size()==2&&h.spoken.get(1).contains("中断"),"late timeout without replay");});
        server.stop(0);System.out.println("TESTS "+results.size());System.exit(0);
    }
}
