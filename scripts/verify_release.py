# SPDX-License-Identifier: LicenseRef-OpenGaokao-SAL-1.0
# Copyright (C) 2026 OpenGaokao Contributors
"""OpenGaokao 发布前本地验证门禁（单一入口）

移植自 YGCare/scripts/verify_release.py，按源码可见版定位改造：
    - 砍掉 YGCare 商业专属检查（飞书插件 dist 黑名单、小程序交付面边界）
    - 换上本地隐私门禁（零外发请求）与当前许可证全表面检查
    - 数据相关检查按省解析（--province）

任何上线/发版（打 git tag）前应跑通。任何一步失败，整个脚本以非 0 退出码结束，
可直接作为 CI 单一门禁调用。

检查项：
    ▶ pytest 全套（不能 failed/error，允许 skipped）
    ▶ 真实运行入口（启动 Flask 进程，检查 Web + 核心推荐 + 数据源标识）
    ▶ 公开树检查（拒绝数据库/密钥/内部文档/异常大文件）
    ▶ post_import_validation 数据完整性（科类标签门禁 + 覆盖率快照）
    ▶ v_enroll_detail 物化表新鲜度（逐年 1:1 对齐 enroll_detail + 含 norm_subject）
    ▶ 本地隐私门禁（gaokao/ 内不得出现对外发网络请求 —— 兑现 README"本地运行"承诺）
    ▶ 当前许可证声明（AGPL 历史阶段或 SAL 固定发行表面）
    ▶ 发布授权（仓库外 Rights BOM、批准回执与 SSH 签名 Tag）

用法：
    python scripts/verify_release.py                       # 默认 yunnan，全套
    python scripts/verify_release.py --province yunnan
    python scripts/verify_release.py --skip-fulltest       # 跳过 pytest（轻量检查）
    python scripts/verify_release.py --ci --public-release \
      --pii-denylist <私有文件> \
      --rights-bom <仓库外最终权属清单> \
      --release-approval <仓库外许可人批准JSON>
"""
from __future__ import annotations

import argparse
import ast
import base64
import binascii
import csv
import hashlib
import html
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PUBLICATION_POLICY = PROJECT_ROOT / 'licensing' / 'publication-policy.json'
_HISTORICAL_PUBLIC_BOUNDARY_CANDIDATE = 'bf1805e6979b6c5022944ce58829e9f27fcabc0c'
_COUNSEL_REVIEWED_DRAFT_SHA256 = (
    '18405F7503A2F0732122BE6FF7E982C2D821948B75D28335E8E4338800965F69'
)
_RELEASE_REPOSITORY = 'heronerar/OpenGaokao'
_SAL_LICENSE_IDENTIFIER = 'LicenseRef-OpenGaokao-SAL-1.0'
_SOURCE_RELEASE_SCOPE = 'source-only-synthetic-demo'

sys.path.insert(0, str(Path(__file__).resolve().parent))
import create_views  # 复用 DEDUP_BELOW_YEAR，保证新鲜度判定与建视图口径一致


class CheckResult:
    def __init__(self, name: str, passed: bool, detail: str = ''):
        self.name = name
        self.passed = passed
        self.detail = detail


_PUBLIC_MAX_FILE_BYTES = 10 * 1024 * 1024
_PUBLIC_INTERNAL_PATHS = {
    'docs/opengaokao_risk_analysis.md',
    'docs/opengaokao_executive_summary.md',
    'docs/opengaokao_decision_matrix.md',
    'docs/audit_report.md',
    'docs/business_model.md',
    'docs/data-table.md',
    'docs/province-priority.md',
    'docs/audit/01_full_audit_20260612.md',
    'docs/audit/02_operations_5m1e_20260614.md',
    'docs/audit/03_data_quality_2020_2022_20260614.md',
    'docs/audit/04_full_audit_20260614.md',
}
_PUBLIC_DB_SUFFIXES = (
    '.db', '.sqlite', '.sqlite3',
    '.db-wal', '.db-shm', '.db-journal',
    '.sqlite-wal', '.sqlite-shm', '.sqlite-journal',
    '.sqlite3-wal', '.sqlite3-shm', '.sqlite3-journal',
)
_PUBLIC_PRIVATE_KEY_SUFFIXES = ('.key', '.pem', '.p12', '.pfx', '.jks', '.keystore')
_PUBLIC_PRIVATE_KEY_NAMES = {'id_rsa', 'id_dsa', 'id_ecdsa', 'id_ed25519'}
_PUBLIC_SECRET_NAMES = {
    'credentials.json', 'secrets.json', 'secret.json',
    'service-account.json', 'service_account.json',
}


def _run_git(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
    """运行 Git 并保留 NUL 分隔输出；调用方决定哪些错误可接受。"""
    return subprocess.run(
        ['git', '-c', 'core.quotepath=false', *args],
        cwd=str(PROJECT_ROOT),
        input=None if input_text is None else input_text.encode('utf-8'),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _decode_git_path(value: bytes) -> str:
    return value.decode('utf-8', errors='surrogateescape')


def _git_root_error() -> str | None:
    proc = _run_git(['rev-parse', '--show-toplevel'])
    if proc.returncode != 0:
        return '当前目录不是可验证的 Git 仓库'
    try:
        actual = Path(_decode_git_path(proc.stdout).strip()).resolve()
        expected = PROJECT_ROOT.resolve()
    except (OSError, RuntimeError, ValueError):
        return '无法解析 Git 仓库根目录'
    if actual != expected:
        return f'Git 根目录不符：{actual}'
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _ssh_public_key_fingerprint(public_key: str) -> str | None:
    """按 OpenSSH SHA256 口径计算无注释公钥指纹。"""
    parts = public_key.split()
    if len(parts) != 2 or not parts[0].startswith('ssh-'):
        return None
    try:
        raw_key = base64.b64decode(parts[1], validate=True)
    except (binascii.Error, ValueError):
        return None
    digest = base64.b64encode(hashlib.sha256(raw_key).digest()).decode('ascii').rstrip('=')
    return f'SHA256:{digest}'


def _load_json_without_duplicate_keys(text: str):
    """解析关键发布 JSON；重复键必须失败，避免人工与机器读取不同值。"""
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'duplicate JSON key: {key}')
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=reject_duplicates)


def _parse_iso_datetime(value: str) -> datetime:
    """解析 ISO 时间；兼容 Python 3.10 不接受 Git `%cI` 的 `Z` 后缀。"""
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _license_acceptance_gate_error(path: Path) -> str | None:
    """核验入口确实定义布尔参数，并在 main 中以 parser.error 失败关闭。"""
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, SyntaxError):
        return '无法解析入口源码'
    main = next(
        (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main'),
        None,
    )
    if main is None:
        return '缺少 main 入口'

    has_flag = False
    has_guard = False
    for node in ast.walk(main):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (
                node.func.attr == 'add_argument'
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == '--accept-license'
                and any(
                    keyword.arg == 'action'
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value == 'store_true'
                    for keyword in node.keywords
                )
            ):
                has_flag = True
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.UnaryOp)
            and isinstance(node.test.op, ast.Not)
            and isinstance(node.test.operand, ast.Attribute)
            and isinstance(node.test.operand.value, ast.Name)
            and node.test.operand.value.id == 'args'
            and node.test.operand.attr == 'accept_license'
        ):
            has_parser_error = any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id == 'parser'
                and child.func.attr == 'error'
                for statement in node.body
                for child in ast.walk(statement)
            )
            if has_parser_error:
                has_guard = True
    if not has_flag:
        return '缺少 store_true 的 --accept-license 参数定义'
    if not has_guard:
        return '缺少 args.accept_license 的 parser.error 失败关闭分支'
    return None


def _resolve_untracked_file(path: Path | None, label: str) -> tuple[Path | None, str | None]:
    """解析严格位于仓库目录之外的发布凭据。"""
    if path is None:
        return None, f'缺少 --{label}'
    lexical = path.expanduser()
    if not lexical.is_absolute():
        lexical = PROJECT_ROOT / lexical
    lexical = Path(os.path.abspath(lexical))
    try:
        resolved = lexical.resolve(strict=True)
    except (OSError, RuntimeError):
        return None, f'{label} 文件不存在：{path}'
    if not resolved.is_file():
        return None, f'{label} 不是普通文件：{resolved}'

    try:
        resolved.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        pass
    else:
        return None, f'{label} 必须位于仓库目录之外，仓库内忽略或未跟踪文件也不能作为信任根'
    return resolved, None


