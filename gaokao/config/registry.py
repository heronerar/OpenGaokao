# SPDX-License-Identifier: LicenseRef-OpenGaokao-SAL-1.0
# Copyright (C) 2026 OpenGaokao Contributors
"""
省份配置注册表 (Province Registry)
动态发现 + 加载省份配置，实现引擎与省份解耦。

使用:
    registry = ProvinceRegistry()
    registry.discover()                          # 扫描 provinces/ 目录
    config = registry.get('yunnan')              # 获取单个省份配置
    all_configs = registry.list_all()            # 列出所有省份
"""
import os
import re
import yaml
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 项目根（从 gaokao/config/registry.py 上溯两级）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PROVINCES_DIR = os.path.join(_PROJECT_ROOT, 'provinces')


@dataclass
class BatchConfig:
    """批次配置"""
    name: str = ''
    batch_key: str = ''
    volunteer_count: int = 10
    method: str = '平行志愿'
    section: str = ''
    batch_type: str = ''
    chong_ratio: float = 0.30
    wen_ratio: float = 0.40
    bao_ratio: float = 0.30
    chong_prob_range: List[int] = field(default_factory=lambda: [20, 35])
    wen_prob_range: List[int] = field(default_factory=lambda: [35, 85])
    bao_prob_range: List[int] = field(default_factory=lambda: [85, 100])
    requires_special: bool = False
    eligible_condition: str = ''


@dataclass
class ProvinceConfig:
    """省份完整配置"""
    name: str = ''
    slug: str = ''
    gaokao_mode: str = ''          # 3+1+2 / 3+3 / 文理分科
    volunteer_mode: str = ''       # group / major / old
    reform_year: int = 2025
    category: Dict[str, List[str]] = field(default_factory=dict)
    years: Dict[str, Any] = field(default_factory=dict)
    tables: Dict[str, str] = field(default_factory=dict)
    thresholds: Dict[str, Any] = field(default_factory=dict)
    probability: Dict[str, Any] = field(default_factory=dict)
    subject_map: Dict[str, str] = field(default_factory=dict)
    score_segments: Dict[str, int] = field(default_factory=dict)
    health_exclusions: Dict[str, List[str]] = field(default_factory=dict)
    batches: Dict[str, BatchConfig] = field(default_factory=dict)
    config_path: str = ''

    @property
    def db_path(self) -> str:
        """省数据库路径（可覆盖）"""
        return os.path.join(
            _PROJECT_ROOT, 'data', f'{self.slug}_gaokao.db'
        )

    @property
    def plan_year(self) -> int:
        return self.years.get('plan', 2025)

    @property
    def score_line_year(self) -> int:
        return self.years.get('score_line', 2025)

    @property
    def history_years(self) -> List[int]:
        return self.years.get('history', [2023, 2024, 2025])

    def get_prob_threshold(self, prob: float) -> str:
        """根据概率返回冲/稳/保/垫标签"""
        c_max = self.thresholds.get('chong_max', 35)
        w_min, w_max = self.thresholds.get('wen_range', [35, 85])
        b_min = self.thresholds.get('bao_min', 85)
        if prob < c_max:
            return '冲'
        elif prob < w_max:
            return '稳'
        elif prob >= b_min:
            return '保'
        else:
            return '垫'

    def get_score_line(self, category: str, line_type: str = '本科线') -> int:
        """获取科类对应的批次线分数。

        从 thresholds.score_lines 获取本科线/专科线等分数线。
        回退逻辑：先精确匹配 category，再尝试短标签（物理→物理类），最后返回 0。
        """
        lines = self.thresholds.get('score_lines', {})
        if category in lines:
            return lines[category].get(line_type, 0)
        # 短标签回退: '物理' → 查 '物理类' (和 vice versa)
        for key in ('物理类', '物理', '理科', '历史类', '历史', '文科'):
            if key in lines:
                return lines[key].get(line_type, 0)
        return 0


