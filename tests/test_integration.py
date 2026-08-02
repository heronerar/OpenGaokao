"""集成测试 — 用 example.db 跑端到端全流程"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE_DB = os.path.join(PROJECT_ROOT, 'data', 'example.db')


def _ensure_example_db():
    if not os.path.exists(EXAMPLE_DB):
        pytest.skip(f'example.db 不存在: {EXAMPLE_DB}')


class TestEndToEnd:
    """用 example.db 跑完整推荐流程"""

    def test_example_database_is_visibly_synthetic(self):
        """示例院校在每个公开查询表中都必须保持可见前缀。"""
        _ensure_example_db()
        import sqlite3

        with sqlite3.connect(EXAMPLE_DB) as conn:
            for table in (
                'school_info', 'score_line_2025', 'score_line_2024',
                'enroll_detail', 'enroll_plan_2025',
            ):
                names = [row[0] for row in conn.execute(
                    f'SELECT DISTINCT school_name FROM {table}'
                )]
                assert names
                assert all(name.startswith('示例·') for name in names), (table, names)

    def _make_questionnaire(self, **overrides):
        from gaokao.core.questionnaire_parser import UserQuestionnaire
        defaults = dict(
            name='测试考生', gender='男', exam_id='EX001', phone='13800138000',
            category='物理类', total_score=580, rank=15000,
            stability_preference=3, stress_tolerance='能适应中等压力',
            core_demand='就业率优先',
            subject_combo='物理+化学+生物',
        )
        defaults.update(overrides)
        return UserQuestionnaire(**defaults)

    def test_configure_with_config_yunnan(self):
        """configure_with_config 能正确加载云南配置"""
        from gaokao.config.registry import get_registry
        reg = get_registry()
        cfg = reg.get('yunnan')
        assert cfg is not None

        from gaokao.core.volunteer_recommender import configure_with_config, get_config
        configure_with_config(cfg)
        loaded = get_config()
        assert loaded is not None
        assert loaded.slug == 'yunnan'
        assert loaded.get_score_line('物理类', '本科线') == 420
        assert loaded.get_score_line('历史类', '本科线') == 430

    def test_match_basic_flow(self):
        """MatchingEngine.match() 端到端跑通"""
        _ensure_example_db()
        from gaokao.core.revocation_risk import set_db_path as _set_rdb
        _set_rdb(EXAMPLE_DB)
        from gaokao.core.matching_engine import MatchingEngine
        engine = MatchingEngine(db_path=EXAMPLE_DB)
        try:
            q = self._make_questionnaire()

            big_five = {i: 3 for i in range(1, 51)}
            holland = {i: 'A' for i in range(1, 77)}
            efficacy = {i: 3 for i in range(76, 91)}
            career_vals = {i: 3 for i in range(91, 111)}

            result = engine.match(q, big_five, holland, efficacy, career_vals, top_n=30)
            assert result is not None
            recs = result.recommendations
            assert '冲' in recs or '稳' in recs or '保' in recs
            total = sum(len(v) for v in recs.values())
            assert total > 0, f'推荐总数为 0: {recs}'
        finally:
            engine.close()

    def test_match_all_categories(self):
        """物理类和历史类都跑通推荐"""
        _ensure_example_db()
        from gaokao.core.revocation_risk import set_db_path as _set_rdb
        _set_rdb(EXAMPLE_DB)
        from gaokao.core.matching_engine import MatchingEngine
        for cat, score, rank in [('物理类', 580, 15000), ('历史类', 550, 8000)]:
            engine = MatchingEngine(db_path=EXAMPLE_DB)
            try:
                q = self._make_questionnaire(category=cat, total_score=score, rank=rank)
                big_five = {i: 3 for i in range(1, 51)}
                holland = {i: 'B' for i in range(1, 77)}
                efficacy = {i: 3 for i in range(76, 91)}
                career_vals = {i: 3 for i in range(91, 111)}
                result = engine.match(q, big_five, holland, efficacy, career_vals, top_n=20)
                total = sum(len(v) for v in result.recommendations.values())
                assert total > 0, f'{cat} 推荐为空'
            finally:
                engine.close()

    def test_probability_calculate_with_db(self):
        """AdmissionProbability.calculate 用真实数据库跑通"""
        _ensure_example_db()
        from gaokao.core.admission_probability import AdmissionProbability
        ap = AdmissionProbability(db_path=EXAMPLE_DB)
        try:
            # example.db 中的合成院校名必须持续带“示例·”前缀
            result = ap.calculate(user_rank=15000, school_name='示例·云岭大学',
                                  years=[2023, 2024])
            assert result is not None
            assert 1 <= result.probability <= 99.5
            assert result.confidence in ('high', 'medium', 'low')
            assert result.predicted_rank > 0
        finally:
            ap.close()

    def test_recommender_filter_candidates_with_db(self):
        """VolunteerRecommender.filter_candidates 用真实数据库跑通"""
        _ensure_example_db()
        from gaokao.core.volunteer_recommender import VolunteerRecommender
        vr = VolunteerRecommender(db_path=EXAMPLE_DB)
        try:
            candidates = vr.filter_candidates(
                user_rank=15000, tolerance=0.30, subject_type='物理'
            )
            assert len(candidates) > 0
            # candidates 是 (school_name, min_rank, ...) 的 tuple
            first = candidates[0]
            assert isinstance(first, tuple)
            assert len(first) >= 2
        finally:
            vr.close()

    def test_recommender_generate_plan(self):
        """VolunteerRecommender.generate_plan 能用真实数据库产生推荐方案"""
        _ensure_example_db()
        from gaokao.core.volunteer_recommender import VolunteerRecommender, UserProfile
        vr = VolunteerRecommender(db_path=EXAMPLE_DB)
        try:
            profile = UserProfile(
                score=580, rank=15000, category='物理类',
                risk_tolerance='balanced',
            )
            plan = vr.generate_plan(profile, top_n=30)
            assert 'batches' in plan or '冲' in plan or '总' in plan
            total = plan.get('total', 0) or sum(
                len(plan.get(c, [])) for c in ['冲', '稳', '保', '垫']
            )
            assert total > 0
        finally:
            vr.close()

    def test_cli_example_runs(self):
        """CLI --example 端到端跑通"""
        _ensure_example_db()
        import subprocess
        r = subprocess.run(
            [sys.executable, '-m', 'gaokao.cli', '--province', 'yunnan', '--example'],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
            timeout=60,
        )
        assert r.returncode == 0, f'CLI 失败:\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}'
        assert '推荐完成' in r.stdout or '总计' in r.stdout
        assert '不可用于实际填报' in r.stdout

    def test_get_score_segment_from_config(self):
        """get_score_segment 从配置读取分数线"""
        from gaokao.core.volunteer_recommender import get_score_segment, get_config, configure_with_config
        from gaokao.config.registry import get_registry

        # 先确保配置已加载
        if get_config() is None:
            reg = get_registry()
            cfg = reg.get('yunnan')
            configure_with_config(cfg)

        assert get_score_segment(580, '物理类') == '高分段'
        assert get_score_segment(450, '物理类') == '关键分数段'
        assert get_score_segment(400, '物理类') == '专科段'
        assert get_score_segment(530, '历史类') == '高分段'
        assert get_score_segment(450, '历史类') == '中分段'