def _normalize_github_repository(remote_url: str) -> str | None:
    """把常见 GitHub HTTPS/SSH origin 规范化为 owner/repository。"""
    value = remote_url.strip().replace('\\', '/')
    match = re.fullmatch(
        r'(?:https?://github\.com/|git@github\.com:|ssh://git@github\.com/)'
        r'([^/]+/[^/]+?)(?:\.git)?/?',
        value,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else None


def _head_tree_entries() -> tuple[dict[str, str] | None, str | None]:
    """返回 HEAD 发布树的 path -> Git object id。"""
    proc = _run_git(['ls-tree', '-r', '-z', '--full-tree', 'HEAD'])
    if proc.returncode != 0:
        return None, '无法读取候选 HEAD tree'
    entries: dict[str, str] = {}
    for raw in proc.stdout.split(b'\0'):
        if not raw:
            continue
        try:
            metadata, raw_path = raw.split(b'\t', 1)
            mode, object_type, object_id = metadata.decode('ascii').split(' ', 2)
            path = _decode_git_path(raw_path)
        except (ValueError, UnicodeError):
            return None, '候选 HEAD tree 输出无法解析'
        if object_type != 'blob' or mode == '160000':
            return None, f'Rights BOM 暂不支持非普通文件对象：{path}'
        entries[path] = object_id
    return entries, None


def _rights_bom_error(path: Path) -> str | None:
    """验证最终 Rights BOM 覆盖 HEAD 全树且没有待审或占位权属。"""
    tree, tree_error = _head_tree_entries()
    if tree_error:
        return tree_error
    assert tree is not None
    required_fields = {
        'release_path', 'sha256', 'git_blob', 'author_or_owner',
        'employment_context', 'coauthors', 'spdx', 'current_license',
        'relicensing_basis', 'source_risk', 'evidence_refs',
        'target_treatment', 'review_status',
    }
    try:
        with path.open('r', encoding='utf-8-sig', newline='') as source:
            reader = csv.DictReader(source)
            if not reader.fieldnames or not required_fields.issubset(reader.fieldnames):
                missing = sorted(required_fields - set(reader.fieldnames or ()))
                return 'rights-bom 缺少字段：' + '、'.join(missing)
            if len(reader.fieldnames) != len(set(reader.fieldnames)):
                return 'rights-bom 表头包含重复字段'
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error):
        return 'rights-bom 无法解析为 UTF-8 CSV'

    seen: set[str] = set()
    errors: list[str] = []
    allowed_statuses = {
        'OWNED_VERIFIED',
        'OWNER_ATTESTED_WITH_SOURCE_DISCLOSURE',
        'THIRD_PARTY_SEPARATE_LICENSE',
    }
    bad_markers = ('UNKNOWN', 'NOT_VERIFIED', 'PENDING', 'NEEDS_REVIEW')
    evidence_fields = (
        'author_or_owner', 'employment_context', 'coauthors',
        'current_license', 'relicensing_basis', 'source_risk', 'evidence_refs',
    )
    for row_number, row in enumerate(rows, start=2):
        if None in row:
            errors.append(f'第{row_number}行包含没有表头的额外字段')
            continue
        release_path = (row.get('release_path') or '').strip().replace('\\', '/')
        if (
            not release_path
            or release_path.startswith('/')
            or '..' in Path(release_path).parts
            or release_path in seen
        ):
            errors.append(f'第{row_number}行 release_path 无效或重复')
            continue
        seen.add(release_path)
        expected_blob = tree.get(release_path)
        if expected_blob is None:
            errors.append(f'{release_path}: 不在候选 HEAD tree')
            continue
        if (row.get('git_blob') or '').strip().lower() != expected_blob.lower():
            errors.append(f'{release_path}: git_blob 与候选 HEAD 不符')
        blob = _run_git(['cat-file', 'blob', expected_blob])
        expected_sha = hashlib.sha256(blob.stdout).hexdigest() if blob.returncode == 0 else None
        actual_sha = (row.get('sha256') or '').strip().lower()
        if expected_sha is None or actual_sha != expected_sha:
            errors.append(f'{release_path}: sha256 与候选 Git blob 不符')

        status = (row.get('review_status') or '').strip()
        if status not in allowed_statuses:
            errors.append(f'{release_path}: review_status={status or "MISSING"} 不可发布')
        for field in evidence_fields:
            value = (row.get(field) or '').strip()
            upper = value.upper()
            if not value or any(marker in upper for marker in bad_markers):
                errors.append(f'{release_path}: {field} 仍为空或待核验')
                break
        treatment = (row.get('target_treatment') or '').strip()
        if status in {'OWNED_VERIFIED', 'OWNER_ATTESTED_WITH_SOURCE_DISCLOSURE'}:
            spdx = (row.get('spdx') or '').strip()
            current_license = (row.get('current_license') or '').strip()
            if (
                treatment != _SAL_LICENSE_IDENTIFIER
                or current_license != _SAL_LICENSE_IDENTIFIER
                or spdx not in {_SAL_LICENSE_IDENTIFIER, 'NOT_APPLICABLE'}
            ):
                errors.append(f'{release_path}: 自有内容 SPDX/current_license/target_treatment 未绑定 SAL')
        elif status == 'THIRD_PARTY_SEPARATE_LICENSE':
            spdx = (row.get('spdx') or '').strip().upper()
            if spdx in {'', 'MISSING', 'UNKNOWN'} or treatment != 'RETAIN_SEPARATE_LICENSE':
                errors.append(f'{release_path}: 第三方内容缺独立 SPDX 或保留许可处理')

    missing_paths = sorted(set(tree) - seen)
    if missing_paths:
        errors.append(f'缺少 {len(missing_paths)} 个 HEAD 文件：' + '、'.join(missing_paths[:5]))
    if errors:
        return 'Rights BOM 未关闭：' + '；'.join(errors[:8])
    return None


def _public_release_local_data_error() -> str | None:
    """公开源码验收不得携带 .private 或真实数据库；仅允许 data/example.db。"""
    if (PROJECT_ROOT / '.private').exists():
        return '隔离候选工作树仍含 .private/ 私有材料目录'
    data_dir = PROJECT_ROOT / 'data'
    if not data_dir.exists():
        return None
    blocked = []
    for path in data_dir.rglob('*'):
        if not path.is_file():
            continue
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        if relative == 'data/example.db':
            continue
        if path.name.lower().endswith(_PUBLIC_DB_SUFFIXES):
            blocked.append(relative)
    if blocked:
        return (
            '隔离候选工作树仍含真实/未知数据库或 sidecar：'
            + '、'.join(sorted(blocked)[:8])
        )
    return None


def _signed_release_tag_error(
    release_tag: str,
    approval_sha: str,
    rights_sha: str,
    license_sha: str,
    release_authorization: dict,
) -> str | None:
    """验证 SSH 签名 Tag，并把 Tag 签名绑定到外部回执、BOM 与 LICENSE。"""
    if release_authorization.get('tag_signature_format') != 'ssh':
        return '发布 Tag 未配置 SSH 签名验证'
    identity = release_authorization.get('signing_identity')
    public_key = release_authorization.get('signing_public_key')
    if (
        not isinstance(identity, str)
        or re.fullmatch(r'[A-Za-z0-9._@+-]+', identity) is None
        or not isinstance(public_key, str)
        or '\n' in public_key
        or re.fullmatch(r'ssh-(?:ed25519|rsa) [A-Za-z0-9+/=]+', public_key) is None
    ):
        return '许可人 SSH 签名身份或公钥无效'

    tag_object = _run_git(['cat-file', 'tag', f'refs/tags/{release_tag}'])
    if tag_object.returncode != 0:
        return '发布 Tag 必须是带 SSH 签名的 annotated tag'
    tag_text = _decode_git_path(tag_object.stdout)
    markers = (
        ('Release-Approval-SHA256', approval_sha),
        ('Rights-BOM-SHA256', rights_sha),
        ('License-SHA256', license_sha),
    )
    for label, value in markers:
        exact = f'{label}: {value}'
        mentions = re.findall(
            rf'(?im)^[ \t]*{re.escape(label)}[ \t]*:',
            tag_text,
        )
        exact_lines = re.findall(rf'(?m)^{re.escape(exact)}$', tag_text)
        if len(mentions) != 1 or exact_lines != [exact]:
            return '签名 Tag 未唯一绑定外部批准、Rights BOM 或 LICENSE 哈希'

    try:
        with tempfile.TemporaryDirectory(prefix='opengaokao-signers-') as temp_dir:
            allowed_signers = Path(temp_dir) / 'allowed_signers'
            allowed_signers.write_text(
                f'{identity} {public_key}\n',
                encoding='utf-8',
            )
            verified = _run_git([
                '-c', 'gpg.format=ssh',
                '-c', f'gpg.ssh.allowedSignersFile={allowed_signers}',
                'verify-tag', '--raw', release_tag,
            ])
    except OSError:
        return '无法建立临时 SSH allowed signers 验证环境'
    if verified.returncode != 0:
        return '发布 Tag 的 SSH 签名无效或不属于许可人公钥'
    return None


