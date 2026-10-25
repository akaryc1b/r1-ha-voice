"""只修改指定门槛，不改唤醒词、断句参数或未知配置。"""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from tune_wakeup import KEYS,tune


class WakeupConfigTests(unittest.TestCase):
    def test_targeted_absolute_changes(self):
        source='# comment\n'+''.join(k+'=-11.3\n' for k in KEYS)+'word=custom\nasr_vad_timeout_back_sil=800\n'
        result,changes=tune(source,1.5)
        self.assertEqual(len(changes),5)
        self.assertIn('wakeup_benchmark=-9.8\n',result)
        self.assertIn('word=custom\nasr_vad_timeout_back_sil=800\n',result)
        self.assertEqual(tune(source,1.5)[0],result)
        with self.assertRaises(ValueError):tune(source+'wakeup_benchmark=-15\n',1.5)
        with self.assertRaises(ValueError):tune(source,float('nan'))


if __name__=='__main__':unittest.main()
