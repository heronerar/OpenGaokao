# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""OpenGaokao 发布前本地验证门禁（单一入口）

移植自 YGCare/scripts/verify_release.py，按开源版定位改造：
    - 砍掉 YGCare 商业专属检查（飞书插件 dist 黑名单、小程序交付面边界）
    - 换上贴合 AGPL 开源版的检查：本地隐私门禁（零外发请求）+ AGPL 许可证声明
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
    ▶ AGPL 许可证声明（LICENSE 为 AGPL + README 声明源码可获取）

用法：
    python scripts/verify_release.py                       # 默认 yunnan，全套
    python scripts/verify_release.py --province yunnan
    python scripts/verify_release.py --skip-fulltest       # 跳过 pytest（轻量检查）
    python scripts/verify_release.py --public-release --pii-denylist <私有文件>
"""
from __future__ import annotations

import argparse
import os
import re
import signal
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

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


def _public_path_reason(relative_path: str) -> str | None:
    """返回被跟踪路径的公开发布阻断原因（不读取文件内容）。"""
    normalized = relative_path.replace('\\', '/').lower()
    name = normalized.rsplit('/', 1)[-1]
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


def check_pytest_full(skip: bool) -> CheckResult:
    """▶ 运行 pytest 全套；任何 failed/error 算失败，允许 skipped。"""
    print('\n▶ pytest 全套...')
    if skip:
        return CheckResult('pytest 全套', True, '（--skip-fulltest 跳过）')
    proc = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests/', '-q', '--tb=short'],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    out = proc.stdout + proc.stderr
    if proc.returncode != 0:
        tail = '\n'.join(out.strip().splitlines()[-6:])
        return CheckResult('pytest 全套', False, f'exit={proc.returncode}\n{tail}')
    summary = next((l for l in out.splitlines() if 'passed' in l), '').strip()
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
        'health', 'page', 'data_source', 'schools', 'summary_total',
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
    try:
        for key in ('schools', 'summary_total', 'pipeline_steps', 'analysis_sections'):
            if int(receipt[key]) <= 0:
                raise ValueError(f'{key}={receipt[key]}')
    except ValueError as exc:
        return CheckResult('真实运行入口', False, f'回执计数无效: {exc}')
    details = [
        f'data_source: {receipt["data_source"]}',
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
    args = parser.parse_args()

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
    province_db = _db_path(args.province)
    # GitHub CI 不含私有省份库，只能显式验收 example；本地有真库时必须命中省份源。
    # 无论哪种环境，test_e2e_api 都会校验响应 data_source，禁止静默降级。
    expected_data_source = (
        args.province
        if province_db.exists() and province_db.stat().st_size > 0
        else 'example'
    )
    results.append(check_runtime_e2e(args.province, expected_data_source))
    if args.ci:
        print('\n（CI 模式：跳过数据完整性 / 视图新鲜度 —— 依赖私有省份库，属发版本地检查）')
    else:
        results.append(check_post_import_validation(args.province))
        results.append(check_view_freshness(args.province))
    results.append(check_local_privacy())
    results.append(check_agpl_license())
    if args.public_release:
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
