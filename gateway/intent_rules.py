"""由共享规则驱动的文字修正与意图判断，Java 由同一 JSON 生成。"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RULES = json.loads((ROOT / 'intent-rules.json').read_text(encoding='utf-8'))
COMMANDS = json.loads((ROOT / 'music-commands.json').read_text(encoding='utf-8'))


def trim(text):
    return re.sub(RULES['trim_pattern'], '', text or '')


def chinese_number(text):
    digits = RULES['chinese_digits']
    if text == '百' or text == '一百':
        return 100
    if text.count('十') == 1:
        left, right = text.split('十')
        if (not left or left in digits and digits[left] > 0) and (not right or right in digits):
            return (digits[left] if left else 1) * 10 + (digits[right] if right else 0)
    if len(text) == 1 and text in digits:
        return digits[text]
    # “三零”支持逐位数字，拒绝“十百”“一百二”等不确定形式。
    if len(text) <= 3 and text and all(c in digits for c in text):
        return int(''.join(str(digits[c]) for c in text))
    return None


def normalize(text):
    text = trim(text)
    compact = re.sub(RULES['compact_pattern'], '', text)
    for rule in RULES['compact_rewrites']:
        if re.fullmatch(rule['pattern'], compact):
            return rule['replacement']
    for rule in RULES['full_rewrites']:
        if re.fullmatch(rule['pattern'], text):
            return re.sub(rule['pattern'], rule['replacement'], text)
    match = re.fullmatch(RULES['volume_number_pattern'], text)
    if match:
        number = chinese_number(match[2])
        if number is not None and 0 <= number <= 100:
            return match[1] + str(number) + match[3]
    if re.match(RULES['sensor_guard'], text) and not re.match(RULES['sensor_exclude'], text):
        return re.sub(RULES['sensor_typo'], '温湿度', text)
    return text


def strip_prefix(text):
    return re.sub(RULES['request_prefix'], '', text, count=1)


def match_music_operation(text, commands=None):
    commands = COMMANDS if commands is None else commands
    clean = re.sub(RULES['compact_pattern'], '', normalize(text))
    if clean in commands:
        return commands[clean]
    clean = strip_prefix(clean)
    clean = re.sub(RULES['music_suffix'], '', clean, count=1)
    return commands.get(clean)


def is_explanation_question(text):
    text = trim(text)
    patterns = RULES['explanation_patterns']
    if re.fullmatch(patterns[0], text):
        return False
    if any(re.fullmatch(p, text) for p in patterns[1:3]):
        return True
    return not re.fullmatch(RULES['control_prefix'], strip_prefix(text)) and any(
        re.fullmatch(p, text) for p in patterns[3:])


def is_music_candidate(text):
    return bool(text) and not is_explanation_question(text) and bool(
        re.fullmatch(RULES['music_candidate'], strip_prefix(trim(text))))


def is_control_request(text):
    if not text or is_explanation_question(text):
        return False
    return is_music_candidate(text) or any(re.fullmatch(p, strip_prefix(trim(text)))
                                          for p in RULES['control_patterns'])


def is_home_request(text):
    return bool(text) and not is_explanation_question(text) and (
        is_control_request(text) or bool(re.fullmatch(RULES['home_keywords'], text)))


def is_fast_control(text):
    clean = trim(text)
    clean = re.sub(RULES['fast_prefix'], '', clean, count=1)
    clean = re.sub(RULES['fast_suffix'], '', clean, count=1)
    return (bool(match_music_operation(text)) or clean in RULES['fast_exact'] or
            any(re.fullmatch(p, clean) for p in RULES['fast_patterns']))


def is_incomplete_transcription(text):
    if match_music_operation(text):
        return False
    clean = re.sub(RULES['incomplete_prefix'], '', trim(text), count=1)
    return (not clean or clean in RULES['incomplete_exact'] or
            bool(re.fullmatch(RULES['incomplete_pattern'], clean)))


def is_noise_only(text):
    clean = re.sub(RULES['compact_pattern'], '', trim(text))
    return bool(clean and re.fullmatch(RULES['noise_only_pattern'], clean))
