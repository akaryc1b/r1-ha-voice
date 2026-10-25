"""组合规划与续听筛选：不接触设备、不执行动作。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'gateway'))
import command_plan
import intent_rules


class CommandPlanTests(unittest.TestCase):
    def test_sequences_and_volume_normalization(self):
        for text in ('先暂停，然后把音量调到三十', '暂停再把音量调到三十',
                     '暂停，把音量调到三十', '暂停把音量调到三十'):
            with self.subTest(text=text):
                result=command_plan.plan(text)
                self.assertTrue(result['valid'])
                self.assertEqual([s['text'] for s in result['steps']],['暂停','把音量调到30'])

    def test_computer_and_sensor_control(self):
        result=command_plan.plan('打开我的电脑然后查询卧室温度')
        self.assertEqual([s['route'] for s in result['steps']],['ha','ha'])

    def test_no_partial_plan_on_unknown_or_over_limit(self):
        for text in ('暂停然后随便聊聊', '暂停然后', '然后暂停', '暂停然后继续然后下一首'):
            result=command_plan.plan(text,2)
            self.assertTrue(result['handled'])
            self.assertFalse(result['valid'])
            self.assertEqual(result['steps'],[])

    def test_titles_and_explanations_stay_single(self):
        for text in ('播放《然后》','播放“再见然后你好”','暂停是什么意思',
                     '解释暂停然后继续是什么意思','播放国语流行','来点音乐'):
            self.assertFalse(command_plan.plan(text)['handled'],text)
        result=command_plan.plan('播放《然后》然后把音量调小')
        self.assertEqual(len(result['steps']),2)

    def test_followup_does_not_accept_filler_or_ordinary_speech(self):
        for text in ('嗯','啊，嗯。','え','歌词里面有很多故事','我昨天出去吃饭'):
            self.assertFalse(command_plan.is_followup_request(text),text)
        for text in ('暂停','音量调小','播放国语流行','打开我的电脑','为什么天空是蓝色的'):
            self.assertTrue(command_plan.is_followup_request(text),text)
        self.assertFalse(intent_rules.is_noise_only('嗯，暂停'))


if __name__=='__main__':unittest.main()