def _public_path_reason(relative_path: str) -> str | None:
    """返回被跟踪路径的公开发布阻断原因（不读取文件内容）。"""
    normalized = relative_path.replace('\\', '/').lower()
    name = normalized.rsplit('/', 1)[-1]
    if normalized == '.private' or normalized.startswith('.private/'):
        return '私有律师、权属或发布凭据目录'
    if name.startswith('.fuse_hidden'):
        return '临时 .fuse_hidden 文件'
    if name.endswith(_PUBLIC_DB_SUFFIXES) or name.endswith(('-wal', '-shm', '-journal')):
        return '数据库或事务日志文件'
    if name == '.env' or name.endswith('.env') or (
        name.startswith('.env.')
        and name not in {'.env.example', '.env.sample', '.env.template'}
    ):
        return '环境密钥文件'
    if name in _PUBLIC_PRIVATE_KEY_NAMES or name.endswith(_PUBLIC_PRIVATE_KEY_SUFFIXES):
        return '私钥/密钥容器文件'
    if name in _PUBLIC_SECRET_NAMES:
        return '凭据/密钥文件'
    if normalized in _PUBLIC_INTERNAL_PATHS:
        return '明确的内部策略文档'
    return None


def check_public_tree() -> CheckResult:
    """▶ 公开树检查：仅基于 Git 跟踪清单，不把本地私有数据纳入发布。"""
    print('\n▶ 公开树检查（跟踪文件）...')
    root_error = _git_root_error()
    if root_error:
        return CheckResult('公开树检查', False, root_error)
    proc = _run_git(['ls-files', '--cached', '-z'])
    if proc.returncode != 0:
        return CheckResult('公开树检查', False, 'git ls-files 执行失败')

    blocked = []
    for raw_path in proc.stdout.split(b'\0'):
        if not raw_path:
            continue
        relative_path = _decode_git_path(raw_path)
        reason = _public_path_reason(relative_path)
        path = PROJECT_ROOT / relative_path
        if reason:
            blocked.append(f'{relative_path}: {reason}')
            continue
        try:
            size = path.lstat().st_size
        except OSError:
            blocked.append(f'{relative_path}: 被跟踪但工作树中无法读取')
            continue
        if size > _PUBLIC_MAX_FILE_BYTES:
            blocked.append(
                f'{relative_path}: 异常大文件 {size:,} bytes '
                f'(上限 {_PUBLIC_MAX_FILE_BYTES:,})'
            )
    if blocked:
        shown = blocked[:20]
        more = '' if len(blocked) <= len(shown) else f'\n  …另有 {len(blocked) - len(shown)} 项'
        return CheckResult(
            '公开树检查', False,
            '跟踪清单含不得公开的文件：\n  ' + '\n  '.join(shown) + more,
        )
    count = len([item for item in proc.stdout.split(b'\0') if item])
    return CheckResult('公开树检查', True, f'{count} 个跟踪文件通过路径/大小门禁')


def _load_private_denylist(denylist: Path | None) -> tuple[list[str] | None, str | None]:
    if denylist is None:
        return None, '缺少 --pii-denylist（公开发布必须显式提供私有名单）'
    expanded = denylist.expanduser()
    lexical = expanded if expanded.is_absolute() else PROJECT_ROOT / expanded
    lexical = Path(os.path.abspath(lexical))
    try:
        resolved = lexical.resolve(strict=True)
    except (OSError, RuntimeError):
        return None, f'PII denylist 不存在：{denylist}'
    if not resolved.is_file():
        return None, f'PII denylist 不是普通文件：{resolved}'
    try:
        content = resolved.read_text(encoding='utf-8-sig')
    except (OSError, UnicodeError):
        return None, 'PII denylist 无法以 UTF-8 读取'
    patterns = [line.strip() for line in content.splitlines() if line.strip()]
    if not patterns:
        return None, 'PII denylist 为空'
    if any('\0' in pattern for pattern in patterns):
        return None, 'PII denylist 含非法 NUL 字符'

    for candidate in {lexical, resolved}:
        try:
            relative = candidate.relative_to(PROJECT_ROOT.resolve()).as_posix()
        except ValueError:
            continue
        tracked = _run_git(['ls-files', '--error-unmatch', '--', relative])
        if tracked.returncode == 0:
            return None, 'PII denylist 本身已被 Git 跟踪，必须放在私有非跟踪位置'
        if tracked.returncode not in (1,):
            return None, '无法确认 PII denylist 的 Git 跟踪状态'
    return patterns, None


def _git_grep_paths(patterns: list[str], treeish: str | None = None) -> tuple[list[str], str | None]:
    # Git for Windows 的 --file=- 会与 --files-* 长选项产生歧义，用 -f - 兼容调用。
    args = ['grep', '--files-with-matches', '--null', '--fixed-strings', '-f', '-']
    if treeish is None:
        args.append('--cached')
    else:
        args.append(treeish)
    args.append('--')
    proc = _run_git(args, input_text='\n'.join(patterns) + '\n')
    if proc.returncode not in (0, 1):
        return [], f'git grep 执行失败（exit={proc.returncode}）'
    return [
        _decode_git_path(item)
        for item in proc.stdout.split(b'\0')
        if item
    ], None


def check_public_release(denylist: Path | None) -> CheckResult:
    """▶ 公开发布门禁：私有 PII 名单 + 当前树 + 全部可达 Git 历史。"""
    print('\n▶ 公开发布门禁（PII + Git 历史）...')
    root_error = _git_root_error()
    if root_error:
        return CheckResult('公开发布门禁', False, root_error)
    tree_result = check_public_tree()
    if not tree_result.passed:
        return CheckResult('公开发布门禁', False, tree_result.detail)
    patterns, denylist_error = _load_private_denylist(denylist)
    if denylist_error:
        return CheckResult('公开发布门禁', False, denylist_error)
    assert patterns is not None

    status = _run_git(['status', '--porcelain=v1', '-z', '--untracked-files=all'])
    if status.returncode != 0:
        return CheckResult('公开发布门禁', False, '无法确认 Git 工作树状态')
    if status.stdout:
        return CheckResult(
            '公开发布门禁', False,
            'Git 工作树不干净；公开发布只验收已提交、可重现的候选版',
        )

    hits = set()
    current_hits, grep_error = _git_grep_paths(patterns)
    if grep_error:
        return CheckResult('公开发布门禁', False, grep_error)
    hits.update(f'CURRENT:{path}' for path in current_hits)

    commits = _run_git(['rev-list', '--all'])
    if commits.returncode != 0:
        return CheckResult('公开发布门禁', False, '无法枚举 Git 可达历史')
    commit_ids = [line for line in _decode_git_path(commits.stdout).splitlines() if line]
    if not commit_ids:
        return CheckResult('公开发布门禁', False, 'Git 仓库没有可达提交')
    for commit_id in commit_ids:
        commit_hits, grep_error = _git_grep_paths(patterns, commit_id)
        if grep_error:
            return CheckResult('公开发布门禁', False, grep_error)
        hits.update(commit_hits)

    if hits:
        ordered = sorted(hits)
        shown = ordered[:30]
        more = '' if len(ordered) <= len(shown) else f'\n  …另有 {len(ordered) - len(shown)} 个 ref/路径'
        return CheckResult(
            '公开发布门禁', False,
            'PII denylist 命中（仅显示 ref/路径，不显示匹配字面量）：\n  '
            + '\n  '.join(shown) + more,
        )
    return CheckResult(
        '公开发布门禁', True,
        f'当前树 + {len(commit_ids)} 个可达提交未命中私有 PII 名单',
    )


