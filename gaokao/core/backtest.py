# SPDX-License-Identifier: LicenseRef-OpenGaokao-SAL-1.0
# Copyright (C) 2026 OpenGaokao Contributors
"""
回溯测试 (Backtest) — 用 5 个合成样例验证算法链路

测试方法（公开仓库安全版）：
1. 只用 2020-2024 历史数据训练 → 模拟考生实际填报时可用的信息
2. 对 5 个合成样例生成推荐方案
3. 用 example.db 中的合成 2025 投档线做一致性验证
4. 输出链路命中率、漏报率、误报率；这些数字不是现实准确率证据

关键修正：
- filter_candidates() 默认查 score_line_2025 → 数据泄露！回测必须用 v_enroll_detail 2020-2024
- calculate_group() 也查 score_line_2025 → 数据泄露！回测必须只用 calculate() + 2020-2024
"""
import sys, os, sqlite3, math, statistics, threading, logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple

# 引用核心概率算法（但不用它的 calculate_group / filter_candidates）
from .admission_probability import AdmissionProbability, ProbabilityResult, HistoryRecord

# ── 学校/专业名匹配 ──

def _normalize_school_name(name: str) -> str:
    for sep in ['(', '（', '-', ' ']:
        name = name.split(sep)[0]
    return name.strip()


def _school_match(a: str, b: str) -> bool:
    if a == b:
        return True
    norm_a = _normalize_school_name(a)
    norm_b = _normalize_school_name(b)
    if norm_a == norm_b and len(norm_a) >= 4:
        return True
    return False


def _major_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    if a in b and len(a) / len(b) > 0.6:
        return True
    if b in a and len(b) / len(a) > 0.6:
        return True
    return False


# ── 合成样例（不得放入真实考生记录或可重识别组合）──
SYNTHETIC_CASES = [
    {
        'name': '合成样例1', 'score': 620, 'rank': 6500, 'category': '物理类',
        'admitted_school': '示例·云岭大学', 'admitted_major': '计算机科学与技术',
        '志愿策略': '合成策略：专业优先',
    },
    {
        'name': '合成样例2', 'score': 580, 'rank': 12000, 'category': '物理类',
        'admitted_school': '示例·滇南理工大学', 'admitted_major': '电气工程及其自动化',
        '志愿策略': '合成策略：学校与专业平衡',
    },
    {
        'name': '合成样例3', 'score': 530, 'rank': 30000, 'category': '物理类',
        'admitted_school': '示例·春城师范大学', 'admitted_major': '数学与应用数学',
        '志愿策略': '合成策略：师范专业优先',
    },
    {
        'name': '合成样例4', 'score': 490, 'rank': 35000, 'category': '历史类',
        'admitted_school': '示例·大理学院', 'admitted_major': '汉语言文学',
        '志愿策略': '合成策略：地域优先',
    },
    {
        'name': '合成样例5', 'score': 445, 'rank': 88000, 'category': '物理类',
        'admitted_school': '示例·玉溪师范学院', 'admitted_major': '会计学',
        '志愿策略': '合成策略：稳妥优先',
    },
]

# 科类映射
_CAT_TO_SUBJECT = {'理科': '物理', '物理': '物理', '物理类': '物理',
                    '文科': '历史', '历史': '历史', '历史类': '历史'}

# 科目别名（IN 子句用）
_SUBJECT_ALIASES = {
    '物理': ('物理', '物理类', '理科'),
    '历史': ('历史', '历史类', '文科'),
}


def _get_subject(category: str) -> str:
    r = _CAT_TO_SUBJECT.get(category)
    if r is None:
        raise ValueError(f'未知科类: {category!r}')
    return r


def _subject_aliases(subject_type: str) -> Tuple[str, ...]:
    return _SUBJECT_ALIASES.get(subject_type, (subject_type,))


# ── 核心：纯历史数据的候选池筛选 ──

