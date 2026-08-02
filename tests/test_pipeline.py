"""管道审计测试 — 验证审计追踪的完整性和正确性"""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'example.db')

# OG-F-43: 与 test_integration 一致——example.db 缺失时整体 skip，而非在用例里直接报
# sqlite OperationalError（守卫策略统一，避免"部分 fail 部分 skip"掩盖回归）。
pytestmark = pytest.mark.skipif(
    not os.path.exists(DB_PATH),
    reason=f'example.db 不存在: {DB_PATH}（运行 python data/generate_example_db.py 生成）',
)


@pytest.fixture
def questionnaire():
    from gaokao.core.questionnaire_parser import QuestionnaireParser
    parser = QuestionnaireParser.create_by_category('物理类')
    test_data = {
        'q1_name': '测试考生', 'q2_gender': '男',
        'q5_exam_id': '5301002026000001', 'q6_phone': '13800138000',
        'q9_color_vision': '无色盲色弱', 'q10_vision': '视力正常',
        'q12_total_score': 580, 'q13_rank': 15000,
        'q14_category': '物理类', 'q15_subject_combo': '物理+化学+生物',
        'q40_total_budget': '4-6万元', 'q43_core_demand': '专业实力优先',
        'q45_target_industries': ['信息技术/互联网'],
        'q56_province_preference': '优先省内，省外也可以',
        'q60_stability_preference': 3,
    }
    return parser.parse(test_data)


class TestPipeline:

    def test_audit_trail_has_7_steps(self):
        from gaokao.pipeline.audit_trail import AuditTrail, AuditNode, PIPELINE_STEPS
        assert len(PIPELINE_STEPS) == 7
        steps = [PIPELINE_STEPS[i]['index'] for i in range(7)]
        assert steps == [1, 2, 3, 4, 5, 6, 7]

    def test_audit_trail_serialization(self):
        from gaokao.pipeline.audit_trail import AuditTrail
        from datetime import datetime
        trail = AuditTrail(
            user_context={'rank': 15000},
            province='yunnan',
            generated_at=datetime.now().isoformat(),
        )
        d = trail.to_dict()
        assert d['province'] == 'yunnan'
        assert d['total_initial'] == 0

    def test_auditor_runs(self, questionnaire):
        import random
        random.seed(42)
        big_five = {i: random.randint(2, 5) for i in range(1, 51)}
        holland = {i: ('A' if random.random() > 0.5 else 'B') for i in range(1, 77)}
        efficacy = {i: random.randint(2, 5) for i in range(76, 91)}
        career_vals = {i: random.randint(2, 5) for i in range(91, 111)}

        from gaokao.core.matching_engine import MatchingEngine
        from gaokao.core.revocation_risk import set_db_path
        set_db_path(DB_PATH)
        from gaokao.pipeline.matching_auditor import audit_match

        engine = MatchingEngine(db_path=DB_PATH)
        try:
            result = audit_match(
                engine, questionnaire,
                big_five_answers=big_five,
                holland_answers=holland,
                efficacy_answers=efficacy,
                career_values_answers=career_vals,
                top_n=30,
            )
            assert result.audit_trail is not None
            assert len(result.audit_trail.steps) == 7
            # Should have at least some recommendations
            recs = getattr(result.match_result, 'recommendations', {}) or {}
            total = sum(len(v) for v in recs.values())
            assert total > 0
        finally:
            engine.close()

    def test_renderer_generates_html(self, questionnaire):
        import random
        random.seed(42)
        big_five = {i: random.randint(2, 5) for i in range(1, 51)}
        holland = {i: ('A' if random.random() > 0.5 else 'B') for i in range(1, 77)}
        efficacy = {i: random.randint(2, 5) for i in range(76, 91)}
        career_vals = {i: random.randint(2, 5) for i in range(91, 111)}

        from gaokao.core.matching_engine import MatchingEngine
        from gaokao.core.revocation_risk import set_db_path
        set_db_path(DB_PATH)
        from gaokao.pipeline.matching_auditor import audit_match
        from gaokao.pipeline.pipeline_renderer import render_audit_trail

        engine = MatchingEngine(db_path=DB_PATH)
        try:
            result = audit_match(
                engine, questionnaire,
                big_five_answers=big_five,
                holland_answers=holland,
                efficacy_answers=efficacy,
                career_values_answers=career_vals,
                top_n=30,
            )
            html = render_audit_trail(result.audit_trail)
            assert 'pipeline-overview' in html
            assert 'step-card' in html
            assert '位次转换' in html
        finally:
            engine.close()