def _db_path(province: str) -> Path:
    return PROJECT_ROOT / 'data' / f'{province}_gaokao.db'


def _expected_runtime_data_source(province: str, ci_mode: bool) -> str:
    """源码发布固定验收合成示例；私有真库只影响非 CI 的另行验收。"""
    if ci_mode:
        return 'example'
    province_db = _db_path(province)
    return (
        province
        if province_db.exists() and province_db.stat().st_size > 0
        else 'example'
    )


def check_pytest_full(skip: bool) -> CheckResult:
    """▶ 运行 pytest 全套；任何 failed/error 算失败，允许 skipped。"""
    print('\n▶ pytest 全套...')
    if skip:
        return CheckResult('pytest 全套', True, '（--skip-fulltest 跳过）')
    clean_env = os.environ.copy()
    clean_env.pop('PYTEST_ADDOPTS', None)
    proc = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests/', '-q', '--tb=short'],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, env=clean_env,
    )
    out = proc.stdout + proc.stderr
    if proc.returncode != 0:
        tail = '\n'.join(out.strip().splitlines()[-6:])
        return CheckResult('pytest 全套', False, f'exit={proc.returncode}\n{tail}')
    summary = next((l for l in out.splitlines() if re.search(r'\b\d+ passed\b', l)), '').strip()
    if not summary:
        tail = '\n'.join(out.strip().splitlines()[-6:])
        return CheckResult(
            'pytest 全套', False,
            'pytest exit=0，但没有实际通过测试的摘要；拒绝把 collect-only/help 当成通过'
            + (f'\n{tail}' if tail else ''),
        )
    return CheckResult('pytest 全套', True, summary)


