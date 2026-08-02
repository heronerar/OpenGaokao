# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""
录取概率算法 (Admission Probability)
基于3年历史数据，计算考生被某校某专业录取的概率。

核心功能：
1. 获取历史录取数据
2. 计算录取概率
3. 评估置信度
4. 生成推荐理由
"""
import sqlite3
import math
import threading
import statistics
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass

@dataclass
class HistoryRecord:
    """历史录取记录"""
    year: int
    school_name: str
    major_name: str
    min_score: Optional[int]
    min_rank: Optional[int]
    enroll_count: Optional[int]

@dataclass
class ProbabilityResult:
    """概率计算结果"""
    probability: float  # 0-100
    confidence: str     # high/medium/low/none
    predicted_rank: int
    trend: float        # 位次变化率
    reasons: List[str]  # 推荐理由

class AdmissionProbability:
    """录取概率计算器"""

    # 新高考标签 → 旧高考标签的映射（用于查询2020-2024数据）
    _NEW_TO_OLD = {
        '物理': '理科', '物理类': '理科',
        '历史': '文科', '历史类': '文科',
    }
    # 旧高考标签 → 新高考标签的映射（用于查询2025+数据）
    _OLD_TO_NEW = {
        '理科': '物理', '文科': '历史',
    }

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._local = threading.local()

    def _init_local(self):
        if not hasattr(self._local, 'cursor'):
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._local.cursor = conn.cursor()

    def _get_cursor(self):
        if not hasattr(self._local, 'cursor'):
            self._init_local()
        return self._local.cursor

    def _normalize_subject_type(self, subject_type: str, year: int) -> str:
        """
        将传入的subject_type规范化为对应年份的数据库标签

        2020-2024旧高考: 理科/文科
        2025+新高考: 物理/历史
        AUDIT-P2-012: 补全 '物理类'/'历史类' 变体（2025+新高考标准标签）。
        """
        if not subject_type:
            return subject_type
        if year <= 2024:
            return self._NEW_TO_OLD.get(subject_type, subject_type)
        else:
            # 2025+: 映射旧标签 + 兼容 '物理类'/'历史类' 变体
            result = self._OLD_TO_NEW.get(subject_type, None)
            if result:
                return result
            if subject_type == '物理类':
                return '物理'
            if subject_type == '历史类':
                return '历史'
            return subject_type

    def get_history_records(self, school_name: str, major_name: str = None,
                            years: List[int] = None,
                            subject_type: str = None) -> List[HistoryRecord]:
        """
        获取历史录取数据（融合投档线+录取明细）

        参数:
            school_name: 院校名称
            major_name: 专业名称（可选）
            years: 年份列表（默认2023-2025）
            subject_type: 科类 '物理'/'历史'（可选，不传则不筛选）

        返回:
            历史录取记录列表
        """
        if years is None:
            # 默认使用所有可用的历史数据（不含当年）
            years = [2020, 2021, 2022, 2023, 2024]

        records = []

        for year in years:
            row = None
            if major_name:
                # 专业级别：获取该专业在该校该年的数据（优先本科批）
                # P0-A1: 科类隔离 — 专业级查询必须按 subject_type 过滤，
                # 否则会跨物理/历史拿录取记录，违反 CLAUDE.md 绝对约束
                from .subject_normalize import aliases_for_sql_param
                subj_aliases = aliases_for_sql_param(subject_type)
                subj_clause = ''
                subj_params: tuple = ()
                if subj_aliases:
                    subj_clause = f' AND subject_type IN ({", ".join("?" for _ in subj_aliases)})'
                    subj_params = subj_aliases

                for tier in ('本科', '专科'):
                    self._get_cursor().execute(f'''
                        SELECT year, school_name, major_name, min_score, min_rank, enroll_count
                        FROM v_enroll_detail
                        WHERE year = ? AND school_name = ? AND major_name = ?
                          AND batch_tier = ? AND min_rank IS NOT NULL
                          AND batch NOT LIKE '提前%'
                          {subj_clause}
                        LIMIT 1
                    ''', (year, school_name, major_name, tier) + subj_params)
                    row = self._get_cursor().fetchone()
                    if row:
                        break

                # 如果精确匹配不到，用 LIKE 模糊匹配专业名变体
                if row is None:
                    self._get_cursor().execute(f'''
                        SELECT year, school_name, major_name, min_score, min_rank, enroll_count
                        FROM v_enroll_detail
                        WHERE year = ? AND school_name = ? AND major_name LIKE ?
                          AND min_rank IS NOT NULL
                          AND batch NOT LIKE '提前%'
                          {subj_clause}
                        LIMIT 1
                    ''', (year, school_name, f'%{major_name}%') + subj_params)
                    row = self._get_cursor().fetchone()

                if row is None:
                    row = self._get_from_score_line(year, school_name, subject_type)

                if row:
                    records.append(HistoryRecord(
                        year=row[0],
                        school_name=row[1],
                        major_name=row[2] or '',
                        min_score=row[3],
                        min_rank=row[4],
                        enroll_count=row[5],
                    ))
                continue
            else:
                # 学校级别：获取该年该校该科类的位次中位数
                # 优先使用本科批数据, 若无则使用专科批
                # AUDIT-P2-013: 使用 IN 子句展开所有等价别名（如"物理"匹配"物理"+"物理类"+"理科"）
                # 避免因数据库历史标签不统一（如v_enroll_detail 2023-2024为'理科/文科'）漏查
                from .subject_normalize import aliases_for_sql_param
                norm_type = self._normalize_subject_type(subject_type, year) if subject_type else None
                aliases = aliases_for_sql_param(subject_type) if subject_type else ()
                for tier in ('本科', '专科'):
                    base = '''
                        SELECT min_rank, min_score, enroll_count
                        FROM v_enroll_detail
                        WHERE year = ? AND school_name = ? AND min_rank IS NOT NULL
                          AND batch_tier = ?
                          AND batch NOT LIKE '提前%'
                    '''
                    params: list = [year, school_name, tier]
                    if aliases:
                        placeholders = ','.join(['?'] * len(aliases))
                        base += f' AND subject_type IN ({placeholders})'
                        params.extend(aliases)
                    elif norm_type:
                        # fallback：subject_normalize 未识别时退回单值匹配
                        base += ' AND subject_type = ?'
                        params.append(norm_type)

                    self._get_cursor().execute(base, params)
                    rows = self._get_cursor().fetchall()
                    if rows:
                        break

                if rows:
                    ranks = [r[0] for r in rows if r[0] is not None]
                    if ranks:
                        median_rank = int(statistics.median(ranks))
                        total_enroll = sum(r[2] for r in rows if r[2])
                        scores = [r[1] for r in rows if r[1] is not None]
                        avg_score = int(sum(scores) / len(scores)) if scores else None
                        records.append(HistoryRecord(
                            year=year,
                            school_name=school_name,
                            major_name=f'全校中位数({len(ranks)}个专业)',
                            min_score=avg_score,
                            min_rank=median_rank,
                            enroll_count=total_enroll,
                        ))
                    continue
                else:
                    # enroll_detail 没有数据，改用投档线表（不mix科类）
                    row = self._get_from_score_line(year, school_name, subject_type)
                    if row:
                        records.append(HistoryRecord(
                            year=row[0],
                            school_name=row[1],
                            major_name=row[2] or '',
                            min_score=row[3],
                            min_rank=row[4],
                            enroll_count=row[5],
                        ))

        return records

    def _get_from_score_line(self, year: int, school_name: str,
                                 subject_type: str = None) -> Optional[tuple]:
        """
        从投档线表获取数据（支持科类过滤，防止mix物理/历史数据）

        返回:
            (year, school_name, '', min_score, min_rank, None) 或 None
        """
        # 白名单验证：只允许已知年份的表名（防SQL注入）
        allowed_years = {2020, 2021, 2022, 2023, 2024, 2025, 2026}
        if year not in allowed_years:
            return None

        table_name = f'score_line_{year}'

        self._get_cursor().execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        if not self._get_cursor().fetchone():
            return None

        if year == 2023:
            base = '''
                SELECT 年份, 院校名称, '', 投档最低分, NULL, NULL
                FROM score_line_2023
                WHERE 院校名称 = ? AND 投档最低分 IS NOT NULL
            '''
            params = [school_name]
            if subject_type:
                # AUDIT-P2-014: 新→旧标签反向映射
                # 注：subject_normalize 模块当前仅提供"任意→新标签"，未提供"新→旧"反向。
                # 待该模块补充 `to_old_label()` 后可统一替换；当前保留集中硬编码以避免误用。
                _NEW_TO_OLD_CAT = {'物理': '理科', '物理类': '理科', '历史': '文科', '历史类': '文科'}
                old_cat = _NEW_TO_OLD_CAT.get(subject_type, subject_type)
                base += ' AND 科类 = ?'
                params.append(old_cat)
            base += ' LIMIT 1'
            self._get_cursor().execute(base, params)
        elif year == 2024:
            base = '''
                SELECT {} as year, school_name, '', min_score_orig, NULL, NULL
                FROM score_line_2024
                WHERE school_name = ? AND min_score_orig IS NOT NULL
            '''.format(year)
            params = [school_name]
            if subject_type:
                cat_map = {'物理': '理科', '物理类': '理科', '历史': '文科', '历史类': '文科'}
                old_cat = cat_map.get(subject_type, subject_type)
                base += ' AND subject_type = ?'
                params.append(old_cat)
            base += ' LIMIT 1'
            self._get_cursor().execute(base, params)
        else:
            # 2025+ score_line 表用 '物理'/'历史'（短标签）
            # AUDIT-P2-037: 使用 aliases_for_sql_param 展开 IN 子句，
            # 同时匹配短标签（物理）和长标签（物理类），为未来数据迁移做准备
            from .subject_normalize import aliases_for_sql_param
            norm_type = self._normalize_subject_type(subject_type, year) if subject_type else None
            base = '''
                SELECT {} as year, school_name, '', min_score, min_rank, NULL
                FROM {}
                WHERE school_name = ? AND min_score IS NOT NULL
            '''.format(year, table_name)
            params = [school_name]
            if subject_type:
                aliases = aliases_for_sql_param(subject_type)
                placeholders = ','.join(['?'] * len(aliases))
                base += f' AND subject_type IN ({placeholders})'
                params.extend(aliases)
            elif norm_type:
                base += ' AND subject_type = ?'
                params.append(norm_type)
            base += ' LIMIT 1'
            self._get_cursor().execute(base, params)

        return self._get_cursor().fetchone()

    def calculate(self, user_rank: int, school_name: str, major_name: str = None,
                  years: List[int] = None, subject_type: str = None) -> Optional[ProbabilityResult]:
        """
        计算录取概率

        参数:
            user_rank: 考生位次
            school_name: 院校名称
            major_name: 专业名称（可选）
            years: 年份列表
            subject_type: 科类 '物理'/'历史'（可选）

        返回:
            概率计算结果
        """
        if years is None:
            # 默认使用所有可用的历史数据（不含当年，防止数据泄漏）
            years = [2020, 2021, 2022, 2023, 2024]

        records = self.get_history_records(school_name, major_name, years, subject_type)

        if len(records) < 2:
            return ProbabilityResult(
                probability=0.0,
                confidence='none',
                predicted_rank=0,
                trend=0,
                reasons=[f'历史数据不足（仅{len(records)}年），无法计算可靠概率，请人工核实']
            )

        ranks = [r.min_rank for r in records if r.min_rank is not None]

        if not ranks:
            return ProbabilityResult(
                probability=50.0,
                confidence='none',
                predicted_rank=0,
                trend=0,
                reasons=['无位次数据，无法评估']
            )

        # 计算趋势（位次变化率）
        # 位次越小越好，trend>0表示位次数字变大（门槛降低、更容易考）
        # CAT-01修复: 新旧高考体系位次基准不同，禁止跨体系计算趋势
        # 2020-2024 = 旧高考(文/理), 2025+ = 新高考(物理/历史)
        _OLD_GAOKAO_CUTOFF = 2024

        # 按高考体系分组
        old_records = [(r.year, r.min_rank) for r in records
                       if r.min_rank is not None and r.year <= _OLD_GAOKAO_CUTOFF]
        new_records = [(r.year, r.min_rank) for r in records
                       if r.min_rank is not None and r.year > _OLD_GAOKAO_CUTOFF]

        trend = 0
        mixed_warning = False

        # 优先使用最新体系的趋势
        if len(new_records) >= 2:
            # 新高考体系: 仅用新高考数据计算趋势
            new_ranks = [r[1] for r in sorted(new_records, key=lambda x: x[0])]
            yoy = [(new_ranks[i] - new_ranks[i-1]) / new_ranks[i-1]
                   for i in range(1, len(new_ranks)) if new_ranks[i-1] > 0]
            trend = statistics.median(yoy) if yoy else 0
            trend = max(-0.30, min(0.30, trend))
        elif len(old_records) >= 2:
            # 仅有旧高考数据: 用旧高考数据计算趋势
            old_ranks = [r[1] for r in sorted(old_records, key=lambda x: x[0])]
            yoy = [(old_ranks[i] - old_ranks[i-1]) / old_ranks[i-1]
                   for i in range(1, len(old_ranks)) if old_ranks[i-1] > 0]
            trend = statistics.median(yoy) if yoy else 0
            trend = max(-0.30, min(0.30, trend))
        elif len(ranks) >= 2:
            # 回退: 混合数据但各体系均不足2年 — 标记混合警告
            yoy_changes = []
            for i in range(1, len(ranks)):
                if ranks[i-1] > 0:
                    yoy_changes.append((ranks[i] - ranks[i-1]) / ranks[i-1])
            trend = statistics.median(yoy_changes) if yoy_changes else 0
            trend = max(-0.30, min(0.30, trend))
            mixed_warning = True

        # 预测今年位次 — 仅用最新体系的最近数据
        if new_records:
            recent_ranks = [r[1] for r in sorted(new_records, key=lambda x: x[0])][-min(3, len(new_records)):]
        elif old_records:
            recent_ranks = [r[1] for r in sorted(old_records, key=lambda x: x[0])][-min(3, len(old_records)):]
        else:
            recent_ranks = ranks[-min(3, len(ranks)):]
        predicted_rank = int(statistics.median(recent_ranks) * (1 + trend * 0.3))

        # Step 4: 贝叶斯先验融合（路线 C）
        # 仅在历史类且新高考数据稀疏（< 3 条）时启用，与现有 predicted_rank 加权融合
        prior_used = False
        if (subject_type in ('历史', '历史类', '文科')
                and 0 < len(new_records) < 3):
            try:
                from .sparse_prior import SparsePriorEstimator
                conn = self._get_cursor().connection
                est = SparsePriorEstimator(conn)
                observed = [r[1] for r in new_records]
                prior_result = est.estimate(school_name, subject_type, observed)
                if prior_result and prior_result.rank > 0:
                    # 加权融合：先验 50% + 原 predicted_rank 50%
                    # （原 predicted_rank 本身已含观测数据，避免重复加权）
                    predicted_rank = int(0.5 * prior_result.rank + 0.5 * predicted_rank)
                    prior_used = True
            except Exception:
                pass  # 静默失败，回退到原 predicted_rank

        # ── 可及性门禁：位次差距过大则完全不可达（防止清北/华五等出现在中分段考生推荐中）───
        if predicted_rank > 0 and user_rank > predicted_rank:
            ratio = user_rank / predicted_rank
            if ratio > 50:
                return ProbabilityResult(
                    probability=0.0,
                    confidence='none',
                    predicted_rank=predicted_rank,
                    trend=trend,
                    reasons=[
                        f"该校历史录取位次（~{predicted_rank}名）远高于考生位次（{user_rank}名），"
                        f"差距{ratio:.0f}倍 — 完全不可达，不建议填报"
                    ],
                )

        # 计算概率
        # 修复: 使用二次衰减替代线性 — 安全裕度越大，概率应更快趋近100%
        # 旧公式: prob = 50 + diff/pred*50 → rank=50000对predicted=173000时只有85.6%
        # 新公式: prob = 50 + 50 * (1 - exp(-2 * diff/pred)) — 二次衰减，安全裕度越大收敛越快
        if predicted_rank <= 0:
            probability = 50.0
        elif user_rank < predicted_rank:
            diff = predicted_rank - user_rank
            ratio = diff / predicted_rank
            probability = 50 + 50 * (1 - math.exp(-2 * ratio))
            probability = min(99.5, probability)
        else:
            diff = user_rank - predicted_rank
            ratio = diff / predicted_rank
            probability = max(1, 50 - 50 * (1 - math.exp(-2 * ratio)))

        probability = round(probability, 1)

        # 置信度评估
        if len(ranks) >= 3:
            confidence = 'high'
        elif len(ranks) >= 2:
            confidence = 'medium'
        else:
            confidence = 'low'

        # 新高考适配：旧高考数据（2023/2024）与新高考（2025）存在科类转换偏差
        has_old_gaokao = any(r.year < 2025 for r in records)
        if has_old_gaokao and confidence != 'none':
            if confidence == 'high':
                confidence = 'medium'
            elif confidence == 'medium':
                confidence = 'low'

        reasons = self._generate_reasons(
            user_rank, predicted_rank, probability, confidence,
            trend, records, school_name, mixed_warning
        )

        return ProbabilityResult(
            probability=probability,
            confidence=confidence,
            predicted_rank=predicted_rank,
            trend=trend,
            reasons=reasons,
        )

    def calculate_group(self, user_rank: int, school_name: str, group_code: str,
                        subject_type: str = None) -> Optional[ProbabilityResult]:
        """
        计算考生被某院校某专业组录取的概率

        优先使用 score_line_{CURRENT_SCORE_LINE_YEAR} 中的专业组级投档线数据。

        参数:
            user_rank: 考生位次
            school_name: 院校名称
            group_code: 专业组代码，如 '01'
            subject_type: 科类 '物理'/'历史'

        返回:
            概率计算结果
        """
        from .volunteer_recommender import CURRENT_SCORE_LINE_YEAR
        norm_type = self._normalize_subject_type(subject_type, CURRENT_SCORE_LINE_YEAR) if subject_type else None

        # AUDIT-P2-037: 使用 aliases_for_sql_param 展开 IN 子句，
        # 匹配短标签（'物理'/'历史'）和长标签（'物理类'/'历史类'）
        from .subject_normalize import aliases_for_sql_param
        if subject_type:
            aliases = aliases_for_sql_param(subject_type)
            placeholders = ','.join(['?'] * len(aliases))
            self._get_cursor().execute(f'''
                SELECT min_rank, subject_req
                FROM score_line_{CURRENT_SCORE_LINE_YEAR}
                WHERE school_name = ? AND group_code = ? AND subject_type IN ({placeholders})
            ''', (school_name, str(group_code), *aliases))
        else:
            self._get_cursor().execute(f'''
                SELECT min_rank, subject_req
                FROM score_line_{CURRENT_SCORE_LINE_YEAR}
                WHERE school_name = ? AND group_code = ?
            ''', (school_name, str(group_code)))

        row = self._get_cursor().fetchone()
        if not row or row[0] is None:
            # Fallback: 用普通 calculate 方法
            return self.calculate(user_rank, school_name, subject_type=subject_type)

        predicted_rank = int(row[0])
        subject_req = row[1] or ''

        # AUDIT-P1-011: 可及性门禁（与 calculate() 主路径一致）
        # 位次差距过大则完全不可达，避免高分名校（如清北）出现在中分段考生的专业组推荐中。
        if predicted_rank > 0 and user_rank > predicted_rank:
            ratio = user_rank / predicted_rank
            if ratio > 50:
                return ProbabilityResult(
                    probability=0.0,
                    confidence='none',
                    predicted_rank=predicted_rank,
                    trend='stable',
                    reasons=[
                        f"该校{group_code}专业组2025年投档位次（~{predicted_rank}名）远高于考生位次（{user_rank}名），"
                        f"差距{ratio:.0f}倍 — 完全不可达，不建议填报"
                    ],
                )

        # 计算概率
        if predicted_rank <= 0:
            probability = 50.0
        elif user_rank < predicted_rank:
            diff = predicted_rank - user_rank
            ratio = diff / predicted_rank
            probability = 50 + 50 * (1 - math.exp(-2 * ratio))
            probability = min(99.5, probability)
        else:
            diff = user_rank - predicted_rank
            ratio = diff / predicted_rank
            probability = max(1, 50 - 50 * (1 - math.exp(-2 * ratio)))

        probability = round(probability, 1)

        # AUDIT-P2-015: 置信度评估对齐 calculate() 主路径逻辑
        # 专业组数据仅 2025 年单年（新高考首年），置信度天然受限：
        #   - 优势位次（user_rank < predicted_rank）: medium（有数据支撑）
        #   - 劣势位次（user_rank >= predicted_rank）: low（差距大则推断不可靠）
        # 进一步根据差距比例细分：差距 < 20% 偏向 medium，否则 low
        if user_rank < predicted_rank:
            confidence = 'medium'
        else:
            # 位次落后：根据落后程度决定置信度
            if predicted_rank > 0:
                lag_ratio = (user_rank - predicted_rank) / predicted_rank
                if lag_ratio < 0.2:
                    confidence = 'medium'
                else:
                    confidence = 'low'
            else:
                confidence = 'low'

        # 生成推荐理由
        reasons = []
        group_display = f'{group_code}专业组'
        if user_rank < predicted_rank:
            diff = predicted_rank - user_rank
            reasons.append(f"您的位次({user_rank}名)优于该专业组2025年投档位次({predicted_rank}名)，领先约{diff}名")
        else:
            diff = user_rank - predicted_rank
            reasons.append(f"您的位次({user_rank}名)低于该专业组2025年投档位次({predicted_rank}名)，落后约{diff}名")

        if subject_req:
            reasons.append(f"选科要求: {subject_req}")

        if probability >= 85:
            reasons.append("录取概率高，建议作为保底志愿")
        elif probability >= 60:
            reasons.append("录取概率中等，建议作为稳妥志愿")
        elif probability >= 30:
            reasons.append("录取概率较低，建议作为冲刺志愿")
        else:
            reasons.append("录取概率很低，谨慎报考")

        reasons.append("该专业组仅参考2025年投档线，数据年限较短，置信度有限")

        return ProbabilityResult(
            probability=probability,
            confidence=confidence,
            predicted_rank=predicted_rank,
            trend=0,
            reasons=reasons,
        )

    def _generate_reasons(self, user_rank: int, predicted_rank: int,
                          probability: float, confidence: str,
                          trend: float, records: List[HistoryRecord],
                          school_name: str,
                          mixed_warning: bool = False) -> List[str]:
        """生成推荐理由"""
        reasons = []

        # 位次对比
        if user_rank < predicted_rank:
            diff = predicted_rank - user_rank
            reasons.append(f"您的位次({user_rank}名)优于预测位次({predicted_rank}名)，约领先{diff}名")
        else:
            diff = user_rank - predicted_rank
            reasons.append(f"您的位次({user_rank}名)略低于预测位次({predicted_rank}名)，约落后{diff}名")

        # 趋势分析
        if abs(trend) > 0.1:
            if trend > 0:
                reasons.append(f"近三年录取位次呈上升趋势（热度下降{trend*100:.1f}%）")
            else:
                reasons.append(f"近三年录取位次呈下降趋势（热度上升{abs(trend)*100:.1f}%）")
        else:
            reasons.append("近三年录取位次相对稳定")

        # 置信度说明
        year_list = sorted(set(r.year for r in records))
        year_str = ','.join(str(y) for y in year_list)
        if mixed_warning:
            reasons.append(f"数据跨越新旧高考体系，趋势仅基于最新体系计算，置信度仅供参考")
        if confidence == 'high':
            reasons.append(f"基于{year_str}完整数据，置信度高")
        elif confidence == 'medium':
            old_note = "（含2023/2024旧高考数据，置信度已下调）" if any(r.year < 2025 for r in records) else ""
            reasons.append(f"基于{year_str}数据，置信度中等{old_note}")
        else:
            old_note = "（含旧高考数据+数据有限）" if any(r.year < 2025 for r in records) else ""
            reasons.append(f"数据有限，仅供参考{old_note}")

        # 概率等级
        if probability >= 85:
            reasons.append("录取概率高，建议作为保底志愿")
        elif probability >= 60:
            reasons.append("录取概率中等，建议作为稳妥志愿")
        elif probability >= 30:
            reasons.append("录取概率较低，建议作为冲刺志愿")
        else:
            reasons.append("录取概率很低，谨慎报考")

        return reasons

    def batch_calculate(self, user_rank: int, schools: List[str],
                        category: str = None, subject_type: str = None) -> List[Dict]:
        """
        批量计算多所院校的录取概率

        参数:
            user_rank: 考生位次
            schools: 院校名称列表
            category: 科类（用于筛选）
            subject_type: 科类 '物理'/'历史'

        返回:
            概率计算结果列表
        """
        results = []

        for school in schools:
            result = self.calculate(user_rank, school, subject_type=subject_type)
            if result:
                results.append({
                    'school_name': school,
                    'probability': result.probability,
                    'confidence': result.confidence,
                    'predicted_rank': result.predicted_rank,
                    'trend': result.trend,
                    'reasons': result.reasons,
                })

        # 按概率降序排序
        results.sort(key=lambda x: x['probability'], reverse=True)

        return results

    def close(self):
        if hasattr(self._local, 'cursor'):
            try:
                self._local.cursor.connection.close()
            except Exception:
                pass


def main():
    """测试用例"""
    calculator = AdmissionProbability()

    print('=' * 70)
    print('录取概率算法测试')
    print('=' * 70)

    print('\n【测试1】云南大学 - 无subject_type（混合）')
    result = calculator.calculate(7869, '云南大学')
    if result:
        print(f'  预测位次: {result.predicted_rank}')
        print(f'  录取概率: {result.probability}%')
        print(f'  置信度: {result.confidence}')
        for reason in result.reasons:
            print(f'    - {reason}')

    print('\n【测试2】云南大学 - 物理类')
    result = calculator.calculate(7869, '云南大学', subject_type='物理')
    if result:
        print(f'  预测位次: {result.predicted_rank}')
        print(f'  录取概率: {result.probability}%')
        print(f'  置信度: {result.confidence}')
        for reason in result.reasons:
            print(f'    - {reason}')

    print('\n【测试3】哈尔滨商业大学 - 物理类')
    result = calculator.calculate(67463, '哈尔滨商业大学', subject_type='物理')
    if result:
        print(f'  预测位次: {result.predicted_rank}')
        print(f'  录取概率: {result.probability}%')
        print(f'  置信度: {result.confidence}')
        for reason in result.reasons:
            print(f'    - {reason}')

    calculator.close()
    print('\n' + '=' * 70)
    print('测试完成！')

if __name__ == '__main__':
    main()
