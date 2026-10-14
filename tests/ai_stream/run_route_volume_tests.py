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

        compiled=compile_suite(work,'route_volume/src',['r1/local/asr/SpeechRouteVolume.java'],args.java_home,dependencies,extra)
        for name in ['RouteVolumeTest']:run_main(compiled,name,35)

if __name__=="__main__":main()
