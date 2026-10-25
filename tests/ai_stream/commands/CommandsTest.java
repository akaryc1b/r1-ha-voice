import org.json.*;
import r1.local.asr.*;

/** 纯模拟 HA；不会执行真实电脑开关机。 */
public final class CommandsTest {
    static void check(boolean value){if(!value)throw new AssertionError();}
    static JSONObject batch()throws Exception{
        return new JSONObject("{handled:true,valid:true,steps:[{text:'暂停',route:'music'},{text:'音量调小',route:'ha'},{text:'打开电脑',route:'ha'}]}");
    }
    public static final class Home {
        int calls,failAt=-1,cancelAt=-1;boolean respond=true;
        public String processCommand(String text)throws Exception{
            check(VoiceCommands.process(this,text)==null);
            calls++;
            if(calls==cancelAt)VoiceSession.turn++;
            if(respond)VoiceCommands.haResponse(new JSONObject().put("response_type",calls==failAt?"error":"action_done"));
            return "已执行";
        }
    }
    public static void main(String[]args)throws Exception{
        Home home=new Home();
        check(VoiceCommands.process(home,"暂停")==null);
        VoiceCommands.offer(1,"组合",batch());
        check(VoiceCommands.hasPlan("组合"));
        check(VoiceCommands.process(home,"组合").contains("已执行"));check(home.calls==3);
        check(!VoiceCommands.hasPlan("组合"));
        home=new Home();home.failAt=2;VoiceCommands.offer(1,"组合",batch());
        check(VoiceCommands.process(home,"组合").contains("前1项已完成"));check(home.calls==2);
        home=new Home();home.respond=false;VoiceCommands.offer(1,"组合",batch());
        check(VoiceCommands.process(home,"组合").contains("第1项"));check(home.calls==1);
        home=new Home();home.cancelAt=1;VoiceCommands.offer(1,"组合",batch());
        check(VoiceCommands.process(home,"组合").equals(""));check(home.calls==1);
        VoiceCommands.offer(1,"组合",batch());check(!VoiceCommands.hasPlan("组合"));
        JSONObject bad=batch();bad.getJSONArray("steps").getJSONObject(2).put("route","unknown");
        home=new Home();VoiceCommands.offer(2,"坏计划",bad);
        check(VoiceCommands.process(home,"坏计划").contains("分开说"));check(home.calls==0);
        FollowupWindow window=new FollowupWindow();window.begin(1,2,false);window.recognized(1,10,100);
        check(window.responseEnded(2,20)==0);
        long ticket=window.responseEnded(1,20);check(ticket>0);
        check(window.responseEnded(1,21)==0);check(window.take(ticket,1,22));check(!window.take(ticket,1,23));
        window.begin(2,2,true);window.recognized(2,30,100);ticket=window.responseEnded(2,40);check(window.take(ticket,2,41));
        window.begin(3,2,true);window.recognized(3,50,100);check(window.responseEnded(3,60)==0);
        window.begin(4,1,false);window.recognized(4,70,10);check(window.responseEnded(4,80)==0);
        window.begin(5,1,false);window.recognized(5,90,100);ticket=window.responseEnded(5,100);
        window.cancel();check(!window.take(ticket,5,101));
        check(!FollowupWindow.listeningExpired(5900,6000,false));
        check(FollowupWindow.listeningExpired(6000,6000,false));
        check(!FollowupWindow.listeningExpired(6100,6000,true));
        System.out.println("Compound order, structured failure, cancellation, plan consumption and followup bounds passed");
    }
}
