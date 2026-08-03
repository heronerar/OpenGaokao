"""发版门禁自身的失效保护测试。"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

import scripts.verify_release as verify_release
from scripts.verify_release import (
    _run_with_process_tree_timeout,
    check_publication_authorization,
    check_public_release,
    check_public_tree,
    check_pytest_full,
    check_runtime_e2e,
)
from tests.test_e2e_api import _assert_server_stopped, _build_payload, _free_port


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _pid_exists(pid: int) -> bool:
    if os.name == 'nt':
        result = subprocess.run(
            ['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'],
            capture_output=True,
            text=True,
        )
        return f'"{pid}"' in result.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _git(repo, *args):
    return subprocess.run(
        ['git', *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )


def _init_repo(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init', '-q')
    _git(repo, 'config', 'user.name', 'Release Gate Test')
    _git(repo, 'config', 'user.email', 'release-gate@example.invalid')
    (repo / 'README.md').write_text('safe\n', encoding='utf-8')
    _git(repo, 'add', 'README.md')
    _git(repo, 'commit', '-q', '-m', 'initial')
    return repo


def _use_repo(monkeypatch, repo):
    monkeypatch.setattr('scripts.verify_release.PROJECT_ROOT', repo)


def test_runtime_timeout_kills_child_process(tmp_path):
    """外层超时必须同时杀掉验收脚本和它启动的服务子进程。"""
    child_pid_file = tmp_path / 'child.pid'
    child_code = 'import time; time.sleep(60)'
    wrapper_code = (
        'import pathlib, subprocess, sys, time; '
        f'p = subprocess.Popen([sys.executable, "-c", {child_code!r}]); '
        f'pathlib.Path({str(child_pid_file)!r}).write_text(str(p.pid), encoding="ascii"); '
        'time.sleep(60)'
    )

    with pytest.raises(subprocess.TimeoutExpired):
        _run_with_process_tree_timeout(
            [sys.executable, '-c', wrapper_code],
            cwd=str(tmp_path),
            timeout=2,
        )

    child_pid = int(child_pid_file.read_text(encoding='ascii'))
    deadline = time.monotonic() + 5
    while _pid_exists(child_pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not _pid_exists(child_pid), f'超时后仍残留子进程 PID {child_pid}'


def test_shutdown_check_rejects_listening_port():
    """仍能接受 TCP 连接时，即使 HTTP 会报错，也不得宣称服务已退出。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(RuntimeError, match='端口 .* 未释放'):
            _assert_server_stopped(port)


def test_shutdown_check_accepts_released_port():
    """没有监听者时，退出检查通过。"""
    port = _free_port()
    _assert_server_stopped(port)


