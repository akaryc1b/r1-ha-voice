"""集中设置渲染只在临时目录验证，不连接 HA、MA 或 R1。"""
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import render_config as config


class ConfigRenderTests(unittest.TestCase):
    def setUp(self):
        self.settings={'queue_id':'custom-bedroom','provider':'apple_music--example',
                       'r1_url':'http://speaker.local:8080','ma_url':'https://music.example.test:8095'}
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output=Path(self.temp.name)/'prepared'

    def test_render_prepares_consistent_packages_dashboard_and_env(self):
        files=config.render(self.settings,self.output)
        self.assertEqual(len(files),5)
        documents={name:yaml.load((self.output/name).read_text(encoding='utf-8'),Loader=config.Loader)
                   for name in files if name.endswith('.yaml')}
        text='\n'.join((self.output/name).read_text(encoding='utf-8') for name in files)
        self.assertNotIn('__QUEUE_ID__',text)
        self.assertNotIn('upbac50e55',text)
        self.assertIn('custom-bedroom',text)
        self.assertIn('apple_music--example',text)
        self.assertIn('!include',text)
        dashboard=documents['r1_music_dashboard.yaml']['views']
        self.assertEqual(dashboard[0]['cards'][0]['r1_url'],self.settings['r1_url'])
        self.assertEqual(dashboard[1]['cards'][0]['url'],self.settings['ma_url']+'/')
        self.assertEqual((self.output/'r1-ma.env.example').read_text(),'R1_MA_QUEUE_ID=custom-bedroom\n')
        resource=documents['configuration.snippet.yaml']['lovelace']['resources'][0]['url']
        self.assertEqual(resource,'/local/r1-ha-voice.js')
        self.assertEqual(config.render(self.settings,self.output),files)

    def test_unknown_missing_or_nonstring_settings_are_rejected(self):
        cases=[dict(self.settings,unknown='value'),{key:value for key,value in self.settings.items() if key!='queue_id'},
               dict(self.settings,queue_id=None),dict(self.settings,queue_id=True),dict(self.settings,provider='')]
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):config.render(value,self.output)
        self.assertFalse(self.output.exists())

    def test_unsafe_urls_queue_and_provider_are_rejected(self):
        urls=['file:///etc/passwd','http://user:secret@host','http://@host','http://host/path?key=secret',
              'http://host/#fragment','http://192.168.999.1:8080','http://host:0','http://host:70000',
              'http://host/{{ unsafe }}','http://host\nInjected']
        for value in urls:
            with self.subTest(url=value):
                with self.assertRaises(ValueError):config.validate_settings(dict(self.settings,r1_url=value))
        for value in ('../queue',"q'unsafe",'{{queue}}',''):
            with self.assertRaises(ValueError):config.validate_settings(dict(self.settings,queue_id=value))
        with self.assertRaises(ValueError):config.validate_settings(dict(self.settings,provider='some_other_service'))

    def test_existing_different_file_refuses_before_any_overwrite(self):
        self.output.mkdir()
        target=self.output/'r1_music_player.yaml'
        target.write_text('user edit',encoding='utf-8')
        with self.assertRaises(ValueError):config.render(self.settings,self.output)
        self.assertEqual(list(self.output.iterdir()),[target])
        self.assertEqual(target.read_text(),'user edit')

    def test_replacement_only_changes_explicit_tokens(self):
        data={'query':'歌曲upbac50e55','id':'__QUEUE_ID__','nested':['__PROVIDER__']}
        actual=config.replace_tokens(data,self.settings)
        self.assertEqual(actual,{'query':'歌曲upbac50e55','id':'custom-bedroom','nested':['apple_music--example']})
        with self.assertRaises(ValueError):config.replace_tokens('__UNRECOGNIZED__',self.settings)


if __name__=='__main__':
    unittest.main()