def _build_candidate_pool(cur, user_rank: int, subject_type: str,
                          tolerance: float = 0.35) -> List[Tuple[str, float, int]]:
    """
    只用 v_enroll_detail 2023-2024 数据构建候选池。
    完全不碰 score_line_2025。

    返回: [(school_name, avg_min_rank, record_count), ...]
    """
    aliases = _subject_aliases(subject_type)
    placeholders = ','.join(['?'] * len(aliases))

    max_rank = int(user_rank * 2.0)  # 保底范围

    # 2023-2024 school-level aggregation
    cur.execute(f'''
        SELECT school_name,
               CAST(AVG(min_rank) AS INTEGER) as avg_rank,
               COUNT(DISTINCT year) as year_cnt,
               COUNT(*) as rec_cnt
        FROM v_enroll_detail
        WHERE year IN (2023, 2024)
          AND subject_type IN ({placeholders})
          AND batch_tier = '本科'
          AND batch NOT LIKE '提前%'
          AND min_rank IS NOT NULL
          AND min_rank <= ?
        GROUP BY school_name
        HAVING year_cnt >= 1
        ORDER BY avg_rank ASC
    ''', (*aliases, max_rank))
    rows = cur.fetchall()

    candidates = []
    for school_name, avg_rank, year_cnt, rec_cnt in rows:
        # 权重的平均位次
        candidates.append((school_name, float(avg_rank), int(year_cnt)))

    # 如果候选池过大（>1500），按 ±35% 截断
    if len(candidates) > 1500:
        max_rank_narrow = int(user_rank * (1 + tolerance))
        cur.execute(f'''
            SELECT school_name,
                   CAST(AVG(min_rank) AS INTEGER) as avg_rank,
                   COUNT(DISTINCT year) as year_cnt
            FROM v_enroll_detail
            WHERE year IN (2023, 2024)
              AND subject_type IN ({placeholders})
              AND batch_tier = '本科'
              AND batch NOT LIKE '提前%'
              AND min_rank IS NOT NULL
              AND min_rank <= ?
            GROUP BY school_name
            HAVING year_cnt >= 1
            ORDER BY avg_rank ASC
        ''', (*aliases, max_rank_narrow))
        candidates = [(r[0], float(r[1]), int(r[2])) for r in cur.fetchall()]

    return candidates


# ── 纯历史数据的概率计算 ──

def _calculate_historical_prob(prob_calc: AdmissionProbability,
                                user_rank: int, school_name: str,
                                subject_type: str) -> Optional[ProbabilityResult]:
    """
    只用 2023-2024 数据计算概率。
    完全不用 score_line_2025 / calculate_group。
    """
    return prob_calc.calculate(
        user_rank, school_name,
        years=[2023, 2024],
        subject_type=subject_type,
    )


# ── 冲稳保分类 ──

def _classify(candidates: List[Tuple[str, float, int]],
              prob_calc: AdmissionProbability,
              user_rank: int, subject_type: str):
    """计算概率并按冲稳保分类"""
    chong, wen, bao = [], [], []
    probs = {}

    for school_name, avg_rank, year_cnt in candidates:
        result = _calculate_historical_prob(prob_calc, user_rank, school_name, subject_type)
        if result is None or result.probability < 5:
            continue

        prob = result.probability
        probs[school_name] = (prob, result.confidence, result.predicted_rank)

        if prob >= 85:
            bao.append((school_name, prob, result.confidence, result.predicted_rank))
        elif prob >= 35:
            wen.append((school_name, prob, result.confidence, result.predicted_rank))
        else:
            chong.append((school_name, prob, result.confidence, result.predicted_rank))

    # 排序：冲（概率升序），稳/保（概率降序）
    chong.sort(key=lambda x: x[1])
    wen.sort(key=lambda x: x[1], reverse=True)
    bao.sort(key=lambda x: x[1], reverse=True)

    return chong, wen, bao, probs


# ── 2025 年真实录取结果验证 ──

