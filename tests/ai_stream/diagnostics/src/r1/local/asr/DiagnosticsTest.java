package r1.local.asr;

import com.sun.net.httpserver.HttpServer;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.json.*;

/** 用本机模拟网关检查设备日志边界；不连接音箱或真实模型。 */
public final class DiagnosticsTest {
    static volatile boolean enabled;
    static volatile String level="INFO";
    static volatile long generation;
    static volatile CountDownLatch hold;
    static final AtomicInteger requests=new AtomicInteger();
    static final List<JSONObject> entries=Collections.synchronizedList(new ArrayList<JSONObject>());
    static final ExecutorService executor=Executors.newCachedThreadPool();

    static void check(boolean okay,String message) { if (!okay) throw new AssertionError(message); }
    static JSONObject state() { return new JSONObject().put("enabled",enabled).put("level",level).put("generation",generation).put("status","ok"); }

    static JSONObject bridge(String method,String path,JSONObject payload) throws Exception {
        final ServerSocket server=new ServerSocket(0,1,InetAddress.getByName("127.0.0.1"));
        Thread handler=new Thread(() -> {
            try (Socket client=server.accept()) {
                BufferedReader reader=new BufferedReader(new InputStreamReader(client.getInputStream(),StandardCharsets.UTF_8));
                String[] line=reader.readLine().split(" ");
                check(VoiceDiagnostics.handle(client,line[1],reader,line[0]),"route not handled");
            } catch (Exception error) { throw new RuntimeException(error); }
        });
        handler.setDaemon(true);handler.start();
        try (Socket client=new Socket("127.0.0.1",server.getLocalPort())) {
            byte[] body=payload==null?new byte[0]:payload.toString().getBytes(StandardCharsets.UTF_8);
            String header=method+" "+path+" HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: "+body.length+"\r\n\r\n";
            client.getOutputStream().write(header.getBytes(StandardCharsets.UTF_8));client.getOutputStream().write(body);client.getOutputStream().flush();
            String response=new String(client.getInputStream().readAllBytes(),StandardCharsets.UTF_8);
            check(response.startsWith("HTTP/1.1 200"),response);
            return new JSONObject(response.substring(response.indexOf("\r\n\r\n")+4));
        } finally { server.close();handler.join(2000); }
    }

    static void waitFor(Callable<Boolean> predicate) throws Exception {
        long end=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
        while (!predicate.call() && System.nanoTime()<end) Thread.sleep(10);
        check(predicate.call(),"timed out waiting for local mock");
    }

    public static void main(String[] args) throws Exception {
        HttpServer server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.setExecutor(executor);
        server.createContext("/logs", exchange -> {
            JSONObject body=exchange.getRequestMethod().equals("POST")?
                    new JSONObject(new String(exchange.getRequestBody().readAllBytes(),StandardCharsets.UTF_8)):new JSONObject();
            JSONObject response=state();String path=exchange.getRequestURI().getPath();
            try {
                if (path.equals("/logs/config") && exchange.getRequestMethod().equals("POST")) {
                    boolean next=body.getBoolean("enabled");String severity=body.getString("level");
                    if (next!=enabled || !severity.equals(level)) generation++;
                    enabled=next;level=severity;response=state();
                } else if (path.equals("/logs/clear")) {
                    generation++;entries.clear();response=state().put("cleared",true);
                } else if (path.equals("/logs/events")) {
                    requests.incrementAndGet();CountDownLatch pending=hold;
                    if (pending!=null) pending.await(2,TimeUnit.SECONDS);
                    boolean stale=body.getLong("generation")!=generation;
                    JSONArray events=body.getJSONArray("events");
                    if (!stale && enabled) for (int i=0;i<events.length();i++) {
                        check(!events.getJSONObject(i).has("generation"),"internal epoch leaked into event");
                        entries.add(events.getJSONObject(i));
                    }
                    response=state().put("accepted",stale?0:events.length()).put("stale",stale);
                } else if (path.equals("/logs")) response.put("entries",new JSONArray(entries));
                byte[] bytes=response.toString().getBytes(StandardCharsets.UTF_8);
                exchange.sendResponseHeaders(200,bytes.length);exchange.getResponseBody().write(bytes);
            } catch (Exception error) { throw new RuntimeException(error); }
            finally { exchange.close(); }
        });
        server.start();CloudVoiceSettings.base="http://127.0.0.1:"+server.getAddress().getPort();
        try {
            VoiceDiagnostics.initialize();
            VoiceDiagnostics.record("INFO","ASR",7,"text","disabled sample");
            Thread.sleep(80);check(requests.get()==0,"disabled transport wrote logs");
            bridge("POST","/voice_logs_config",new JSONObject().put("enabled",true).put("level","INFO"));
            VoiceDiagnostics.record("DEBUG","ASR",7,"text","debug must be skipped");
            VoiceDiagnostics.record("INFO","ASR",7,"text","暂停","Authorization","private header");
            waitFor(() -> entries.size()==1);
            check(!entries.get(0).getJSONObject("fields").has("Authorization"),"unknown field retained");
            check(entries.get(0).getJSONObject("fields").getString("text").equals("暂停"),"Chinese text damaged");

            String jwt="eyJ"+"testheader.testpayload.testsignature";
            String secret="sk-"+"synthetic-fixture";
            VoiceDiagnostics.record("INFO","AI",7,"response","Bearer fake-token "+jwt+" "+secret+" https://example.invalid/private");
            waitFor(() -> entries.size()==2);
            String text=entries.get(1).getJSONObject("fields").getString("response");
            check(!text.contains(jwt) && !text.contains(secret) && !text.contains("fake-token") && !text.contains("example.invalid"),"credential or URL not redacted");

            hold=new CountDownLatch(1);final int before=requests.get();
            VoiceDiagnostics.record("INFO","ASR",7,"text","old before clear");
            waitFor(() -> requests.get()>before);
            Thread producer=new Thread(() -> VoiceDiagnostics.record("INFO","ASR",7,"text","queued before clear"));
            producer.start();producer.join(500);check(!producer.isAlive(),"record waited for blocked network");
            bridge("POST","/voice_logs_clear",new JSONObject());
            hold.countDown();hold=null;Thread.sleep(100);
            check(entries.isEmpty(),"old in-flight or queued records returned after clear");
            VoiceDiagnostics.record("INFO","ASR",7,"text","new after clear");
            waitFor(() -> entries.size()==1);
            check(entries.get(0).getJSONObject("fields").getString("text").equals("new after clear"),"new generation lost");

            VoiceDiagnostics.haStarted("播放国语流行");
            VoiceDiagnostics.haResponse(new JSONObject().put("response_type","error").put("data",new JSONObject().put("code","no_intent_match")));
            VoiceDiagnostics.haReturned(null);
            waitFor(() -> entries.size()==3);
            check(entries.get(2).getJSONObject("fields").getString("error_kind").equals("no_intent_match"),"HA failure summary lost");
            bridge("POST","/voice_logs_config",new JSONObject().put("enabled",false).put("level","WARN"));
            VoiceDiagnostics.initialize();int disabledBefore=requests.get();
            VoiceDiagnostics.record("ERROR","ASR",7,"text","disabled again");Thread.sleep(80);
            check(requests.get()==disabledBefore,"saved disabled state not restored");
            check(bridge("GET","/voice_logs?limit=50",null).getJSONArray("entries").length()==3,"disable removed history");
            System.out.println("PASS: disabled storage, severity/field filter, redaction, nonblocking transport, generation-safe clear, HA result and saved configuration");
        } finally { if (hold!=null) hold.countDown();server.stop(0);executor.shutdownNow(); }
    }
}
