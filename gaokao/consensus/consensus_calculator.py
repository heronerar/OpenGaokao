# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""
家庭共识引擎 — 帮家长和考生找到共识区域

背景: 83.4%的家庭在志愿填报时有分歧(中国青年报2022)。
共识引擎通过分离作答+算法比对，标注共识/分歧区域并推荐折中方案。

流程:
    家长15题偏好问卷 → 偏好向量
    考生248题测评   → 霍兰德代码+兴趣向量
           ↓
    共识度计算 → 共识区域(✅) / 分歧区域(⚠️) / 禁止区域(❌)
           ↓
    折中方案查找 → 推荐双方都能接受的专业方向
"""
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Tuple


@dataclass
class ParentPreference:
    """家长偏好画像"""
    stability_priority: float = 3.0   # 稳定性优先度 1-5
    income_priority: float = 3.0      # 收入优先度
    location_preference: str = ''     # 地域偏好
    industry_preference: str = ''     # 行业偏好
    forbidden_majors: List[str] = field(default_factory=list)  # 绝对不能选的专业
    preferred_majors: List[str] = field(default_factory=list)  # 家长倾向的专业
    risk_tolerance: str = 'balanced'  # aggressive/balanced/conservative


@dataclass
class ConsensusReport:
    """共识报告"""
    consensus_rate: float = 0.0       # 共识度 0-100%
    consensus_areas: List[str] = field(default_factory=list)     # ✅ 共识区域(直接推荐)
    divergent_areas: List[str] = field(default_factory=list)     # ⚠️ 分歧区域(需要讨论)
    forbidden_areas: List[str] = field(default_factory=list)     # ❌ 双方都否定(自动排除)
    compromise_suggestions: List[str] = field(default_factory=list)  # 折中方案

    def is_high_consensus(self) -> bool:
        return self.consensus_rate >= 70.0

    def to_display_text(self) -> str:
        lines = [f'家庭共识度：{self.consensus_rate:.0f}%']
        if self.consensus_areas:
            lines.append(f'\n✅ 共识区域（{len(self.consensus_areas)}个）：{", ".join(self.consensus_areas[:5])}')
        if self.divergent_areas:
            lines.append(f'\n⚠️ 分歧区域（{len(self.divergent_areas)}个）：{", ".join(self.divergent_areas[:5])}')
        if self.forbidden_areas:
            lines.append(f'\n❌ 双方否定（{len(self.forbidden_areas)}个）：{", ".join(self.forbidden_areas[:5])}')
        if self.compromise_suggestions:
            lines.append(f'\n💡 折中建议：{", ".join(self.compromise_suggestions[:5])}')
        return '\n'.join(lines)


# ── 专业 → 属性映射（用于跨维度共识计算）──
MAJOR_ATTRIBUTES = {
    '计算机科学与技术': {'stability': 3, 'income': 5, 'creative': 3, 'help': 1},
    '软件工程': {'stability': 3, 'income': 5, 'creative': 3, 'help': 1},
    '人工智能': {'stability': 4, 'income': 5, 'creative': 4, 'help': 1},
    '电气工程及其自动化': {'stability': 4, 'income': 4, 'creative': 2, 'help': 1},
    '自动化': {'stability': 4, 'income': 4, 'creative': 3, 'help': 1},
    '临床医学': {'stability': 5, 'income': 4, 'creative': 1, 'help': 5},
    '口腔医学': {'stability': 5, 'income': 5, 'creative': 2, 'help': 4},
    '汉语言文学': {'stability': 3, 'income': 2, 'creative': 4, 'help': 3},
    '法学': {'stability': 3, 'income': 3, 'creative': 2, 'help': 3},
    '会计学': {'stability': 4, 'income': 3, 'creative': 1, 'help': 1},
    '数学与应用数学': {'stability': 3, 'income': 3, 'creative': 4, 'help': 1},
    '土木工程': {'stability': 2, 'income': 3, 'creative': 2, 'help': 1},
    '数字媒体技术': {'stability': 3, 'income': 3, 'creative': 5, 'help': 1},
    '建筑学': {'stability': 3, 'income': 3, 'creative': 5, 'help': 1},
    '教育学': {'stability': 4, 'income': 2, 'creative': 3, 'help': 4},
    '心理学': {'stability': 3, 'income': 2, 'creative': 3, 'help': 5},
    '护理学': {'stability': 5, 'income': 2, 'creative': 1, 'help': 5},
    '新闻传播学': {'stability': 2, 'income': 2, 'creative': 4, 'help': 2},
    '生物医学工程': {'stability': 3, 'income': 4, 'creative': 4, 'help': 3},
}


def calculate_consensus(
    parent: ParentPreference,
    student_holland_code: str,
    student_major_interests: List[str],
    student_excluded_majors: Set[str],
    holland_major_map: Optional[Dict[str, List[str]]] = None,
) -> ConsensusReport:
    """
    计算家长-考生共识度

    Args:
        parent: 家长偏好画像
        student_holland_code: 考生霍兰德代码(如"RIA")
        student_major_interests: 考生感兴趣的专业列表
        student_excluded_majors: 考生排除的专业集合
        holland_major_map: 霍兰德→专业类映射表(可选)

    Returns:
        ConsensusReport 对象
    """
    if holland_major_map is None:
        holland_major_map = {
            'R': ['机械类', '电气类', '土木类', '航空航天类', '材料类'],
            'I': ['数学类', '计算机类', '电子信息类', '物理学类', '生物科学类'],
            'A': ['设计学类', '建筑类', '中国语言文学类', '新闻传播学类', '美术学类'],
            'S': ['教育学类', '心理学类', '护理学类', '社会学类', '公共管理类'],
            'E': ['工商管理类', '金融学类', '法学类', '经济学类', '管理科学类'],
            'C': ['会计类', '统计学类', '财政学类', '图书情报类'],
        }

    parent_forbidden = set(parent.forbidden_majors or [])
    student_forbidden = set(student_excluded_majors or [])

    # 双方都排除的 = 自动禁止区域
    forbidden_areas = list(parent_forbidden & student_forbidden)

    # 考生霍兰德高分维度对应的专业类
    holland_high_dims = set(student_holland_code[:2])  # 取前2个字母
    student_preferred_classes = set()
    for dim in holland_high_dims:
        student_preferred_classes.update(holland_major_map.get(dim, []))

    # 家长倾向的专业方向
    parent_preferred_set = set(parent.preferred_majors or [])

    # 共识区域：考生兴趣 ∩ 家长不反对
    consensus = set()
    for major in student_major_interests:
        if major in parent_forbidden:
            continue  # 家长反对 → 分歧
        attrs = MAJOR_ATTRIBUTES.get(major, {})
        # 家长偏好高分属性匹配（稳定性/收入）
        if parent.stability_priority >= 4 and attrs.get('stability', 3) >= 4:
            consensus.add(major)  # 家长要稳定性 + 该专业稳定 → 共识
        elif parent.income_priority >= 4 and attrs.get('income', 3) >= 4:
            consensus.add(major)  # 家长要收入 + 该专业高薪 → 共识
        elif parent.risk_tolerance != 'conservative':
            consensus.add(major)  # 家长不保守 → 接受
        # 家长保守但专业属于稳定型也是共识
        elif attrs.get('stability', 3) >= 4:
            consensus.add(major)

    # 家长倾向但考生不感兴趣 → 分歧
    parent_only = parent_preferred_set - set(student_major_interests) - parent_forbidden
    divergent = parent_only | (set(student_major_interests) - consensus)

    # 计算共识率
    total_items = len(consensus) + len(divergent) + len(forbidden_areas)
    if total_items == 0:
        consensus_rate = 0.0
    else:
        consensus_rate = round(len(consensus) / total_items * 100, 1)

    # 折中方案：找属性匹配的专业
    compromises = _find_compromises(parent, student_holland_code, holland_major_map)

    return ConsensusReport(
        consensus_rate=consensus_rate,
        consensus_areas=sorted(consensus),
        divergent_areas=sorted(divergent),
        forbidden_areas=sorted(forbidden_areas),
        compromise_suggestions=compromises,
    )


def _find_compromises(
    parent: ParentPreference,
    student_holland: str,
    holland_major_map: Dict[str, List[str]],
    max_suggestions: int = 5,
) -> List[str]:
    """查找折中方案：家长偏好属性和考生兴趣维度的交叉专业"""
    # 评分：每个专业对 parent 偏好 + student 兴趣的综合分
    scores = {}
    student_dims = set(student_holland[:3])

    for major, attrs in MAJOR_ATTRIBUTES.items():
        # 跳过禁止的
        if major in (parent.forbidden_majors or []):
            continue

        # 家长分：稳定性+收入匹配
        parent_score = 0
        if parent.stability_priority >= 4:
            parent_score += attrs.get('stability', 3)
        if parent.income_priority >= 4:
            parent_score += attrs.get('income', 3)

        # 考生分：霍兰德匹配（RIA创意分高=A高分好）
        student_score = 0
        if 'A' in student_dims:
            student_score += attrs.get('creative', 3)
        if 'S' in student_dims:
            student_score += attrs.get('help', 3)
        if 'I' in student_dims or 'R' in student_dims:
            student_score += max(attrs.get('income', 3), attrs.get('stability', 3))

        scores[major] = (parent_score + student_score) / 2

    # 返回 top N
    sorted_majors = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [m for m, s in sorted_majors[:max_suggestions]]
