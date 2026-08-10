# SPDX-License-Identifier: LicenseRef-OpenGaokao-SAL-1.0
# Copyright (C) 2026 OpenGaokao Contributors
"""
撤销风险信号模块

基于教育部5年撤销数据（2020-2024），提供"学校-专业"组合级风险评估。

核心原则：
1. 撤销 ≠ 专业不行，而是特定学校办不好该专业
2. 数据应用于"学校-专业"组合级，不是"专业类"级
3. 区分撤销原因：985战略调整 vs 普通院校质量淘汰
4. 逐年趋势 > 累计总量：撤销加速才是预警信号

数据来源：
- 2020: Excel (教高函〔2021〕1号) 518条
- 2021: PDF  (教高函〔2021〕14号) 798条
- 2022: PDF  (教高函〔2023〕3号) 906条
- 2023: PDF  (教高函〔2024〕7号) 1588条
- 2024: PDF  (教高函〔2025〕5号) 1387条
"""
import sqlite3
import os
from typing import Optional
from functools import lru_cache

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'yunnan_gaokao.db')
_OVERRIDE_DB_PATH = None

def set_db_path(path: str):
    """Override the default database path (used by CLI/server)."""
    global _OVERRIDE_DB_PATH
    _OVERRIDE_DB_PATH = path
    # Clear all caches since they're bound to the old DB
    get_school_tier.cache_clear()
    _get_revocation_by_school_major.cache_clear()
    _get_revocation_by_major_tier.cache_clear()
    _get_school_count.cache_clear()


def _get_conn(db_path: str = None) -> sqlite3.Connection:
    return sqlite3.connect(db_path or _OVERRIDE_DB_PATH or DB_PATH)


@lru_cache(maxsize=1)
def _get_school_count(major_class: str = None):
    """获取各专业类在major_catalog中的总学校数（用于计算撤销率）"""
    conn = _get_conn()
    try:
        c = conn.cursor()
        if major_class:
            c.execute('''SELECT major_class, COUNT(DISTINCT schools) as total
                         FROM major_catalog WHERE major_class = ? AND schools IS NOT NULL AND schools != ''
                         GROUP BY major_class''', (major_class,))
        else:
            c.execute('''SELECT major_class, COUNT(DISTINCT schools) as total
                         FROM major_catalog WHERE schools IS NOT NULL AND schools != ''
                         GROUP BY major_class''')
        result = dict(c.fetchall())
        return result
    finally:
        conn.close()


@lru_cache(maxsize=256)
def get_school_tier(school_name: str) -> str:
    """获取学校层次: '985' / '211' / '普通' / '未知'"""
    if not school_name:
        return '未知'
    conn = _get_conn()
    try:
        c = conn.cursor()
        c.execute('''SELECT is_985, is_211 FROM school_info WHERE school_name = ?''', (school_name,))
        row = c.fetchone()
        if not row:
            return '未知'
        if row[0] == 1:
            return '985'
        if row[1] == 1:
            return '211'
        return '普通'
    finally:
        conn.close()


@lru_cache(maxsize=256)
def _get_revocation_by_school_major(school_name: str, major_name: str) -> dict:
    """查询该"学校-专业"组合5年内的撤销记录"""
    conn = _get_conn()
    try:
        c = conn.cursor()
        c.execute('''SELECT year, COUNT(*) FROM major_revocation_stats
                     WHERE note = ? AND major_name = ? AND major_name NOT IN ('全国合计', '(未知)')
                     GROUP BY year ORDER BY year''', (school_name, major_name))
        rows = c.fetchall()
        if rows:
            return {year: count for year, count in rows}
        return {}
    finally:
        conn.close()


@lru_cache(maxsize=256)
def _get_revocation_by_major_tier(major_name: str, tier: str) -> dict:
    """查询该专业在指定学校层次5年内的撤销数量"""
    conn = _get_conn()
    c = conn.cursor()

    _TIER_CONDITIONS = {
        '985': 's.is_985 = 1',
        '211': 's.is_211 = 1 AND s.is_985 = 0',
        '普通': '(s.is_211 = 0 OR s.is_211 IS NULL) AND (s.is_985 = 0 OR s.is_985 IS NULL)',
    }
    cond = _TIER_CONDITIONS.get(tier)
    if cond is None:
        conn.close()
        return {}

    # P1-fix: 使用 INNER JOIN 防止未匹配学校被错误归入'普通'类；
    # 使用 COUNT(DISTINCT r.note) 去重学校数而非撤销记录条数
    c.execute(f'''SELECT r.year, COUNT(DISTINCT r.note)
                  FROM major_revocation_stats r
                  INNER JOIN school_info s ON r.note = s.school_name
                  WHERE r.major_name = ? AND r.major_name NOT IN ('全国合计', '(未知)')
                    AND {cond}
                  GROUP BY r.year ORDER BY r.year''', (major_name,))
    rows = c.fetchall()
    conn.close()
    if rows:
        return {year: count for year, count in rows}
    return {}


