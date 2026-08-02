# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""
科类标签归一化 (Subject Type Normalization)

统一处理"物理类/物理/理科"、"历史类/历史/文科"等同义标签的转换。
所有需要按科类过滤数据库的地方都应调用本模块，禁止重复维护映射表。

设计原则：
- 输入归一化：把用户/数据库标签都映射到规范键（物理 / 历史）
- 别名展开：在 SQL IN 子句中覆盖所有数据源标签变体（旧高考文/理 + 新高考物理类/历史类）
- 两种用法：
    aliases_for_sql_param() → 返回 tuple[str]，用于参数化 SQL（推荐）
    aliases_for_sql_literal() → 返回 tuple[str]，含引号，用于字面量拼接（已存在的旧代码）

云南数据语境：
- 旧高考(2020-2024): 文科 / 理科
- 新高考(2025+): 历史类 / 物理类
- score_line_2025 表中可能同时混存"物理"和"物理类"两种写法
"""
from typing import Optional, Tuple


# 规范键 → 数据库可能出现的所有等价标签
_ALIAS_MAP = {
    '物理': ('物理', '物理类', '理科'),
    '历史': ('历史', '历史类', '文科'),
    '理科': ('物理', '物理类', '理科'),
    '文科': ('历史', '历史类', '文科'),
    '物理类': ('物理', '物理类', '理科'),
    '历史类': ('历史', '历史类', '文科'),
}


def normalize_subject_type(subject_type: Optional[str]) -> Optional[str]:
    """
    将任意科类标签归一化为规范键 '物理' / '历史'。
    None / 未识别 → 原样返回（允许后续按"无过滤"处理）。

    P2-fix: 增加空白修剪，防止 '物理 ' 等输入匹配失败
    """
    if not subject_type:
        return subject_type
    subject_type = subject_type.strip()
    if subject_type in ('物理类', '物理', '理科'):
        return '物理'
    if subject_type in ('历史类', '历史', '文科'):
        return '历史'
    return subject_type


def aliases_for_sql_param(subject_type: Optional[str]) -> Tuple[str, ...]:
    """
    返回用于参数化 SQL（IN ? ?）的别名元组（不含引号）。
    用法：
        aliases = aliases_for_sql_param(subject_type)
        sql += f" AND subject_type IN ({', '.join('?' for _ in aliases)})"
        params.extend(aliases)
    """
    if not subject_type:
        return ()
    aliases = _ALIAS_MAP.get(subject_type)
    if aliases:
        return aliases
    return (subject_type,)


def aliases_for_sql_literal(subject_type: Optional[str]) -> Tuple[str, ...]:
    """
    返回用于字面量拼接 SQL（IN ('物理', '物理类')）的别名元组（含单引号）。
    仅供存量代码兼容；新代码请用 aliases_for_sql_param()。

    P2-fix: 转义单引号，防止 SQL 注入
    """
    if not subject_type:
        return ()
    _esc = lambda s: s.replace("'", "''")
    aliases = _ALIAS_MAP.get(subject_type)
    if aliases:
        return tuple(f"'{_esc(a)}'" for a in aliases)
    # 不可识别输入：转义单引号后返回
    escaped = _esc(subject_type)
    return (f"'{escaped}'",)


if __name__ == '__main__':
    # 自检
    assert normalize_subject_type('物理类') == '物理'
    assert normalize_subject_type('理科') == '物理'
    assert normalize_subject_type('文科') == '历史'
    assert normalize_subject_type(None) is None
    assert normalize_subject_type('未知') == '未知'

    assert aliases_for_sql_param('物理') == ('物理', '物理类', '理科')
    assert aliases_for_sql_param('历史类') == ('历史', '历史类', '文科')
    assert aliases_for_sql_param(None) == ()

    assert aliases_for_sql_literal('未知') == ("'未知'",)

    assert aliases_for_sql_literal('物理') == ("'物理'", "'物理类'", "'理科'")
    # C-25: 不可识别输入应返回带引号的字面量
    assert aliases_for_sql_literal('未知') == ("'未知'",)
    assert aliases_for_sql_literal("") == ()

    print('subject_normalize 自检通过')
