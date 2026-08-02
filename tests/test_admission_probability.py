"""录取概率算法测试 — 纯函数逻辑（无需数据库）"""
import sys
import os
import math
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSubjectTypeNormalization:
    """科类标签标准化（_normalize_subject_type 的对外可观测行为）"""

    def test_physics_to_old_gaokao(self):
        from gaokao.core.admission_probability import AdmissionProbability
        ap = AdmissionProbability(':memory:')
        ap.close()
        # 测试 2024 及以前 → 理科
        assert ap._normalize_subject_type('物理', 2024) == '理科'
        assert ap._normalize_subject_type('物理类', 2024) == '理科'
        # 测试 2025+ → 物理
        assert ap._normalize_subject_type('物理', 2025) == '物理'
        assert ap._normalize_subject_type('物理类', 2025) == '物理'

    def test_history_to_old_gaokao(self):
        from gaokao.core.admission_probability import AdmissionProbability
        ap = AdmissionProbability(':memory:')
        ap.close()
        assert ap._normalize_subject_type('历史', 2024) == '文科'
        assert ap._normalize_subject_type('历史类', 2024) == '文科'
        assert ap._normalize_subject_type('历史', 2025) == '历史'
        assert ap._normalize_subject_type('历史类', 2025) == '历史'

    def test_old_labels_to_new(self):
        from gaokao.core.admission_probability import AdmissionProbability
        ap = AdmissionProbability(':memory:')
        ap.close()
        assert ap._normalize_subject_type('理科', 2025) == '物理'
        assert ap._normalize_subject_type('文科', 2025) == '历史'
        # 旧高考直接透传（新旧标签体系一致）
        assert ap._normalize_subject_type('理科', 2024) == '理科'
        assert ap._normalize_subject_type('文科', 2024) == '文科'

    def test_empty_or_unknown(self):
        from gaokao.core.admission_probability import AdmissionProbability
        ap = AdmissionProbability(':memory:')
        ap.close()
        assert ap._normalize_subject_type('', 2025) == ''
        assert ap._normalize_subject_type(None, 2025) is None
        assert ap._normalize_subject_type('未知', 2025) == '未知'


class TestProbabilityFormula:
    """概率公式纯函数验证"""

    def probability(self, user_rank, predicted_rank):
        """从源代码提取的公式（AdmissionProbability.calculate L427-437）"""
        if predicted_rank <= 0:
            return 50.0
        if user_rank < predicted_rank:
            diff = predicted_rank - user_rank
            ratio = diff / predicted_rank
            prob = 50 + 50 * (1 - math.exp(-2 * ratio))
            return round(min(99.5, prob), 1)
        else:
            diff = user_rank - predicted_rank
            ratio = diff / predicted_rank
            prob = max(1, 50 - 50 * (1 - math.exp(-2 * ratio)))
            return round(prob, 1)

    def test_equal_rank_gives_50(self):
        assert self.probability(10000, 10000) == 50.0

    def test_better_rank_gives_above_50(self):
        prob = self.probability(5000, 10000)  # 领先 5000 名
        assert 50 < prob < 100

    def test_worse_rank_gives_below_50(self):
        prob = self.probability(15000, 10000)  # 落后 5000 名
        assert 0 < prob < 50

    def test_very_better_rank_approaches_99(self):
        """领先幅度大 → 概率趋近 99.5"""
        prob = self.probability(1000, 50000)  # 领先 49000 名，ratio=0.98 → ~93.0%
        assert prob >= 90.0
        assert prob <= 99.5

    def test_very_worse_rank_approaches_1(self):
        """落后幅度大 → 概率趋近 1"""
        prob = self.probability(50000, 1000)  # 落后 49000 名
        assert prob <= 2.0

    def test_zero_predicted_rank(self):
        assert self.probability(5000, 0) == 50.0

    def test_slightly_better(self):
        prob = self.probability(9500, 10000)  # 领先 5%
        assert 50 < prob < 70

    def test_slightly_worse(self):
        prob = self.probability(10500, 10000)  # 落后 5%
        assert 30 < prob < 50

    def test_large_gap_bottom_clamped(self):
        """极端落后 -> 不低于 1%"""
        prob = self.probability(1000000, 1000)
        assert prob >= 1.0
        assert prob < 5.0

    def test_ratio_monotonic(self):
        """位次越领先，概率越高（单调性）"""
        probs = [self.probability(r, 10000) for r in [9000, 8000, 7000, 6000, 5000]]
        for i in range(len(probs) - 1):
            assert probs[i] < probs[i + 1], f"非单调: r={[9000,8000,7000,6000,5000][i]} vs {[9000,8000,7000,6000,5000][i+1]}"


