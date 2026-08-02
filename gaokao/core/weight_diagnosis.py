# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""
推荐权重诊断脚本 V3.0
========================
校准发现100%命中率→评估指标过宽。本脚本从以下维度诊断权重合理性：

1. 霍兰德主导性：首码权重是否显著大于次码/第三码
2. BOOST合理性：BigFive/效能感BOOST是否适度（不过度覆盖霍兰德）
3. 区分度测试：不同霍兰德码的推荐是否不同
4. 交叉干扰测试：霍兰德IR型考生的推荐是否包含S/A专业
5. 参数敏感性：改变一个权重是否导致推荐变化
"""

from .personality_test import PersonalityTestEngine

# ──────────────────────────────────────────
# 1. 霍兰德主导性测试
# ──────────────────────────────────────────
def test_holland_dominance(engine):
    """测试霍兰德码在推荐中的主导性"""
    print("\n" + "=" * 70)
    print("测试1: 霍兰德主导性")
    print("=" * 70)

    # 纯RI型霍兰德（不掺入任何Big Five/效能感/价值观影响）
    bf = {'O': 3.0, 'C': 3.0, 'E': 3.0, 'A': 3.0, 'N': 3.0}  # 所有维度中性
    se = {'chinese': 3.0, 'math': 3.0, 'english': 3.0}  # 所有效能中性
    cv = {k: 3.0 for k in ['income', 'stability', 'achievement', 'help',
                            'creative', 'balance', 'leadership', 'autonomy',
                            'location', 'learning']}  # 所有价值观中性

    # 测试不同霍兰德代码
    test_codes = ['RIA', 'IRE', 'SAE', 'ESC', 'ARC', 'RCE']

    for code in test_codes:
        recs = engine.generate_recommendations(bf, code, se, cv)
        # 检查前3个推荐的前2个字母是否在霍兰德码中
        hit_in_top3 = sum(1 for m in recs[:3]
                         if any(c in code for c in 'RIASEC'
                                if c in engine.HOLLAND_MAJOR_MAP
                                and m in engine.HOLLAND_MAJOR_MAP[c]))
        # 找到第一个来自HOLLAND_MAJOR_MAP的推荐
        first_holland_idx = None
        for i, m in enumerate(recs):
            for dim in code:
                if m in engine.HOLLAND_MAJOR_MAP.get(dim, []):
                    first_holland_idx = i
                    break
            if first_holland_idx is not None:
                break

        print(f"\n  霍兰德码: {code}")
        print(f"  推荐TOP5: {', '.join(recs[:5])}")
        print(f"  首码维度专业在TOP3: {hit_in_top3}/3")
        if first_holland_idx is not None:
            print(f"  首个码相关专业排名: #{first_holland_idx + 1}")
        else:
            print(f"  ⚠️  TOP10中无霍兰德直接相关专业")


# ──────────────────────────────────────────
# 2. BOOST合理性测试
# ──────────────────────────────────────────
def test_boost_reasonableness(engine):
    """测试BOOST是否过度覆盖霍兰德"""
    print("\n" + "=" * 70)
    print("测试2: BOOST合理性（不同Big Five配置对比）")
    print("=" * 70)

    holland_code = 'RIA'
    se = {'chinese': 3.0, 'math': 3.0, 'english': 3.0}
    cv = {k: 3.0 for k in ['income', 'stability', 'achievement', 'help',
                            'creative', 'balance', 'leadership', 'autonomy',
                            'location', 'learning']}

    # 基准：所有Big Five中性
    bf_neutral = {'O': 3.0, 'C': 3.0, 'E': 3.0, 'A': 3.0, 'N': 3.0}

    # 高开放性 → 会增加O_high专业
    bf_ohigh = {'O': 4.5, 'C': 3.0, 'E': 3.0, 'A': 3.0, 'N': 3.0}

    recs_neutral = engine.generate_recommendations(bf_neutral, holland_code, se, cv)
    recs_ohigh = engine.generate_recommendations(bf_ohigh, holland_code, se, cv)

    print(f"\n  基准霍兰德: {holland_code}")
    print(f"  中性BigFive TOP10: {recs_neutral[:10]}")
    print(f"  高O BigFive TOP10: {recs_ohigh[:10]}")

    # 计算变化
    new_majors = [m for m in recs_ohigh if m not in recs_neutral]
    removed_majors = [m for m in recs_neutral if m not in recs_ohigh]

    print(f"\n  高O新增: {new_majors}")
    print(f"  高O移除: {removed_majors}")
    print(f"  变化数: {len(new_majors)} (占比{len(new_majors)/len(recs_neutral)*100 if recs_neutral else 0:.0f}%)")

    if len(new_majors) == 0 and len(removed_majors) == 0:
        print(f"  → BOOST完全无影响（权重过小或阈值过高）")
    elif len(new_majors) >= 5:
        print(f"  → BOOST过度影响（权重过大，覆盖了霍兰德）")
    else:
        print(f"  → BOOST影响合理（适度修正）")


# ──────────────────────────────────────────
# 3. 区分度测试
# ──────────────────────────────────────────
def test_discrimination(engine):
    """测试不同考生是否产生不同推荐"""
    print("\n" + "=" * 70)
    print("测试3: 区分度（6种典型考生profile推荐对比）")
    print("=" * 70)

    se = {'chinese': 3.0, 'math': 3.0, 'english': 3.0}
    cv = {k: 3.0 for k in ['income', 'stability', 'achievement', 'help',
                            'creative', 'balance', 'leadership', 'autonomy',
                            'location', 'learning']}
    bf_neutral = {'O': 3.0, 'C': 3.0, 'E': 3.0, 'A': 3.0, 'N': 3.0}

    profiles = {
        'IR型(理工)': 'IRE',
        'SA型(人文)': 'SAE',
        'EC型(经管)': 'ESC',
        'AR型(艺术)': 'ARC',
        'RC型(技工)': 'RCE',
        'IS型(医疗)': 'ISR',
    }

    recommendations = {}
    for label, code in profiles.items():
        recs = engine.generate_recommendations(bf_neutral, code, se, cv)
        recommendations[label] = recs[:6]

    # 打印对比
    print(f"\n  {'考生类型':15s} {'推荐TOP6'}")
    print(f"  {'-'*15} {'-'*50}")
    for label, recs in recommendations.items():
        print(f"  {label:15s} {', '.join(recs)}")

    # 计算两两Jaccard相似度
    labels = list(recommendations.keys())
    max_sim = 0
    max_pair = ('', '')
    min_sim = 1
    min_pair = ('', '')

    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            set_i = set(recommendations[labels[i]])
            set_j = set(recommendations[labels[j]])
            intersection = len(set_i & set_j)
            union = len(set_i | set_j)
            sim = intersection / union if union > 0 else 0
            if sim > max_sim:
                max_sim = sim
                max_pair = (labels[i], labels[j])
            if sim < min_sim:
                min_sim = sim
                min_pair = (labels[i], labels[j])

    print(f"\n  最大Jaccard相似度: {max_sim:.2f} ({max_pair[0]} vs {max_pair[1]})")
    print(f"  最小Jaccard相似度: {min_sim:.2f} ({min_pair[0]} vs {min_pair[1]})")

    if max_sim > 0.6:
        print(f"  ⚠️  某些不同profile推荐高度相似（区分度不足）")
    elif min_sim < 0.1:
        print(f"  → 区分度良好")
    else:
        print(f"  → 区分度可接受")


# ──────────────────────────────────────────
# 4. 交叉干扰测试
# ──────────────────────────────────────────
def test_cross_contamination(engine):
    """测试推荐是否包含不相关专业的推荐"""
    print("\n" + "=" * 70)
    print("测试4: 交叉干扰测试（IR型考生是否推荐了S/A专业）")
    print("=" * 70)

    # IR型考生
    bf = {'O': 3.0, 'C': 3.0, 'E': 3.0, 'A': 3.0, 'N': 3.0}
    se = {'chinese': 3.0, 'math': 3.0, 'english': 3.0}
    cv = {k: 3.0 for k in ['income', 'stability', 'achievement', 'help',
                            'creative', 'balance', 'leadership', 'autonomy',
                            'location', 'learning']}

    recs = engine.generate_recommendations(bf, 'IRE', se, cv)

    # 检查每个推荐属于哪个霍兰德维度
    dim_assignments = {}
    for dim, majors in engine.HOLLAND_MAJOR_MAP.items():
        for m in majors:
            dim_assignments[m] = dim

    ir_majors = []
    saec_majors = []
    unmapped = []

    for m in recs:
        assigned_dim = dim_assignments.get(m, '?')
        if assigned_dim in ('R', 'I'):
            ir_majors.append((m, assigned_dim))
        elif assigned_dim in ('S', 'A', 'E', 'C'):
            saec_majors.append((m, assigned_dim))
        else:
            unmapped.append(m)

    print(f"\n  霍兰德IRE推荐分析:")
    print(f"  IR相关（预期内）: {[f'{m}({d})' for m, d in ir_majors]}")
    print(f"  其他维度（干扰）: {[f'{m}({d})' for m, d in saec_majors]}")
    print(f"  未映射: {unmapped}")

    ir_ratio = len(ir_majors) / len(recs) if recs else 0
    print(f"\n  IR专业占比: {ir_ratio:.0%}")
    if ir_ratio >= 0.6:
        print(f"  → 干扰比例低（推荐聚焦）")
    elif ir_ratio >= 0.4:
        print(f"  → 干扰比例中等（推荐有一定聚焦）")
    else:
        print(f"  ⚠️  干扰比例过高（推荐散乱）")


# ──────────────────────────────────────────
# 5. 参数敏感性测试
# ──────────────────────────────────────────
def test_parameter_sensitivity(engine):
    """测试权重变化是否导致推荐变化"""
    print("\n" + "=" * 70)
    print("测试5: 参数敏感性")
    print("=" * 70)

    bf = {'O': 4.5, 'C': 4.0, 'E': 3.5, 'A': 4.0, 'N': 2.5}
    se = {'chinese': 4.5, 'math': 4.0, 'english': 3.5}
    cv = {
        'income': 4.0, 'stability': 3.0, 'achievement': 4.5, 'help': 3.5,
        'creative': 4.0, 'balance': 3.0, 'leadership': 3.5, 'autonomy': 4.0,
        'location': 3.5, 'learning': 4.5
    }

    # 基准推荐
    baseline = engine.generate_recommendations(bf, 'RIA', se, cv)
    print(f"\n  基准(H3.0/2.0/1.0, B1.0, V0.8): {baseline[:10]}")

    changes = []

    # 改变霍兰德首位权重
    # 注意：generate_recommendations内部硬编码了权重，
    # 这里通过改变输入间接测试

    # 测试1: 改变霍兰德码
    recs_ria = engine.generate_recommendations(bf, 'RIA', se, cv)
    recs_ria_rev = engine.generate_recommendations(bf, 'AIR', se, cv)
    diff = len(set(recs_ria[:6]) - set(recs_ria_rev[:6]))
    changes.append(('霍兰德码首↔次互换', diff, 6))

    # 测试2: 改变Big Five
    bf_no_boost = {'O': 3.0, 'C': 3.0, 'E': 3.0, 'A': 3.0, 'N': 3.0}
    recs_no_bf = engine.generate_recommendations(bf_no_boost, 'RIA', se, cv)
    diff = len(set(recs_ria[:10]) - set(recs_no_bf[:10]))
    changes.append(('Big FiveBOOST生效/取消', diff, 10))

    # 测试3: 改变效能感
    se_low = {'chinese': 2.0, 'math': 2.0, 'english': 2.0}
    recs_low_se = engine.generate_recommendations(bf, 'RIA', se_low, cv)
    diff = len(set(recs_ria[:10]) - set(recs_low_se[:10]))
    changes.append(('效能感高→低', diff, 10))

    # 测试4: 改变职业价值观
    cv_diff = {
        'income': 2.0, 'stability': 5.0, 'achievement': 2.0, 'help': 5.0,
        'creative': 2.0, 'balance': 5.0, 'leadership': 2.0, 'autonomy': 2.0,
        'location': 2.0, 'learning': 2.0
    }
    recs_diff_cv = engine.generate_recommendations(bf, 'RIA', se, cv_diff)
    diff = len(set(recs_ria[:10]) - set(recs_diff_cv[:10]))
    changes.append(('职业价值观反转', diff, 10))

    print(f"\n  {'测试项':30s} {'变化专业数':>8s} {'总可选':>6s} {'敏感度':>8s}")
    print(f"  {'-'*30} {'-'*8} {'-'*6} {'-'*8}")
    for name, changed, total in changes:
        sensitivity = changed / total if total > 0 else 0
        level = "高" if sensitivity > 0.4 else ("中" if sensitivity > 0.15 else "低")
        print(f"  {name:30s} {changed:>8d} {total:>6d} {level:>8s} ({sensitivity:.0%})")

    all_sensitive = all((d / t) > 0.1 for d, t in [x[1:] for x in changes])
    if all_sensitive:
        print(f"\n  → 所有参数均对推荐有影响（敏感性合理）")
    else:
        print(f"\n  ⚠️  某些参数对推荐无影响（可能需要调整阈值/权重）")


# ──────────────────────────────────────────
# 6. 推荐映射表覆盖度分析
# ──────────────────────────────────────────
def test_mapping_coverage():
    """分析推荐映射表与数据库的覆盖度"""
    import sqlite3

    print("\n" + "=" * 70)
    print("测试6: 推荐映射表与数据库覆盖度")
    print("=" * 70)

    conn = sqlite3.connect(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'yunnan_gaokao.db'
    ))
    c = conn.cursor()

    c.execute('SELECT DISTINCT major_name FROM enroll_detail WHERE major_name IS NOT NULL')
    db_majors = set(row[0] for row in c.fetchall())

    engine = PersonalityTestEngine()

    all_rec_majors = set()
    all_rec_majors.update(engine.HOLLAND_MAJOR_MAP.get('R', []))
    all_rec_majors.update(engine.HOLLAND_MAJOR_MAP.get('I', []))
    all_rec_majors.update(engine.HOLLAND_MAJOR_MAP.get('A', []))
    all_rec_majors.update(engine.HOLLAND_MAJOR_MAP.get('S', []))
    all_rec_majors.update(engine.HOLLAND_MAJOR_MAP.get('E', []))
    all_rec_majors.update(engine.HOLLAND_MAJOR_MAP.get('C', []))

    exact_match = all_rec_majors & db_majors
    partial_match = []
    unmatched = []

    for m in all_rec_majors:
        if m in exact_match:
            continue
        matched = [db for db in db_majors if m in db or db in m]
        if matched:
            partial_match.append((m, matched[:2]))
        else:
            unmatched.append(m)

    conn.close()

    print(f"\n  推荐专业总数: {len(all_rec_majors)}")
    print(f"  精确匹配: {len(exact_match)}")
    print(f"  部分匹配(子串): {len(partial_match)}")
    for m, hits in partial_match:
        print(f"    {m} ≈ {hits}")
    print(f"  完全未匹配: {len(unmatched)}")
    for m in unmatched:
        print(f"    ✗ {m}")

    coverage = (len(exact_match) + len(partial_match)) / len(all_rec_majors) * 100 if all_rec_majors else 0
    print(f"\n  总覆盖度: {coverage:.0f}%")
    if coverage >= 90:
        print(f"  → 覆盖度良好")
    elif coverage >= 70:
        print(f"  → 覆盖度可接受")
    else:
        print(f"  ⚠️  覆盖度不足（需要扩充映射表）")


# ──────────────────────────────────────────
# 主函数
# ──────────────────────────────────────────
def main():
    print('=' * 70)
    print('推荐权重诊断脚本 V3.0')
    print('=' * 70)

    engine = PersonalityTestEngine()

    test_holland_dominance(engine)
    test_boost_reasonableness(engine)
    test_discrimination(engine)
    test_cross_contamination(engine)
    test_parameter_sensitivity(engine)
    test_mapping_coverage()

    print("\n" + "=" * 70)
    print("诊断完成！")
    print("=" * 70)


if __name__ == '__main__':
    main()
