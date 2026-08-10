"""发版门禁自身的失效保护测试。"""
import csv
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import scripts.verify_release as verify_release
from scripts.verify_release import (
    _expected_runtime_data_source,
    _run_with_process_tree_timeout,
    check_publication_authorization,
    check_public_release,
    check_public_tree,
    check_pytest_full,
    check_release_license_surface,
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
    monkeypatch.setattr(
        'scripts.verify_release.PUBLICATION_POLICY',
        repo / 'licensing' / 'publication-policy.json',
    )


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _write_final_rights_bom(repo, rights_bom, *, unsafe_path=None):
    """为已提交 HEAD 生成覆盖全树、哈希按 Git blob 计算的测试清单。"""
    result = subprocess.run(
        ['git', 'ls-tree', '-r', '-z', '--full-tree', 'HEAD'],
        cwd=str(repo),
        capture_output=True,
        check=True,
    )
    fieldnames = [
        'release_path', 'sha256', 'git_blob', 'author_or_owner',
        'employment_context', 'coauthors', 'spdx', 'current_license',
        'relicensing_basis', 'source_risk', 'evidence_refs',
        'target_treatment', 'review_status',
    ]
    rights_bom.parent.mkdir(parents=True, exist_ok=True)
    with rights_bom.open('w', encoding='utf-8', newline='') as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        for raw in result.stdout.split(b'\0'):
            if not raw:
                continue
            metadata, raw_path = raw.split(b'\t', 1)
            _, _, blob_id = metadata.decode('ascii').split(' ', 2)
            release_path = raw_path.decode('utf-8')
            blob = subprocess.run(
                ['git', 'cat-file', 'blob', blob_id],
                cwd=str(repo),
                capture_output=True,
                check=True,
            ).stdout
            status = (
                'NEEDS_REVIEW'
                if release_path == unsafe_path
                else 'OWNER_ATTESTED_WITH_SOURCE_DISCLOSURE'
            )
            writer.writerow({
                'release_path': release_path,
                'sha256': hashlib.sha256(blob).hexdigest(),
                'git_blob': blob_id,
                'author_or_owner': 'heronerar owner attestation',
                'employment_context': 'SOLE_PERSONAL_NON_EMPLOYMENT_OWNER_ATTESTED',
                'coauthors': 'NONE_OWNER_ATTESTED',
                'spdx': 'LicenseRef-OpenGaokao-SAL-1.0',
                'current_license': 'LicenseRef-OpenGaokao-SAL-1.0',
                'relicensing_basis': 'owner approval plus E-COMMON source disclosure',
                'source_risk': 'NONE_IDENTIFIED_AFTER_REVIEW',
                'evidence_refs': 'E-COMMON;E-FINAL',
                'target_treatment': 'LicenseRef-OpenGaokao-SAL-1.0',
                'review_status': status,
            })


def _build_ready_release(
    tmp_path,
    *,
    approval_inside_repo=False,
    rights_inside_repo=False,
    unsafe_rights_path=None,
):
    """生成带外部权属清单和许可人凭据的最小已提交候选。"""
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init', '-q')
    _git(repo, 'config', 'user.name', 'Release Gate Test')
    _git(repo, 'config', 'user.email', 'release-gate@example.invalid')
    signing_key = tmp_path / 'release_signing_key'
    subprocess.run(
        ['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(signing_key)],
        capture_output=True,
        check=True,
    )
    signing_public_key = ' '.join(
        signing_key.with_suffix('.pub').read_text(encoding='utf-8').split()[:2]
    )

    license_path = repo / 'LICENSE'
    license_path.write_text(
        'OpenGaokao Source-Available License 1.0\n'
        'LicenseRef-OpenGaokao-SAL-1.0\n',
        encoding='utf-8',
    )
    license_sha = _sha256(license_path)
    (repo / 'README.md').write_text(
        'source-available\n'
        'Current-License: LicenseRef-OpenGaokao-SAL-1.0\n'
        'Historical-License-Exception: AGPL-3.0-or-later\n',
        encoding='utf-8',
    )
    (repo / 'NOTICE').write_text(
        'Current-License: LicenseRef-OpenGaokao-SAL-1.0\n'
        'Historical-License-Exception: AGPL-3.0-or-later\n',
        encoding='utf-8',
    )
    (repo / 'LICENSING.md').write_text(
        'Current-License: LicenseRef-OpenGaokao-SAL-1.0\n'
        'Historical-License-Exception: AGPL-3.0-or-later\n',
        encoding='utf-8',
    )
    (repo / 'pyproject.toml').write_text(
        '[project]\nlicense = {text = "LicenseRef-OpenGaokao-SAL-1.0"}\n',
        encoding='utf-8',
    )
    required_surfaces = {
        'CONTRIBUTING.md': 'LicenseRef-OpenGaokao-SAL-1.0\n',
        'CLAUDE.md': 'LicenseRef-OpenGaokao-SAL-1.0\n',
        'gaokao/__init__.py': (
            '# SPDX-License-Identifier: LicenseRef-OpenGaokao-SAL-1.0\n'
        ),
        'gaokao/cli.py': (
            '# SPDX-License-Identifier: LicenseRef-OpenGaokao-SAL-1.0\n'
            'import argparse\n'
            'def main():\n'
            '    parser = argparse.ArgumentParser()\n'
            '    parser.add_argument("--accept-license", action="store_true")\n'
            '    args = parser.parse_args()\n'
            '    if not args.accept_license:\n'
            '        parser.error("license acceptance required")\n'
        ),
        'gaokao/api/server.py': (
            '# SPDX-License-Identifier: LicenseRef-OpenGaokao-SAL-1.0\n'
            'import argparse\n'
            'def main():\n'
            '    parser = argparse.ArgumentParser()\n'
            '    parser.add_argument("--accept-license", action="store_true")\n'
            '    args = parser.parse_args()\n'
            '    if not args.accept_license:\n'
            '        parser.error("license acceptance required")\n'
        ),
        'web/index.html': 'LicenseRef-OpenGaokao-SAL-1.0\n',
        'web/js/app.js': 'LicenseRef-OpenGaokao-SAL-1.0\n',
        'tests/test_e2e_api.py': 'LicenseRef-OpenGaokao-SAL-1.0\n',
    }
    for relative, content in required_surfaces.items():
        surface = repo / relative
        surface.parent.mkdir(parents=True, exist_ok=True)
        surface.write_text(content, encoding='utf-8')

    source_policy = json.loads(
        (PROJECT_ROOT / 'licensing/publication-policy.json').read_text(encoding='utf-8')
    )
    source_policy.update({
        'status': 'READY_PENDING_EXTERNAL_RECEIPT',
        'release_target': {
            'repository': 'heronerar/OpenGaokao',
            'license_path': 'LICENSE',
            'license_identifier': 'LicenseRef-OpenGaokao-SAL-1.0',
            'license_sha256': license_sha,
            'release_scope': 'source-only-synthetic-demo',
            'synthetic_example_only': True,
            'real_yunnan_data_included': False,
        },
    })
    source_policy['legal_text_review'].update({
        'derived_publication_text_status': 'OWNER_APPROVAL_REQUIRES_EXTERNAL_RECEIPT',
        'derived_publication_text_sha256': license_sha,
    })
    source_policy['rights_clearance'] = {
        'status': 'RIGHTS_MANIFEST_REQUIRES_EXTERNAL_RECEIPT',
        'publication_allowed_only_with_external_receipt': True,
    }
    source_policy['release_authorization'] = {
        'status': 'READY_PENDING_EXTERNAL_RECEIPT',
        'mechanism': 'external-release-approval-receipt',
        'configured': True,
        'in_repository_self_approval_permitted': False,
        'tag_signature_required': True,
        'tag_signature_format': 'ssh',
        'signing_public_key_status': 'OWNER_CONFIRMED_OUT_OF_BAND',
        'signing_trust_anchor_source': 'owner-confirmed-out-of-band',
        'candidate_generated_key_permitted': False,
        'signing_identity': 'heronerar',
        'signing_public_key': signing_public_key,
        'signing_public_key_fingerprint': verify_release._ssh_public_key_fingerprint(
            signing_public_key
        ),
        'owner_authorization_record_sha256': 'A' * 64,
    }
    policy_path = repo / 'licensing' / 'publication-policy.json'
    policy_path.parent.mkdir()
    policy_path.write_text(json.dumps(source_policy, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    _git(repo, 'add', '.')
    _git(repo, 'commit', '-q', '-m', 'release candidate')
    _git(repo, 'remote', 'add', 'origin', 'https://github.com/heronerar/OpenGaokao.git')

    head = _git(repo, 'rev-parse', 'HEAD').stdout.strip()
    tree = _git(repo, 'rev-parse', 'HEAD^{tree}').stdout.strip()
    commit_time = datetime.fromisoformat(
        _git(repo, 'show', '-s', '--format=%cI', 'HEAD').stdout.strip().replace('Z', '+00:00')
    ).astimezone(timezone.utc)
    approval_time = max(
        datetime.now(timezone.utc),
        commit_time + timedelta(seconds=1),
    )
    rights_bom = (
        repo / '.private' / 'rights-bom.csv'
        if rights_inside_repo
        else tmp_path / 'rights-bom.csv'
    )
    _write_final_rights_bom(repo, rights_bom, unsafe_path=unsafe_rights_path)
    rights_sha = _sha256(rights_bom)
    approval_path = (
        repo / '.private' / 'approval.json'
        if approval_inside_repo
        else tmp_path / 'approval.json'
    )
    approval_path.parent.mkdir(parents=True, exist_ok=True)
    approval = {
        'schema_version': 1,
        'repository': 'heronerar/OpenGaokao',
        'release_commit': head,
        'release_tree': tree,
        'release_tag': 'v1.0.0-sal.1',
        'license_identifier': 'LicenseRef-OpenGaokao-SAL-1.0',
        'license_sha256': license_sha,
        'rights_bom_sha256': rights_sha,
        'release_scope': 'source-only-synthetic-demo',
        'synthetic_example_only': True,
        'real_yunnan_data_included': False,
        'historical_agpl_existing_rights_not_retracted': True,
        'owner_public_id': 'heronerar',
        'owner_decision': 'APPROVE_PUBLIC_RELEASE',
        'owner_approved_at': approval_time.isoformat(),
        'counsel_status': 'OWNER_APPROVED_NOT_COUNSEL_VERIFIED',
        'owner_signing_public_key_sha256': hashlib.sha256(
            signing_public_key.encode('utf-8')
        ).hexdigest().upper(),
        'owner_authorization_record_sha256': 'A' * 64,
    }
    approval_path.write_text(
        json.dumps(approval, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    approval_sha = _sha256(approval_path)
    tag_message = (
        'OpenGaokao public release authorization\n\n'
        f'Release-Approval-SHA256: {approval_sha}\n'
        f'Rights-BOM-SHA256: {rights_sha}\n'
        f'License-SHA256: {license_sha}\n'
    )
    _git(repo, 'config', 'gpg.format', 'ssh')
    _git(repo, 'config', 'user.signingkey', str(signing_key))
    _git(repo, 'tag', '-s', 'v1.0.0-sal.1', '-m', tag_message)
    return repo, rights_bom, approval_path, approval


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


def test_ci_runtime_scope_stays_on_synthetic_example_with_private_db_present(
    tmp_path, monkeypatch
):
    """源码公开验收不因维护者机器碰巧有私有真库而改变证据范围。"""
    repo = tmp_path / 'repo'
    data_dir = repo / 'data'
    data_dir.mkdir(parents=True)
    (data_dir / 'yunnan_gaokao.db').write_bytes(b'private-db-placeholder')
    _use_repo(monkeypatch, repo)

    assert _expected_runtime_data_source('yunnan', True) == 'example'
    assert _expected_runtime_data_source('yunnan', False) == 'yunnan'


def test_public_tree_rejects_forbidden_paths_and_large_file(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    (repo / 'data').mkdir()
    (repo / 'docs').mkdir()
    (repo / 'docs' / 'audit').mkdir()
    (repo / '.private').mkdir()
    (repo / 'data' / 'example.db').write_bytes(b'')
    (repo / '.fuse_hidden0001').write_bytes(b'control')
    (repo / '.env').write_text('TOKEN=placeholder\n', encoding='utf-8')
    (repo / 'deploy.pem').write_text('placeholder\n', encoding='utf-8')
    (repo / '.private' / 'owner-record.md').write_text('private\n', encoding='utf-8')
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
        '.private/owner-record.md',
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


def test_publication_authorization_requires_external_release_materials():
    """READY 只表示可接收外部凭据，仓库状态本身仍不能批准公开。"""
    result = check_publication_authorization()

    assert not result.passed
    assert '缺少 --release-approval' in result.detail


def test_publication_policy_separates_reviewed_draft_from_owner_approved_text():
    """私有律师原稿与许可人批准、尚未律师复核的派生文本必须分开。"""
    policy = json.loads((PROJECT_ROOT / 'licensing/publication-policy.json').read_text(encoding='utf-8'))
    legal_review = policy['legal_text_review']

    assert legal_review['status'] == 'OWNER_REPORTED_COUNSEL_CONFIRMED_UNCHANGED'
    assert legal_review['reviewed_draft_sha256'] == (
        '18405F7503A2F0732122BE6FF7E982C2D821948B75D28335E8E4338800965F69'
    )
    assert legal_review['derived_publication_text_status'] == (
        'OWNER_APPROVAL_REQUIRES_EXTERNAL_RECEIPT'
    )
    assert legal_review['derived_publication_text_sha256'] == (
        '94CA1C665A33F52F1800364A9DD33CFB5025825C9D00F2644DC9BC6AFAAE98FC'
    )
    assert policy['rights_clearance']['status'] == 'RIGHTS_MANIFEST_REQUIRES_EXTERNAL_RECEIPT'
    assert policy['rights_clearance']['publication_allowed_only_with_external_receipt'] is True


def test_publication_policy_binds_owner_authorized_external_signing_key():
    """READY policy 必须绑定仓库外授权记录、公钥和精确指纹。"""
    policy = json.loads(
        (PROJECT_ROOT / 'licensing/publication-policy.json').read_text(encoding='utf-8')
    )
    release_authorization = policy['release_authorization']

    assert release_authorization['signing_public_key_status'] == 'OWNER_CONFIRMED_OUT_OF_BAND'
    assert release_authorization['signing_trust_anchor_source'] == 'owner-confirmed-out-of-band'
    assert release_authorization['candidate_generated_key_permitted'] is False
    assert verify_release._ssh_public_key_fingerprint(
        release_authorization['signing_public_key']
    ) == release_authorization['signing_public_key_fingerprint']
    assert len(release_authorization['owner_authorization_record_sha256']) == 64


@pytest.mark.parametrize(
    ('field', 'bad_value', 'expected_detail'),
    [
        ('qualified_nonprofit_classroom_display_allowed', False, '商业硬约束缺失'),
        ('qualified_noncommercial_research_allowed', False, '商业硬约束缺失'),
        ('single_personal_report_limited_sharing_allowed', False, '商业硬约束缺失'),
        ('significant_standard_terms_require_affirmative_acceptance', False, '商业硬约束缺失'),
        ('no_express_patent_license', False, '商业硬约束缺失'),
        ('free_use_liability_cap_cny', 0, '责任上限或一般违约补救期'),
        ('general_breach_cure_period_business_days', 0, '责任上限或一般违约补救期'),
    ],
)
def test_publication_authorization_enforces_every_persisted_license_term(
    tmp_path, monkeypatch, field, bad_value, expected_detail
):
    """任何已确认许可条件漂移都必须在读取外部批准前失败关闭。"""
    policy = json.loads((PROJECT_ROOT / 'licensing/publication-policy.json').read_text(encoding='utf-8'))
    policy['required_terms'][field] = bad_value
    candidate = tmp_path / 'publication-policy.json'
    candidate.write_text(json.dumps(policy), encoding='utf-8')
    monkeypatch.setattr(verify_release, 'PUBLICATION_POLICY', candidate)

    result = check_publication_authorization()

    assert not result.passed
    assert expected_detail in result.detail


def test_publication_authorization_rejects_derived_text_self_approval(tmp_path, monkeypatch):
    """仓库内补一个派生许可证哈希不得冒充律师复核或发布授权。"""
    policy = json.loads((PROJECT_ROOT / 'licensing/publication-policy.json').read_text(encoding='utf-8'))
    policy['legal_text_review']['derived_publication_text_status'] = 'COUNSEL_VERIFIED'
    policy['legal_text_review']['derived_publication_text_sha256'] = '0' * 64
    candidate = tmp_path / 'publication-policy.json'
    candidate.write_text(json.dumps(policy), encoding='utf-8')
    monkeypatch.setattr(verify_release, 'PUBLICATION_POLICY', candidate)

    result = check_publication_authorization()

    assert not result.passed
    assert '派生许可证必须绑定精确 SHA-256' in result.detail


@pytest.mark.parametrize(
    ('mutation', 'expected_detail'),
    [
        ('rights', '权属状态未要求外部完整清单'),
        ('release', '仓库外发布批准机制未正确配置'),
        ('all', '仓库内策略不能自我批准'),
    ],
)
def test_publication_authorization_rejects_repository_field_escalation(
    tmp_path, monkeypatch, mutation, expected_detail
):
    """权属、发布授权或全部字段一起自我升级都不能开放发布。"""
    policy = json.loads((PROJECT_ROOT / 'licensing/publication-policy.json').read_text(encoding='utf-8'))
    if mutation in {'rights', 'all'}:
        policy['rights_clearance'].update({
            'status': 'RIGHTS_ACCEPTED_FOR_RELEASE',
            'publication_allowed': True,
            'current_worktree_evidence_complete': True,
        })
    if mutation in {'release', 'all'}:
        policy['release_authorization'].update({
            'status': 'GRANTED',
            'configured': True,
        })
    if mutation == 'all':
        policy['status'] = 'APPROVED'
        policy['legal_text_review'].update({
            'derived_publication_text_status': 'COUNSEL_VERIFIED',
            'derived_publication_text_sha256': '0' * 64,
        })
    candidate = tmp_path / 'publication-policy.json'
    candidate.write_text(json.dumps(policy), encoding='utf-8')
    monkeypatch.setattr(verify_release, 'PUBLICATION_POLICY', candidate)

    result = check_publication_authorization()

    assert not result.passed
    assert expected_detail in result.detail


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


def test_publication_authorization_accepts_matching_external_receipt(tmp_path, monkeypatch):
    """正向路径必须把外部许可人批准绑定到提交、tree、LICENSE 和 Rights BOM。"""
    repo, rights_bom, approval_path, _ = _build_ready_release(tmp_path)
    _use_repo(monkeypatch, repo)

    result = check_publication_authorization(approval_path, rights_bom)

    assert result.passed, result.detail
    assert '许可人 SSH 签名 Tag 已绑定仓库外凭据' in result.detail


def test_publication_authorization_rejects_signing_fingerprint_drift(tmp_path, monkeypatch):
    """policy 声明的公钥指纹必须由实际公钥字节重新计算。"""
    repo, rights_bom, approval_path, _ = _build_ready_release(tmp_path)
    policy_path = repo / 'licensing/publication-policy.json'
    policy = json.loads(policy_path.read_text(encoding='utf-8'))
    policy['release_authorization']['signing_public_key_fingerprint'] = 'SHA256:not-the-key'
    policy_path.write_text(json.dumps(policy), encoding='utf-8')
    _use_repo(monkeypatch, repo)

    result = check_publication_authorization(approval_path, rights_bom)

    assert not result.passed
    assert '公钥指纹与信任锚不一致' in result.detail


@pytest.mark.parametrize(
    ('field', 'bad_value'),
    [
        ('repository', 'someone/else'),
        ('release_commit', '0' * 40),
        ('release_tree', '1' * 40),
        ('license_sha256', '2' * 64),
        ('rights_bom_sha256', '3' * 64),
        ('release_scope', 'real-data-service'),
        ('owner_authorization_record_sha256', '4' * 64),
    ],
)
def test_publication_authorization_rejects_external_receipt_mismatch(
    tmp_path, monkeypatch, field, bad_value
):
    """任一承重字段不匹配都必须拒绝，不能只验收一个批准词。"""
    repo, rights_bom, approval_path, approval = _build_ready_release(tmp_path)
    approval[field] = bad_value
    approval_path.write_text(
        json.dumps(approval, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    _use_repo(monkeypatch, repo)

    result = check_publication_authorization(approval_path, rights_bom)

    assert not result.passed
    assert field in result.detail


def test_publication_authorization_rejects_duplicate_approval_json_key(tmp_path, monkeypatch):
    """批准 JSON 的重复键不得让人工和机器看到不同仓库值。"""
    repo, rights_bom, approval_path, _ = _build_ready_release(tmp_path)
    original = approval_path.read_text(encoding='utf-8')
    approval_path.write_text(
        original.replace('{\n', '{\n  "repository": "someone/else",\n', 1),
        encoding='utf-8',
    )
    _use_repo(monkeypatch, repo)

    result = check_publication_authorization(approval_path, rights_bom)

    assert not result.passed
    assert '无法解析' in result.detail


def test_publication_authorization_rejects_duplicate_rights_bom_header(
    tmp_path, monkeypatch
):
    """Rights BOM 重复表头不得静默覆盖前一列。"""
    repo, rights_bom, approval_path, _ = _build_ready_release(tmp_path)
    lines = rights_bom.read_text(encoding='utf-8').splitlines()
    lines[0] += ',release_path'
    rights_bom.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    _use_repo(monkeypatch, repo)

    result = check_publication_authorization(approval_path, rights_bom)

    assert not result.passed
    assert '表头包含重复字段' in result.detail


def test_publication_authorization_rejects_repository_internal_approval(tmp_path, monkeypatch):
    """仓库内 ignored/untracked JSON 也不能形成仓库外信任根。"""
    repo, rights_bom, approval_path, _ = _build_ready_release(
        tmp_path,
        approval_inside_repo=True,
    )
    _use_repo(monkeypatch, repo)

    result = check_publication_authorization(approval_path, rights_bom)

    assert not result.passed
    assert '必须位于仓库目录之外' in result.detail


def test_publication_authorization_rejects_repository_internal_rights_bom(tmp_path, monkeypatch):
    """Rights BOM 也必须严格位于仓库目录之外。"""
    repo, rights_bom, approval_path, _ = _build_ready_release(
        tmp_path,
        rights_inside_repo=True,
    )
    _use_repo(monkeypatch, repo)

    result = check_publication_authorization(approval_path, rights_bom)

    assert not result.passed
    assert '必须位于仓库目录之外' in result.detail


def test_publication_authorization_rejects_incomplete_rights_bom(tmp_path, monkeypatch):
    """仅列部分文件的一行式 Rights BOM 不能放行。"""
    repo, rights_bom, approval_path, _ = _build_ready_release(tmp_path)
    rows = list(csv.DictReader(rights_bom.read_text(encoding='utf-8').splitlines()))
    with rights_bom.open('w', encoding='utf-8', newline='') as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows[:-1])
    _use_repo(monkeypatch, repo)

    result = check_publication_authorization(approval_path, rights_bom)

    assert not result.passed
    assert '缺少 1 个 HEAD 文件' in result.detail


def test_publication_authorization_rejects_unresolved_rights_status(tmp_path, monkeypatch):
    """Rights BOM 任一 NEEDS_REVIEW 都必须失败关闭。"""
    repo, rights_bom, approval_path, _ = _build_ready_release(
        tmp_path,
        unsafe_rights_path='LICENSE',
    )
    _use_repo(monkeypatch, repo)

    result = check_publication_authorization(approval_path, rights_bom)

    assert not result.passed
    assert 'review_status=NEEDS_REVIEW 不可发布' in result.detail


def test_publication_authorization_rejects_empty_owned_license_fields(tmp_path, monkeypatch):
    """自有文件的空 SPDX/current_license 不能靠其他非空列蒙混过关。"""
    repo, rights_bom, approval_path, _ = _build_ready_release(tmp_path)
    rows = list(csv.DictReader(rights_bom.read_text(encoding='utf-8').splitlines()))
    for row in rows:
        row['spdx'] = ''
        row['current_license'] = ''
    with rights_bom.open('w', encoding='utf-8', newline='') as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _use_repo(monkeypatch, repo)

    result = check_publication_authorization(approval_path, rights_bom)

    assert not result.passed
    assert 'current_license 仍为空或待核验' in result.detail


def test_public_release_data_boundary_rejects_database_sidecars(tmp_path, monkeypatch):
    """没有主库文件时，遗留 WAL/SHM 也必须阻止源码候选验收。"""
    repo = tmp_path / 'repo'
    data = repo / 'data'
    data.mkdir(parents=True)
    (data / 'example.db').write_bytes(b'synthetic placeholder')
    (data / 'yunnan_gaokao.db-shm').write_bytes(b'private sidecar')
    _use_repo(monkeypatch, repo)

    detail = verify_release._public_release_local_data_error()

    assert detail is not None
    assert 'data/yunnan_gaokao.db-shm' in detail


def test_public_release_isolation_rejects_ignored_private_directory(tmp_path, monkeypatch):
    """即使未跟踪，.private 也不得伴随公开候选工作树。"""
    repo = tmp_path / 'repo'
    (repo / '.private').mkdir(parents=True)
    (repo / '.private' / 'legal-record.md').write_text('private\n', encoding='utf-8')
    _use_repo(monkeypatch, repo)

    detail = verify_release._public_release_local_data_error()

    assert detail is not None
    assert '.private/' in detail


def test_publication_authorization_verifies_origin_repository(tmp_path, monkeypatch):
    """批准 JSON 中的仓库名不能替代真实 origin 检查。"""
    repo, rights_bom, approval_path, _ = _build_ready_release(tmp_path)
    _git(repo, 'remote', 'set-url', 'origin', 'https://github.com/someone/else.git')
    _use_repo(monkeypatch, repo)

    result = check_publication_authorization(approval_path, rights_bom)

    assert not result.passed
    assert 'origin 远端不是目标 GitHub 仓库' in result.detail


def test_publication_authorization_verifies_release_tag_points_to_head(tmp_path, monkeypatch):
    """批准中声明的固定 Tag 必须真实存在并指向候选 HEAD。"""
    repo, rights_bom, approval_path, _ = _build_ready_release(tmp_path)
    _git(repo, 'tag', '-d', 'v1.0.0-sal.1')
    _use_repo(monkeypatch, repo)

    result = check_publication_authorization(approval_path, rights_bom)

    assert not result.passed
    assert 'release_tag' in result.detail


def test_publication_authorization_rejects_unsigned_release_tag(tmp_path, monkeypatch):
    """同名 lightweight Tag 即使指向 HEAD 也不能替代许可人 SSH 签名。"""
    repo, rights_bom, approval_path, _ = _build_ready_release(tmp_path)
    _git(repo, 'tag', '-d', 'v1.0.0-sal.1')
    _git(repo, 'tag', 'v1.0.0-sal.1')
    _use_repo(monkeypatch, repo)

    result = check_publication_authorization(approval_path, rights_bom)

    assert not result.passed
    assert '带 SSH 签名的 annotated tag' in result.detail


def test_publication_authorization_rejects_conflicting_signed_tag_marker(
    tmp_path, monkeypatch
):
    """签名 Tag 内同名哈希字段必须唯一，不能同时放正确值和冲突值。"""
    repo, rights_bom, approval_path, approval = _build_ready_release(tmp_path)
    _git(repo, 'tag', '-d', 'v1.0.0-sal.1')
    message = (
        'OpenGaokao public release authorization\n\n'
        f'Release-Approval-SHA256: {_sha256(approval_path)}\n'
        'Release-Approval-SHA256: ' + ('0' * 64) + '\n'
        f'Rights-BOM-SHA256: {_sha256(rights_bom)}\n'
        f'License-SHA256: {approval["license_sha256"]}\n'
    )
    _git(repo, 'tag', '-s', 'v1.0.0-sal.1', '-m', message)
    _use_repo(monkeypatch, repo)

    result = check_publication_authorization(approval_path, rights_bom)

    assert not result.passed
    assert '未唯一绑定' in result.detail


def test_signed_release_tag_binds_exact_approval_bytes(tmp_path, monkeypatch):
    """批准 JSON 即使仅多一个空行，也不再是签名 Tag 绑定的精确回执。"""
    repo, rights_bom, approval_path, _ = _build_ready_release(tmp_path)
    with approval_path.open('a', encoding='utf-8') as target:
        target.write('\n')
    _use_repo(monkeypatch, repo)

    result = check_publication_authorization(approval_path, rights_bom)

    assert not result.passed
    assert '签名 Tag 未唯一绑定' in result.detail


def test_publication_authorization_rejects_invalid_owner_approval_time(tmp_path, monkeypatch):
    """owner_approved_at 必须是带时区且不早于候选提交的 ISO 时间。"""
    repo, rights_bom, approval_path, approval = _build_ready_release(tmp_path)
    approval['owner_approved_at'] = 'T'
    approval_path.write_text(json.dumps(approval), encoding='utf-8')
    _use_repo(monkeypatch, repo)

    result = check_publication_authorization(approval_path, rights_bom)

    assert not result.passed
    assert 'owner_approved_at' in result.detail


def test_ready_candidate_uses_sal_surface_instead_of_agpl_gate(tmp_path, monkeypatch):
    """SAL 候选不得在授权通过后又被旧 AGPL 专用检查必然阻断。"""
    repo, rights_bom, approval_path, _ = _build_ready_release(tmp_path)
    pii = tmp_path / 'pii.txt'
    pii.write_text('private-literal\n', encoding='utf-8')
    _use_repo(monkeypatch, repo)
    passed = verify_release.CheckResult('test', True, 'ok')
    monkeypatch.setattr(verify_release, 'check_pytest_full', lambda _: passed)
    monkeypatch.setattr(verify_release, 'check_runtime_e2e', lambda *_: passed)
    monkeypatch.setattr(verify_release, 'check_public_release', lambda *_: passed)
    monkeypatch.setattr(
        verify_release,
        'check_agpl_license',
        lambda: pytest.fail('SAL 正向流程不应调用 AGPL 专用检查'),
    )
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'verify_release.py', '--ci', '--public-release',
            '--pii-denylist', str(pii),
            '--rights-bom', str(rights_bom),
            '--release-approval', str(approval_path),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        verify_release.main()

    assert exit_info.value.code == 0
    assert check_release_license_surface().passed


def test_sal_surface_rejects_stale_current_agpl_claim(tmp_path, monkeypatch):
    """追加 SAL 标记不能掩盖 README 仍宣称当前 AGPL。"""
    repo, _, _, _ = _build_ready_release(tmp_path)
    with (repo / 'README.md').open('a', encoding='utf-8') as target:
        target.write('根目录 `LICENSE` 目前仍是 AGPL\n')
    _use_repo(monkeypatch, repo)

    result = check_release_license_surface()

    assert not result.passed
    assert '仍包含当前 AGPL/PRIVATE 阶段声明' in result.detail


@pytest.mark.parametrize('relative', ['pyproject.toml', 'gaokao/api/server.py'])
def test_sal_surface_rejects_missing_required_surface(tmp_path, monkeypatch, relative):
    """包元数据或真实入口被删掉时不得把缺失误当成已迁移。"""
    repo, _, _, _ = _build_ready_release(tmp_path)
    (repo / relative).unlink()
    _use_repo(monkeypatch, repo)

    result = check_release_license_surface()

    assert not result.passed
    assert '缺少 pyproject.toml' in result.detail or '仍未切换 SAL 的表面' in result.detail


def test_sal_surface_requires_acceptance_parameter_on_real_entries(tmp_path, monkeypatch):
    """仅写 SAL 标识不能替代 CLI/服务端的主动接受入口。"""
    repo, _, _, _ = _build_ready_release(tmp_path)
    cli = repo / 'gaokao/cli.py'
    cli.write_text(
        cli.read_text(encoding='utf-8').replace('--accept-license', ''),
        encoding='utf-8',
    )
    _use_repo(monkeypatch, repo)

    result = check_release_license_surface()

    assert not result.passed
    assert '缺少显式许可接受参数' in result.detail


@pytest.mark.parametrize('relative', ['gaokao/cli.py', 'gaokao/api/server.py'])
def test_sal_surface_rejects_acceptance_text_without_failure_guard(
    tmp_path, monkeypatch, relative
):
    """帮助文本保留参数名时，也不能掩盖实际失败关闭分支被删除。"""
    repo, _, _, _ = _build_ready_release(tmp_path)
    entry = repo / relative
    entry.write_text(
        entry.read_text(encoding='utf-8').replace(
            '    if not args.accept_license:\n',
            '    if False:  # removed acceptance guard\n',
        ),
        encoding='utf-8',
    )
    _use_repo(monkeypatch, repo)

    result = check_release_license_surface()

    assert not result.passed
    assert '缺少显式许可接受参数' in result.detail


@pytest.mark.parametrize('relative', ['README.md', 'NOTICE', 'LICENSING.md'])
def test_sal_surface_rejects_conflicting_current_license_marker(
    tmp_path, monkeypatch, relative
):
    """SAL 标记存在时，第二个 Current-License 也必须失败关闭。"""
    repo, _, _, _ = _build_ready_release(tmp_path)
    with (repo / relative).open('a', encoding='utf-8') as target:
        target.write('Current-License: AGPL-3.0-or-later\n')
    _use_repo(monkeypatch, repo)

    result = check_release_license_surface()

    assert not result.passed
    assert 'Current-License 必须唯一且严格等于' in result.detail


@pytest.mark.parametrize('relative', ['README.md', 'NOTICE', 'LICENSING.md'])
def test_sal_surface_rejects_indented_case_variant_license_markers(
    tmp_path, monkeypatch, relative
):
    """Unicode、Markdown 包装或大小写变化不能隐藏第二套许可标记。"""
    repo, _, _, _ = _build_ready_release(tmp_path)
    _use_repo(monkeypatch, repo)
    path = repo / relative
    original = path.read_text(encoding='utf-8')
    variants = [
        (' current-license: AGPL-3.0-or-later\n', 'Current-License'),
        ('\u00a0Current-License: AGPL-3.0-or-later\n', 'Current-License'),
        ('\u2003Current-License: AGPL-3.0-or-later\n', 'Current-License'),
        ('> Current-License: AGPL-3.0-or-later\n', 'Current-License'),
        ('- Current-License: AGPL-3.0-or-later\n', 'Current-License'),
        ('Current-License： AGPL-3.0-or-later\n', 'Current-License'),
        ('Current‑License: AGPL-3.0-or-later\n', 'Current-License'),
        ('Current-\u200bLicense: AGPL-3.0-or-later\n', 'Current-License'),
        ('Current-\u00adLicense: AGPL-3.0-or-later\n', 'Current-License'),
        ('Current\\-License: AGPL-3.0-or-later\n', 'Current-License'),
        ('Current-**License**: AGPL-3.0-or-later\n', 'Current-License'),
        ('Current&#45;License: AGPL-3.0-or-later\n', 'Current-License'),
        ('\u00a0Historical-License-Exception: AGPL-3.0-only\n', 'Historical-License-Exception'),
        ('Historical‑License-Exception: AGPL-3.0-only\n', 'Historical-License-Exception'),
    ]
    for marker, field in variants:
        path.write_text(original + marker, encoding='utf-8')
        result = check_release_license_surface()
        assert not result.passed, f'{relative} accepted conflicting marker {marker!r}'
        assert f'{field} 必须唯一且严格等于' in result.detail


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


def test_public_release_requires_ci_synthetic_scope():
    """公开源码发行必须固定为 --ci 合成示例范围。"""
    result = subprocess.run(
        [sys.executable, 'scripts/verify_release.py', '--public-release'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert '--public-release 必须与 --ci 组合' in result.stderr


def test_public_release_cannot_change_province_to_bypass_data_boundary():
    """公开模式固定云南，不能用不存在的省份名跳过真实库扫描。"""
    result = subprocess.run(
        [
            sys.executable, 'scripts/verify_release.py', '--ci',
            '--public-release', '--province', 'example',
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert '当前只允许 --province yunnan' in result.stderr


def test_public_release_fails_before_tests_without_external_receipts():
    """READY policy 缺仓库外回执时，正式命令仍应快速非零退出。"""
    result = subprocess.run(
        [sys.executable, 'scripts/verify_release.py', '--ci', '--public-release'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 1
    output = result.stdout + result.stderr
    assert '缺少 --release-approval' in output
