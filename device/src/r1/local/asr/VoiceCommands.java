package r1.local.asr;

import java.lang.reflect.Method;
import org.json.JSONArray;
import org.json.JSONObject;

/** 网关规划，复用已有 HA 实例顺序执行；结果必须由结构化 HA 响应确认。 */
public final class VoiceCommands {
    private static int planTurn;
    private static String planText;
    private static JSONObject plan;
    private static final ThreadLocal<Step> STEP=new ThreadLocal<Step>();
    private static final class Step {boolean confirmed;}
    private VoiceCommands() {}

    public static synchronized void offer(int turn,String text,JSONObject value) {
        if(!VoiceSession.isCurrent(turn))return;
        planTurn=turn;planText=text;plan=value;
    }

    public static synchronized boolean hasPlan(String text) {
        return plan!=null && VoiceSession.isCurrent(planTurn) && text!=null &&
                text.equals(planText) && plan.optBoolean("handled",false);
    }

    private static synchronized JSONObject take(String text) {
        if(!hasPlan(text))return null;
        JSONObject value=plan;plan=null;return value;
    }

    public static void haResponse(JSONObject response) {
        Step step=STEP.get();
        if(step==null || response==null)return;
        String type=response.optString("response_type","");
        step.confirmed="action_done".equals(type)||"query_answer".equals(type);
    }

    /** null 表示普通单指令，继续执行原有方法。 */
    public static String process(Object homeAssistant,String text) {
        if(STEP.get()!=null)return null;
        JSONObject batch=take(text);
        if(batch==null)return null;
        int turn=VoiceSession.currentTurn();
        JSONArray steps=batch.optJSONArray("steps");
        if(!batch.optBoolean("valid",false) || steps==null || steps.length()<2 || steps.length()>6)
            return "这句话里的操作还不能完整确认，请分开说。";
        // 执行之前验证整个计划，拒绝缺项或未识别的步骤。
        for(int i=0;i<steps.length();i++) {
            JSONObject item=steps.optJSONObject(i);
            if(item==null || item.optString("text","").length()==0 ||
                    !("music".equals(item.optString("route"))||"ha".equals(item.optString("route"))))
                return "这句话里的操作还不能完整确认，请分开说。";
        }
        StringBuilder replies=new StringBuilder();
        int completed=0;
        try {
            Method execute=homeAssistant.getClass().getMethod("processCommand",String.class);
            for(int i=0;i<steps.length();i++) {
                if(!VoiceSession.isCurrent(turn))return "";
                Step step=new Step();STEP.set(step);
                String answer;
                try {answer=(String)execute.invoke(homeAssistant,steps.optJSONObject(i).optString("text"));}
                finally {STEP.remove();}
                if(!VoiceSession.isCurrent(turn))return "";
                if(!step.confirmed) {
                    VoiceFollowup.cancelTurn(turn);
                    return "第"+(i+1)+"项操作没有确认成功，后面的操作已停止。"+
                            (completed>0?"前"+completed+"项已完成。":"");
                }
                completed++;
                if(answer!=null && answer.length()>0) {
                    if(replies.length()>0)replies.append("；");
                    replies.append(answer.substring(0,Math.min(240,answer.length())));
                }
            }
            return replies.length()>0?replies.toString():"已完成这"+completed+"项操作。";
        }catch(Exception error) {
            VoiceFollowup.cancelTurn(turn);
            return "组合操作中断，后面的操作已停止。"+(completed>0?"前"+completed+"项已完成。":"");
        }finally {STEP.remove();}
    }
}
