"""Generate closed core controls from HA grammar; runtime handles polite wrappers."""
import argparse
import json
from pathlib import Path

import yaml
from hassil import Intents
from hassil.parse_expression import parse_sentence
from hassil.sample import sample_sentence


def generate_core_commands(data: dict) -> dict[str, str]:
    intents = Intents.from_dict(data)
    rules = dict(intents.expansion_rules)
    # Listening words belong to a phrase; the final polite suffix is normalized at runtime.
    ending = data['expansion_rules']['music_request_end']
    polite = '[吧|好吗|可以吗|行吗]'
    if ending.count(polite) != 1:
        raise ValueError('Review core generation after changing music_request_end')
    rules['music_request_end'] = parse_sentence(ending.replace(polite, '', 1))
    commands = {}
    for row in intents.intents['R1MusicControl'].data:
        for text in row.sentence_texts:
            core = text.replace('[<music_prefix>]', '').replace('[<music_suffix>]', '')
            for phrase in sample_sentence(parse_sentence(core), expansion_rules=rules, language='zh-cn'):
                phrase = phrase.replace(' ', '')
                operation = row.slots['operation']
                if phrase in commands and commands[phrase] != operation:
                    raise ValueError('Conflicting control: ' + phrase)
                commands[phrase] = operation
    return dict(sorted(commands.items()))


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sentences', type=Path, default=root / 'custom_sentences/zh-cn/r1_music.yaml')
    parser.add_argument('--output', type=Path, default=root.parent / 'gateway/music-commands.json')
    args = parser.parse_args()
    commands = generate_core_commands(yaml.safe_load(args.sentences.read_text(encoding='utf-8')))
    args.output.write_bytes((json.dumps(commands, ensure_ascii=False, separators=(',', ':')) + '\n').encode())
    print(json.dumps({'commands': len(commands), 'bytes': args.output.stat().st_size}))


if __name__ == '__main__':
    main()
