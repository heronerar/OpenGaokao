# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""
数据导入后自动验证 (Post-Import Validation) — OpenGaokao 多省版

移植自 YGCare/scripts/post_import_validation.py，按开源版定位改造：
    - 按省解析数据库（data/<省>_gaokao.db，而非单库硬编码）
    - 去掉飞书告警（本地隐私承诺：脚本零外发请求，失败仅退出码 + stderr）
    - P0 回归门禁改用 pytest tests/（OpenGaokao 无 full_pipeline_test.py）
    - 常量引用路径对齐 gaokao/core/*

用途：
    新增/更新某省录取数据后，运行此脚本完成数据状态的完整验证。
    检测：
    - 数据覆盖率快照（各表行数、按科类、按年份）
    - 科类标签导入门禁（不让第 7 种标签污染推荐链路）
    - 数据稀疏阈值是否触发
    - 贝叶斯先验校准（HISTORY_TO_PHYSICS_RATIO）
    - P0 回归测试（pytest tests/）
    - 列出需要更新的硬编码常量

用法：
    python scripts/post_import_validation.py                      # 默认 yunnan，完整验证
    python scripts/post_import_validation.py --province yunnan    # 指定省份
    python scripts/post_import_validation.py --quick              # 跳过 P0 回归测试
    python scripts/post_import_validation.py --baseline path      # 指定基线文件对比覆盖率

退出码：
    0 = 验证通过；1 = 科类标签门禁拦截 或 P0 回归未通过（带病数据/回归不得放行）

输出：
    output/validation_<省>_<时间>.md   — 验证报告（markdown）
    output/validation_<省>_<时间>.json — 当前快照（可作为下次基线）
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'output')

# 关键阈值（与 gaokao/core/* 保持一致；不一致即提示更新）
SPARSITY_THRESHOLD = 2000     # matching_engine.py:357  history_count < 2000 触发稀疏预警
PHYSICS_HISTORY_RATIO = 0.28  # sparse_prior.py:44       HISTORY_TO_PHYSICS_RATIO
HISTORY_BAO_MULTIPLIER = 1.2  # volunteer_recommender.py:983  历史类保档安全垫


def resolve_db_path(province: str) -> str:
    """按省解析真库路径。

    与 gaokao/config/registry.py 的 ProvinceConfig.db_path 公式一致：
    data/<slug>_gaokao.db。仓库根与 gaokao/ 下的同名 db 是 0 字节假文件，
    不要连那两个（pitfalls O1）。
    """
    return os.path.join(PROJECT_ROOT, 'data', f'{province}_gaokao.db')


def section(title: str) -> str:
    """打印分节标题"""
    line = '=' * 70
    print(f'\n{line}\n{title}\n{line}')
    return f'\n## {title}\n'


def data_coverage_snapshot(conn: sqlite3.Connection) -> Dict:
    """模块 1：数据覆盖率快照"""
    snap = {}

    # 各表行数（表不存在时记 None，覆盖多省 schema 差异）
    tables = [
        'score_line_2024', 'score_line_2025', 'score_line_2026',
        'enroll_detail', 'enroll_plan_2025', 'enroll_plan_2026',
        'school_info', 'major_catalog',
        'major_employment_stats', 'major_revocation_stats',
        'wef_occupation_mapping',
    ]
    snap['table_counts'] = {}
    for t in tables:
        try:
            row = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()
            snap['table_counts'][t] = int(row[0])
        except sqlite3.OperationalError:
            snap['table_counts'][t] = None  # 表不存在

    # score_line_2025 按科类
    snap['score_line_2025_by_subject'] = {}
    try:
        rows = conn.execute(
            "SELECT subject_type, COUNT(*) FROM score_line_2025 "
            "WHERE min_rank IS NOT NULL GROUP BY subject_type"
        ).fetchall()
        for r in rows:
            snap['score_line_2025_by_subject'][r[0]] = int(r[1])
    except sqlite3.OperationalError:
        pass

    # enroll_detail 按年份与科类
    snap['enroll_detail_by_year_subject'] = {}
    try:
        rows = conn.execute(
            "SELECT year, subject_type, COUNT(*) FROM enroll_detail "
            "GROUP BY year, subject_type ORDER BY year DESC, subject_type"
        ).fetchall()
        for r in rows:
            snap['enroll_detail_by_year_subject'][f'{r[0]}_{r[1]}'] = int(r[2])
    except sqlite3.OperationalError:
        pass

    # enroll_detail min_rank 缺失率（共享陷阱 1：覆盖率必须现场实测，禁止引用文档数字）
    snap['enroll_detail_missing_rank'] = {}
    try:
        rows = conn.execute(
            "SELECT year, COUNT(*), "
            "SUM(CASE WHEN min_rank IS NULL THEN 1 ELSE 0 END) "
            "FROM enroll_detail GROUP BY year ORDER BY year"
        ).fetchall()
        for r in rows:
            total, missing = int(r[1]), int(r[2])
            pct = round(100.0 * missing / total, 1) if total else 0.0
            snap['enroll_detail_missing_rank'][str(r[0])] = {
                'total': total, 'missing': missing, 'missing_pct': pct
            }
    except sqlite3.OperationalError:
        pass

    # 专科批覆盖
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM score_line_2025 "
            "WHERE batch LIKE '%专科%' OR batch LIKE '%高职%'"
        ).fetchone()
        snap['vocational_2025'] = int(row[0])
    except sqlite3.OperationalError:
        snap['vocational_2025'] = 0

    return snap


def subject_label_gate(conn: sqlite3.Connection) -> Tuple[List[str], bool]:
    """模块 1.5：科类标签导入门禁（共享陷阱 2 的安全半步）

    当前库内长短标签并存是历史欠账。本门禁的职责是：
    **不让新导入引入集合外的第 7 种标签**（如 '综合'、空串、繁体变体），
    出现集合外标签即验证失败（退出码非 0），阻断带病数据进入推荐链路。
    """
    legal = {'物理类', '历史类', '文科', '理科', '物理', '历史'}
    checks = [
        ('enroll_detail', 'subject_type'),
        ('score_line_2024', 'subject_type'),
        ('score_line_2025', 'subject_type'),
        ('score_line_2026', 'subject_type'),
        ('enroll_plan_2025', 'category'),
        ('enroll_plan_2026', 'category'),
    ]
    msgs = []
    failed = False
    for table, col in checks:
        try:
            rows = conn.execute(f'SELECT DISTINCT {col} FROM {table}').fetchall()
        except sqlite3.OperationalError:
            msgs.append(f'- `{table}`：表或列不存在，跳过')
            continue
        labels = {r[0] for r in rows if r[0] is not None}
        illegal = {l for l in labels if l not in legal}
        if illegal:
            failed = True
            msgs.append(
                f'- 🔴 `{table}.{col}` 存在集合外标签：{sorted(map(repr, illegal))} '
                f'——拒绝放行，请修正数据源或导入映射后重导'
            )
        else:
            msgs.append(f'- ✅ `{table}.{col}` 标签合法（{len(labels)} 种）')
    msgs.append(f'- 合法集合：{sorted(legal)}')
    return msgs, failed


def sparsity_check(snap: Dict) -> List[str]:
    """模块 2：数据稀疏阈值检测"""
    msgs = []
    sl25 = snap.get('score_line_2025_by_subject', {})
    history_count = sum(v for k, v in sl25.items() if k in ('历史', '历史类'))
    physics_count = sum(v for k, v in sl25.items() if k in ('物理', '物理类'))

    msgs.append(f'- 历史类 score_line_2025 总记录数：**{history_count}**')
    msgs.append(f'- 物理类 score_line_2025 总记录数：**{physics_count}**')
    msgs.append(f'- 稀疏标签阈值：< {SPARSITY_THRESHOLD} 触发')

    if history_count < SPARSITY_THRESHOLD:
        msgs.append(
            f'- 🟡 **历史类仍属稀疏**，报告会显示稀疏提示标签。'
            f'差 {SPARSITY_THRESHOLD - history_count} 条达到阈值。'
        )
    else:
        msgs.append(
            f'- ✅ **历史类已脱离稀疏**（>= {SPARSITY_THRESHOLD}），稀疏标签将自动隐藏。'
        )

    voc = snap.get('vocational_2025', 0)
    if voc < 100:
        msgs.append(f'- 🔴 **专科批数据极度不足**（{voc} 条），F7 分数段无法生成有效推荐')
    elif voc < 500:
        msgs.append(f'- 🟡 专科批数据偏少（{voc} 条）')
    else:
        msgs.append(f'- ✅ 专科批数据已覆盖（{voc} 条）')

    return msgs


def calibrate_bayesian_prior(conn: sqlite3.Connection) -> Dict:
    """模块 3：贝叶斯先验校准

    重新计算"同学校的历史类位次 / 物理类位次"实际中位数比例，
    与 sparse_prior.py 的 HISTORY_TO_PHYSICS_RATIO 常量对比。
    """
    result = {
        'current_constant': PHYSICS_HISTORY_RATIO,
        'observed_ratio': None,
        'school_count': 0,
        'recommendation': None,
    }

    try:
        rows = conn.execute(
            """
            SELECT
                h.school_name,
                AVG(h.min_rank) AS history_rank,
                (SELECT AVG(p.min_rank) FROM score_line_2025 p
                 WHERE p.school_name = h.school_name
                   AND p.subject_type IN ('物理', '物理类')
                   AND p.min_rank IS NOT NULL) AS physics_rank
            FROM score_line_2025 h
            WHERE h.subject_type IN ('历史', '历史类')
              AND h.min_rank IS NOT NULL
            GROUP BY h.school_name
            HAVING physics_rank IS NOT NULL AND physics_rank > 0
            """
        ).fetchall()
    except sqlite3.OperationalError:
        result['recommendation'] = '⚠️ score_line_2025 表缺失，无法校准，保留当前常量 0.28'
        return result

    if not rows or len(rows) < 30:
        result['recommendation'] = (
            f'⚠️ 同时有物理类和历史类数据的学校仅 {len(rows)} 所，'
            '校准样本不足，保留当前常量 0.28'
        )
        return result

    ratios = sorted(r[1] / r[2] for r in rows if r[1] and r[2])
    median_ratio = ratios[len(ratios) // 2]

    result['observed_ratio'] = round(median_ratio, 4)
    result['school_count'] = len(rows)

    diff = abs(median_ratio - PHYSICS_HISTORY_RATIO) / PHYSICS_HISTORY_RATIO
    if diff > 0.15:
        result['recommendation'] = (
            f'🔴 **校准偏差 {diff*100:.1f}%**（实测 {median_ratio:.3f} vs 常量 '
            f'{PHYSICS_HISTORY_RATIO}），建议更新 '
            f'`gaokao/core/sparse_prior.py:44 HISTORY_TO_PHYSICS_RATIO = {median_ratio:.3f}`'
        )
    elif diff > 0.05:
        result['recommendation'] = (
            f'🟡 校准偏差 {diff*100:.1f}%（实测 {median_ratio:.3f} vs 常量 '
            f'{PHYSICS_HISTORY_RATIO}），可考虑微调'
        )
    else:
        result['recommendation'] = (
            f'✅ 当前常量 {PHYSICS_HISTORY_RATIO} 与实测 {median_ratio:.3f} 吻合，无需更新'
        )

    return result


def run_p0_test() -> Optional[Dict]:
    """模块 4：跑 P0 回归测试（pytest tests/），严格按退出码判定。

    OpenGaokao 无 full_pipeline_test.py，回归门禁直接用 pytest 套件。
    任何非 0 退出码都视为失败，不允许"测试崩了但当通过"的假阳性
    （共享陷阱 6：测试可能空通过 —— returncode 是唯一可信信号）。
    """
    tests_dir = os.path.join(PROJECT_ROOT, 'tests')
    if not os.path.isdir(tests_dir):
        return {'error': 'tests/ 目录不存在，无法执行 P0 回归', 'returncode': -1}

    print('   运行 P0 回归测试（pytest tests/）...')
    try:
        proc = subprocess.run(
            [sys.executable, '-m', 'pytest', 'tests/', '-q'],
            capture_output=True, text=True, timeout=2400, cwd=PROJECT_ROOT,
        )
    except subprocess.TimeoutExpired:
        return {'error': 'P0 回归测试超时（> 40 分钟）', 'returncode': -1}
    except Exception as e:
        return {'error': f'P0 回归测试启动失败: {e}', 'returncode': -1}

    if proc.returncode != 0:
        tail = (proc.stdout or '')[-2000:] + '\n' + (proc.stderr or '')[-1000:]
        return {
            'error': f'P0 回归测试未通过（returncode={proc.returncode}）',
            'returncode': proc.returncode,
            'output_tail': tail,
        }

    # 提取 pytest 结尾汇总行（如 "42 passed in 3.21s"）
    summary = ''
    for line in reversed((proc.stdout or '').splitlines()):
        if 'passed' in line or 'failed' in line or 'error' in line:
            summary = line.strip()
            break
    return {'pass_summary': summary or 'pytest 全部通过', 'returncode': 0}


def compare_with_baseline(snap: Dict, baseline_path: str) -> List[str]:
    """模块 4 续：与基线快照对比各表行数，发现数据缩水/异常增减。"""
    msgs = []
    if not os.path.exists(baseline_path):
        msgs.append(f'- 未找到基线文件 `{baseline_path}`，跳过对比')
        return msgs

    with open(baseline_path, 'r', encoding='utf-8') as f:
        baseline = json.load(f)

    base_counts = baseline.get('data_snapshot', {}).get('table_counts', {})
    cur_counts = snap.get('table_counts', {})
    if not base_counts:
        msgs.append('- 基线无 table_counts，跳过对比')
        return msgs

    msgs.append('| 表名 | 基线行数 | 当前行数 | 变化 |')
    msgs.append('|------|---------|---------|------|')
    for t in sorted(cur_counts.keys()):
        b = base_counts.get(t)
        c = cur_counts.get(t)
        if isinstance(b, int) and isinstance(c, int):
            delta = c - b
            flag = ' 🔴缩水' if delta < 0 else ''
            msgs.append(f'| `{t}` | {b:,} | {c:,} | {delta:+,}{flag} |')
        else:
            msgs.append(f'| `{t}` | {b if b is not None else "无"} | {c if c is not None else "无"} | - |')
    return msgs


def constant_recommendations(snap: Dict, calib: Dict) -> List[str]:
    """模块 5：硬编码常量更新建议"""
    msgs = []
    sl25 = snap.get('score_line_2025_by_subject', {})
    history_count = sum(v for k, v in sl25.items() if k in ('历史', '历史类'))

    if history_count >= SPARSITY_THRESHOLD:
        msgs.append(
            f'- 历史类已达阈值（{history_count} >= {SPARSITY_THRESHOLD}），'
            '稀疏标签将自动失效，无需手动改代码'
        )
    else:
        msgs.append(f'- 历史类仍 < {SPARSITY_THRESHOLD}，保持稀疏标签开启')

    if calib.get('observed_ratio') and calib.get('school_count', 0) >= 30:
        obs = calib['observed_ratio']
        diff = abs(obs - PHYSICS_HISTORY_RATIO) / PHYSICS_HISTORY_RATIO
        if diff > 0.05:
            msgs.append(
                f'- ✏️ 建议更新 `gaokao/core/sparse_prior.py:44`：\n'
                f'  `HISTORY_TO_PHYSICS_RATIO = {obs:.3f}` （当前 {PHYSICS_HISTORY_RATIO}）'
            )

    if history_count >= 3000:
        msgs.append(
            f'- ✏️ 历史类数据已充足（{history_count}），可考虑下调 '
            f'`gaokao/core/volunteer_recommender.py:983` 历史类保档安全垫 '
            f'{HISTORY_BAO_MULTIPLIER}x → 1.1x'
        )

    if not msgs:
        msgs.append('- 无需调整')
    return msgs


def write_report(report: List[str], snap: Dict, p0_result: Optional[Dict],
                 province: str, db_path: str) -> str:
    """模块 6：输出 markdown 报告 + JSON 快照"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')

    md_path = os.path.join(OUTPUT_DIR, f'validation_{province}_{ts}.md')
    json_path = os.path.join(OUTPUT_DIR, f'validation_{province}_{ts}.json')

    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(f'# OpenGaokao 数据导入后验证报告（{province}）\n\n')
        f.write(f'**生成时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n\n')
        f.write(f'**数据库**: `{db_path}`\n\n')
        f.write('\n'.join(report))

    snapshot = {
        'timestamp': ts,
        'province': province,
        'data_snapshot': snap,
        'p0_test': p0_result or {},
    }
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    return md_path


def main():
    parser = argparse.ArgumentParser(description='OpenGaokao 数据导入后验证')
    parser.add_argument('--province', type=str, default='yunnan',
                        help='省份 slug（对应 data/<省>_gaokao.db），默认 yunnan')
    parser.add_argument('--quick', action='store_true', help='跳过 P0 回归测试')
    parser.add_argument('--baseline', type=str, default='',
                        help='基线 JSON 路径（与当前快照对比各表行数）')
    args = parser.parse_args()

    province = args.province
    db_path = resolve_db_path(province)

    print('OpenGaokao 数据导入后验证')
    print(f'省份: {province}')
    print(f'数据库: {db_path}')
    print(f'时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

    # 防 pitfalls O1：连到 0 字节假库会得出"无数据"的错误结论
    if not os.path.exists(db_path):
        print(f'\n❌ 数据库不存在: {db_path}')
        print('   提示：真库在 data/ 目录；仓库根与 gaokao/ 下的同名 db 是 0 字节假文件。')
        sys.exit(1)
    if os.path.getsize(db_path) == 0:
        print(f'\n❌ 数据库为 0 字节假文件: {db_path}（pitfalls O1）')
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    report_lines = []

    # 模块 1：数据覆盖率快照
    report_lines.append(section('一、数据覆盖率快照'))
    snap = data_coverage_snapshot(conn)
    report_lines.append('### 各表行数')
    report_lines.append('| 表名 | 行数 |')
    report_lines.append('|------|------|')
    for t, n in snap['table_counts'].items():
        n_str = f'{n:,}' if isinstance(n, int) else '表不存在'
        report_lines.append(f'| `{t}` | {n_str} |')
        print(f'  {t}: {n_str}')

    if snap.get('score_line_2025_by_subject'):
        report_lines.append('\n### score_line_2025 按科类')
        for k, v in snap['score_line_2025_by_subject'].items():
            report_lines.append(f'- {k}: {v:,}')

    if snap.get('enroll_detail_missing_rank'):
        report_lines.append('\n### enroll_detail min_rank 缺失率（实测）')
        report_lines.append('| 年份 | 总行数 | 缺失 | 缺失率 |')
        report_lines.append('|------|-------|------|-------|')
        for yr, d in snap['enroll_detail_missing_rank'].items():
            report_lines.append(
                f"| {yr} | {d['total']:,} | {d['missing']:,} | {d['missing_pct']}% |"
            )

    # 模块 1.5：科类标签门禁
    report_lines.append(section('一·五、科类标签导入门禁'))
    label_msgs, label_gate_failed = subject_label_gate(conn)
    report_lines.extend(label_msgs)
    for m in label_msgs:
        print(f'  {m}')

    # 模块 2：稀疏检测
    report_lines.append(section('二、数据稀疏阈值检测'))
    msgs = sparsity_check(snap)
    report_lines.extend(msgs)
    for m in msgs:
        print(f'  {m}')

    # 模块 3：贝叶斯先验校准
    report_lines.append(section('三、贝叶斯先验校准（HISTORY_TO_PHYSICS_RATIO）'))
    calib = calibrate_bayesian_prior(conn)
    report_lines.append(f"- 当前常量: **{calib['current_constant']}**")
    if calib['observed_ratio']:
        report_lines.append(
            f"- 实测中位数: **{calib['observed_ratio']}**（基于 {calib['school_count']} 所学校）"
        )
    report_lines.append(f"- 建议: {calib['recommendation']}")
    print(f"  当前常量: {calib['current_constant']}")
    print(f"  实测: {calib.get('observed_ratio', 'N/A')}")
    print(f"  建议: {calib['recommendation']}")

    # 模块 4：P0 回归测试 + 基线对比
    p0_result = None
    if not args.quick:
        report_lines.append(section('四、P0 回归测试与基线对比'))
        p0_result = run_p0_test()
        if p0_result and 'error' not in p0_result:
            report_lines.append(f"- ✅ {p0_result['pass_summary']}")
            print(f"  ✅ {p0_result['pass_summary']}")
        elif p0_result:
            report_lines.append(f"- ❌ {p0_result['error']}")
            print(f"  ❌ {p0_result['error']}")
        if args.baseline:
            report_lines.extend(compare_with_baseline(snap, args.baseline))
    else:
        report_lines.append(section('四、P0 回归测试'))
        report_lines.append('（已跳过 — `--quick` 模式）')
        if args.baseline:
            report_lines.extend(compare_with_baseline(snap, args.baseline))

    # 模块 5：常量更新建议
    report_lines.append(section('五、硬编码常量更新建议'))
    msgs = constant_recommendations(snap, calib)
    report_lines.extend(msgs)
    for m in msgs:
        print(f'  {m}')

    # 模块 6：输出报告
    md_path = write_report(report_lines, snap, p0_result, province, db_path)
    print(f'\n报告已生成: {md_path}')

    conn.close()

    # 退出码语义：带病数据/回归失败必须暴露，不允许仅记录在报告里就当通过
    if p0_result and 'error' in p0_result:
        print(f'\n❌ 验证失败：P0 回归测试未通过（{p0_result.get("error")}）', file=sys.stderr)
        sys.exit(1)

    if label_gate_failed:
        print('\n❌ 验证失败：存在集合外科类标签（详见上方"一·五"）', file=sys.stderr)
        sys.exit(1)

    print('\n✅ 验证通过')


if __name__ == '__main__':
    main()
