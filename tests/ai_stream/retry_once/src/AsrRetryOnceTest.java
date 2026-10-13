import r1.local.asr.AsrRetryOnce;

public final class AsrRetryOnceTest {
    static int passed;
    static void check(boolean value) { if (!value) throw new AssertionError(); }
    static AsrRetryOnce ready() {
        AsrRetryOnce retry=new AsrRetryOnce();retry.newTurn(1);return retry;
    }
    static long prompt(AsrRetryOnce retry) {
        long ticket=retry.arm(1,true,true,0);
        check(ticket!=0);retry.speechRequested(AsrRetryOnce.PROMPT,1);
        check(retry.speechEvent(2106,1,2)==0);
        return ticket;
    }
    static void pass(String name) { passed++;System.out.println("PASS "+name); }
    public static void main(String[] args) {
        AsrRetryOnce retry=ready();long ticket=prompt(retry);
        check(retry.speechEvent(2107,1,100)==ticket);check(retry.take(ticket,1,101));
        check(retry.arm(1,true,true,200)==0);pass("one retry after completed prompt, no third listening");

        retry=ready();ticket=retry.arm(1,true,true,0);
        check(retry.speechEvent(2107,1,1)==0);check(!retry.take(ticket,1,2));
        retry.speechRequested(AsrRetryOnce.PROMPT,3);
        check(retry.speechEvent(2107,1,4)==0);pass("completion before prompt PLAYING cannot start recording");

        retry=ready();ticket=prompt(retry);retry.newTurn(2);
        check(retry.speechEvent(2107,1,50)==0);check(!retry.take(ticket,2,51));
        check(retry.arm(2,true,true,60)!=0);pass("new wakeup cancels old turn and restores one retry budget");

        retry=ready();ticket=prompt(retry);retry.speechRequested("别的回答",20);
        check(retry.speechEvent(2107,1,50)==0);check(!retry.take(ticket,1,51));
        pass("unrelated TTS and AI segments cancel the expected prompt");

        retry=ready();ticket=prompt(retry);retry.speechEvent(2111,1,20);
        check(retry.speechEvent(2107,1,50)==0);check(!retry.take(ticket,1,51));pass("TTS cancellation prevents retry");

        retry=ready();ticket=prompt(retry);retry.cancel();
        check(retry.speechEvent(2107,1,50)==0);pass("TTS error prevents retry");

        retry=ready();ticket=prompt(retry);
        check(retry.expire(ticket,AsrRetryOnce.PROMPT_TIMEOUT_MS));
        check(retry.speechEvent(2107,1,AsrRetryOnce.PROMPT_TIMEOUT_MS+1)==0);
        pass("missing completion expires without timer-triggered recording");

        retry=ready();check(retry.arm(1,false,true,0)==0);check(retry.arm(1,true,false,0)==0);
        check(retry.arm(0,true,true,0)==0);pass("disabled, network error and stale result do not arm");

        retry=ready();ticket=prompt(retry);check(retry.speechEvent(2107,1,100)==ticket);
        check(retry.speechEvent(2107,1,101)==0);check(retry.take(ticket,1,102));
        check(!retry.take(ticket,1,103));pass("duplicate complete and queued callbacks start once");

        retry=ready();ticket=prompt(retry);check(retry.speechEvent(2107,1,100)==ticket);
        retry.newTurn(2);long newer=retry.arm(2,true,true,110);
        retry.cancel(ticket);check(!retry.expire(ticket,12000));
        retry.speechRequested(AsrRetryOnce.PROMPT,111);retry.speechEvent(2106,2,112);
        check(retry.speechEvent(2107,2,113)==newer);check(retry.take(newer,2,114));
        pass("stale cleanup cannot cancel newer pending prompt");

        retry=ready();ticket=prompt(retry);retry.speechEvent(2107,1,100);
        check(!retry.take(ticket,1,AsrRetryOnce.PROMPT_TIMEOUT_MS));
        pass("delayed main-loop callback respects absolute deadline");

        retry=ready();ticket=retry.arm(1,true,true,0);
        retry.speechRequested(AsrRetryOnce.PROMPT,AsrRetryOnce.PROMPT_TIMEOUT_MS);
        check(retry.speechEvent(2106,1,13000)==0);check(!retry.take(ticket,1,13001));
        pass("expired synthesis never resumes listening");
        System.out.println(passed+" lifecycle tests passed");
    }
}
