"""共享规则保护：数字转换限于音量，歌名和解释请求不误执行。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gateway'))
import intent_rules as rules


CASES = [
    ('下一手', '下一首'), ('切换一下守', '下一首'), ('上一手', '上一首'),
    ('播放放音乐', '播放音乐'), ('播放第一手歌', '播放第一首歌'),
    ('放手歌', '放首歌'), ('卧室温师度多少', '卧室温湿度多少'),
    ('播放温师度的歌', '播放温师度的歌'),
    ('把音乐音量调到百分之三十', '把音乐音量调到百分之30'),
    ('助手音量调到百分之百', '助手音量调到百分之100'),
    ('音量调到二十', '音量调到20'), ('音量调到零', '音量调到0'),
    ('音量调到一百零', '音量调到一百零'),
    ('音量调到一百二', '音量调到一百二'),
    ('播放三十岁的女人', '播放三十岁的女人'), ('三十是什么意思', '三十是什么意思'),
    ('暂停', '暂停'), ('播放', '播放'), ('放', '放'),
    ('播放国语流行', '播放国语流行'), ('随机播放点音乐', '随机播放点音乐'),
    ('播放周杰伦的晴天', '播放周杰伦的晴天'),
    ('播放音乐是什么意思', '播放音乐是什么意思'),
    ('帮我打开我的电脑', '帮我打开我的电脑'),
    ('彩虹是怎么形成的', '彩虹是怎么形成的'),
    ('  请给我暂停一下可以吗。  ', '请给我暂停一下可以吗'),
]


class IntentRulesTests(unittest.TestCase):
    def test_scoped_normalization(self):
        for text, expected in CASES:
            with self.subTest(text=text):
                self.assertEqual(rules.normalize(text), expected)

    def test_chinese_volume_range(self):
        digits = ('零', '一', '二', '三', '四', '五', '六', '七', '八', '九')
        for number in range(101):
            if number < 10:
                word = digits[number]
            elif number == 100:
                word = '一百'
            else:
                tens, units = divmod(number, 10)
                word = (digits[tens] if tens > 1 else '') + '十' + (digits[units] if units else '')
            text = '把音乐音量调到百分之' + word
            self.assertEqual(rules.normalize(text), '把音乐音量调到百分之' + str(number))

    def test_explanations_and_queries_are_not_music_controls(self):
        for text in ('播放音乐是什么意思', '暂停是什么意思', '解释随机播放是什么意思'):
            self.assertTrue(rules.is_explanation_question(text))
            self.assertFalse(rules.is_music_candidate(text))
            self.assertIsNone(rules.match_music_operation(text))
        self.assertIsNone(rules.match_music_operation('播放国语流行'))
        self.assertEqual(rules.match_music_operation('随机播放点音乐'), 'random')
        self.assertEqual(rules.match_music_operation('播放'), 'resume')
        self.assertTrue(rules.is_control_request('帮我打开我的电脑'))


if __name__ == '__main__':
    unittest.main()
