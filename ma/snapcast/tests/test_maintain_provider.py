"""维护器只在临时目录验证已登记旧 SHA；未知内容保持拒绝。"""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('test_snap_maintainer',ROOT/'maintain_provider.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class MaintainProviderTests(unittest.TestCase):
    def check(self,current,known=True):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);provider=root/'live';provider.mkdir()
            source=root/'provider';source.mkdir()
            latest=b'value = 2\n';prior=b'value = 1\n'
            (provider/'file.py').write_bytes(current);(source/'file.py').write_bytes(latest)
            (root/'upstream-manifest.json').write_text(json.dumps({'music_assistant_version':'2.10.6','files':[{
                'name':'file.py','upstream_sha256':None,'patched_sha256':hashlib.sha256(latest).hexdigest(),
                'accepted_prior_sha256':[hashlib.sha256(prior).hexdigest()]}]}))
            with patch.object(module,'ROOT',root),patch.object(sys,'argv',['maintain_provider.py','--provider-dir',str(provider)]),\
                    patch.object(module.importlib.metadata,'version',return_value='2.10.6'),contextlib.redirect_stdout(io.StringIO()):
                if known:module.main()
                else:
                    with self.assertRaisesRegex(SystemExit,'Unknown source'):module.main()
            self.assertEqual((provider/'file.py').read_bytes(),current)

    def test_accepts_explicit_prior_hash_without_writing(self):self.check(b'value = 1\n')
    def test_accepts_only_newline_difference_in_known_prior(self):self.check(b'value = 1\r\n')
    def test_rejects_unknown_source_without_writing(self):self.check(b'value = 999\n',False)


if __name__=='__main__':unittest.main(verbosity=2)