def _terminate_process_tree(proc: subprocess.Popen) -> None:
    """终止验收进程及其启动的 Flask 子进程，避免超时后遗留监听端口。"""
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        result = subprocess.run(
            ['taskkill', '/PID', str(proc.pid), '/T', '/F'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0 and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
            raise RuntimeError(
                f'taskkill 未能确认清理验收进程树（exit={result.returncode}）'
            )
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _run_with_process_tree_timeout(command: list[str], *, cwd: str, timeout: int):
    """运行可派生子进程的命令；超时时清理整个进程树并保留标准输出。"""
    group_args = (
        {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == 'nt'
        else {'start_new_session': True}
    )
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **group_args,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(proc)
        stdout, stderr = proc.communicate()
        raise subprocess.TimeoutExpired(
            command, timeout, output=stdout, stderr=stderr,
        )
    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)


def check_runtime_e2e(province: str, expected_data_source: str) -> CheckResult:
    """▶ 从 README 声明的 Flask 入口启动真实进程，验收 Web 与核心推荐。"""
    print('\n▶ 真实运行入口（Web + API + 核心推荐）...')
    script = PROJECT_ROOT / 'tests' / 'test_e2e_api.py'
    if not script.exists():
        return CheckResult('真实运行入口', False, '缺少 tests/test_e2e_api.py')
    try:
        proc = _run_with_process_tree_timeout(
            [sys.executable, str(script), '--province', province,
             '--expect-data-source', expected_data_source],
            cwd=str(PROJECT_ROOT),
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        return CheckResult('真实运行入口', False, '超过 180 秒，验收进程已终止')
    out = proc.stdout + proc.stderr
    if proc.returncode != 0:
        tail = '\n'.join(out.strip().splitlines()[-24:])
        return CheckResult('真实运行入口', False, f'exit={proc.returncode}\n{tail}')
    required_keys = {
        'health', 'page', 'data_source', 'data_provenance', 'schools', 'summary_total',
        'pipeline_steps', 'analysis_sections', 'restart_semantics',
    }
    receipt = {}
    for line in proc.stdout.splitlines():
        key, sep, value = line.strip().partition(':')
        if sep and key in required_keys:
            receipt[key] = value.strip()
    missing = sorted(required_keys - receipt.keys())
    if missing:
        return CheckResult('真实运行入口', False,
                           f'验收脚本 exit=0 但缺少回执字段: {", ".join(missing)}')
    if receipt['health'] != 'ok' or receipt['data_source'] != expected_data_source:
        return CheckResult('真实运行入口', False,
                           f'回执不符: health={receipt["health"]}, '
                           f'data_source={receipt["data_source"]}')
    if expected_data_source == 'example':
        if receipt['data_provenance'] != 'synthetic_example':
            return CheckResult('真实运行入口', False,
                               f'示例来源标记不符: {receipt["data_provenance"]}')
    elif receipt['data_provenance'] == 'synthetic_example':
        return CheckResult('真实运行入口', False, '真实省份验收拒绝合成示例数据')
    try:
        for key in ('schools', 'summary_total', 'pipeline_steps', 'analysis_sections'):
            if int(receipt[key]) <= 0:
                raise ValueError(f'{key}={receipt[key]}')
    except ValueError as exc:
        return CheckResult('真实运行入口', False, f'回执计数无效: {exc}')
    details = [
        f'data_source: {receipt["data_source"]}',
        f'data_provenance: {receipt["data_provenance"]}',
        f'schools: {receipt["schools"]}',
        f'restart_semantics: {receipt["restart_semantics"]}',
    ]
    return CheckResult('真实运行入口', True, '；'.join(details))


def check_post_import_validation(province: str) -> CheckResult:
    """▶ 运行 post_import_validation.py --quick；returncode 非 0 视为失败。"""
    print('\n▶ post_import_validation 数据完整性...')
    script = PROJECT_ROOT / 'scripts' / 'post_import_validation.py'
    if not script.exists():
        return CheckResult('数据完整性校验', False, '缺少 scripts/post_import_validation.py')
    proc = subprocess.run(
        [sys.executable, str(script), '--province', province, '--quick'],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    if proc.returncode != 0:
        tail = '\n'.join((proc.stdout + proc.stderr).strip().splitlines()[-6:])
        return CheckResult('数据完整性校验', False, f'exit={proc.returncode}\n{tail}')
    return CheckResult('数据完整性校验', True, '科类标签门禁通过、覆盖率快照已出')


def check_view_freshness(province: str) -> CheckResult:
    """▶ v_enroll_detail 物化表新鲜度。

    判定：视图存在 + 含 norm_subject 列 + 视图内每个年份的行数与 enroll_detail
    同年份 1:1 相等（源表更新后忘了重建会在此暴露）。与 --min-year 口径无关。
    """
    print('\n▶ v_enroll_detail 物化表新鲜度...')
    db = _db_path(province)
    if not db.exists() or db.stat().st_size == 0:
        return CheckResult('视图新鲜度', False, f'数据库不存在或为 0 字节: {db}')
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT type FROM sqlite_master WHERE name='v_enroll_detail'"
        ).fetchone()
        if not row:
            return CheckResult('视图新鲜度', False,
                               '缺少 v_enroll_detail，请先跑 scripts/create_views.py')
        cols = [r[1] for r in conn.execute('PRAGMA table_info(v_enroll_detail)')]
        if 'norm_subject' not in cols:
            return CheckResult('视图新鲜度', False,
                               'v_enroll_detail 缺 norm_subject 列，请重跑 create_views.py')
        view_years = conn.execute(
            'SELECT year, COUNT(*) FROM v_enroll_detail GROUP BY year'
        ).fetchall()
        if not view_years:
            return CheckResult('视图新鲜度', False, 'v_enroll_detail 为空')
        # 年份感知：>=DEDUP_BELOW_YEAR 期望 1:1；以下期望 = norm 去重后的唯一数。
        dedup_below = create_views.DEDUP_BELOW_YEAR
        stale = []
        for yr, vcnt in view_years:
            try:
                yi = int(yr)
            except (TypeError, ValueError):
                yi = dedup_below  # 非数值年份按 1:1 处理
            if yi >= dedup_below:
                expect = conn.execute(
                    'SELECT COUNT(*) FROM enroll_detail WHERE year = ?', (yr,)
                ).fetchone()[0]
            else:
                expect = conn.execute("""
                    SELECT COUNT(*) FROM (
                        SELECT DISTINCT school_name, major_name, batch, min_rank,
                            CASE WHEN subject_type IN ('物理','物理类','理科') THEN '物理'
                                 WHEN subject_type IN ('历史','历史类','文科') THEN '历史'
                                 ELSE subject_type END
                        FROM enroll_detail WHERE year = ?)
                """, (yr,)).fetchone()[0]
            if vcnt != expect:
                stale.append(f'{yr}: 视图 {vcnt:,} ≠ 期望 {expect:,}')
        if stale:
            return CheckResult('视图新鲜度', False,
                               '视图已过期/口径不符（请重跑 create_views.py）：' + '；'.join(stale))
        scope = ', '.join(str(y) for y, _ in sorted(view_years))
        total = sum(c for _, c in view_years)
        return CheckResult('视图新鲜度', True,
                           f'年份 [{scope}] 共 {total:,} 行，年份感知口径对齐')
    finally:
        conn.close()


# 对外发网络请求特征（本地版严禁；允许 127.0.0.1/localhost 的本地 API 服务）
_OUTBOUND_PATTERNS = [
    r'\bimport\s+requests\b', r'\bfrom\s+requests\b', r'\brequests\.(get|post|put|delete|patch|head|request)\b',
    r'\bfrom\s+urllib\b.*\brequest\b', r'\burllib\.request\b', r'\burlopen\b',
    r'\bimport\s+httpx\b', r'\bimport\s+aiohttp\b',
    r'\bhttp\.client\b', r'\bimport\s+smtplib\b',
]


def check_local_privacy() -> CheckResult:
    """▶ 本地隐私门禁：gaokao/ 内不得出现对外发网络请求。

    兑现 README"本地运行·数据不出电脑"承诺，防止未来误引入遥测/上云。
    """
    print('\n▶ 本地隐私门禁（零外发请求）...')
    # OG-F-41: 扫描面含 scripts/（用户同样会运行；subprocess 调本地 python 子进程合法、不在特征内）
    hits = []
    compiled = [re.compile(p) for p in _OUTBOUND_PATTERNS]
    for sub in ('gaokao', 'scripts'):
        root = PROJECT_ROOT / sub
        if not root.exists():
            continue
        for py in root.rglob('*.py'):
            if '__pycache__' in py.parts:
                continue
            try:
                text = py.read_text(encoding='utf-8')
            except (UnicodeDecodeError, OSError):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                stripped = line.lstrip()
                if stripped.startswith('#'):
                    continue
                for rx in compiled:
                    if rx.search(line):
                        rel = py.relative_to(PROJECT_ROOT)
                        hits.append(f'{rel}:{i}: {line.strip()[:80]}')
                        break
    if hits:
        return CheckResult('本地隐私门禁', False,
                           '发现疑似对外发请求（违背本地隐私承诺）：\n  ' + '\n  '.join(hits[:10]))
    return CheckResult('本地隐私门禁', True, 'gaokao/ + scripts/ 内无对外发网络请求')


def check_syntax_smoke() -> CheckResult:
    """py_compile 全部 gaokao/ + scripts/，捕获语法错误。

    pytest 不导入 api/server.py 等模块，其语法错误（OG-F-02 类"提交即坏"）不会被
    测试发现。本检查用 py_compile 兜底，是 CI 的最后一道，环境无关。
    """
    print('\n▶ 语法烟测（py_compile）...')
    import py_compile
    bad = []
    for sub in ('gaokao', 'scripts'):
        root = PROJECT_ROOT / sub
        if not root.exists():
            continue
        for py in root.rglob('*.py'):
            if '__pycache__' in py.parts:
                continue
            try:
                py_compile.compile(str(py), doraise=True)
            except py_compile.PyCompileError as e:
                bad.append(f'{py.relative_to(PROJECT_ROOT)}: {str(e).splitlines()[-1][:80]}')
    if bad:
        return CheckResult('语法烟测', False, '存在语法错误：\n  ' + '\n  '.join(bad[:10]))
    return CheckResult('语法烟测', True, 'gaokao/ + scripts/ 全部可编译')


def check_agpl_license() -> CheckResult:
    """▶ AGPL 合规：LICENSE 为 AGPL + README 声明 + NOTICE 衍生声明(§5) + 源文件 SPDX 头。

    OG-F-46: 此前仅查 README 含 'AGPL' 字串即过（拦不住 §5/SPDX/衍生声明缺失）。
    """
    print('\n▶ AGPL 合规声明...')
    lic = PROJECT_ROOT / 'LICENSE'
    if not lic.exists():
        return CheckResult('AGPL 合规', False, '缺少 LICENSE 文件')
    head = lic.read_text(encoding='utf-8', errors='ignore')[:400]
    if 'AFFERO GENERAL PUBLIC LICENSE' not in head:
        return CheckResult('AGPL 合规', False, 'LICENSE 非 AGPL')
    readme = PROJECT_ROOT / 'README.md'
    if readme.exists() and 'AGPL' not in readme.read_text(encoding='utf-8', errors='ignore'):
        return CheckResult('AGPL 合规', False, 'README 未声明 AGPL 许可')
    # §5: NOTICE 衍生/修改声明
    notice = PROJECT_ROOT / 'NOTICE'
    if not notice.exists():
        return CheckResult('AGPL 合规', False, '缺少 NOTICE 衍生声明（AGPL §5）')
    # §5: 源文件 SPDX 头（抽查 gaokao/+scripts/，缺头则失败并列出）
    missing_spdx = []
    for sub in ('gaokao', 'scripts'):
        root = PROJECT_ROOT / sub
        if not root.exists():
            continue
        for py in root.rglob('*.py'):
            if '__pycache__' in py.parts:
                continue
            if 'SPDX-License-Identifier' not in py.read_text(encoding='utf-8', errors='ignore')[:200]:
                missing_spdx.append(str(py.relative_to(PROJECT_ROOT)))
    if missing_spdx:
        return CheckResult('AGPL 合规', False,
                           f'{len(missing_spdx)} 个源文件缺 SPDX 头：' + '、'.join(missing_spdx[:5]) + ' …')
    return CheckResult('AGPL 合规', True, 'LICENSE=AGPL + README + NOTICE + 源文件 SPDX 头齐备')


def check_release_license_surface() -> CheckResult:
    """▶ SAL 正式表面：根许可证、文档、代码头、API/Web 与包元数据必须一致。"""
    print('\n▶ SAL 正式许可表面...')
    try:
        policy = _load_json_without_duplicate_keys(
            PUBLICATION_POLICY.read_text(encoding='utf-8')
        )
        derived_sha = policy['legal_text_review']['derived_publication_text_sha256']
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return CheckResult('SAL 许可表面', False, '无法读取派生许可证哈希')

    license_path = PROJECT_ROOT / 'LICENSE'
    if not license_path.is_file() or _sha256_file(license_path) != derived_sha:
        return CheckResult('SAL 许可表面', False, '根 LICENSE 与获批派生哈希不一致')
    license_text = license_path.read_text(encoding='utf-8', errors='ignore')
    if (
        'OpenGaokao Source-Available License 1.0' not in license_text
        or _SAL_LICENSE_IDENTIFIER not in license_text
        or 'AFFERO GENERAL PUBLIC LICENSE' in license_text[:400]
    ):
        return CheckResult('SAL 许可表面', False, '根 LICENSE 不是获批 SAL 1.0 文本')

    required_marker_files = ('README.md', 'NOTICE', 'LICENSING.md')
    forbidden_current_claims = {
        'README.md': (
            'license-AGPL', '目前仍是 AGPL', '当前迁移候选仍保留历史 `AGPL',
        ),
        'NOTICE': (
            '本程序是自由软件', '按 AGPL-3.0 发布', '如你基于本项目再行修改与分发',
        ),
        'LICENSING.md': (
            '总体状态：`PUBLICATION_BLOCKED`', '公开状态：`PRIVATE`',
            '根目录 `LICENSE` 仍是 AGPL', '新的商业限制尚未生效',
        ),
    }
    for relative in required_marker_files:
        path = PROJECT_ROOT / relative
        if not path.is_file():
            return CheckResult('SAL 许可表面', False, f'缺少 {relative}')
        text = path.read_text(encoding='utf-8', errors='ignore')
        rendered_text = unicodedata.normalize('NFKC', html.unescape(text)).casefold()
        rendered_text = ''.join(
            character for character in rendered_text
            if unicodedata.category(character) != 'Cf'
        )
        current_license_mentions = re.findall(
            r'(?<![a-z0-9])current[^a-z0-9]*license(?![a-z0-9])',
            rendered_text,
        )
        if len(current_license_mentions) != 1:
            return CheckResult(
                'SAL 许可表面', False,
                f'{relative} 的 Current-License 必须唯一且严格等于 {_SAL_LICENSE_IDENTIFIER}',
            )
        current_license_values = re.findall(
            r'^Current-License: ([^\r\n]+)$', text, flags=re.MULTILINE,
        )
        if current_license_values != [_SAL_LICENSE_IDENTIFIER]:
            return CheckResult(
                'SAL 许可表面', False,
                f'{relative} 的 Current-License 必须唯一且严格等于 {_SAL_LICENSE_IDENTIFIER}',
            )
        historical_license_mentions = re.findall(
            r'(?<![a-z0-9])historical[^a-z0-9]*license[^a-z0-9]*exception(?![a-z0-9])',
            rendered_text,
        )
        if len(historical_license_mentions) != 1:
            return CheckResult(
                'SAL 许可表面', False,
                f'{relative} 的 Historical-License-Exception 必须唯一且严格等于 AGPL-3.0-or-later',
            )
        historical_license_values = re.findall(
            r'^Historical-License-Exception: ([^\r\n]+)$',
            text,
            flags=re.MULTILINE,
        )
        if historical_license_values != ['AGPL-3.0-or-later']:
            return CheckResult(
                'SAL 许可表面', False,
                f'{relative} 的 Historical-License-Exception 必须唯一且严格等于 AGPL-3.0-or-later',
            )
        stale_claims = [
            claim for claim in forbidden_current_claims[relative]
            if claim in text
        ]
        if stale_claims:
            return CheckResult(
                'SAL 许可表面', False,
                f'{relative} 仍包含当前 AGPL/PRIVATE 阶段声明：{stale_claims[0]}',
            )

    pyproject = PROJECT_ROOT / 'pyproject.toml'
    if not pyproject.is_file():
        return CheckResult('SAL 许可表面', False, '缺少 pyproject.toml 包元数据')
    package_text = pyproject.read_text(encoding='utf-8', errors='ignore')
    if (
        _SAL_LICENSE_IDENTIFIER not in package_text
        or 'AGPL' in package_text
        or 'GNU Affero' in package_text
        or 'License :: OSI Approved' in package_text
    ):
        return CheckResult('SAL 许可表面', False, 'pyproject 包元数据仍声明 AGPL/OSI 或缺 SAL')

    required_surfaces = (
        'CONTRIBUTING.md', 'CLAUDE.md', 'gaokao/__init__.py', 'gaokao/cli.py',
        'gaokao/api/server.py', 'web/index.html', 'web/js/app.js',
        'tests/test_e2e_api.py',
    )
    stale_surfaces = []
    misleading_agpl_surfaces = []
    for relative in required_surfaces:
        path = PROJECT_ROOT / relative
        if not path.is_file():
            stale_surfaces.append(f'{relative} (缺失)')
            continue
        text = path.read_text(encoding='utf-8', errors='ignore')
        if _SAL_LICENSE_IDENTIFIER not in text:
            stale_surfaces.append(relative)
        if 'AGPL-3.0' in text or 'GNU Affero' in text:
            misleading_agpl_surfaces.append(relative)
    if stale_surfaces:
        return CheckResult('SAL 许可表面', False, '仍未切换 SAL 的表面：' + '、'.join(stale_surfaces))
    if misleading_agpl_surfaces:
        return CheckResult(
            'SAL 许可表面', False,
            '仍把当前用户表面声明为 AGPL：' + '、'.join(misleading_agpl_surfaces),
        )

    acceptance_missing = []
    for relative in ('gaokao/cli.py', 'gaokao/api/server.py'):
        error = _license_acceptance_gate_error(PROJECT_ROOT / relative)
        if error:
            acceptance_missing.append(f'{relative} ({error})')
    if acceptance_missing:
        return CheckResult(
            'SAL 许可表面', False,
            '真实运行入口缺少显式许可接受参数：' + '、'.join(acceptance_missing),
        )

    stale_spdx = _run_git([
        'grep', '-l', '-F',
        'SPDX-License-Identifier: ' + 'AGPL-3.0-or-later',
        '--',
    ])
    if stale_spdx.returncode == 0:
        paths = _decode_git_path(stale_spdx.stdout).splitlines()
        return CheckResult('SAL 许可表面', False, '仍存在 AGPL SPDX：' + '、'.join(paths[:8]))
    if stale_spdx.returncode not in (1,):
        return CheckResult('SAL 许可表面', False, '无法扫描旧 AGPL SPDX')

    missing_spdx = []
    for sub in ('gaokao', 'scripts', 'data'):
        root = PROJECT_ROOT / sub
        if not root.exists():
            continue
        for py in root.rglob('*.py'):
            if '__pycache__' in py.parts:
                continue
            head = py.read_text(encoding='utf-8', errors='ignore')[:250]
            if f'SPDX-License-Identifier: {_SAL_LICENSE_IDENTIFIER}' not in head:
                missing_spdx.append(str(py.relative_to(PROJECT_ROOT)).replace('\\', '/'))
    if missing_spdx:
        return CheckResult('SAL 许可表面', False, '源文件缺 SAL SPDX：' + '、'.join(missing_spdx[:8]))
    return CheckResult(
        'SAL 许可表面', True,
        '根 LICENSE、README/NOTICE/LICENSING、包元数据、API/Web 与源码 SPDX 已统一',
    )


def check_current_license_surface() -> CheckResult:
    """按机器策略选择当前应生效的 AGPL 或待发布 SAL 全表面。"""
    try:
        status = _load_json_without_duplicate_keys(
            PUBLICATION_POLICY.read_text(encoding='utf-8')
        ).get('status')
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return CheckResult('许可表面', False, '无法读取 publication policy 状态')
    if status == 'PUBLICATION_BLOCKED':
        return check_agpl_license()
    if status == 'READY_PENDING_EXTERNAL_RECEIPT':
        return check_release_license_surface()
    return CheckResult('许可表面', False, f'未知 publication policy 状态：{status}')


def check_publication_authorization(
    release_approval: Path | None = None,
    rights_bom: Path | None = None,
) -> CheckResult:
    """▶ 许可迁移硬门禁：仅仓库外批准凭据可开放正向路径。"""
    print('\n▶ 发布授权（权属 + 获批定制许可证 + 外部凭据）...')
    if not PUBLICATION_POLICY.exists():
        return CheckResult('许可迁移授权', False, '缺少 licensing/publication-policy.json')
    try:
        policy = _load_json_without_duplicate_keys(
            PUBLICATION_POLICY.read_text(encoding='utf-8')
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return CheckResult('许可迁移授权', False, 'publication-policy.json 无法解析')

    if policy.get('schema_version') != 2:
        return CheckResult('许可迁移授权', False, '不支持的 publication policy schema')
    if policy.get('target_model') != 'source-available-commercial-restricted':
        return CheckResult('许可迁移授权', False, '目标许可模型不符')
    required_terms = policy.get('required_terms') or {}
    expected_terms = (
        'public_source_visibility',
        'not_osi_open_source',
        'personal_noncommercial_local_use_allowed',
        'necessary_local_copy_and_single_backup_allowed',
        'personal_local_modification_allowed',
        'qualified_nonprofit_classroom_display_allowed',
        'qualified_noncommercial_research_allowed',
        'single_personal_report_limited_sharing_allowed',
        'commercial_use_requires_separate_paid_license',
        'competing_product_or_service_use_prohibited_by_default',
        'original_source_off_platform_redistribution_prohibited',
        'modified_version_redistribution_prohibited',
        'modified_version_redistribution_not_commercially_licensable',
        'commercial_hosting_saas_api_requires_paid_license',
        'github_direct_platform_rights_exception_required',
        'github_on_platform_fork_allowed',
        'significant_standard_terms_require_affirmative_acceptance',
        'no_express_patent_license',
        'historical_agpl_existing_rights_not_retracted',
        'public_release_synthetic_example_only',
        'real_yunnan_data_excluded',
    )
    missing_terms = [key for key in expected_terms if required_terms.get(key) is not True]
    if missing_terms:
        return CheckResult('许可迁移授权', False,
                           '商业硬约束缺失：' + '、'.join(missing_terms))
    if (
        required_terms.get('free_use_liability_cap_cny') != 100
        or required_terms.get('general_breach_cure_period_business_days') != 10
    ):
        return CheckResult('许可迁移授权', False, '责任上限或一般违约补救期与获批策略不符')

    history = policy.get('historical_agpl') or {}
    if (
        history.get('conservative_boundary_candidate') != _HISTORICAL_PUBLIC_BOUNDARY_CANDIDATE
        or history.get('license') != 'AGPL-3.0-or-later'
        or history.get('existing_rights_not_retracted') is not True
        or history.get('boundary_not_final_legal_determination') is not True
    ):
        return CheckResult('许可迁移授权', False, '历史 AGPL 例外未被完整保留')

    legal_review = policy.get('legal_text_review') or {}
    if (
        legal_review.get('status') != 'OWNER_REPORTED_COUNSEL_CONFIRMED_UNCHANGED'
        or legal_review.get('reviewed_draft_sha256') != _COUNSEL_REVIEWED_DRAFT_SHA256
        or legal_review.get('confirmation_scope') != 'exact-private-draft-bytes-only'
    ):
        return CheckResult(
            '许可迁移授权', False,
            '律师确认边界缺失或被改写；不得把派生公开文本冒充已确认的私有草案',
        )

    status = policy.get('status') or 'MISSING'
    rights = policy.get('rights_clearance') or {}
    release_authorization = policy.get('release_authorization') or {}

    if status == 'PUBLICATION_BLOCKED':
        if (
            legal_review.get('derived_publication_text_status')
            not in {'NOT_COUNSEL_VERIFIED', 'OWNER_APPROVAL_PENDING'}
            or (
                legal_review.get('derived_publication_text_status') == 'NOT_COUNSEL_VERIFIED'
                and legal_review.get('derived_publication_text_sha256') is not None
            )
        ):
            return CheckResult(
                '许可迁移授权', False,
                '派生公开文本状态越权；不得把候选哈希冒充许可人或律师批准',
            )
        if (
            rights.get('status') != 'OWNERSHIP_AND_SOURCE_EVIDENCE_INCOMPLETE'
            or rights.get('publication_allowed') is not False
            or rights.get('current_worktree_evidence_complete') is not False
        ):
            return CheckResult(
                '许可迁移授权', False,
                '权属状态不能由仓库内字段自我升级；必须以逐文件证据另行验收',
            )
        if (
            release_authorization.get('status') != 'NOT_GRANTED'
            or release_authorization.get('mechanism') != 'external-release-approval-receipt'
            or release_authorization.get('configured') is not False
            or release_authorization.get('in_repository_self_approval_permitted') is not False
            or release_authorization.get('tag_signature_required') is not True
            or release_authorization.get('tag_signature_format') != 'ssh'
            or release_authorization.get('signing_public_key_status') != 'NOT_CONFIGURED'
            or release_authorization.get('signing_trust_anchor_requirement')
            != 'owner-confirmed-out-of-band-before-ready'
            or release_authorization.get('candidate_generated_key_permitted') is not False
        ):
            return CheckResult(
                '许可迁移授权', False,
                '仓库内策略不能自我批准；发布授权凭据尚未实现或被改写',
            )
        return CheckResult(
            '许可迁移授权', False,
            f'{legal_review["status"]} / {rights["status"]} / {status}；'
            '律师确认仅覆盖私有草案的精确字节，派生公开许可证、'
            '逐文件权属和发布授权仍未完成，仓库必须保持 PRIVATE',
        )

    if status != 'READY_PENDING_EXTERNAL_RECEIPT':
        return CheckResult(
            '许可迁移授权', False,
            f'当前状态={status}；仓库内策略不能自我批准。必须由独立发布凭据绑定'
            '最终许可证、权属证据和候选提交',
        )

    derived_sha = legal_review.get('derived_publication_text_sha256')
    if (
        legal_review.get('derived_publication_text_status')
        != 'OWNER_APPROVAL_REQUIRES_EXTERNAL_RECEIPT'
        or not isinstance(derived_sha, str)
        or re.fullmatch(r'[0-9A-F]{64}', derived_sha) is None
    ):
        return CheckResult(
            '许可迁移授权', False,
            '派生许可证必须绑定精确 SHA-256，且只能由仓库外许可人凭据批准',
        )

    if (
        rights.get('status') != 'RIGHTS_MANIFEST_REQUIRES_EXTERNAL_RECEIPT'
        or rights.get('publication_allowed_only_with_external_receipt') is not True
    ):
        return CheckResult(
            '许可迁移授权', False,
            '权属状态未要求外部完整清单，或仓库内字段试图直接授予发布权',
        )
    if (
        release_authorization.get('status') != 'READY_PENDING_EXTERNAL_RECEIPT'
        or release_authorization.get('mechanism') != 'external-release-approval-receipt'
        or release_authorization.get('configured') is not True
        or release_authorization.get('in_repository_self_approval_permitted') is not False
        or release_authorization.get('tag_signature_required') is not True
        or release_authorization.get('tag_signature_format') != 'ssh'
        or release_authorization.get('signing_public_key_status')
        != 'OWNER_CONFIRMED_OUT_OF_BAND'
        or release_authorization.get('signing_trust_anchor_source')
        != 'owner-confirmed-out-of-band'
        or release_authorization.get('candidate_generated_key_permitted') is not False
    ):
        return CheckResult('许可迁移授权', False, '仓库外发布批准机制未正确配置')
    signing_public_key = release_authorization.get('signing_public_key')
    if not isinstance(signing_public_key, str):
        return CheckResult('许可迁移授权', False, '缺少许可人 SSH 签名公钥')
    signing_key_sha = hashlib.sha256(signing_public_key.encode('utf-8')).hexdigest().upper()
    signing_key_fingerprint = _ssh_public_key_fingerprint(signing_public_key)
    if (
        signing_key_fingerprint is None
        or release_authorization.get('signing_public_key_fingerprint')
        != signing_key_fingerprint
    ):
        return CheckResult('许可迁移授权', False, '许可人 SSH 公钥指纹与信任锚不一致')
    owner_record_sha = release_authorization.get('owner_authorization_record_sha256')
    if not isinstance(owner_record_sha, str) or re.fullmatch(r'[0-9A-F]{64}', owner_record_sha) is None:
        return CheckResult('许可迁移授权', False, '缺少仓库外许可人授权记录哈希')

    target = policy.get('release_target') or {}
    expected_target = {
        'repository': _RELEASE_REPOSITORY,
        'license_path': 'LICENSE',
        'license_identifier': _SAL_LICENSE_IDENTIFIER,
        'license_sha256': derived_sha,
        'release_scope': _SOURCE_RELEASE_SCOPE,
        'synthetic_example_only': True,
        'real_yunnan_data_included': False,
    }
    if any(target.get(key) != value for key, value in expected_target.items()):
        return CheckResult('许可迁移授权', False, '仓库内发布目标与派生许可证边界不一致')

    approval_path, approval_error = _resolve_untracked_file(
        release_approval, 'release-approval'
    )
    if approval_error:
        return CheckResult('许可迁移授权', False, approval_error)
    evidence_path, evidence_error = _resolve_untracked_file(rights_bom, 'rights-bom')
    if evidence_error:
        return CheckResult('许可迁移授权', False, evidence_error)
    assert approval_path is not None and evidence_path is not None

    try:
        approval = _load_json_without_duplicate_keys(
            approval_path.read_text(encoding='utf-8-sig')
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return CheckResult('许可迁移授权', False, 'release-approval 无法解析为 UTF-8 JSON')

    rights_error = _rights_bom_error(evidence_path)
    if rights_error:
        return CheckResult('许可迁移授权', False, rights_error)
    evidence_sha = _sha256_file(evidence_path)
    license_path = PROJECT_ROOT / 'LICENSE'
    if not license_path.is_file() or _sha256_file(license_path) != derived_sha:
        return CheckResult('许可迁移授权', False, '根 LICENSE SHA-256 与派生许可证不符')

    head = _run_git(['rev-parse', 'HEAD'])
    tree = _run_git(['rev-parse', 'HEAD^{tree}'])
    if head.returncode != 0 or tree.returncode != 0:
        return CheckResult('许可迁移授权', False, '无法读取候选提交或 tree')
    head_sha = _decode_git_path(head.stdout).strip()
    tree_sha = _decode_git_path(tree.stdout).strip()

    origin = _run_git(['remote', 'get-url', 'origin'])
    if origin.returncode != 0:
        return CheckResult('许可迁移授权', False, '缺少可核验的 origin 远端')
    origin_repo = _normalize_github_repository(_decode_git_path(origin.stdout))
    if origin_repo is None or origin_repo.casefold() != _RELEASE_REPOSITORY.casefold():
        return CheckResult('许可迁移授权', False, 'origin 远端不是目标 GitHub 仓库')

    expected_approval = {
        'schema_version': 1,
        'repository': _RELEASE_REPOSITORY,
        'release_commit': head_sha,
        'release_tree': tree_sha,
        'license_identifier': _SAL_LICENSE_IDENTIFIER,
        'license_sha256': derived_sha,
        'rights_bom_sha256': evidence_sha,
        'release_scope': _SOURCE_RELEASE_SCOPE,
        'synthetic_example_only': True,
        'real_yunnan_data_included': False,
        'historical_agpl_existing_rights_not_retracted': True,
        'owner_public_id': 'heronerar',
        'owner_decision': 'APPROVE_PUBLIC_RELEASE',
        'counsel_status': 'OWNER_APPROVED_NOT_COUNSEL_VERIFIED',
        'owner_signing_public_key_sha256': signing_key_sha,
        'owner_authorization_record_sha256': owner_record_sha,
    }
    mismatches = [
        key for key, value in expected_approval.items()
        if approval.get(key) != value
    ]
    release_tag = approval.get('release_tag')
    approved_at = approval.get('owner_approved_at')
    if not isinstance(release_tag, str) or re.fullmatch(r'v[0-9A-Za-z][0-9A-Za-z._-]*', release_tag) is None:
        mismatches.append('release_tag')
    else:
        tag = _run_git(['rev-parse', '-q', '--verify', f'refs/tags/{release_tag}^{{commit}}'])
        if tag.returncode != 0 or _decode_git_path(tag.stdout).strip() != head_sha:
            mismatches.append('release_tag')
    try:
        approved_time = _parse_iso_datetime(approved_at)
        commit_raw = _run_git(['show', '-s', '--format=%cI', 'HEAD'])
        if commit_raw.returncode != 0:
            raise ValueError('missing commit time')
        commit_time = _parse_iso_datetime(_decode_git_path(commit_raw.stdout).strip())
        if (
            approved_time.tzinfo is None
            or approved_time < commit_time
            or approved_time > datetime.now(timezone.utc) + timedelta(minutes=5)
        ):
            raise ValueError('approval time out of range')
    except (AttributeError, TypeError, ValueError):
        mismatches.append('owner_approved_at')
    if mismatches:
        return CheckResult(
            '许可迁移授权', False,
            'release-approval 与候选不符：' + '、'.join(sorted(set(mismatches))),
        )

    approval_sha = _sha256_file(approval_path)
    signature_error = _signed_release_tag_error(
        release_tag,
        approval_sha,
        evidence_sha,
        derived_sha,
        release_authorization,
    )
    if signature_error:
        return CheckResult('许可迁移授权', False, signature_error)

    return CheckResult(
        '许可迁移授权', True,
        f'许可人 SSH 签名 Tag 已绑定仓库外凭据、commit={head_sha}、tree={tree_sha}、'
        f'LICENSE={derived_sha}、Rights BOM={evidence_sha}、tag={release_tag}',
    )


def main():
    parser = argparse.ArgumentParser(description='OpenGaokao 发布前验证门禁')
    parser.add_argument('--province', type=str, default='yunnan',
                        help='数据相关检查针对的省份，默认 yunnan')
    parser.add_argument('--skip-fulltest', action='store_true',
                        help='跳过 pytest 全套（仅做轻量检查）')
    parser.add_argument('--ci', action='store_true',
                        help='CI 模式：跳过依赖私有省份库的检查（数据完整性 / 视图新鲜度）')
    parser.add_argument('--public-release', action='store_true',
                        help='公开发布模式：要求干净工作树并扫描全部 Git 可达历史')
    parser.add_argument('--pii-denylist', type=Path,
                        help='私有 UTF-8 PII 字面量名单（每行一项，不得被 Git 跟踪）')
    parser.add_argument('--release-approval', type=Path,
                        help='许可人发布批准 JSON（必须位于仓库目录之外）')
    parser.add_argument('--rights-bom', type=Path,
                        help='最终逐文件权属证据清单（必须位于仓库目录之外）')
    args = parser.parse_args()
    if args.public_release and args.skip_fulltest:
        parser.error('--public-release 不允许与 --skip-fulltest 组合')
    if args.public_release and not args.ci:
        parser.error('--public-release 必须与 --ci 组合，固定验收源码与合成示例发行')
    if args.public_release and args.province != 'yunnan':
        parser.error('--public-release 当前只允许 --province yunnan，不能改参数绕过数据隔离')

    if args.public_release:
        authorization = check_publication_authorization(
            args.release_approval,
            args.rights_bom,
        )
        if not authorization.passed:
            print(f'\n❌ {authorization.name}')
            print(f'     {authorization.detail}')
            print('\n❌ 许可迁移授权未通过 — 仓库必须保持 PRIVATE', file=sys.stderr)
            sys.exit(1)
        local_data_error = _public_release_local_data_error()
        if local_data_error:
            print('\n❌ 公开源码数据隔离')
            print(f'     {local_data_error}')
            print('\n❌ 公开候选含私有/未知数据 — 禁止发版', file=sys.stderr)
            sys.exit(1)

    print('=' * 70)
    mode = '公开发布' if args.public_release else ('CI' if args.ci else '本地发版')
    print(f'OpenGaokao 验证门禁（{mode}）  |  省份: {args.province}')
    print('=' * 70)

    # 语法烟测 + 公开树 + pytest 是代码级检查，CI 与本地都跑
    results = [
        check_syntax_smoke(),
        check_public_tree(),
        check_pytest_full(args.skip_fulltest),
    ]
    # GitHub CI 不含私有省份库，只能显式验收 example；本地有真库时必须命中省份源。
    # 无论哪种环境，test_e2e_api 都会校验响应 data_source，禁止静默降级。
    expected_data_source = _expected_runtime_data_source(args.province, args.ci)
    results.append(check_runtime_e2e(args.province, expected_data_source))
    if args.ci:
        print('\n（CI 模式：跳过数据完整性 / 视图新鲜度 —— 依赖私有省份库，属发版本地检查）')
    else:
        results.append(check_post_import_validation(args.province))
        results.append(check_view_freshness(args.province))
    results.append(check_local_privacy())
    results.append(check_current_license_surface())
    if args.public_release:
        results.append(authorization)
        results.append(check_public_release(args.pii_denylist))

    print('\n' + '=' * 70)
    print('结果汇总')
    print('=' * 70)
    all_passed = True
    for r in results:
        mark = '✅' if r.passed else '❌'
        print(f'{mark} {r.name}')
        if r.detail:
            for line in r.detail.splitlines():
                print(f'     {line}')
        if not r.passed:
            all_passed = False

    if all_passed:
        if args.public_release:
            print('\n✅ 全部通过 — 公开发布机械门禁已通过')
        else:
            print('\n✅ 当前验证范围通过（未执行私有 PII 历史扫描）')
        sys.exit(0)
    print('\n❌ 存在未通过项 — 禁止发版', file=sys.stderr)
    sys.exit(1)


if __name__ == '__main__':
    main()
