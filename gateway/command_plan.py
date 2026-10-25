"""只规划明确的组合操作，不调用 HA、MA 或执行设备动作。"""
import re

import intent_rules as intents

QUOTES = {'《': '》', '“': '”', '‘': '’', '「': '」', '『': '』', '"': '"', "'": "'"}
ERROR = '这句话里的操作还不能完整确认，请分开说。'


def _kind(text):
    if intents.is_explanation_question(text) or intents.is_incomplete_transcription(text):
        return None
    operation = intents.match_music_operation(text)
    if operation:
        return 'music'
    # “随便聊聊”不能仅因“随便”开头就成为音乐操作。
    if re.match(r'^(随便|随机)',intents.strip_prefix(intents.trim(text))) and not re.search('播放|放歌|听歌|音乐|歌曲',text):
        return None
    if intents.is_music_candidate(text):
        return 'ha'
    clean = intents.strip_prefix(intents.trim(text))
    if any(re.fullmatch(pattern, clean) for pattern in intents.RULES['control_patterns']):
        return 'ha'
    if (re.search('温度|湿度|温湿度', clean) and
            re.fullmatch(intents.RULES['compound_sensor_pattern'], clean)):
        return 'ha'
    return None


def _pieces(text):
    """保留引号中的歌名；不把普通“和”或“再见”当作操作分隔符。"""
    pieces = []
    current = []
    quote = None
    found = False
    index = 0
    joiners = intents.RULES['compound_joiners']
    while index < len(text):
        char = text[index]
        if quote:
            current.append(char)
            if char == quote and (index == 0 or text[index - 1] != '\\'):
                quote = None
            index += 1
            continue
        if char in QUOTES:
            quote = QUOTES[char]
            current.append(char)
            index += 1
            continue
        separator = next((word for word in joiners if text.startswith(word, index)), None)
        if separator is None:
            if char in '，,；;' and re.match(intents.RULES['compound_action_prefix'], text[index+1:].lstrip()):
                separator = char
            elif char == '再' and current and re.match(intents.RULES['compound_action_prefix'], text[index+1:]):
                separator = char
            elif char == '把' and current and intents.match_music_operation(''.join(current)):
                separator = ''
        if separator is not None:
            found = True
            pieces.append(''.join(current))
            current = []
            if separator:
                index += len(separator)
                continue
        current.append(char)
        index += 1
    pieces.append(''.join(current))
    return found, quote is None, pieces


def plan(text, maximum=4):
    if not isinstance(text, str) or not text.strip() or len(text) > 256:
        return {'handled': True, 'valid': False, 'steps': [], 'message': ERROR}
    if intents.is_explanation_question(text):
        return {'handled': False, 'valid': True, 'steps': []}
    found, balanced, pieces = _pieces(text.strip())
    if not found:
        return {'handled': False, 'valid': True, 'steps': []}
    if not balanced or not 2 <= len(pieces) <= maximum:
        return {'handled': True, 'valid': False, 'steps': [], 'message': ERROR}
    steps = []
    for index, piece in enumerate(pieces):
        clean = piece.strip(' ，,；;。！？!?')
        if index == 0:
            clean = re.sub(r'^(?:请)?先', '', clean, count=1)
        clean = intents.normalize(clean)
        route = _kind(clean)
        if not clean or route is None:
            return {'handled': True, 'valid': False, 'steps': [], 'message': ERROR}
        steps.append({'text': clean, 'route': route})
    return {'handled': True, 'valid': True, 'steps': steps}


def is_followup_request(text, maximum=4):
    if not text or intents.is_noise_only(text):
        return False
    batch = plan(text, maximum)
    if batch['handled']:
        return batch['valid']
    return (_kind(text) is not None or
            bool(re.fullmatch(intents.RULES['followup_question_pattern'], intents.trim(text))))
