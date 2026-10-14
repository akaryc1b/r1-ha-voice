"""编译实际生成的 Java 分类器，与 Python 同源实现逐项比较。"""
import argparse
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'gateway'), str(ROOT / 'tests'), str(ROOT / 'tests/ai_stream')]
import intent_rules as rules
from test_intent_rules import CASES
from java_test_support import java_tools, json_dependency
from generate_intent_rules import generate

RUNNER = '''import org.json.*;import java.io.*;import java.nio.charset.StandardCharsets;
import java.util.Base64;import r1.local.asr.SharedIntentRules;
public class IntentParity {
 public static void main(String[] args)throws Exception {
  BufferedReader input=new BufferedReader(new InputStreamReader(System.in,StandardCharsets.UTF_8));String row;
  while((row=input.readLine())!=null) {
   String text=new String(Base64.getDecoder().decode(row),StandardCharsets.UTF_8);
   JSONObject out=new JSONObject();out.put("normalize",SharedIntentRules.normalize(text));
   out.put("music",SharedIntentRules.isMusicCandidate(text));out.put("explanation",SharedIntentRules.isExplanationQuestion(text));
   out.put("control",SharedIntentRules.isControlRequest(text));out.put("home",SharedIntentRules.isHomeRequest(text));
   out.put("fast",SharedIntentRules.isFastControl(text));out.put("incomplete",SharedIntentRules.isIncompleteTranscription(text));
   String operation=SharedIntentRules.matchMusicOperation(text);out.put("operation",operation==null?JSONObject.NULL:operation);
   System.out.println(out.toString());
  }
 }
}'''


def main():
    import os
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java-home', type=Path)
    args = parser.parse_args()
    texts = list(dict.fromkeys([text for text, _ in CASES] + list(rules.COMMANDS)))
    with tempfile.TemporaryDirectory(prefix='r1-intent-parity-') as work_name:
        work = Path(work_name)
        source = work / 'r1/local/asr/SharedIntentRules.java'
        source.parent.mkdir(parents=True)
        source.write_bytes(generate(ROOT / 'gateway/intent-rules.json', ROOT / 'gateway/music-commands.json').encode('utf-8'))
        runner = work / 'IntentParity.java'
        runner.write_bytes(RUNNER.encode('utf-8'))
        jar = json_dependency(work)
        java, javac = java_tools(args.java_home)
        subprocess.run([javac, '-encoding', 'UTF-8', '--release', '11', '-cp', str(jar), '-d', str(work), str(source), str(runner)], check=True)
        result = subprocess.run([java, '-Dfile.encoding=UTF-8', '-cp', os.pathsep.join([str(work), str(jar)]), 'IntentParity'],
                                input=''.join(base64.b64encode(text.encode('utf-8')).decode() + '\n' for text in texts),
                                capture_output=True, text=True, encoding='utf-8', check=True, timeout=60)
        rows = result.stdout.splitlines()
        assert len(rows) == len(texts)
        for text, row in zip(texts, rows):
            expected = {'normalize': rules.normalize(text), 'music': bool(rules.is_music_candidate(text)),
                        'explanation': bool(rules.is_explanation_question(text)), 'control': bool(rules.is_control_request(text)),
                        'home': bool(rules.is_home_request(text)), 'fast': bool(rules.is_fast_control(text)),
                        'incomplete': bool(rules.is_incomplete_transcription(text)), 'operation': rules.match_music_operation(text)}
            assert json.loads(row) == expected, (text, json.loads(row), expected)
    print(json.dumps({'parity_cases': len(texts), 'fields_per_case': 8, 'passed': True}))


if __name__ == '__main__':
    main()