class ProvinceRegistry:
    """省份注册表 — 动态发现 provinces/ 目录下的 YAML 配置"""

    def __init__(self, provinces_dir: str = None):
        self._dir = provinces_dir or _PROVINCES_DIR
        self._configs: Dict[str, ProvinceConfig] = {}

    def discover(self) -> List[str]:
        """扫描 provinces/ 目录，加载所有 province.yaml"""
        if not os.path.isdir(self._dir):
            logger.warning(f'省份目录不存在: {self._dir}')
            return []

        discovered = []
        for entry in os.listdir(self._dir):
            if entry.startswith('_') or entry.startswith('.'):
                continue
            prov_dir = os.path.join(self._dir, entry)
            yaml_path = os.path.join(prov_dir, 'province.yaml')
            if os.path.isfile(yaml_path):
                try:
                    config = self._load_yaml(yaml_path)
                    config.config_path = yaml_path
                    slug = config.slug or entry
                    self._configs[slug] = config
                    discovered.append(slug)
                    logger.info(f'已注册省份: {slug} ({config.name})')
                except Exception as e:
                    logger.error(f'加载省份失败 {entry}: {e}')

        return discovered

    def _load_yaml(self, path: str) -> ProvinceConfig:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError(f'空配置文件: {path}')

        # 解析批次配置
        batches = {}
        raw_batches = data.pop('batches', {}) or {}
        for key, bd in raw_batches.items():
            batches[key] = BatchConfig(
                name=bd.get('name', key),
                batch_key=bd.get('batch_key', key),
                volunteer_count=bd.get('volunteer_count', 10),
                method=bd.get('method', '平行志愿'),
                section=bd.get('section', ''),
                batch_type=bd.get('batch_type', ''),
                chong_ratio=bd.get('chong_ratio', 0.30),
                wen_ratio=bd.get('wen_ratio', 0.40),
                bao_ratio=bd.get('bao_ratio', 0.30),
                chong_prob_range=bd.get('chong_prob_range', [20, 35]),
                wen_prob_range=bd.get('wen_prob_range', [35, 85]),
                bao_prob_range=bd.get('bao_prob_range', [85, 100]),
                requires_special=bd.get('requires_special', False),
                eligible_condition=bd.get('eligible_condition', ''),
            )

        return ProvinceConfig(
            name=data.get('name', ''),
            slug=data.get('slug', ''),
            gaokao_mode=data.get('gaokao_mode', ''),
            volunteer_mode=data.get('volunteer_mode', ''),
            reform_year=data.get('reform_year', 2025),
            category=data.get('category', {}),
            years=data.get('years', {}),
            tables=data.get('tables', {}),
            thresholds=data.get('thresholds', {}),
            probability=data.get('probability', {}),
            subject_map=data.get('subject_map', {}),
            score_segments=data.get('score_segments', {}),
            health_exclusions=data.get('health_exclusions', {}),
            batches=batches,
        )

    def get(self, slug: str) -> Optional[ProvinceConfig]:
        """获取省份配置"""
        return self._configs.get(slug)

    def list_all(self) -> Dict[str, ProvinceConfig]:
        """列出所有已注册省份"""
        return dict(self._configs)

    def get_recommender_type(self, slug: str) -> str:
        """根据省份的 volunteer_mode 返回推荐器类型"""
        config = self.get(slug)
        if not config:
            raise KeyError(f'未知省份: {slug}')
        mode = config.volunteer_mode
        if mode == 'group':
            return 'GroupRecommender'
        elif mode == 'major':
            return 'MajorRecommender'
        else:
            return 'GroupRecommender'  # 默认院校专业组


# ── 全局单例 ──
_registry: Optional[ProvinceRegistry] = None


def get_registry() -> ProvinceRegistry:
    """获取全局省份注册表单例"""
    global _registry
    if _registry is None:
        _registry = ProvinceRegistry()
        _registry.discover()
    return _registry
