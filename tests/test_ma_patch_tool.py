"""离线补丁生命周期测试；官方固定源码缓存可由 CI 提前准备。"""
import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ma'))
import maintain_ma_optimizations as tool


class PatchLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.patches = tool.read_bundle()
        selected = os.environ.get('R1_MA_CACHE_DIR')
        cache = Path(selected) if selected else None
        cls.before = {item['path']:tool.upstream_source(item,cls.manifest,cache)
                      for item in cls.manifest['files']}
        cls.after = {item['path']:tool.transform(cls.before[item['path']],item,cls.patches[item['path']])
                     for item in cls.manifest['files']}
        migration=tool.read_migrations(cls.manifest)
        cls.previous=dict(cls.after)
        for item in cls.manifest['files']:
            if 'previous_after_sha256' not in item:continue
            transition={'path':item['path'],'before_sha256':item['previous_after_sha256'],'after_sha256':item['after_sha256']}
            cls.previous[item['path']]=tool.transform(cls.after[item['path']],transition,migration[item['path']],reverse=True)
        upgrades=tool.read_upgrade(cls.manifest)
        cls.upgrade_from=dict(cls.after)
        for item in cls.manifest['files']:
            if 'upgrade_from_sha256' not in item:continue
            transition={'path':item['path'],'before_sha256':item['upgrade_from_sha256'],'after_sha256':item['after_sha256']}
            cls.upgrade_from[item['path']]=tool.transform(cls.after[item['path']],transition,upgrades[item['path']],reverse=True)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='r1-ma-patch-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        for path,data in self.before.items():
            target=self.base/path
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(data)

    def actual(self):
        return {path:(self.base/path).read_bytes() for path in self.before}

    def test_preview_apply_reapply_restore_rerestore(self):
        self.assertEqual(len(tool.maintain(self.base,'check')),7)
        self.assertEqual(self.actual(),self.before)
        tool.maintain(self.base,'apply')
        self.assertEqual(self.actual(),self.after)
        tool.maintain(self.base,'apply')
        self.assertEqual(self.actual(),self.after)
        tool.maintain(self.base,'check')
        tool.maintain(self.base,'restore')
        self.assertEqual(self.actual(),self.before)
        tool.maintain(self.base,'restore')
        self.assertEqual(self.actual(),self.before)

    def test_unknown_last_file_refuses_all_writes(self):
        last=list(self.before)[-1]
        (self.base/last).write_bytes(self.before[last]+b'\n# unknown\n')
        original=self.actual()
        for action in ('check','apply','restore'):
            with self.assertRaises(ValueError):tool.maintain(self.base,action)
            self.assertEqual(self.actual(),original)

    def test_known_previous_optimized_state_migrates_and_restores(self):
        for path,data in self.previous.items():(self.base/path).write_bytes(data)
        tool.maintain(self.base,'check')
        self.assertEqual(self.actual(),self.previous)
        tool.maintain(self.base,'apply')
        self.assertEqual(self.actual(),self.after)
        for path,data in self.previous.items():(self.base/path).write_bytes(data)
        tool.maintain(self.base,'restore')
        self.assertEqual(self.actual(),self.before)

    def test_crlf_only_compatibility(self):
        for path,data in self.before.items():(self.base/path).write_bytes(data.replace(b'\n',b'\r\n'))
        tool.maintain(self.base,'check')
        tool.maintain(self.base,'apply')
        self.assertEqual(self.actual(),self.after)
        tool.maintain(self.base,'restore')
        self.assertEqual(self.actual(),self.before)

    def test_deployed_optimized_state_upgrades_without_replacing_unknown_source(self):
        for path,data in self.upgrade_from.items():(self.base/path).write_bytes(data)
        tool.maintain(self.base,'check')
        self.assertEqual(self.actual(),self.upgrade_from)
        tool.maintain(self.base,'apply')
        self.assertEqual(self.actual(),self.after)
        for path,data in self.upgrade_from.items():(self.base/path).write_bytes(data)
        tool.maintain(self.base,'restore')
        self.assertEqual(self.actual(),self.before)

    def test_partial_write_failure_restores_original_bytes(self):
        real=tool.replace_bytes
        calls=0
        def fail_once(path,data):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('simulated write failure')
            real(path,data)
        with patch.object(tool,'replace_bytes',side_effect=fail_once):
            with self.assertRaises(OSError):tool.maintain(self.base,'apply')
        self.assertEqual(self.actual(),self.before)
        self.assertFalse(list(self.base.rglob('.r1-ma-*')))

    def test_edit_after_validation_aborts_and_preserves_external_change(self):
        real=tool.replace_bytes
        second=list(self.before)[1]
        changed=self.before[second]+b'\n# concurrent editor\n'
        def edit_next(path,data):
            real(path,data)
            (self.base/second).write_bytes(changed)
        with patch.object(tool,'replace_bytes',side_effect=edit_next):
            with self.assertRaises(ValueError):tool.maintain(self.base,'apply')
        expected=dict(self.before);expected[second]=changed
        self.assertEqual(self.actual(),expected)

    def test_patch_hash_and_context_are_enforced(self):
        with patch.object(tool,'sha',return_value='bad'):
            with self.assertRaises(ValueError):tool.read_bundle()
        item=self.manifest['files'][0]
        hunks=list(self.patches[item['path']])
        old,new,removed,added=hunks[0]
        hunks[0]=(old,new,['bad context\n']+removed[1:],added)
        with self.assertRaises(ValueError):tool.transform(self.before[item['path']],item,hunks)

    def test_unknown_upstream_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as cache:
            item=self.manifest['files'][0]
            target=Path(cache)/item['path'];target.parent.mkdir(parents=True)
            target.write_bytes(b'unknown upstream')
            with self.assertRaises(ValueError):tool.upstream_source(item,self.manifest,Path(cache))

    def test_traversal_paths_rejected(self):
        for value in ('../escape.py','/absolute.py','C:/absolute.py','x\\escape.py'):
            with self.assertRaises(ValueError):tool.relative_path(value)

    def test_test_sources_match_exact_optimized_hash(self):
        tool.maintain(self.base,'apply')
        for item in self.manifest['files']:
            self.assertEqual(tool.optimized_source(item['path'],self.base).encode(),self.after[item['path']])

    def test_generated_modules_compile(self):
        for path,data in self.after.items():
            compile(data,path,'exec')

    def test_queue_environment_scope_and_empty_rejection(self):
        guarded=[]
        for path,data in self.after.items():
            if b'R1_MA_QUEUE_ID' not in data:continue
            tree=ast.parse(data)
            nodes=[node for node in tree.body if
                   (isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='R1_MA_QUEUE_ID' for t in node.targets)) or
                   (isinstance(node,ast.If) and isinstance(node.test,ast.UnaryOp) and isinstance(node.test.operand,ast.Name) and node.test.operand.id=='R1_MA_QUEUE_ID')]
            self.assertEqual(len(nodes),2)
            module=compile(ast.Module(body=nodes,type_ignores=[]),path,'exec')
            for value,expected in ((None,'upbac50e55'),('bedroom-queue','bedroom-queue'),(' bedroom-queue ','bedroom-queue')):
                env=dict(os.environ)
                if value is None:env.pop('R1_MA_QUEUE_ID',None)
                else:env['R1_MA_QUEUE_ID']=value
                with patch.dict(os.environ,env,clear=True):
                    namespace={'os':os};exec(module,namespace)
                    self.assertEqual(namespace['R1_MA_QUEUE_ID'],expected)
            with patch.dict(os.environ,{'R1_MA_QUEUE_ID':'  '}):
                with self.assertRaises(ValueError):exec(module,{'os':os})
            # 所有限制引用同一环境常量，旧默认值只出现在默认配置中。
            self.assertEqual(data.count(b'upbac50e55'),1)
            guarded.append(path)
        self.assertEqual(len(guarded),5)


if __name__=='__main__':
    unittest.main()
