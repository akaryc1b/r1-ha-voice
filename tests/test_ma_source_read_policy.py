"""验证真实源读取条件的边界；不下载用户的歌曲或改变音频样本。"""
import ast
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ma"))
from maintain_ma_optimizations import optimized_source

tree = ast.parse(optimized_source("controllers/streams/audio.py"))
condition = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                 and "R1_APPLE_SEQUENTIAL_SEEK_MAX_SECONDS" in ast.unparse(n.test)
                 and "seek_position" in ast.unparse(n.test))
initializers=[n for n in ast.walk(tree) if isinstance(n, ast.Assign) and
              any(isinstance(t,ast.Name) and t.id in ('r1_sequential_apple','extra_output_args') for t in n.targets) and
              (not isinstance(n.value,ast.Constant) or n.value.value is False)]
seek_condition=next(n for n in ast.walk(tree) if isinstance(n, ast.If) and
                    ast.unparse(n.test)=='seek_position and streamdetails.duration and streamdetails.allow_seek')
code = compile(ast.Module(body=[*initializers,condition,seek_condition], type_ignores=[]), "actual_source_read_policy", "exec")

class SourceReadPolicyTests(unittest.TestCase):
    def options(self, seek=0, queue="r1", provider="apple_music--example", stream_type="encrypted", initial=None, maximum=120, piped=False):
        values = dict(streamdetails=SimpleNamespace(queue_id=queue, provider=provider, stream_type=stream_type,duration=300,allow_seek=True,decryption_key="test-key"),
                      seek_position=seek, R1_MA_QUEUE_ID="r1",
                      R1_APPLE_SEQUENTIAL_SEEK_MAX_SECONDS=maximum,
                      R1_APPLE_HTTP_PIPE=piped,
                      audio_source="https://example.test/audio", self=SimpleNamespace(_get_r1_apple_http_stream=Mock(return_value="test-generator")),
                      StreamType=SimpleNamespace(ENCRYPTED_HTTP="encrypted"),
                      extra_input_args=list(initial or []))
        exec(code, values)
        self.last_values=values
        return values["extra_input_args"],values["extra_output_args"]

    def args(self,*args,**kwargs):
        return self.options(*args,**kwargs)[0]

    def test_initial_and_bounded_resume_use_sequential_input(self):
        for seek in (0, 1, 76, 120):
            self.assertEqual(self.args(seek), ["-seekable", "0"])

    def test_far_seek_and_other_sources_keep_original_range_behavior(self):
        for changes in ({"seek":121}, {"seek":-1}, {"queue":"other"},
                        {"provider":"local"}, {"stream_type":"http"}):
            args=self.args(**changes)
            self.assertNotIn('-seekable',args)

    def test_explicit_input_option_is_preserved(self):
        self.assertEqual(self.options(76, initial=["-seekable", "1"]), (["-seekable", "1", "-ss", "76"],[]))

    def test_zero_limit_retains_only_initial_read_optimization(self):
        self.assertEqual(self.args(0, maximum=0), ["-seekable", "0"])
        self.assertEqual(self.args(1, maximum=0), ['-ss','1'])

    def test_bounded_seek_is_an_output_trim_and_far_seek_retains_input_seek(self):
        self.assertEqual(self.options(76), (['-seekable','0'],['-ss','76']))
        self.assertEqual(self.options(121), (['-ss','121'],[]))

    def test_pipe_keeps_decryption_and_output_seek_without_http_protocol_options(self):
        self.assertEqual(self.options(76, initial=['-decryption_key','test-key'], piped=True), (['-decryption_key','test-key'],['-ss','76']))
        self.assertEqual(self.last_values['audio_source'],'test-generator')

    def test_explicit_network_options_keep_original_ffmpeg_reader(self):
        self.options(initial=['-decryption_key','test-key','-headers','custom'], piped=True)
        self.last_values['self']._get_r1_apple_http_stream.assert_not_called()

if __name__ == "__main__":
    unittest.main()