def get_revocation_trend(major_name: str) -> dict:
    """
    获取某专业的5年撤销趋势

    返回: {
        'yearly': {2020: x, 2021: x, ...},
        'total': int,
        'direction': 'rising' | 'stable' | 'declining',
        'tier_breakdown': {'985': x, '211': x, '普通': x},
        'interpretation': str,
    }
    """
    conn = _get_conn()
    c = conn.cursor()

    # 年度总计
    c.execute('''SELECT year, COUNT(*) FROM major_revocation_stats
                 WHERE major_name = ? AND major_name NOT IN ('全国合计', '(未知)')
                 GROUP BY year ORDER BY year''', (major_name,))
    yearly = dict(c.fetchall())

    # 按层次分解
    tier_breakdown = {'985': 0, '211': 0, '普通': 0}
    c.execute('''SELECT
                 COUNT(DISTINCT CASE WHEN s.is_985 = 1 THEN r.note END) as c985,
                 COUNT(DISTINCT CASE WHEN s.is_211 = 1 AND s.is_985 = 0 THEN r.note END) as c211,
                 COUNT(DISTINCT CASE WHEN s.is_211 = 0 AND s.is_985 = 0 THEN r.note END) as cother
                 FROM major_revocation_stats r
                 INNER JOIN school_info s ON r.note = s.school_name
                 WHERE r.major_name = ? AND r.major_name NOT IN ('全国合计', '(未知)')''', (major_name,))
    row = c.fetchone()
    if row:
        tier_breakdown = {'985': row[0] or 0, '211': row[1] or 0, '普通': row[2] or 0}

    conn.close()

    total = sum(yearly.values())

    # 判断趋势方向（近3年）
    # P2-fix: 零值年份可能是数据缺失而非真实趋势，需过滤后判断
    years = sorted(yearly.keys())
    direction = 'stable'
    if len(years) >= 3:
        recent = [yearly.get(y, 0) for y in years[-3:]]
        # 过滤零值：至少2个非零年份才判断趋势
        nonzero = [v for v in recent if v > 0]
        if len(nonzero) >= 2:
            if all(nonzero[i+1] > nonzero[i] * 1.2 for i in range(len(nonzero)-1)):
                direction = 'rising'
            elif all(nonzero[i+1] < nonzero[i] * 0.8 for i in range(len(nonzero)-1)):
                direction = 'declining'

    # 生成解读
    if total == 0:
        interpretation = f'{major_name}近5年无撤销记录'
    elif tier_breakdown['985'] + tier_breakdown['211'] > total * 0.5:
        interpretation = f'{major_name}在985/211院校中撤销较多({tier_breakdown["985"]+tier_breakdown["211"]}/{total}所)，属战略调整'
    elif tier_breakdown['普通'] > total * 0.7:
        interpretation = f'{major_name}撤销主要集中在普通院校({tier_breakdown["普通"]}/{total}所)，反映低水平重复办学被淘汰'
    else:
        interpretation = f'{major_name}各层次院校均有撤销，建议关注具体学校的办学实力'

    if direction == 'rising':
        interpretation += '，且撤销数量逐年上升'
    elif direction == 'declining':
        interpretation += '，但撤销数量逐年下降，风险在收敛'

    return {
        'yearly': yearly,
        'total': total,
        'direction': direction,
        'tier_breakdown': tier_breakdown,
        'interpretation': interpretation,
    }


