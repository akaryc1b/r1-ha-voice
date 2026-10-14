"""网关上行协议；兼容旧 Float32，PCM16 原样封装 WAV。"""
import io
import wave

import numpy as np

FORMATS = {'pcm_s16le': 2, 'float32': 4}
SAMPLE_RATE = 16000


def sample_width(audio_format):
    try:
        return FORMATS[audio_format]
    except KeyError:
        raise ValueError('Unsupported audio_format') from None


def sherpa_frame(data, audio_format):
    width = sample_width(audio_format)
    if len(data) % width:
        raise ValueError('Misaligned audio frame')
    if audio_format == 'float32':
        return data
    samples = np.frombuffer(data, dtype='<i2').astype('<f4')
    samples /= 32768.0
    return samples.tobytes()


def wav_bytes(chunks, audio_format='float32'):
    raw = b''.join(chunks)
    width = sample_width(audio_format)
    if len(raw) % width:
        raise ValueError('Misaligned audio data')
    if audio_format == 'pcm_s16le':
        pcm = raw
    else:
        samples = np.frombuffer(raw, dtype='<f4')
        samples = np.nan_to_num(samples, nan=0, posinf=1, neginf=-1)
        pcm = (np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes()
    # PCM16 不做采样值转换；拼接和 WAV 封装仍需内存复制。
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as output:
        output.setparams((1, 2, SAMPLE_RATE, 0, 'NONE', 'not compressed'))
        output.writeframes(pcm)
    return buffer.getvalue()
