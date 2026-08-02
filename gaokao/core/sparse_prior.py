# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""
稀疏数据贝叶斯先验融合 (Sparse Bayesian Prior Fusion)

适用场景：
- 历史类 2025 年首年新高考，单个学校历史录取数据仅 1-2 年
- 直接用 1-2 个数据点估计位次不可靠（单年波动可能超过 ±20%）

核心思路：
- 用"全国同分数段平均规律"作为弱信息先验
- 用"同省物理类同水平学校"作为强信息先验
- 与现有 1-2 年历史类数据做贝叶斯加权融合
- 公式：posterior_rank = (w_prior * prior_rank + w_data * mean_data) / (w_prior + w_data)
  其中 w_data 随样本量增大而增大，样本足够时先验权重自动衰减为 0

设计原则：
- 不引入新依赖（纯 Python + sqlite3）
- 函数级 API，可独立单元测试
- 失败时返回 None，由调用方决定 fallback
"""
import sqlite3
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class PriorEstimate:
    """先验估计结果"""
    rank: int  # 估计位次
    confidence_low: int  # 置信区间下界
    confidence_high: int  # 置信区间上界
    source: str  # 先验来源 'physics_peer' | 'rank_band' | 'none'
    prior_weight: float  # 先验权重（0-1，越接近1代表先验越强）


class SparsePriorEstimator:
    """稀疏数据先验估计器"""

    # 数据量 < 此阈值时启用先验
    SPARSE_THRESHOLD = 3

    # 历史类 vs 物理类的位次比例（基于云南2025年一分一段数据估算）
    # 历史类上线~6万 vs 物理类~21万 → 历史类位次约为物理类的 0.28x
    HISTORY_TO_PHYSICS_RATIO = 0.28

    # 进程级缓存：避免重复查询同一所学校
    _physics_cache: dict = {}
    _band_cache: dict = {}

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def estimate(
        self,
        school_name: str,
        subject_type: str,
        observed_ranks: List[int],
    ) -> Optional[PriorEstimate]:
        """
        基于先验和观测数据，返回融合后的位次估计

        参数：
            school_name: 学校名称
            subject_type: 科类 '历史'/'物理'
            observed_ranks: 已观测到的历史位次（如 [12000, 13500]）

        返回：
            PriorEstimate 或 None（先验不可得时）
        """
        n_observed = len(observed_ranks)

        # 数据充足时不需要先验（直接用观测数据即可）
        if n_observed >= self.SPARSE_THRESHOLD:
            return None

        # 优先尝试同省物理类对照（强先验）
        prior = self._physics_peer_prior(school_name, subject_type)
        if prior is None:
            # 次选：分数段平均（弱先验）
            prior = self._rank_band_prior(school_name, subject_type)

        if prior is None:
            return None

        prior_rank, prior_source = prior

        # 贝叶斯加权融合：样本量越大，先验权重越小
        # w_data = n_observed; w_prior = 2 (相当于 2 个虚拟样本)
        w_prior = 2.0
        w_data = float(n_observed)
        if w_data > 0:
            mean_observed = sum(observed_ranks) / len(observed_ranks)
            fused_rank = (w_prior * prior_rank + w_data * mean_observed) / (w_prior + w_data)
        else:
            fused_rank = prior_rank

        # 置信区间：样本越少，区间越宽（±30% → ±15% → ±10%）
        if n_observed == 0:
            tolerance = 0.30
        elif n_observed == 1:
            tolerance = 0.20
        else:  # n_observed == 2
            tolerance = 0.15

        return PriorEstimate(
            rank=int(fused_rank),
            confidence_low=int(fused_rank * (1 - tolerance)),
            confidence_high=int(fused_rank * (1 + tolerance)),
            source=prior_source,
            prior_weight=w_prior / (w_prior + w_data),
        )

    def _physics_peer_prior(
        self, school_name: str, subject_type: str
    ) -> Optional[Tuple[int, str]]:
        """
        强先验：用同校物理类位次推算历史类位次
        前提：同一所学校在物理类有充足数据
        """
        if subject_type not in ('历史', '历史类', '文科'):
            return None

        if school_name in self._physics_cache:
            return self._physics_cache[school_name]

        result = None
        try:
            from .volunteer_recommender import CURRENT_SCORE_LINE_YEAR
            row = self.conn.execute(
                f"""
                SELECT AVG(min_rank) FROM score_line_{CURRENT_SCORE_LINE_YEAR}
                WHERE school_name = ?
                  AND subject_type IN ('物理', '物理类')
                  AND min_rank IS NOT NULL
                """,
                (school_name,),
            ).fetchone()
            if row and row[0]:
                physics_rank = float(row[0])
                history_rank = int(physics_rank * self.HISTORY_TO_PHYSICS_RATIO)
                result = (history_rank, 'physics_peer')
        except Exception as e:
            logging.warning(f'_physics_peer_prior failed for {school_name}: {e}')

        self._physics_cache[school_name] = result
        return result

    def _rank_band_prior(
        self, school_name: str, subject_type: str
    ) -> Optional[Tuple[int, str]]:
        """
        弱先验：基于同校历年（含旧高考）平均位次推算
        """
        if school_name in self._band_cache:
            return self._band_cache[school_name]

        result = None
        try:
            # P1-fix: 按 subject_type 过滤，防止历史类/物理类位次混合
            row = self.conn.execute(
                """
                SELECT AVG(min_rank) FROM v_enroll_detail
                WHERE school_name = ?
                  AND subject_type = ?
                  AND min_rank IS NOT NULL
                  AND year >= 2022
                """,
                (school_name, subject_type),
            ).fetchone()
            if row and row[0]:
                result = (int(row[0]), 'rank_band')
        except Exception as e:
            logging.warning(f'_rank_band_prior failed for {school_name}: {e}')

        self._band_cache[school_name] = result
        return result


if __name__ == '__main__':
    import os
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'yunnan_gaokao.db')
    conn = sqlite3.connect(db_path)
    est = SparsePriorEstimator(conn)

    # 测试场景 1：历史类只有 1 个数据点
    print('=== 场景1: 历史类·云南大学·1个观测点 ===')
    r1 = est.estimate('云南大学', '历史', [8000])
    print(r1)

    # 测试场景 2：历史类无观测
    print('\n=== 场景2: 历史类·北京大学·0个观测点 ===')
    r2 = est.estimate('北京大学', '历史', [])
    print(r2)

    # 测试场景 3：数据充足（>=3）
    print('\n=== 场景3: 物理类·清华大学·3个观测点 ===')
    r3 = est.estimate('清华大学', '物理', [50, 60, 55])
    print(r3, '(应为 None - 数据充足)')

    conn.close()