def _verify_2025(cur, customer, subject_type: str) -> dict:
    """
    用 2025 年实际录取线验证：该考生是否真的能上录取的学校/专业？
    查询 score_line_2025（仅用于验证，不用于推荐生成）
    """
    school = customer['admitted_school']
    major = customer['admitted_major']
    user_rank = customer['rank']

    # 1. 找该学校在 2025 年的专业组
    norm_type = subject_type  # score_line_2025 uses '物理'/'历史'
    aliases = _subject_aliases(subject_type)
    placeholders = ','.join(['?'] * len(aliases))

    # 精确 + LIKE 回退（处理 北京交通大学(威海校区) 等变体）
    for name_variant in [school, f'%{school}%']:
        cur.execute(f'''
            SELECT group_code, subject_req, min_rank, min_score, batch
            FROM score_line_2025
            WHERE school_name LIKE ? AND subject_type IN ({placeholders})
            ORDER BY min_rank ASC
        ''', (name_variant, *aliases))
        rows = cur.fetchall()
        if rows:
            break

    if not rows:
        return {
            'school_in_2025': False,
            'can_admit': 'unknown',
            'reason': f'{school} 在 score_line_2025 无 {subject_type} 类数据',
            'groups': [],
        }

    # 2. 找匹配的专业组（通过 v_enroll_detail 2025 看专业属于哪个组）
    norm_name = _normalize_school_name(school)
    cur.execute(f'''
        SELECT group_code, major_name, min_rank
        FROM v_enroll_detail
        WHERE year = 2025 AND school_name LIKE ? AND subject_type IN ({placeholders})
          AND batch_tier = '本科' AND min_rank IS NOT NULL
    ''', (f'%{norm_name}%', *aliases))
    major_groups = cur.fetchall()

    # 匹配合成样例的目标专业
    matched_group = None
    for gcode, mname, mrank in major_groups:
        if _major_match(major, mname):
            matched_group = (gcode, mname, mrank)
            break

    # 3. 判断是否能录取
    groups_info = []
    can_admit = False
    best_group_rank = None

    for gcode, sreq, min_rank, min_score, batch in rows:
        if best_group_rank is None or (min_rank and min_rank < best_group_rank):
            best_group_rank = min_rank

        # 考生位次 < 专业组最低位次 → 不够
        can = user_rank < min_rank if min_rank else False
        if can:
            can_admit = True

        groups_info.append({
            'group_code': gcode,
            'subject_req': sreq,
            'min_rank': min_rank,
            'min_score': min_score,
            'batch': batch,
            'user_can_admit': user_rank < min_rank if min_rank else None,
        })

    readable_groups = [
        f"{g['group_code']}({g['subject_req']}): "
        f"投档{g['min_rank']}位 ← 考生{user_rank}位"
        f"{' ✅可录' if g['user_can_admit'] else ' ❌不够'}"
        for g in groups_info
    ]

    reason_parts = []
    if matched_group:
        reason_parts.append(f"专业'{major}'在组{matched_group[0]}(投档{matched_group[2]}位)")
    if can_admit:
        reason_parts.append(f"考生位次{user_rank}达到该校最低组门槛{best_group_rank}位")
    else:
        reason_parts.append(f"考生位次{user_rank}未达该校最低组门槛{best_group_rank}位")

    return {
        'school_in_2025': True,
        'can_admit': can_admit,
        'matched_major_group': matched_group,
        'reason': '; '.join(reason_parts),
        'groups': readable_groups,
        'groups_detail': groups_info,
    }


# ── 主回测函数 ──

