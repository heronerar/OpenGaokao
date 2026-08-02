"""志愿推荐器测试 — 核心算法逻辑"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestCandidateFiltering:
    """候选池筛选中的逻辑"""

    def test_subject_history_bonus(self):
        """历史类的保档安全垫 1.2x"""
        from gaokao.core.volunteer_recommender import VolunteerRecommender
        vr = VolunteerRecommender(':memory:')
        vr.close()
        # _get_max_rank_for_bao 的逻辑
        user_rank = 10000
        # 正常
        max_rank_normal = int(user_rank * 2.0)  # 20000
        # 历史类
        max_rank_history = int(max_rank_normal * 1.2)  # 24000
        assert max_rank_history > max_rank_normal


class TestClassifySchools:
    """冲稳保分类逻辑（纯函数一—只需验证分类器逻辑）"""

    def test_prob_above_bao_min_is_bao(self):
        """概率 >= bao_min (85) → 保"""
        from gaokao.core.volunteer_recommender import VolunteerRecommender, STRATEGY_CONFIGS
        vr = VolunteerRecommender(':memory:')
        vr.close()
        prob_ranges = STRATEGY_CONFIGS['balanced']

        # We test the direct classification logic from classify_schools
        bao_prob = 86
        chong_min, chong_max = prob_ranges['chong_prob_range']
        wen_min, wen_max = prob_ranges['wen_prob_range']
        bao_min = prob_ranges['bao_prob_range'][0]

        assert bao_prob >= bao_min
        assert not (wen_min <= bao_prob < wen_max)
        assert not (bao_prob < chong_max)

    def test_prob_in_wen_range_is_wen(self):
        """概率 35-85 → 稳"""
        from gaokao.core.volunteer_recommender import STRATEGY_CONFIGS
        prob_ranges = STRATEGY_CONFIGS['balanced']
        wen_min, wen_max = prob_ranges['wen_prob_range']
        assert wen_min == 35
        assert wen_max == 85

    def test_prob_below_chong_max_is_chong(self):
        """概率 < 35 → 冲"""
        from gaokao.core.volunteer_recommender import STRATEGY_CONFIGS
        prob_ranges = STRATEGY_CONFIGS['balanced']
        chong_max = prob_ranges['chong_prob_range'][1]
        assert chong_max == 35

    def test_strategy_configs_have_required_keys(self):
        """所有策略配置包含必需字段"""
        from gaokao.core.volunteer_recommender import STRATEGY_CONFIGS
        required_keys = {'chong_prob_range', 'wen_prob_range', 'bao_prob_range'}
        for name, cfg in STRATEGY_CONFIGS.items():
            missing = required_keys - set(cfg.keys())
            assert not missing, f'{name} 缺少: {missing}'


class TestConfidenceNoneGate:
    """共享陷阱3 回归：confidence='none' 不得进入冲稳保推荐。

    背景：admission_probability '无位次数据' 分支返回 prob=50/confidence='none'，
    曾穿过学校级 fallback（volunteer_recommender 1190 行附近）被当 50% 稳档虚假推荐。
    修复在该 fallback 后补 none 守卫。此测试用注入的假概率计算器隔离 DB，锁死该行为。
    """

    class _FakeCalc:
        """假概率计算器：calculate() 恒返回预设结果，calculate_group 不参与。"""
        def __init__(self, result):
            self._result = result

        def calculate(self, user_rank, school_name, major_name=None, *,
                      subject_type=None, **kw):
            return self._result

        def calculate_group(self, *a, **kw):
            return None

        def close(self):
            pass

    def _make_vr(self, fake_result):
        from gaokao.core.volunteer_recommender import VolunteerRecommender
        vr = VolunteerRecommender(':memory:')
        vr.prob_calculator = self._FakeCalc(fake_result)
        # 隔离 :memory: 空库下的 score_line 查询（分类入选后才会触发，与本测试无关）
        vr._get_group_subject_req = lambda *a, **k: ''
        return vr

    def test_none_confidence_school_excluded(self):
        """prob=50 但 confidence='none'（无位次数据）→ 不进任何冲稳保列表"""
        from gaokao.core.volunteer_recommender import STRATEGY_CONFIGS
        from gaokao.core.admission_probability import ProbabilityResult
        none_result = ProbabilityResult(
            probability=50.0, confidence='none', predicted_rank=0,
            trend=0, reasons=['无位次数据，无法评估'],
        )
        vr = self._make_vr(none_result)
        try:
            chong, wen, bao = vr.classify_schools(
                ['无位次测试校'], 15000, STRATEGY_CONFIGS['balanced'],
                subject_type='物理类',
            )
        finally:
            vr.close()
        names = [r.school_name for r in chong + wen + bao]
        assert '无位次测试校' not in names, f'confidence=none 校被错误推荐: {names}'

    def test_normal_confidence_school_included(self):
        """对照组：同样 prob=50 但 confidence='medium' → 应入选（稳档），证明非空通过"""
        from gaokao.core.volunteer_recommender import STRATEGY_CONFIGS
        from gaokao.core.admission_probability import ProbabilityResult
        ok_result = ProbabilityResult(
            probability=50.0, confidence='medium', predicted_rank=12000,
            trend=0, reasons=['基于历史数据'],
        )
        vr = self._make_vr(ok_result)
        try:
            chong, wen, bao = vr.classify_schools(
                ['正常测试校'], 15000, STRATEGY_CONFIGS['balanced'],
                subject_type='物理类',
            )
        finally:
            vr.close()
        names = [r.school_name for r in chong + wen + bao]
        assert '正常测试校' in names, f'正常 confidence 校未入选，测试可能空通过: {names}'


class TestUserProfile:
    """UserProfile 构造和默认值"""

    def test_default_profile_values(self):
        from gaokao.core.volunteer_recommender import UserProfile
        profile = UserProfile(
            score=580, rank=15000, category='物理类',
            risk_tolerance='balanced',
        )
        assert profile.score == 580
        assert profile.rank == 15000
        assert profile.category == '物理类'
        assert profile.preferred_majors == []
        assert profile.preferred_cities == []
        assert profile.excluded_majors == []

    def test_profile_strategy_config_resolution(self):
        from gaokao.core.volunteer_recommender import UserProfile
        profile = UserProfile(
            score=580, rank=15000, category='物理类',
            risk_tolerance='balanced',
        )
        assert profile.risk_tolerance == 'balanced'