def test_shutdown_check_accepts_recently_closed_listener():
    """连接关闭后的短暂 TCP 状态不得冒充仍在监听的服务。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        port = listener.getsockname()[1]
        with socket.create_connection(('127.0.0.1', port), timeout=1) as client:
            accepted, _ = listener.accept()
            accepted.close()
    _assert_server_stopped(port)


def test_runtime_gate_rejects_empty_success_receipt(monkeypatch):
    """子脚本空跑且 exit=0 时，发版门禁仍必须失败。"""
    monkeypatch.setattr(
        'scripts.verify_release._run_with_process_tree_timeout',
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, '', ''),
    )
    result = check_runtime_e2e('yunnan', 'yunnan')
    assert not result.passed
    assert '缺少回执字段' in result.detail


def test_renamed_example_db_remains_synthetic(tmp_path, monkeypatch):
    """示例库复制成省份文件名后，API 仍必须把内容标为 example。"""
    from data import generate_example_db
    from gaokao.api import server

    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    example_db = data_dir / 'example.db'
    renamed_db = data_dir / 'yunnan_gaokao.db'
    monkeypatch.setattr(generate_example_db, 'DB_PATH', str(example_db))
    generate_example_db.create_example_db()
    shutil.copy2(example_db, renamed_db)
    monkeypatch.setattr(server, 'PROJECT_ROOT', str(tmp_path))

    resolved, data_source, provenance = server.resolve_database('yunnan')

    assert resolved == str(renamed_db)
    assert data_source == 'example'
    assert provenance == 'synthetic_example'

    server._engine_cache.clear()
    try:
        response = server.app.test_client().post(
            '/api/recommend', json=_build_payload('yunnan')
        )
        payload = response.get_json()
        assert response.status_code == 200, payload
        assert payload['data_source'] == 'example'
        assert payload['data_provenance'] == 'synthetic_example'
    finally:
        for engine in server._engine_cache.values():
            engine.close()
        server._engine_cache.clear()


def test_public_tree_rejects_forbidden_paths_and_large_file(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    (repo / 'data').mkdir()
    (repo / 'docs').mkdir()
    (repo / 'docs' / 'audit').mkdir()
    (repo / 'data' / 'example.db').write_bytes(b'')
    (repo / '.fuse_hidden0001').write_bytes(b'control')
    (repo / '.env').write_text('TOKEN=placeholder\n', encoding='utf-8')
    (repo / 'deploy.pem').write_text('placeholder\n', encoding='utf-8')
    (repo / 'docs' / 'OpenGaokao_Risk_Analysis.md').write_text('internal\n', encoding='utf-8')
    for internal_name in (
        'audit_report.md', 'business_model.md', 'data-table.md', 'province-priority.md',
    ):
        (repo / 'docs' / internal_name).write_text('internal\n', encoding='utf-8')
    for audit_name in (
        '01_full_audit_20260612.md',
        '02_operations_5m1e_20260614.md',
        '03_data_quality_2020_2022_20260614.md',
        '04_full_audit_20260614.md',
    ):
        (repo / 'docs' / 'audit' / audit_name).write_text('private audit\n', encoding='utf-8')
    (repo / 'artifact.bin').write_bytes(b'x' * 101)
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-q', '-m', 'unsafe files')
    _use_repo(monkeypatch, repo)
    monkeypatch.setattr('scripts.verify_release._PUBLIC_MAX_FILE_BYTES', 100)

    result = check_public_tree()

    assert not result.passed
    for path in (
        'data/example.db', '.fuse_hidden0001', '.env', 'deploy.pem',
        'docs/OpenGaokao_Risk_Analysis.md', 'artifact.bin',
        'docs/audit_report.md', 'docs/business_model.md',
        'docs/data-table.md', 'docs/province-priority.md',
        'docs/audit/01_full_audit_20260612.md',
        'docs/audit/02_operations_5m1e_20260614.md',
        'docs/audit/03_data_quality_2020_2022_20260614.md',
        'docs/audit/04_full_audit_20260614.md',
    ):
        assert path in result.detail


def test_public_release_rejects_sensitive_current_tree_without_echoing_literal(
    tmp_path, monkeypatch,
):
    repo = _init_repo(tmp_path)
    sensitive_literal = 'CURRENT-PRIVATE-PERSON-2026'
    (repo / 'README.md').write_text(f'safe\n{sensitive_literal}\n', encoding='utf-8')
    _git(repo, 'add', 'README.md')
    _git(repo, 'commit', '-q', '-m', 'current sensitive value')
    denylist = tmp_path / 'private-denylist.txt'
    denylist.write_text(sensitive_literal + '\n', encoding='utf-8')
    _use_repo(monkeypatch, repo)

    result = check_public_release(denylist)

    assert not result.passed
    assert 'CURRENT:README.md' in result.detail
    assert sensitive_literal not in result.detail


def test_public_release_rejects_sensitive_reachable_history_without_echoing_literal(
    tmp_path, monkeypatch,
):
    repo = _init_repo(tmp_path)
    sensitive_literal = 'HISTORICAL-PRIVATE-PERSON-2026'
    base_branch = _git(repo, 'branch', '--show-current').stdout.strip()
    _git(repo, 'checkout', '-q', '-b', 'archived-sensitive-ref')
    (repo / 'old-notes.txt').write_text(sensitive_literal + '\n', encoding='utf-8')
    _git(repo, 'add', 'old-notes.txt')
    _git(repo, 'commit', '-q', '-m', 'add sensitive history')
    _git(repo, 'checkout', '-q', base_branch)
    denylist = tmp_path / 'private-denylist.txt'
    denylist.write_text(sensitive_literal + '\n', encoding='utf-8')
    _use_repo(monkeypatch, repo)

    result = check_public_release(denylist)

    assert not result.passed
    assert 'old-notes.txt' in result.detail
    assert 'CURRENT:' not in result.detail
    assert sensitive_literal not in result.detail


def test_public_release_rejects_tracked_denylist(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    denylist = repo / 'private-denylist.txt'
    denylist.write_text('PRIVATE-PERSON\n', encoding='utf-8')
    _git(repo, 'add', 'private-denylist.txt')
    _git(repo, 'commit', '-q', '-m', 'tracked denylist')
    _use_repo(monkeypatch, repo)

    result = check_public_release(denylist)

    assert not result.passed
    assert '已被 Git 跟踪' in result.detail


def test_public_release_rejects_empty_denylist(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    denylist = tmp_path / 'private-denylist.txt'
    denylist.write_text('\n  \n', encoding='utf-8')
    _use_repo(monkeypatch, repo)

    result = check_public_release(denylist)

    assert not result.passed
    assert '为空' in result.detail


def test_public_release_rejects_missing_denylist(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    _use_repo(monkeypatch, repo)

    result = check_public_release(tmp_path / 'missing-denylist.txt')

    assert not result.passed
    assert '不存在' in result.detail


def test_public_release_rejects_dirty_worktree(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    denylist = tmp_path / 'private-denylist.txt'
    denylist.write_text('PRIVATE-PERSON\n', encoding='utf-8')
    (repo / 'README.md').write_text('dirty\n', encoding='utf-8')
    _use_repo(monkeypatch, repo)

    result = check_public_release(denylist)

    assert not result.passed
    assert '工作树不干净' in result.detail


def test_public_release_accepts_clean_history_without_denylist_hits(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    denylist = tmp_path / 'private-denylist.txt'
    denylist.write_text('PRIVATE-PERSON\n', encoding='utf-8')
    _use_repo(monkeypatch, repo)

    result = check_public_release(denylist)

    assert result.passed, result.detail
    assert '可达提交' in result.detail


def test_publication_authorization_fails_closed_during_legal_review():
    """权属/律师审定未完成时，机械门禁必须阻止恢复公开。"""
    result = check_publication_authorization()

    assert not result.passed
    assert 'LEGAL_REVIEW_REQUIRED' in result.detail
    assert '保持 PRIVATE' in result.detail


def test_publication_authorization_rejects_in_repository_self_approval(tmp_path, monkeypatch):
    """把仓库内状态自填为 APPROVED 不能冒充权属和律师批准。"""
    policy = json.loads((PROJECT_ROOT / 'licensing/publication-policy.json').read_text(encoding='utf-8'))
    policy['status'] = 'APPROVED'
    candidate = tmp_path / 'publication-policy.json'
    candidate.write_text(json.dumps(policy), encoding='utf-8')
    monkeypatch.setattr(verify_release, 'PUBLICATION_POLICY', candidate)

    result = check_publication_authorization()

    assert not result.passed
    assert '不能自我批准' in result.detail


def test_pytest_gate_ignores_inherited_addopts(monkeypatch):
    """外部 PYTEST_ADDOPTS 不能把全量测试改成 collect-only/help。"""
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args[0], 0, stdout='18 passed in 1.00s\n', stderr='')

    monkeypatch.setenv('PYTEST_ADDOPTS', '--collect-only')
    monkeypatch.setattr(subprocess, 'run', fake_run)

    result = check_pytest_full(False)

    assert result.passed
    assert 'PYTEST_ADDOPTS' not in captured['env']


def test_pytest_gate_rejects_exit_zero_without_passed_tests(monkeypatch):
    """pytest 空跑即使 exit=0 也不得被宣告为全套通过。"""
    monkeypatch.setattr(
        subprocess,
        'run',
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout='collected 18 items\n', stderr=''
        ),
    )

    result = check_pytest_full(False)

    assert not result.passed
    assert '没有实际通过测试' in result.detail


def test_public_release_cannot_skip_full_pytest():
    """正式公开发布不得用轻量模式绕过全量 pytest。"""
    result = subprocess.run(
        [
            sys.executable,
            'scripts/verify_release.py',
            '--ci',
            '--public-release',
            '--skip-fulltest',
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert '--public-release 不允许与 --skip-fulltest 组合' in result.stderr


def test_public_release_fails_before_tests_when_license_review_is_pending():
    """许可未获批时即使调用正式命令，也应快速非零退出。"""
    result = subprocess.run(
        [sys.executable, 'scripts/verify_release.py', '--ci', '--public-release'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 1
    output = result.stdout + result.stderr
    assert 'LEGAL_REVIEW_REQUIRED' in output
    assert '仓库必须保持 PRIVATE' in output
