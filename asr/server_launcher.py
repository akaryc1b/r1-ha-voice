"""仅为该进程清除 OpenWrt 的 musl 日志预加载库。"""
import os,pathlib,sys
root=pathlib.Path(__file__).resolve().parent
runtime=root/"runtime"
environment=os.environ.copy()
environment.pop("LD_PRELOAD",None)
command=[str(runtime/"compat/ld-linux-aarch64.so.1"),"--library-path",str(runtime)+":"+str(runtime/"compat"),str(runtime/"sherpa-onnx-online-websocket-server")]+sys.argv[1:]
os.execve(command[0],command,environment)
