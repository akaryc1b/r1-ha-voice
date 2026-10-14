"""将唯一的意图规则与 HA 生成命令表编入 Android；不手写第二套规则。"""
import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TEMPLATE = r'''package r1.local.asr;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Pattern;
import java.util.regex.Matcher;
import org.json.JSONObject;
import org.json.JSONArray;

/** 由 tools/generate_intent_rules.py 生成，请修改 gateway/intent-rules.json。 */
public final class SharedIntentRules {
    public static final String SOURCE_SHA256 = "@SHA@";
    private static final JSONObject R;
    private static final JSONObject COMMANDS;
    private static final ConcurrentHashMap<String,Pattern> PATTERNS = new ConcurrentHashMap<String,Pattern>();
    static {
        try { R=new JSONObject(@RULES@); COMMANDS=new JSONObject(@COMMANDS@); }
        catch(Exception error) { throw new ExceptionInInitializerError(error); }
    }
    private SharedIntentRules() {}
    private static Pattern pattern(String expression) {
        Pattern old=PATTERNS.get(expression);
        if(old!=null)return old;
        Pattern created=Pattern.compile(expression);
        Pattern raced=PATTERNS.putIfAbsent(expression,created);
        return raced==null?created:raced;
    }
    private static String rule(String key) { return R.optString(key,""); }
    private static boolean matches(String expression,String text) { return pattern(expression).matcher(text).matches(); }
    private static String replace(String expression,String text,String value) { return pattern(expression).matcher(text).replaceAll(value); }
    private static String first(String expression,String text) { return pattern(expression).matcher(text).replaceFirst(""); }
    private static String trim(String text) { return replace(rule("trim_pattern"),text==null?"":text,""); }
    private static String stripPrefix(String text) { return first(rule("request_prefix"),text); }
    private static boolean any(JSONArray expressions,String text) {
        for(int i=0;i<expressions.length();i++)if(matches(expressions.optString(i),text))return true;
        return false;
    }
    private static int chineseNumber(String text) {
        JSONObject digits=R.optJSONObject("chinese_digits");
        if(text.equals("百")||text.equals("一百"))return 100;
        int at=text.indexOf('十');
        if(at>=0&&at==text.lastIndexOf('十')) {
            String left=text.substring(0,at),right=text.substring(at+1);
            int tens=left.length()==0?1:digits.optInt(left,-1);
            int units=right.length()==0?0:digits.optInt(right,-1);
            if(tens>0&&units>=0)return tens*10+units;
        }
        if(text.length()==0||text.length()>3)return -1;
        int number=0;
        for(int i=0;i<text.length();i++) {
            int digit=digits.optInt(text.substring(i,i+1),-1);
            if(digit<0)return -1;
            number=number*10+digit;
        }
        return number;
    }
    public static String normalize(String value) {
        String text=trim(value),compact=replace(rule("compact_pattern"),text,"");
        JSONArray compactRules=R.optJSONArray("compact_rewrites");
        for(int i=0;i<compactRules.length();i++) {
            JSONObject item=compactRules.optJSONObject(i);
            if(matches(item.optString("pattern"),compact))return item.optString("replacement");
        }
        JSONArray fullRules=R.optJSONArray("full_rewrites");
        for(int i=0;i<fullRules.length();i++) {
            JSONObject item=fullRules.optJSONObject(i);
            if(matches(item.optString("pattern"),text))return replace(item.optString("pattern"),text,item.optString("replacement"));
        }
        Matcher volume=pattern(rule("volume_number_pattern")).matcher(text);
        if(volume.matches()) {
            int number=chineseNumber(volume.group(2));
            if(number>=0&&number<=100)return volume.group(1)+number+volume.group(3);
        }
        if(pattern(rule("sensor_guard")).matcher(text).find()&&!pattern(rule("sensor_exclude")).matcher(text).find())
            return replace(rule("sensor_typo"),text,"温湿度");
        return text;
    }
    public static String matchMusicOperation(String text) {
        String clean=replace(rule("compact_pattern"),normalize(text),"");
        if(COMMANDS.has(clean))return COMMANDS.optString(clean);
        clean=first(rule("music_suffix"),stripPrefix(clean));
        return COMMANDS.has(clean)?COMMANDS.optString(clean):null;
    }
    public static boolean isExplanationQuestion(String value) {
        String text=trim(value);JSONArray patterns=R.optJSONArray("explanation_patterns");
        if(matches(patterns.optString(0),text))return false;
        if(matches(patterns.optString(1),text)||matches(patterns.optString(2),text))return true;
        return !matches(rule("control_prefix"),stripPrefix(text))&&
            (matches(patterns.optString(3),text)||matches(patterns.optString(4),text));
    }
    public static boolean isMusicCandidate(String text) {
        return text!=null&&text.length()>0&&!isExplanationQuestion(text)&&matches(rule("music_candidate"),stripPrefix(trim(text)));
    }
    public static boolean isControlRequest(String text) {
        return text!=null&&text.length()>0&&!isExplanationQuestion(text)&&
            (isMusicCandidate(text)||any(R.optJSONArray("control_patterns"),stripPrefix(trim(text))));
    }
    public static boolean isHomeRequest(String text) {
        return text!=null&&text.length()>0&&!isExplanationQuestion(text)&&
            (isControlRequest(text)||matches(rule("home_keywords"),text));
    }
    public static boolean isFastControl(String value) {
        String text=first(rule("fast_suffix"),first(rule("fast_prefix"),trim(value)));
        if(matchMusicOperation(value)!=null)return true;
        JSONArray exact=R.optJSONArray("fast_exact");
        for(int i=0;i<exact.length();i++)if(text.equals(exact.optString(i)))return true;
        return any(R.optJSONArray("fast_patterns"),text);
    }
    public static boolean isIncompleteTranscription(String value) {
        if(matchMusicOperation(value)!=null)return false;
        String text=first(rule("incomplete_prefix"),trim(value));
        if(text.length()==0)return true;
        JSONArray exact=R.optJSONArray("incomplete_exact");
        for(int i=0;i<exact.length();i++)if(text.equals(exact.optString(i)))return true;
        return matches(rule("incomplete_pattern"),text);
    }
}
'''


def generate(rules_path, commands_path):
    raw = rules_path.read_bytes()
    commands_raw = commands_path.read_bytes()
    rules = json.loads(raw)
    if rules.get('schema_version') != 1:
        raise ValueError('Unsupported intent rule schema')
    rules = copy.deepcopy(rules)
    for item in rules['full_rewrites']:
        item['replacement'] = re.sub(r'\\([1-9])', r'$\1', item['replacement'])
    values = [json.dumps(rules, ensure_ascii=False, separators=(',', ':')),
              json.dumps(json.loads(commands_raw), ensure_ascii=False, separators=(',', ':'))]
    if any(len(value.encode('utf-8')) > 60000 for value in values):
        raise ValueError('Java string constant exceeds limit')
    source = TEMPLATE.replace('@SHA@', hashlib.sha256(raw + commands_raw).hexdigest())
    return source.replace('@RULES@', json.dumps(values[0])).replace('@COMMANDS@', json.dumps(values[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rules', type=Path, default=ROOT / 'gateway/intent-rules.json')
    parser.add_argument('--commands', type=Path, default=ROOT / 'gateway/music-commands.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'device/src/r1/local/asr/SharedIntentRules.java')
    args = parser.parse_args()
    source = generate(args.rules, args.commands)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(source.encode('utf-8'))


if __name__ == '__main__':
    main()
