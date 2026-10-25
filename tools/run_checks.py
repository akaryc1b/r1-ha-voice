"""本地与 CI 共用检查入口；报告写入 ignored reports，不提交测试状态快照。"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def steps(group):
    unit = lambda directory, pattern: [PYTHON, '-m', 'unittest', 'discover', '-s', directory, '-p', pattern, '-v']
    if group == 'gateway':
        return [[PYTHON, 'tools/check_repository.py', '--history']] + [unit('tests', pattern) for pattern in ('test_event_log*.py', 'test_gateway*.py', 'test_music_preemption.py', 'test_intent_rules.py', 'test_command_plan.py')] + [
            unit('deployment/tests', 'test_*.py'), unit('ma/snapcast/tests', 'test_*.py'), unit('tests','test_wakeup_config.py')]
    if group == 'java':
        return [[PYTHON, 'tests/ai_stream/' + name] for name in (
            'run_tests.py', 'run_asr_retry_tests.py', 'run_route_volume_tests.py',
            'run_listen_mute_tests.py', 'run_diagnostic_tests.py', 'run_audio_tests.py',
            'run_settings_cache_tests.py','run_command_tests.py')] + [[PYTHON, 'tools/test_intent_parity.py'], unit('device/tests', 'test_hook_pipeline.py')]
    if group == 'ma':
        target = Path(os.environ.get('R1_MA_SOURCE_ROOT', str(ROOT / '.cache/ma-after')))
        cache = Path(os.environ.get('R1_MA_CACHE_DIR', str(ROOT / '.cache/ma-upstream')))
        os.environ['R1_MA_SOURCE_ROOT'] = str(target)
        os.environ['R1_MA_CACHE_DIR'] = str(cache)
        return [[PYTHON, 'ma/maintain_ma_optimizations.py', '--prepare', str(target), '--cache-dir', str(cache)],
                unit('tests', 'test_ma_*.py'),
                [PYTHON, 'ma/tests/test_flow_offset.py', '--source-root', str(target)]]
    if group == 'ha':
        return [[PYTHON, 'ha/tests/test_music_rules.py'], unit('ha/tests', 'test_render_config.py')]
    if group == 'frontend':
        browser = [PYTHON, 'device/tests/test_voice_logs_browser.py', '--report', 'reports/voice-logs-browser.json']
        settings = [PYTHON, 'device/tests/test_voice_settings_browser.py', '--report', 'reports/voice-settings-browser.json']
        if os.environ.get('R1_TEST_BROWSER'):
            browser += ['--browser', os.environ['R1_TEST_BROWSER']]
            settings += ['--browser', os.environ['R1_TEST_BROWSER']]
        return [['node', 'tests/test_player_card.cjs'], browser, settings]
    raise ValueError(group)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('group', choices=['gateway', 'java', 'ma', 'ha', 'frontend'])
    args = parser.parse_args()
    reports = ROOT / 'reports'
    reports.mkdir(exist_ok=True)
    records = []
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    for index, command in enumerate(steps(args.group), 1):
        started = time.monotonic()
        path = reports / f'{args.group}-{index:02}.log'
        try:
            with path.open('wb') as output:
                result = subprocess.run(command, cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT, timeout=600)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
        records.append({'command': command[1:], 'exit_code': code, 'seconds': round(time.monotonic() - started, 3), 'log': path.name})
        print(f'{args.group} {index}: ' + ('PASS' if code == 0 else f'FAIL ({code})'), flush=True)
        if code:
            print('\n'.join(path.read_text(encoding='utf-8', errors='replace').splitlines()[-35:]), flush=True)
    passed = all(record['exit_code'] == 0 for record in records)
    (reports / f'{args.group}.json').write_text(json.dumps({'passed': passed, 'checks': records}, indent=2) + '\n', encoding='utf-8')
    raise SystemExit(0 if passed else 1)


if __name__ == '__main__':
    main()
