"""CLI 基础测试 — 验证所有命令能正常执行"""
import subprocess
import sys
import os
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cli(*args: str, accept_license: bool = True) -> subprocess.CompletedProcess:
    command = [sys.executable, '-m', 'gaokao.cli']
    if accept_license:
        command.append('--accept-license')
    command.extend(args)
    return subprocess.run(
        command,
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )


class TestCLI:

    def test_cli_requires_affirmative_license_acceptance(self):
        r = _cli('--list-provinces', accept_license=False)
        assert r.returncode == 2
        assert '--accept-license' in r.stderr

    def test_list_provinces(self):
        r = _cli('--list-provinces')
        assert r.returncode == 0
        assert 'yunnan' in r.stdout

    def test_check_config_yunnan(self):
        r = _cli('--province', 'yunnan', '--check-config')
        assert r.returncode == 0
        assert '云南省' in r.stdout
        assert '3+1+2' in r.stdout

    def test_list_provinces_has_yunnan(self):
        r = _cli('--list-provinces')
        assert 'yunnan' in r.stdout
        assert '云南省' in r.stdout

    def test_example_missing_database_fails_closed(self, monkeypatch, capsys):
        from gaokao import cli

        original_exists = cli.os.path.exists
        monkeypatch.setattr(
            cli.os.path,
            'exists',
            lambda path: False if str(path).endswith('example.db') else original_exists(path),
        )

        assert cli.cmd_run_example('yunnan') == 1
        assert '示例数据库不存在' in capsys.readouterr().out


def test_server_requires_affirmative_license_acceptance():
    result = subprocess.run(
        [sys.executable, '-m', 'gaokao.api.server', '--port', '0'],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=15,
    )
    assert result.returncode == 2
    assert '--accept-license' in result.stderr


def test_public_questionnaire_does_not_require_exam_id():
    """本地开源推荐不得强迫用户提供真实考生号。"""
    from gaokao.core.questionnaire_parser import QuestionnaireParser

    questionnaire = QuestionnaireParser.create_by_category('物理类').parse({
        'q1_name': '本地昵称',
        'q12_total_score': 580,
        'q13_rank': 15000,
        'q14_category': '物理类',
    })

    assert questionnaire.exam_id == ''


def test_no_color_blindness_label_is_not_misclassified():
    """“无色盲色弱”含敏感子串，但必须归一为正常。"""
    from gaokao.core.questionnaire_parser import QuestionnaireParser

    questionnaire = QuestionnaireParser.create_by_category('物理类').parse({
        'q1_name': '本地昵称',
        'q9_color_vision': '无色盲色弱',
        'q12_total_score': 580,
        'q13_rank': 15000,
        'q14_category': '物理类',
    })

    assert questionnaire.health_screening.color_vision == '正常'
    from gaokao.core.matching_engine import MatchingEngine
    answers = MatchingEngine.__new__(MatchingEngine)._build_constraint_answers(questionnaire)
    assert answers['color_vision'] == '正常'