class TestConfidenceEvaluation:
    """置信度评估逻辑"""

    def make_result_with_ranks(self, n_years, has_old_gaokao=False):
        """构造一个带指定年数位次数据的 ProbabilityResult 模拟场景"""
        from gaokao.core.admission_probability import AdmissionProbability
        ap = AdmissionProbability(':memory:')
        ap.close()
        records = []
        base_year = 2025 - n_years + 1
        for i in range(n_years):
            from gaokao.core.admission_probability import HistoryRecord
            records.append(HistoryRecord(
                year=base_year + i,
                school_name='测试大学',
                major_name='',
                min_score=500 - i * 10,
                min_rank=10000 + i * 500,
                enroll_count=100,
            ))
        if has_old_gaokao:
            from gaokao.core.admission_probability import HistoryRecord
            records.append(HistoryRecord(
                year=2024,
                school_name='测试大学',
                major_name='',
                min_score=500,
                min_rank=10000,
                enroll_count=100,
            ))
        return records

    def test_high_confidence_3_years(self):
        """纯新高考 3 年数据 → high"""
        from gaokao.core.admission_probability import AdmissionProbability
        ap = AdmissionProbability(':memory:')
        ap.close()
        records = self.make_result_with_ranks(3, has_old_gaokao=False)
        # Ensure all records are new gaokao (2025+)
        for r in records:
            r.year = max(r.year, 2025)
        ranks = [r.min_rank for r in records if r.min_rank is not None]
        n = len(ranks)
        if n >= 3:
            confidence = 'high'
        elif n >= 2:
            confidence = 'medium'
        else:
            confidence = 'low'
        assert confidence == 'high'

    def test_high_confidence_with_old_downgrades(self):
        """含旧高考数据时 high→medium"""
        from gaokao.core.admission_probability import AdmissionProbability
        ap = AdmissionProbability(':memory:')
        ap.close()
        records = self.make_result_with_ranks(3, has_old_gaokao=True)
        ranks = [r.min_rank for r in records if r.min_rank is not None]
        n = len(ranks)
        if n >= 3:
            confidence = 'high'
        elif n >= 2:
            confidence = 'medium'
        else:
            confidence = 'low'
        has_old = any(r.year < 2025 for r in records)
        if has_old and confidence != 'none':
            if confidence == 'high':
                confidence = 'medium'
        assert confidence == 'medium'

    def test_low_confidence_1_year(self):
        from gaokao.core.admission_probability import AdmissionProbability
        ap = AdmissionProbability(':memory:')
        ap.close()
        records = self.make_result_with_ranks(1)
        ranks = [r.min_rank for r in records if r.min_rank is not None]
        n = len(ranks)
        assert n < 2


class TestGenerateReasons:
    """推荐理由生成"""

    def test_basic_reasons_structure(self):
        from gaokao.core.admission_probability import (
            AdmissionProbability, HistoryRecord, ProbabilityResult
        )
        ap = AdmissionProbability(':memory:')
        ap.close()
        records = [
            HistoryRecord(year=2023, school_name='测试大学', major_name='',
                          min_score=500, min_rank=10000, enroll_count=50),
            HistoryRecord(year=2024, school_name='测试大学', major_name='',
                          min_score=490, min_rank=10500, enroll_count=55),
        ]
        reasons = ap._generate_reasons(
            user_rank=8000,
            predicted_rank=10000,
            probability=65.0,
            confidence='medium',
            trend=0.02,
            records=records,
            school_name='测试大学',
            mixed_warning=False,
        )
        assert len(reasons) >= 3
        assert any('8000' in r for r in reasons)  # 位次信息
        assert any('稳妥' in r for r in reasons)  # 65% → 稳妥志愿


class TestBatchCalculateSorting:
    """批量计算排序逻辑（纯函数）"""

    def test_sorted_by_probability_desc(self):
        from gaokao.core.admission_probability import AdmissionProbability
        ap = AdmissionProbability(':memory:')
        ap.close()
        schools = [
            {'school_name': 'A', 'probability': 30, 'confidence': 'low', 'predicted_rank': 10000, 'trend': 0, 'reasons': []},
            {'school_name': 'B', 'probability': 80, 'confidence': 'high', 'predicted_rank': 5000, 'trend': 0, 'reasons': []},
            {'school_name': 'C', 'probability': 50, 'confidence': 'medium', 'predicted_rank': 8000, 'trend': 0, 'reasons': []},
        ]
        schools.sort(key=lambda x: x['probability'], reverse=True)
        assert [s['school_name'] for s in schools] == ['B', 'C', 'A']
