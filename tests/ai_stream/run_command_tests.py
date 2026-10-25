"""组合指令与有界续听 JVM 测试；不连接音箱。"""
import argparse
from pathlib import Path
import tempfile
from java_test_support import compile_suite,run_main,HERE

parser=argparse.ArgumentParser()
parser.add_argument('--java-home',type=Path)
args=parser.parse_args()
with tempfile.TemporaryDirectory(prefix='r1-command-tests-') as directory:
    compiled=compile_suite(Path(directory),'commands',[
        'r1/local/asr/VoiceCommands.java','r1/local/asr/FollowupWindow.java'],args.java_home)
    run_main(compiled,'CommandsTest')
with tempfile.TemporaryDirectory(prefix='r1-followup-event-tests-') as directory:
    compiled=compile_suite(Path(directory),'followup',[
        'r1/local/asr/VoiceFollowup.java','r1/local/asr/FollowupWindow.java',
        'r1/local/asr/AsrRetryOnce.java'],args.java_home,
        extra=[HERE/'commands/VoiceSession.java'])
    run_main(compiled,'FollowupEventsTest',20)