def get_revocation_risk(major_name: str, school_name: str) -> dict:
    """
    获取具体"学校-专业"组合的撤销风险信号

    参数:
        major_name: 专业名称（如"信息管理与信息系统"）
        school_name: 学校名称（如"北京大学"）

    返回: {
        'level': 0|1|2|3,          # 无风险/轻微/中等/较高
        'label': str,               # 人类可读的风险标签
        'details': {
            'direct_hit': bool,     # 该学校该专业是否被撤销过
            'peer_rate': float,     # 同类学校该专业的撤销率
            'yearly_trend': dict,   # 该学校该专业的年度撤销记录
            'direction': str,       # rising/stable/declining (该专业全国趋势)
            'tier_breakdown': dict, # {985: x, 211: x, 普通: x}
        }
    }

    判断逻辑:
        1. 直接命中：该"学校-专业"5年内是否被撤销 → level=3
        2. 同层次撤销率：该专业在同类学校的撤销比例
           - 985/211撤销率 > 10% → level=2（连顶尖学校都在撤）
           - 普通院校撤销率 > 20% → level=1（低水平重复多）
           - 否则 → level=0
        3. 逐年趋势：追加标签
    """
    tier = get_school_tier(school_name)

    # P1-fix: 空 school_name 时委托给全国趋势评估
    if not school_name or school_name.strip() == '':
        trend = get_revocation_trend(major_name)
        level = 0
        if trend['total'] > 100:
            level = 2
        elif trend['total'] > 30:
            level = 1
        label = trend['interpretation'] if level > 0 else f'{major_name}近5年无显著撤销风险'
        return {
            'level': level,
            'label': label,
            'details': {
                'direct_hit': False,
                'peer_rate': 0,
                'yearly_trend': trend['yearly'],
                'direction': trend['direction'],
                'tier_breakdown': trend['tier_breakdown'],
                'school_tier': '全国',
            }
        }

    # Step 1: 直接命中检查
    school_major_history = _get_revocation_by_school_major(school_name, major_name)
    direct_hit = len(school_major_history) > 0

    if direct_hit:
        # 该校该专业已被撤销
        return {
            'level': 3,
            'label': f'该校已停招{major_name}',
            'details': {
                'direct_hit': True,
                'revocation_years': school_major_history,
                'school_tier': tier,
                'peer_rate': 0,
                'direction': 'N/A',
                'tier_breakdown': {},
            }
        }

    # P1-fix: tier_total 现在是去重后的学校数（_get_revocation_by_major_tier 已改用 COUNT DISTINCT）
    tier_revocation = _get_revocation_by_major_tier(major_name, tier)
    tier_total = sum(tier_revocation.values())

    # 估算该层次该专业的总点数（从major_catalog）
    school_count_map = _get_school_count()
    # 从major_class推导总学校数
    conn = _get_conn()
    c = conn.cursor()
    c.execute('SELECT major_class FROM major_catalog WHERE major_name = ?', (major_name,))
    row = c.fetchone()
    major_class = row[0] if row else ''
    conn.close()

    # 用专业类中的学校数作为分母估算
    total_schools = school_count_map.get(major_class, 100)
    # 同层次学校数估算（简化：按985=39, 211=73, 普通=total-112）
    if tier == '985':
        peer_total = 39
    elif tier == '211':
        peer_total = 73
    else:
        peer_total = max(total_schools - 112, 100)

    peer_rate = tier_total / peer_total if peer_total > 0 else 0

    # 判断风险等级
    level = 0
    if tier in ('985', '211') and peer_rate > 0.10:
        level = 2
    elif tier == '普通' and peer_rate > 0.20:
        level = 1
    elif peer_rate > 0.30:  # 任何层次撤销率极高
        level = 2

    # Step 3: 全国趋势
    trend = get_revocation_trend(major_name)
    direction = trend['direction']

    # 生成标签
    if level == 0:
        label = '无撤销风险'
    elif level == 1:
        label = f'普通院校撤销较多（{tier_total}所），该校仍在正常招生'
    elif level == 2:
        label = f'{tier}院校撤销率较高（{tier_total}所），建议关注该专业质量'
    else:
        label = f'该校已停招{major_name}'

    # 追加趋势标签
    if direction == 'rising' and level < 2:
        label += '，撤销加速'
    elif direction == 'declining' and level > 0:
        label += '，风险收敛'

    return {
        'level': level,
        'label': label,
        'details': {
            'direct_hit': False,
            'peer_rate': round(peer_rate, 3),
            'yearly_trend': tier_revocation,
            'direction': direction,
            'tier_breakdown': trend['tier_breakdown'],
            'school_tier': tier,
        }
    }
