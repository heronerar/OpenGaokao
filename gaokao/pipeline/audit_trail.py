# SPDX-License-Identifier: LicenseRef-OpenGaokao-SAL-1.0
# Copyright (C) 2026 OpenGaokao Contributors
"""
审计追踪数据模型 (Audit Trail)
决策管道的核心数据抽象。每个推荐步骤产生一个 AuditNode，
七个步骤拼接成完整的 AuditTrail。

设计原则:
- 每个数字都有来源 (data_sources)
- 每次排除都有原因 (excluded_items)
- 每个计算都有公式 (detail)
- 前端零逻辑——JSON 直接驱动 HTML 渲染
"""
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional
from datetime import datetime
import json


@dataclass
class ExcludedItem:
    """被排除的项目"""
    name: str                    # 项目名称（学校名/专业名）
    reason: str                  # 排除原因
    severity: str = 'info'       # info / warning / critical


@dataclass
class DataSource:
    """数据来源"""
    name: str                    # 人类可读的名称
    table: str = ''              # 数据库表名（如 score_line_2025）
    url: str = ''                # 公开链接（如 education.yn.gov.cn）
    year: str = ''               # 数据年份


@dataclass
class AuditNode:
    """管道中单个步骤的完整审计信息"""
    step_index: int              # 步骤序号 1-7
    step_name: str               # 步骤名称（中文）
    step_icon: str = ''          # emoji 图标 (🔢🔬📋🏥📊🧠🏆)

    # 摘要
    input_count: int = 0         # 输入数量
    output_count: int = 0        # 输出数量
    excluded_count: int = 0      # 本轮排除数量

    # 详情
    input_summary: str = ''      # 输入摘要（一行文字）
    output_summary: str = ''     # 输出摘要（一行文字）
    formula: str = ''            # 使用的公式（如有）
    formula_params: Dict[str, Any] = field(default_factory=dict)  # 公式参数
    detail_items: List[Dict[str, Any]] = field(default_factory=list)  # 详细数据行
    excluded_items: List[Dict[str, str]] = field(default_factory=list)  # 排除项
    data_sources: List[Dict[str, str]] = field(default_factory=list)    # 数据来源
    notes: List[str] = field(default_factory=list)  # 备注/风险提示


@dataclass
class AuditTrail:
    """完整的审计追踪——包含7步管道的所有中间状态"""
    # 用户上下文
    user_context: Dict[str, Any] = field(default_factory=dict)
    province: str = ''
    generated_at: str = ''

    # 7步审计节点
    steps: List[AuditNode] = field(default_factory=list)

    # 摘要
    total_initial: int = 0       # 初始候选数
    total_final: int = 0         # 最终推荐数
    total_excluded: int = 0      # 总排除数

    def to_json(self) -> str:
        """序列化为前端可渲染的 JSON"""
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'AuditTrail':
        steps = []
        for s in data.get('steps', []):
            steps.append(AuditNode(**s))
        return cls(
            user_context=data.get('user_context', {}),
            province=data.get('province', ''),
            generated_at=data.get('generated_at', ''),
            steps=steps,
            total_initial=data.get('total_initial', 0),
            total_final=data.get('total_final', 0),
            total_excluded=data.get('total_excluded', 0),
        )


# ── 7步管道的静态定义 ──

PIPELINE_STEPS = [
    {
        'index': 1,
        'name': '位次转换',
        'icon': '🔢',
        'description': '你的分数在全省的排名',
        'question': '我的分数值多少？',
    },
    {
        'index': 2,
        'name': '选科过滤',
        'icon': '🔬',
        'description': '你的选科组合能报什么',
        'question': '我能报哪些专业？',
    },
    {
        'index': 3,
        'name': '批次过滤',
        'icon': '📋',
        'description': '你在哪个池子里选择',
        'question': '我在哪个池子？',
    },
    {
        'index': 4,
        'name': '限制过滤',
        'icon': '🏥',
        'description': '体检/政审/禁忌项排除',
        'question': '有什么我不能读的？',
    },
    {
        'index': 5,
        'name': '概率计算',
        'icon': '📊',
        'description': '每个选择的录取可能性',
        'question': '我能进吗？概率多大？',
    },
    {
        'index': 6,
        'name': '兴趣匹配',
        'icon': '🧠',
        'description': '你的性格和兴趣适合什么',
        'question': '什么适合我？',
    },
    {
        'index': 7,
        'name': '排序输出',
        'icon': '🏆',
        'description': '综合决策，生成最终推荐',
        'question': '我怎么选？',
    },
]


def create_empty_step(step_index: int) -> AuditNode:
    """创建空的步骤节点（由后续逻辑填充）"""
    for step in PIPELINE_STEPS:
        if step['index'] == step_index:
            return AuditNode(
                step_index=step_index,
                step_name=step['name'],
                step_icon=step['icon'],
            )
    return AuditNode(step_index=step_index, step_name='未知步骤', step_icon='❓')
