"""仅临时文件、模拟下载和自建子进程；不访问设备、容器或云端 API。"""
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(REPO/'gateway'))
import assets
import configuration
import entrypoint
import healthcheck
from gateway_config import GatewayConfig,DEFAULTS,SECRETS


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)

    def tearDown(self):self.temp.cleanup()

    def model_manifest(self):
        return [{'name':name,'sha256':hashlib.sha256(name.encode()).hexdigest(),
                 'url':'https://example.invalid/'+name} for name in assets.MODEL_NAMES]

    def test_both_architectures_have_fixed_official_runtime_hashes(self):
        entries=assets.manifest(REPO/'asr/sources.json')
        runtime={e['architecture']:e for e in entries if 'architecture' in e}
        self.assertEqual(set(runtime),{'amd64','arm64'})
        for entry in runtime.values():
            self.assertIn('/v1.13.8/',entry['url']);self.assertEqual(len(entry['sha256']),64)
        self.assertEqual(runtime['amd64']['sha256'],'c0bdb7907d3a74bba1d55d22bf4d9fa75586cf1530614ebe88a27b9118e015c4')

    def test_missing_models_fail_without_network_access(self):
        with patch('assets.urllib.request.urlopen') as network:
            with self.assertRaisesRegex(ValueError,'bootstrap'):
                assets.verify_models(self.model_manifest(),self.root)
            network.assert_not_called()

    def test_explicit_bootstrap_checks_download_and_skips_verified_files(self):
        class Response(io.BytesIO):
            def geturl(self):return 'https://example.invalid/file'
        def fetch(request,timeout):return Response(request.full_url.rsplit('/',1)[-1].encode())
        with patch('assets.urllib.request.urlopen',side_effect=fetch) as network:
            assets.bootstrap(self.model_manifest(),self.root)
            self.assertEqual(network.call_count,4)
            assets.bootstrap(self.model_manifest(),self.root)
            self.assertEqual(network.call_count,4)
        assets.verify_models(self.model_manifest(),self.root)

    def test_bad_download_does_not_replace_previous_file(self):
        entry=self.model_manifest()[0];target=self.root/entry['name'];target.write_bytes(b'previous')
        response=io.BytesIO(b'wrong');response.geturl=lambda:'https://example.invalid/file'
        with patch('assets.urllib.request.urlopen',return_value=response):
            with self.assertRaises(ValueError):assets.download(entry,target)
        self.assertEqual(target.read_bytes(),b'previous')
        self.assertFalse(target.with_name(target.name+'.part').exists())

    def archive(self,members):
        archive=self.root/'test.tar.bz2'
        with tarfile.open(archive,'w:bz2') as output:
            for name,kind,value in members:
                info=tarfile.TarInfo(name)
                if kind=='file':info.size=len(value);info.mode=0o755;output.addfile(info,io.BytesIO(value))
                else:info.type=tarfile.SYMTYPE;info.linkname=value;output.addfile(info)
        return archive

    def test_archive_path_and_link_escape_rejected(self):
        for name in ('../outside','/outside','..\\outside'):
            with self.assertRaises(ValueError):
                assets.extract_runtime(self.archive([(name,'file',b'bad')]),self.root/'extract')
        with self.assertRaises(ValueError):
            assets.extract_runtime(self.archive([('lib/link','link','../../outside')]),self.root/'extract')
        self.assertFalse((self.root/'outside').exists())

    def test_plain_archive_keeps_binary_executable(self):
        archive=self.archive([('release/bin/server','file',b'ELF')])
        assets.extract_runtime(archive,self.root/'extract')
        self.assertEqual((self.root/'extract/release/bin/server').read_bytes(),b'ELF')

    @unittest.skipUnless(os.name=='posix','运行时 so 链接需要 Linux 文件系统验证')
    def test_archive_library_symlink_chain_is_order_independent(self):
        archive=self.archive([('release/lib/library.so','link','library.so.1'),
            ('release/lib/library.so.1','link','library.so.1.2'),
            ('release/lib/library.so.1.2','file',b'ELF')])
        assets.extract_runtime(archive,self.root/'extract')
        self.assertEqual((self.root/'extract/release/lib/library.so').read_bytes(),b'ELF')

    def test_config_reuses_validation_and_persists_web_edits(self):
        state=self.root/'state'
        settings=configuration.prepare(REPO/'gateway',state,{'R1_ASR_MODEL':'custom/asr',
            'R1_ALLOWED_CLIENTS':'["127.0.0.1","192.0.2.1"]','R1_LOCAL_FIRST':'false'})
        self.assertEqual(settings.snapshot()['bind_host'],'0.0.0.0')
        self.assertEqual(settings.snapshot()['asr_model'],'custom/asr')
        self.assertFalse(settings.public()['restart_required'])
        settings.update({'tts_voice':'custom-saved-voice'})
        restarted=configuration.prepare(REPO/'gateway',state,{})
        self.assertEqual(restarted.snapshot()['tts_voice'],'custom-saved-voice')
        self.assertEqual(restarted.snapshot()['asr_model'],'custom/asr')
        before=restarted.path.read_bytes()
        with self.assertRaises(ValueError):configuration.prepare(REPO/'gateway',state,{'R1_BIND_PORT':'true'})
        self.assertEqual(restarted.path.read_bytes(),before)

    def test_secret_files_and_plain_secret_env_rejection(self):
        secret=self.root/'secret';secret.write_text('TEST_PRIVATE_SENTINEL\n',encoding='utf-8')
        settings=configuration.prepare(REPO/'gateway',self.root/'state',{'R1_ASR_API_KEY_FILE':str(secret)})
        self.assertTrue(settings.public()['asr_api_key_configured'])
        self.assertNotIn('TEST_PRIVATE_SENTINEL',json.dumps(settings.public()))
        with self.assertRaises(ValueError) as caught:
            configuration.prepare(REPO/'gateway',self.root/'state',{'R1_ASR_API_KEY':'TEST_PRIVATE_SENTINEL'})
        self.assertNotIn('TEST_PRIVATE_SENTINEL',str(caught.exception))
        secret.write_text('x'*4097)
        with self.assertRaises(ValueError):configuration.prepare(REPO/'gateway',self.root/'state',{'R1_MA_TOKEN_FILE':str(secret)})

    def test_all_non_secret_default_fields_can_be_overridden(self):
        # 动态遍历 DEFAULTS；新增网关非秘密字段不需要在入口复制字段表。
        environment={}
        for key,value in DEFAULTS.items():
            if key not in SECRETS:environment['R1_'+key.upper()]=value if isinstance(value,str) else json.dumps(value)
        settings=configuration.prepare(REPO/'gateway',self.root/'state',environment)
        for key in set(DEFAULTS)-SECRETS:self.assertEqual(settings.snapshot()[key],DEFAULTS[key])

    def test_asr_args_keep_current_endpointing_and_no_host_loader(self):
        args=entrypoint.asr_command(self.root)
        self.assertIn('--rule2-min-trailing-silence=1.3',args)
        self.assertIn('--port=16066',args)
        self.assertFalse(any('compat' in arg or 'ld-linux' in arg for arg in args))

    def test_supervisor_stops_other_child_if_one_exits(self):
        children=[]
        real_popen=subprocess.Popen
        def spawn(*args,**kwargs):
            child=real_popen(*args,**kwargs);children.append(child);return child
        with patch('entrypoint.subprocess.Popen',side_effect=spawn):
            result=entrypoint.supervise([[sys.executable,'-c','import time;time.sleep(30)'],
                [sys.executable,'-c','raise SystemExit(7)']],ready=lambda:True)
        self.assertEqual(result,1);self.assertEqual(len(children),2)
        self.assertTrue(all(child.poll() is not None for child in children))

    def test_supervisor_terminates_early_exit_and_readiness_timeout(self):
        with self.assertRaises(RuntimeError):
            entrypoint.supervise([[sys.executable,'-c','raise SystemExit(3)']],ready=lambda:False,start_timeout=.3)
        with self.assertRaises(RuntimeError):
            entrypoint.supervise([[sys.executable,'-c','import time;time.sleep(30)']],ready=lambda:False,start_timeout=.1)

    def test_supervisor_stop_handler_cleans_both_children(self):
        handlers={};children=[];real_popen=subprocess.Popen
        def signal_handler(signum,handler):handlers[signum]=handler
        def spawn(*args,**kwargs):
            child=real_popen(*args,**kwargs);children.append(child);return child
        def ready(group):handlers[signal.SIGTERM](signal.SIGTERM,None)
        with patch('entrypoint.signal.signal',side_effect=signal_handler),patch('entrypoint.subprocess.Popen',side_effect=spawn):
            result=entrypoint.supervise([[sys.executable,'-c','import time;time.sleep(30)']]*2,
                ready=lambda:True,on_ready=ready)
        self.assertEqual(result,0);self.assertTrue(all(child.poll() is not None for child in children))

    def test_health_needs_both_processes_and_real_asr_protocol(self):
        state=self.root/'health.json'
        state.write_text(json.dumps({'asr_pid':50,'gateway_pid':51,'gateway_host':'0.0.0.0','gateway_port':16068}))
        with patch('healthcheck.process_alive',return_value=False),patch('healthcheck.websocket_ready') as ready:
            self.assertFalse(healthcheck.healthy(state));ready.assert_not_called()
        with patch('healthcheck.process_alive',return_value=True),patch('healthcheck.websocket_ready',return_value=False):
            self.assertFalse(healthcheck.healthy(state))

    def test_docker_context_allowlist_and_explicit_model_bootstrap(self):
        patterns=(ROOT/'Dockerfile.dockerignore').read_text(encoding='utf-8')
        self.assertTrue(patterns.splitlines()[1]=='**')
        self.assertNotIn('!gateway/*.json',patterns)
        dockerfile=(ROOT/'Dockerfile').read_text(encoding='utf-8')
        self.assertNotIn('assets.py bootstrap',dockerfile)
        self.assertIn('slim-trixie',dockerfile);self.assertIn('USER 1000:1000',dockerfile)
        compose=(ROOT/'compose.yaml').read_text(encoding='utf-8')
        self.assertIn('network_mode: host',compose);self.assertNotIn('ports:',compose)


if __name__=='__main__':unittest.main(verbosity=2)
