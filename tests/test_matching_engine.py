"""匹配引擎测试 — 纯函数逻辑"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from pathlib import Path
from unittest.mock import patch

from gaokao.core.constraint_checker import check_constraints
from gaokao.core.matching_engine import MatchingEngine
from gaokao.core.questionnaire_parser import (
    HealthScreening, QuestionnaireParser, UserQuestionnaire,
)


class TestRiskStrategyInference:
    """风险策略推断（_infer_risk_strategy 的等价测试）"""

    def test_aggressive_low_score(self):
        """低总分 → aggressive"""
        from gaokao.core.matching_engine import MatchingEngine
        from gaokao.core.questionnaire_parser import UserQuestionnaire
        from gaokao.core.personality_test import TestResult

        engine = MatchingEngine(':memory:')
        engine.close()

        q = UserQuestionnaire(
            name='测试', gender='男', exam_id='EX001', phone='13800138000',
            category='物理类', total_score=600, rank=10000,
            stability_preference=1, stress_tolerance='能适应很高强度的压力（高强度竞争环境）',
            core_demand='就业率优先',
            subject_combo='物理+化学+生物',
        )
        personality = TestResult(
            big_five={'N': 2.0}, career_values={'stability': 2.0, 'income': 4.0},
            holland_code='RIE', holland_scores={'R': 20, 'I': 18, 'E': 15},
            self_efficacy={}, sd_score=2, confidence='high', recommendations=[],
        )
        strategy = engine._infer_risk_strategy(q, personality)
        assert strategy == 'aggressive'

    def test_conservative_high_score(self):
        """高总分 → conservative"""
        from gaokao.core.matching_engine import MatchingEngine
        from gaokao.core.questionnaire_parser import UserQuestionnaire
        from gaokao.core.personality_test import TestResult

        engine = MatchingEngine(':memory:')
        engine.close()

        q = UserQuestionnaire(
            name='测试', gender='男', exam_id='EX001', phone='13800138000',
            category='物理类', total_score=600, rank=10000,
            stability_preference=5, stress_tolerance='偏好低压稳定环境',
            core_demand='学校名气优先',
            subject_combo='物理+化学+生物',
        )
        personality = TestResult(
            big_five={'N': 4.5}, career_values={'stability': 5.0, 'income': 2.0},
            holland_code='CSE', holland_scores={'C': 20, 'S': 15, 'E': 10},
            self_efficacy={}, sd_score=5, confidence='high', recommendations=[],
        )
        strategy = engine._infer_risk_strategy(q, personality)
        assert strategy == 'conservative'

    def test_balanced_mid_score(self):
        """中等总分 → balanced"""
        from gaokao.core.matching_engine import MatchingEngine
        from gaokao.core.questionnaire_parser import UserQuestionnaire
        from gaokao.core.personality_test import TestResult

        engine = MatchingEngine(':memory:')
        engine.close()

        q = UserQuestionnaire(
            name='测试', gender='男', exam_id='EX001', phone='13800138000',
            category='物理类', total_score=600, rank=10000,
            stability_preference=3, stress_tolerance='能适应中等压力',
            core_demand='其他',
            subject_combo='物理+化学+生物',
        )
        personality = None
        strategy = engine._infer_risk_strategy(q, personality)
        assert strategy == 'balanced'

    def test_no_personality_uses_defaults(self):
        """无性格数据时仅依赖问卷"""
        from gaokao.core.matching_engine import MatchingEngine
        from gaokao.core.questionnaire_parser import UserQuestionnaire

        engine = MatchingEngine(':memory:')
        engine.close()

        q = UserQuestionnaire(
            name='测试', gender='男', exam_id='EX001', phone='13800138000',
            category='物理类', total_score=600, rank=10000,
            stability_preference=2, stress_tolerance='能适应较高压力',
            core_demand='',
            subject_combo='物理+化学+生物',
        )
        strategy = engine._infer_risk_strategy(q, None)
        # score=2+2=4 → aggressive
        assert strategy == 'aggressive'


class TestTierLevelProtection:
    """保档层次保护（_protect_tier_level）"""

    def make_rec(self, school_name, batch, category='物理类', total_score=430):
        """辅助构造 SchoolRecommendation"""
        from gaokao.core.matching_engine import SchoolRecommendation
        from gaokao.core.volunteer_recommender import UserProfile

        return SchoolRecommendation(
            school_name=school_name, category='保', probability=90.0,
            confidence='high', predicted_rank=50000, school_quality='本科',
            location='昆明', tuition=5000, recommended_majors=[], reasons=[],
            batch=batch,
        )

    def make_questionnaire(self, category='物理类', total_score=430):
        from gaokao.core.questionnaire_parser import UserQuestionnaire
        return UserQuestionnaire(
            name='测试', gender='男', exam_id='EX001', phone='13800138000',
            category=category, total_score=total_score, rank=50000,
            stability_preference=3, core_demand='', subject_combo='物理+化学+生物',
        )

    def test_benke_line_nearby_prefers_benke(self):
        """本科线附近：本科院校放前面"""
        from gaokao.core.matching_engine import MatchingEngine

        engine = MatchingEngine(':memory:')
        engine.close()

        q = self.make_questionnaire(category='物理类', total_score=440)
        benke = self.make_rec('本科大学', batch='本科批B段')
        zhuanke = self.make_rec('专科大学', batch='高职专科批')

        result = engine._protect_tier_level([zhuanke, benke], q)
        assert result[0].batch == '本科批B段'

    def test_benke_sorted_same_priority(self):
        """混合排序不影响非本科线附近考生"""
        from gaokao.core.matching_engine import MatchingEngine

        engine = MatchingEngine(':memory:')
        engine.close()

        q = self.make_questionnaire(category='物理类', total_score=500)
        a = self.make_rec('大学A', batch='本科批B段')
        b = self.make_rec('大学B', batch='高职专科批')

        result = engine._protect_tier_level([a, b], q)
        # 500 分超出本科线 30 分范围，保持原序
        assert result == [a, b]

    def test_empty_input_returns_empty(self):
        """空输入返回空列表"""
        from gaokao.core.matching_engine import MatchingEngine

        engine = MatchingEngine(':memory:')
        engine.close()

        q = self.make_questionnaire()
        assert engine._protect_tier_level([], q) == []


class TestScoreMajors:
    """专业评分（_score_majors）的核心逻辑"""

    def test_explicit_major_highest_score(self):
        """明确偏好的专业评分最高"""
        from gaokao.core.matching_engine import MatchingEngine
        engine = MatchingEngine(':memory:')
        engine.close()

        school_majors = ['计算机科学与技术', '软件工程', '数据科学']
        recommended = [('计算机科学与技术', 'explicit'), ('数据科学', 'industry')]
        result = engine._score_majors(school_majors, recommended)

        assert len(result) == 3
        # 计算机是 explicit + 第1顺位 → 最高分
        comp = [r for r in result if r.major_name == '计算机科学与技术'][0]
        data = [r for r in result if r.major_name == '数据科学'][0]
        soft = [r for r in result if r.major_name == '软件工程'][0]
        assert comp.score > data.score
        assert data.score > soft.score

    def test_result_sorted_by_score(self):
        """返回结果按分数降序"""
        from gaokao.core.matching_engine import MatchingEngine
        engine = MatchingEngine(':memory:')
        engine.close()

        school_majors = ['专业A', '专业B', '专业C']
        recommended = [('专业A', 'explicit'), ('专业C', 'industry')]
        result = engine._score_majors(school_majors, recommended)
        scores = [r.score for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_new_major_capped(self):
        """新专业评分上限 70"""
        from gaokao.core.matching_engine import MatchingEngine
        from unittest.mock import patch, MagicMock
        engine = MatchingEngine(':memory:')
        engine.close()

        # Mock 所有涉及 DB 的方法
        with patch.multiple(
            engine,
            _get_new_major_set=MagicMock(return_value={'新工科试验班'}),
            _get_employment_stats=MagicMock(return_value=(0.0, 0.0)),
            _get_revocation_risk_label=MagicMock(return_value='none'),
            _get_similar_major_historical_data=MagicMock(return_value=None),
            _get_trend_bonus=MagicMock(return_value=(0, '')),
        ):
            school_majors = ['新工科试验班', '计算机科学与技术']
            recommended = [('新工科试验班', 'explicit'), ('计算机科学与技术', 'explicit')]
            result = engine._score_majors(school_majors, recommended)
            new_major = [r for r in result if r.major_name == '新工科试验班'][0]
            old_major = [r for r in result if r.major_name == '计算机科学与技术'][0]
            assert new_major.score <= 70
            assert new_major.is_new_major is True
            assert old_major.score > 70


# Read the public surveys so changes to their real options are covered automatically.

_COLOR_EXPECTATIONS = {
    '无色盲色弱': ('正常', []),
    '轻度色弱（部分专业受限）': ('色弱', ['化学类', '医学类']),
    '色盲（多项专业受限）': ('色盲', ['化学类', '医学类', '生物类', '美术类']),
    '红绿色盲（多项专业受限）': ('色盲', ['化学类', '医学类', '生物类', '美术类']),
    '不清楚': (None, []),
}


def _survey_color_cases():
    cases = []
    for subject in ('physics', 'history'):
        path = Path(__file__).resolve().parents[1] / 'questionnaires' / (
            f'volunteer_survey_{subject}.json'
        )
        survey = json.loads(path.read_text(encoding='utf-8'))
        question = next(q for section in survey['sections']
                        for q in section['questions'] if q['id'] == 'q9_color_vision')
        cases.extend((survey['category'], option) for option in question['options'])
    return cases


def _color_questionnaire(category, value, parsed=False):
    if parsed:
        parser = QuestionnaireParser.create_by_category(category)
        return parser.parse({
            'q1_name': '色觉回归', 'q12_total_score': 600,
            'q13_rank': 10000, 'q14_category': category, 'q9_color_vision': value,
        })
    return UserQuestionnaire(
        name='色觉回归', gender='男', exam_id='EX001', phone='',
        category=category, total_score=600, rank=10000,
        health_screening=HealthScreening(color_vision=value),
    )


class TestColorVisionRegression:
    @pytest.mark.parametrize('category,option', _survey_color_cases())
    @pytest.mark.parametrize('parsed', [False, True], ids=['direct', 'parsed'])
    def test_real_survey_options(self, category, option, parsed):
        expected_color, expected_restrictions = _COLOR_EXPECTATIONS[option]
        q = _color_questionnaire(category, option, parsed)
        engine = MatchingEngine(':memory:')
        try:
            assert engine._get_health_restrictions(q) == expected_restrictions
            assert set(engine._get_excluded_majors(q)) == set(expected_restrictions)
            # Exercise match's real call to the checker; isolate recommendation/DB work.
            with patch('gaokao.core.matching_engine.check_constraints',
                       wraps=check_constraints) as checker, \
                 patch.object(engine, '_generate_recommendations',
                              return_value={'冲': [], '稳': [], '保': []}), \
                 patch.object(engine, '_get_all_schools_with_majors', return_value=[]):
                result = engine.match(q)
            checker.assert_called_once()
            assert checker.call_args.args[0]['color_vision'] == expected_color
            # No restriction rules are changed: compare against the existing checker.
            baseline = check_constraints({'color_vision': expected_color})
            assert set(result.constraint_result.filtered_majors) == set(baseline.filtered_majors)
            assert set(engine._get_excluded_majors(q)) == (
                set(expected_restrictions) | set(baseline.filtered_majors)
            )
        finally:
            engine.close()

    @pytest.mark.parametrize('value', ['', None, '正常', '无', '无色弱', '不清楚', '未知'])
    def test_normal_and_unspecified_do_not_restrict(self, value):
        engine = MatchingEngine(':memory:')
        try:
            q = _color_questionnaire('物理类', value)
            assert engine._get_health_restrictions(q) == []
            expected = '正常' if value and (value.startswith('无') or value == '正常') else None
            assert engine._build_constraint_answers(q)['color_vision'] == expected
            # Other health restrictions must still apply.
            q.health_screening.smell = '嗅觉迟钝'
            assert engine._get_health_restrictions(q) == ['食品科学类']
        finally:
            engine.close()

    def test_no_health_screening(self):
        engine = MatchingEngine(':memory:')
        try:
            q = _color_questionnaire('物理类', '')
            q.health_screening = None
            assert engine._get_health_restrictions(q) == []
            assert engine._build_constraint_answers(q)['color_vision'] is None
        finally:
            engine.close()
