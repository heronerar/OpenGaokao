# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""
推荐权重校准脚本 V3.0
========================
目标：通过历史录取数据反推，校准四维融合推荐的权重参数。

校准策略：
1. 从enroll_detail中按major_class分层采样，构建校准集
2. 对每条记录，根据学科分数模拟性格数据
3. 用不同权重组合生成推荐专业列表
4. 计算推荐列表与实际专业(major_class级别)的命中率
5. 网格搜索最优权重

权重参数：
  holland_weights = (w_h1, w_h2, w_h3)  # 霍兰德三位码权重
  boost_weight = w_boost                 # Big Five/效能感/价值观统一BOOST权重
  values_weight = w_values               # 职业价值观权重
"""
import sqlite3
import random
import itertools
import json
from collections import defaultdict
from typing import Dict, List, Tuple

import sys, os

from .personality_test import PersonalityTestEngine

# ──────────────────────────────────────────
# 推荐专业名 → 数据库专业名/大类 映射表
# 用于模糊匹配评估命中率
# ──────────────────────────────────────────
MAJOR_ALIAS_MAP = {
    # 推荐专业名 → [数据库匹配关键词列表]
    '机械工程': ['机械工程', '机械'],
    '电气工程': ['电气工程', '电气'],
    '土木工程': ['土木工程', '土木'],
    '汽车工程': ['汽车工程', '汽车服务', '智能网联汽车'],
    '计算机科学': ['计算机科学', '计算机', '计算机科学与技术'],
    '物理学': ['物理学'],
    '数学': ['数学', '数学与应用数学', '数学类'],
    '化学': ['化学'],
    '艺术设计': ['艺术设计', '艺术设计类'],
    '音乐表演': ['音乐表演'],
    '影视制作': ['影视制作', '影视'],
    '建筑学': ['建筑学', '建筑'],
    '教育学': ['教育学', '教育'],
    '心理学': ['心理学'],
    '医学': ['临床医学', '口腔医学', '医学类'],
    '社会工作': ['社会工作'],
    '工商管理': ['工商管理'],
    '金融学': ['金融学'],
    '市场营销': ['市场营销'],
    '法学': ['法学'],
    '会计学': ['会计学', '会计'],
    '信息管理': ['信息管理', '信息管'],
    '行政管理': ['行政管理'],
    '统计学': ['统计学'],
    '中国语言文学': ['中国语言', '汉语言'],
    '新闻传播': ['新闻传播', '新闻'],
    '历史学': ['历史学'],
    '哲学': ['哲学'],
    '护理学': ['护理'],
    '数据科学': ['数据科学', '数据'],
    '旅游管理': ['旅游管理'],
    '人力资源管理': ['人力资源'],
    '广告学': ['广告'],
    '汉语言文学': ['汉语言', '汉语言文学'],
    '外语类': ['外语', '英语', '翻译'],
    '国际关系': ['国际关系', '国际政治'],
    '国际贸易': ['国际贸易'],
    '政治学': ['政治学', '政治'],
}


def find_major_in_db(major_name: str, db_majors: set) -> bool:
    """检查推荐专业名是否匹配数据库中任意专业"""
    # 精确匹配
    if major_name in db_majors:
        return True
    # 通过别名映射模糊匹配
    if major_name in MAJOR_ALIAS_MAP:
        keywords = MAJOR_ALIAS_MAP[major_name]
        for db_major in db_majors:
            for kw in keywords:
                if kw in db_major or db_major in kw:
                    return True
    return False


def get_major_class_for_major(major_name: str, major_class_map: Dict) -> str:
    """获取专业对应的大类"""
    if major_name in major_class_map:
        return major_class_map[major_name]
    return ''


def generate_mock_personality_answers(
    score: int, major_class: str
) -> Tuple[Dict, Dict, Dict, Dict]:
    """
    根据录取记录生成模拟性格测试答案

    基于教育研究假设：
    - 高分考生更可能选择匹配其学科优势的专业
    - 不同大类对应不同的霍兰德代码倾向
    """
    random.seed(hash(major_class) % 10000)

    if score is None:
        score = 500  # 默认中分段

    # 霍兰德倾向映射（基于major_class）
    holland_tendency = {
        '计算机类': 'IR', '电子信息类': 'IR', '数学类': 'IR',
        '机械类': 'RI', '土木类': 'RI', '电气类': 'RI',
        '金融学类': 'EC', '经济学类': 'EC', '工商管理类': 'EC',
        '中国语言文学类': 'SA', '新闻传播学类': 'SA',
        '法学类': 'ES', '教育类': 'SA', '心理学类': 'SI',
        '临床医学类': 'SI', '药学类': 'SI',
        '艺术设计类': 'AR', '外语类': 'SA',
    }

    primary_dim = holland_tendency.get(major_class, 'RI')

    # 霍兰德答案：偏向primary_dim
    holland_answers = {}
    from .personality_test import RIASEC_PAIRS
    for q_num, (dim_a, dim_b) in RIASEC_PAIRS.items():
        if dim_a in primary_dim and dim_b not in primary_dim:
            holland_answers[q_num] = 'A'
        elif dim_b in primary_dim and dim_a not in primary_dim:
            holland_answers[q_num] = 'B'
        elif dim_a in primary_dim and dim_b in primary_dim:
            holland_answers[q_num] = 'A'
        elif dim_a == dim_b:
            holland_answers[q_num] = 'A'
        else:
            holland_answers[q_num] = random.choice(['A', 'B'])

    # 大五答案：高分→高O低N，低分→不同模式
    if score >= 560:
        big_five_answers = {i: random.choice([4, 5]) if i % 3 != 0 else random.choice([3, 4]) for i in range(1, 51)}
        # 低神经质
        for i in range(41, 51):
            big_five_answers[i] = random.choice([1, 2, 3])
    else:
        big_five_answers = {i: random.choice([3, 4]) if i % 2 == 0 else random.choice([2, 3]) for i in range(1, 51)}

    # 自我效能感：高分→高效能
    if score >= 560:
        efficacy_answers = {i: random.choice([4, 5]) for i in range(76, 91)}
    else:
        efficacy_answers = {i: random.choice([3, 4]) for i in range(76, 91)}

    # 职业价值观
    career_values_answers = {i: random.choice([3, 4, 5]) for i in range(91, 111)}

    return big_five_answers, holland_answers, efficacy_answers, career_values_answers


def test_weight_combination(
    engine: PersonalityTestEngine,
    calibration_set: List[Dict],
    holland_weights: Tuple[float, float, float],
    boost_weight: float,
    values_weight: float,
    db_majors: set,
) -> Dict:
    """
    测试一组权重在全部校准集上的表现

    返回:
    {
        'hit_rate': float,      # 命中率：推荐专业命中数据库专业的比例
        'avg_rank': float,       # 平均排名
        'diversity': float,      # 推荐专业多样性
        'total': int,
    }
    """
    hits = 0
    total = 0
    ranks = []
    all_recommended_majors = set()

    for record in calibration_set:
        major_class = record['major_class']
        major_name = record['major_name']
        score = record['min_score']

        big_five, holland, efficacy, cv = generate_mock_personality_answers(
            score, major_class
        )

        # 手动计算推荐（不依赖generate_recommendations内部权重）
        recommended = _generate_with_weights(
            engine, big_five, holland, efficacy, cv,
            holland_weights, boost_weight, values_weight,
        )

        all_recommended_majors.update(recommended)

        # 检查是否命中数据库
        hit = False
        for i, rec_major in enumerate(recommended):
            if find_major_in_db(rec_major, db_majors):
                hit = True
                ranks.append(i + 1)
                break

        if hit:
            hits += 1
        total += 1

    return {
        'hit_rate': hits / total if total > 0 else 0,
        'avg_rank': sum(ranks) / len(ranks) if ranks else 999,
        'diversity': len(all_recommended_majors) / max(len(calibration_set), 1),
        'total': total,
    }


def _generate_with_weights(
    engine: PersonalityTestEngine,
    big_five: Dict,
    holland_answers: Dict,
    efficacy: Dict,
    cv: Dict,
    holland_weights: Tuple[float, float, float],
    boost_weight: float,
    values_weight: float,
) -> List[str]:
    """用指定权重生成推荐（替代generate_recommendations）"""
    # 先计算霍兰德代码
    holland_code, holland_scores = engine.calculate_holland(holland_answers)
    bf = engine.calculate_big_five(big_five)
    se = engine.calculate_self_efficacy(efficacy)
    cv_scores = engine.calculate_career_values(cv)

    candidate_scores: Dict[str, float] = {}

    # 步骤1: 霍兰德基础推荐（使用自定义权重）
    for i, code in enumerate(holland_code):
        weight = holland_weights[i] if i < 3 else 0.5
        if code in engine.HOLLAND_MAJOR_MAP:
            for major in engine.HOLLAND_MAJOR_MAP[code]:
                candidate_scores[major] = candidate_scores.get(major, 0) + weight

    # 步骤2: Big Five修正
    if bf.get('O', 0) >= 4.0:
        engine._boost_candidates(candidate_scores, engine.BIG_FIVE_MAJOR_BOOST['O_high'], boost_weight)
    if bf.get('C', 0) >= 4.0:
        engine._boost_candidates(candidate_scores, engine.BIG_FIVE_MAJOR_BOOST['C_high'], boost_weight)
    if bf.get('E', 0) >= 4.0:
        engine._boost_candidates(candidate_scores, engine.BIG_FIVE_MAJOR_BOOST['E_high'], boost_weight)
    if bf.get('A', 0) >= 4.0:
        engine._boost_candidates(candidate_scores, engine.BIG_FIVE_MAJOR_BOOST['A_high'], boost_weight)
    if bf.get('N', 99) < 3.0:
        engine._boost_candidates(candidate_scores, engine.BIG_FIVE_MAJOR_BOOST['N_low'], boost_weight)

    # 步骤3: 自我效能感修正
    if se.get('chinese', 0) >= 4.0:
        engine._boost_candidates(candidate_scores, engine.EFFICACY_MAJOR_BOOST['chinese_high'], boost_weight)
    if se.get('math', 0) >= 4.0:
        engine._boost_candidates(candidate_scores, engine.EFFICACY_MAJOR_BOOST['math_high'], boost_weight)
    if se.get('english', 0) >= 4.0:
        engine._boost_candidates(candidate_scores, engine.EFFICACY_MAJOR_BOOST['english_high'], boost_weight)

    # 步骤4: 职业价值观修正
    sorted_values = sorted(cv_scores.items(), key=lambda x: x[1], reverse=True)
    for val_name, val_score in sorted_values[:2]:
        if val_score >= 4.0 and val_name in engine.VALUES_MAJOR_BOOST:
            engine._boost_candidates(candidate_scores, engine.VALUES_MAJOR_BOOST[val_name], values_weight)

    # 排序输出TOP10
    sorted_majors = sorted(candidate_scores.items(), key=lambda x: x[1], reverse=True)
    return [m[0] for m in sorted_majors[:10]]


def main():
    print('=' * 70)
    print('推荐权重校准脚本 V3.0')
    print('=' * 70)

    conn = sqlite3.connect(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'yunnan_gaokao.db'))
    c = conn.cursor()

    # ── 步骤1: 构建校准集 ──
    print('\n[1/5] 构建校准集...')

    # 获取所有唯一major_class
    c.execute('''
        SELECT DISTINCT major_class FROM enroll_detail
        WHERE major_class IS NOT NULL AND major_class != ''
    ''')
    major_classes = [row[0] for row in c.fetchall()]
    print(f'  共{len(major_classes)}个专业大类')

    # 每个大类采样3条（共约600条），取最新年份(2025)
    calibration_records = []
    for mc in major_classes:
        c.execute('''
            SELECT school_name, major_name, major_class, min_score, min_rank, category, year
            FROM enroll_detail
            WHERE major_class = ? AND year = 2025 AND min_score IS NOT NULL AND min_rank IS NOT NULL
            ORDER BY RANDOM()
            LIMIT 3
        ''', (mc,))
        for row in c.fetchall():
            calibration_records.append({
                'school_name': row[0],
                'major_name': row[1],
                'major_class': row[2],
                'min_score': row[3],
                'min_rank': row[4],
                'category': row[5],
                'year': row[6],
            })

    # 如果2025数据不足，补充2024年
    if len(calibration_records) < 200:
        for mc in major_classes:
            c.execute('''
                SELECT school_name, major_name, major_class, min_score, min_rank, category, year
                FROM enroll_detail
                WHERE major_class = ? AND year = 2024 AND min_score IS NOT NULL AND min_rank IS NOT NULL
                ORDER BY RANDOM()
                LIMIT 2
            ''', (mc,))
            for row in c.fetchall():
                calibration_records.append({
                    'school_name': row[0],
                    'major_name': row[1],
                    'major_class': row[2],
                    'min_score': row[3],
                    'min_rank': row[4],
                    'category': row[5],
                    'year': row[6],
                })
                if len(calibration_records) >= 400:
                    break
        print(f'  2025年数据不足，补充2024年数据')

    random.shuffle(calibration_records)
    print(f'  校准集大小: {len(calibration_records)}条')

    # P2-fix: 空校准集无法进行有意义的权重校准，应尽早报错
    if not calibration_records:
        raise ValueError(
            '校准集为空。请确保 enroll_detail 表中有 2024-2025 年的录取数据。'
        )

    # 获取数据库专业集合（用于匹配）
    c.execute('SELECT DISTINCT major_name FROM enroll_detail WHERE major_name IS NOT NULL AND major_name != ""')
    db_majors = set(row[0] for row in c.fetchall())

    # 也加入major_class作为匹配目标
    c.execute('SELECT DISTINCT major_class FROM enroll_detail WHERE major_class IS NOT NULL AND major_class != ""')
    db_major_classes = set(row[0] for row in c.fetchall())

    all_db_targets = db_majors | db_major_classes

    conn.close()

    # ── 步骤2: 定义权重搜索空间 ──
    print('\n[2/5] 定义权重搜索空间...')

    # 霍兰德三位码权重：第一位必须 > 第二位 > 第三位
    holland_weight_options = [
        (3.0, 2.0, 1.0),   # 当前值
        (3.5, 2.0, 1.0),
        (4.0, 2.5, 1.0),
        (3.0, 2.5, 1.5),
        (3.0, 1.5, 0.5),   # 递减更快
        (4.0, 2.0, 1.0),
        (5.0, 3.0, 1.0),   # 更激进
        (2.0, 1.5, 1.0),   # 递减更平缓
        (3.0, 2.0, 1.5),   # 第三位权重提高
    ]

    # BOOST权重选项
    boost_options = [0.5, 1.0, 1.5, 2.0]

    # 价值观权重选项
    values_options = [0.3, 0.5, 0.8, 1.0]

    total_combinations = len(holland_weight_options) * len(boost_options) * len(values_options)
    print(f'  权重组合数: {total_combinations}')
    print(f'  预估计算量: {total_combinations * len(calibration_records)}次推荐生成')

    # ── 步骤3: 网格搜索 ──
    print('\n[3/5] 开始网格搜索...')

    engine = PersonalityTestEngine()
    results = []
    count = 0

    for hw in holland_weight_options:
        for bw in boost_options:
            for vw in values_options:
                result = test_weight_combination(
                    engine, calibration_records,
                    hw, bw, vw, all_db_targets,
                )

                results.append({
                    'holland_weights': hw,
                    'boost_weight': bw,
                    'values_weight': vw,
                    **result,
                })

                count += 1
                if count % 20 == 0:
                    print(f'  进度: {count}/{total_combinations} ({count*100//total_combinations}%)')

    print(f'  完成！共评估{count}组权重')

    # ── 步骤4: 排序输出 ──
    print('\n[4/5] 评估结果排序...')

    # 综合评分 = hit_rate * 0.5 + (1 / (1 + avg_rank)) * 0.3 + diversity * 0.2
    for r in results:
        r['composite_score'] = (
            r['hit_rate'] * 0.5 +
            (1.0 / (1.0 + r['avg_rank'])) * 0.3 +
            min(r['diversity'], 1.0) * 0.2
        )

    results.sort(key=lambda x: x['composite_score'], reverse=True)

    print(f'\n{"排名":>4s} {"霍兰德权重":>20s} {"BOOST":>6s} {"价值观":>6s} '
          f'{"命中率":>8s} {"平均排名":>8s} {"多样性":>8s} {"综合":>8s}')
    print('-' * 85)

    for i, r in enumerate(results[:20], 1):
        hw_str = f"({r['holland_weights'][0]}, {r['holland_weights'][1]}, {r['holland_weights'][2]})"
        print(f"{i:>4d} {hw_str:>20s} {r['boost_weight']:>6.1f} {r['values_weight']:>6.1f} "
              f"{r['hit_rate']:>7.1%} {r['avg_rank']:>8.1f} {r['diversity']:>8.2f} "
              f"{r['composite_score']:>7.3f}")

    # ── 步骤5: 输出建议 ──
    print('\n[5/5] 最优权重推荐...')

    best = results[0]
    current = next((r for r in results
                   if r['holland_weights'] == (3.0, 2.0, 1.0)
                   and r['boost_weight'] == 1.0
                   and r['values_weight'] == 0.8), None)

    print(f'\n当前权重配置:')
    print(f'  霍兰德权重: ({current["holland_weights"][0]}, {current["holland_weights"][1]}, {current["holland_weights"][2]})')
    print(f'  BOOST权重: {current["boost_weight"]}')
    print(f'  价值观权重: {current["values_weight"]}')
    print(f'  综合评分: {current["composite_score"]:.3f}')
    print(f'  命中率: {current["hit_rate"]:.1%}')
    print(f'  平均排名: {current["avg_rank"]:.1f}')

    print(f'\n推荐权重配置:')
    print(f'  霍兰德权重: ({best["holland_weights"][0]}, {best["holland_weights"][1]}, {best["holland_weights"][2]})')
    print(f'  BOOST权重: {best["boost_weight"]}')
    print(f'  价值观权重: {best["values_weight"]}')
    print(f'  综合评分: {best["composite_score"]:.3f}')
    print(f'  命中率: {best["hit_rate"]:.1%}')
    print(f'  平均排名: {best["avg_rank"]:.1f}')

    improvement = (best['composite_score'] - current['composite_score']) / current['composite_score'] * 100
    print(f'\n改善幅度: {improvement:+.1f}%')

    # 保存结果
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'output')
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, 'weight_calibration_results.json')

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results[:50], f, ensure_ascii=False, indent=2)

    print(f'\n完整结果已保存至: {output_path}')
    print('=' * 70)


if __name__ == '__main__':
    main()