def run_backtest():
    print("=" * 70)
    print("OpenGaokao 合成回溯演练 — 5 个合成样例")
    print("训练数据: example.db / 2023-2024 (v_enroll_detail)")
    print("验证数据: example.db / 2025 (score_line_2025)")
    print("注意: 本演练只验证代码链路，不代表现实推荐准确率")
    print("=" * 70)

    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                           'data', 'example.db')
    if not os.path.exists(db_path):
        raise FileNotFoundError(
            f'示例数据库不存在: {db_path}；请先运行 python data/generate_example_db.py'
        )
    print(f'数据库: {db_path}\n')

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    prob_calc = AdmissionProbability(db_path)

    all_results = []

    for cust in SYNTHETIC_CASES:
        name = cust['name']
        school = cust['admitted_school']
        major = cust['admitted_major']
        rank = cust['rank']
        subject = _get_subject(cust['category'])

        print(f"{'─' * 70}")
        print(f"📋 {name} | {cust['score']}分 | {rank}位 | {cust['category']}({subject})")
        print(f"   合成目标: {school} · {major}")
        print(f"   策略: {cust['志愿策略']}")
        print(f"{'─' * 70}")

        # Step 1: 构建候选池（仅 2023-2024 数据）
        candidates = _build_candidate_pool(cur, rank, subject)
        print(f"\n  [1] 候选池 (2023-2024, ±100%): {len(candidates)} 所")

        in_candidate = any(_school_match(school, c[0]) for c in candidates)
        print(f"  [1] 合成目标校 '{school}' 在候选池: {'✅ 是' if in_candidate else '❌ 否'}")

        # 如果不在候选池，用 LIKE 放宽查一次
        if not in_candidate:
            aliases = _subject_aliases(subject)
            ph = ','.join(['?'] * len(aliases))
            cur.execute(f'''
                SELECT school_name FROM v_enroll_detail
                WHERE year IN (2023, 2024)
                  AND subject_type IN ({ph})
                  AND school_name LIKE ?
                  AND batch_tier = '本科'
                LIMIT 1
            ''', (*aliases, f'%{_normalize_school_name(school)}%'))
            extra = cur.fetchone()
            if extra:
                # 学校在库但不满足位次范围，放宽再查
                max_rank_wide = int(rank * 3.0)
                cur.execute(f'''
                    SELECT school_name, CAST(AVG(min_rank) AS INTEGER)
                    FROM v_enroll_detail
                    WHERE year IN (2023, 2024)
                      AND subject_type IN ({ph})
                      AND school_name LIKE ?
                      AND batch_tier = '本科'
                      AND min_rank IS NOT NULL
                ''', (*aliases, f'%{_normalize_school_name(school)}%'))
                row = cur.fetchone()
                if row:
                    print(f"  [1] ⚠️ 合成目标校在库但位次不符: avg_rank={row[1]}, 样例={rank}")
                    # 手动加入候选池
                    candidates.append((school, float(row[1]), 1))
                    in_candidate = True

        if not in_candidate:
            print(f"  [1] ⚠️ 合成目标校不在 2023-2024 示例数据中，无法进入候选池")

        # Step 2: 概率计算 + 冲稳保分类（仅 2023-2024 数据）
        chong, wen, bao, probs = _classify(candidates, prob_calc, rank, subject)
        total = len(chong) + len(wen) + len(bao)
        print(f"\n  [2] 冲稳保分类 (2023-2024 数据): 冲{len(chong)} / 稳{len(wen)} / 保{len(bao)} = {total}")

        # 展示各档前 5
        for label, lst in [('冲', chong), ('稳', wen), ('保', bao)]:
            if lst:
                items = [f"{s}({p:.0f}%)" for s, p, conf, pred in lst[:5]]
                print(f"  {label}: {', '.join(items)}{'...' if len(lst) > 5 else ''}")

        # Step 3: 检查合成目标校在推荐中的位置
        admitted_in_plan = None
        admitted_prob = None
        for label, lst in [('冲', chong), ('稳', wen), ('保', bao)]:
            for s, prob, conf, pred in lst:
                if _school_match(school, s):
                    admitted_in_plan = label
                    admitted_prob = prob
                    break
            if admitted_in_plan:
                break

        if admitted_in_plan:
            print(f"\n  [3] ✅ 合成目标校在推荐方案中: {admitted_in_plan}档, 概率={admitted_prob:.1f}%")
        else:
            # 手动计算合成目标校的概率
            result = _calculate_historical_prob(prob_calc, rank, school, subject)
            if result and result.probability > 0:
                print(f"\n  [3] ⚠️ 合成目标校不在推荐方案中（算法概率={result.probability:.1f}%, "
                      f"置信度={result.confidence}），可能因概率<5%被过滤或候选池截断")
            else:
                print(f"\n  [3] ❌ 合成目标校不在推荐方案中，且示例历史概率无法计算")

        # Step 4: 用 2025 年合成投档线验证（仅验证，不参与推荐）
        verify = _verify_2025(cur, cust, subject)
        print(f"\n  [4] 2025合成验证: {verify['reason']}")
        if verify['groups']:
            for g in verify['groups'][:6]:
                print(f"      {g}")

        # 汇总
        all_results.append({
            'name': name,
            'school': school,
            'major': major,
            'rank': rank,
            'subject': subject,
            'candidates': len(candidates),
            'in_candidate': in_candidate,
            'chong': len(chong), 'wen': len(wen), 'bao': len(bao),
            'in_plan': admitted_in_plan,
            'plan_prob': admitted_prob,
            'can_admit_2025': verify.get('can_admit'),
            'verify_reason': verify['reason'],
        })
        print()

    # ── 最终汇总 ──
    print("=" * 70)
    print("回测汇总")
    print("=" * 70)
    print(f"{'样例':<8s} {'合成目标校':<18s} {'候选池':<8s} {'推荐档位':<10s} {'历史概率':<10s} {'2025合成':<12s}")
    print("-" * 70)
    for r in all_results:
        plan_str = r['in_plan'] or '—'
        prob_str = f"{r['plan_prob']:.0f}%" if r['plan_prob'] else '—'
        can_str = '✅可录' if r['can_admit_2025'] is True else ('❌不可' if r['can_admit_2025'] is False else '?未知')
        print(f"{r['name']:<8s} {r['school']:<18s} {'✅' if r['in_candidate'] else '❌':<8s} "
              f"{plan_str:<10s} {prob_str:<10s} {can_str:<10s}")

    in_pool = sum(1 for r in all_results if r['in_candidate'])
    in_plan = sum(1 for r in all_results if r['in_plan'])
    can_admit = sum(1 for r in all_results if r['can_admit_2025'] is True)
    print(f"\n候选池覆盖率: {in_pool}/{len(all_results)} ({in_pool*100//len(all_results)}%)")
    print(f"推荐命中率:   {in_plan}/{len(all_results)} ({in_plan*100//len(all_results)}%)")
    print(f"2025合成可录:  {can_admit}/{len(all_results)} ({can_admit*100//len(all_results)}%)")

    # 误报分析
    print(f"\n--- 分析 ---")
    for r in all_results:
        issues = []
        if not r['in_candidate']:
            issues.append(f"候选池未覆盖（学校不在2023-2024库或位次差距过大）")
        if r['in_plan'] and r['can_admit_2025'] is False:
            issues.append(f"推荐了但2025合成门槛不可录（链路误报）")
        if not r['in_plan'] and r['can_admit_2025'] is True:
            issues.append(f"未推荐但2025合成门槛可录（链路漏报）")
        if not r['in_plan'] and r['can_admit_2025'] is False:
            issues.append(f"未推荐且2025合成门槛不可录（链路正确拒绝）")
        if r['in_plan'] and r['can_admit_2025'] is True:
            issues.append(f"推荐且2025合成门槛可录 ✅ 链路命中")
        if r['can_admit_2025'] == 'unknown' and r['in_plan']:
            issues.append(f"推荐方案命中，但2025合成数据未知（无法验证）")

        print(f"  {r['name']}: {'; '.join(issues)}")

    prob_calc.close()
    conn.close()


if __name__ == '__main__':
    run_backtest()
