"""运行隔离 JVM suite；不访问设备或生产服务。"""
from pathlib import Path
import argparse
import tempfile
from java_test_support import compile_suite,json_dependency,run_main,ROOT

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--java-home",type=Path,help="JDK 11 or later")
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="r1-jvm-tests-") as temporary:
        work=Path(temporary)
        dependencies=[json_dependency(work)] if False else []
        extra=[]
        import re
        source=(ROOT/"device/src/r1/local/asr/LocalAsr.java").read_text(encoding="utf-8")
        method=re.search(r"(?s)    public static String normalize\(String text\) \{.*?\n    \}",source)
        if not method or method.group().count("{")!=1 or method.group().count("}")!=1:
            raise SystemExit("Normalize method changed; update isolated extraction")
        normalized=work/"NormalizeUnderTest.java"
        normalized.write_text("import r1.local.asr.SharedIntentRules; public final class NormalizeUnderTest {"+method.group()+"}",encoding="utf-8")
        extra=[normalized]
        compiled=compile_suite(work,'retry_once/src',['r1/local/asr/AsrRetryOnce.java'],args.java_home,dependencies,extra)
        for name in ['AsrRetryOnceTest', 'LocalAsrNormalizeTest']:run_main(compiled,name,35)

if __name__=="__main__":main()
