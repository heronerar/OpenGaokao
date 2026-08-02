"""风险引擎 + 共识引擎测试"""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestRisk:

    def test_assess_risks_basic(self):
        from gaokao.risk.risk_calculator import assess_risks
        risk = assess_risks(
            user_rank=15000,
            recommendations={},
        )
        assert risk.overall_risk in ('low', 'medium', 'high')
        assert 0 <= risk.slip_probability <= 100

    def test_checklist_in_risk(self):
        from gaokao.risk.risk_calculator import assess_risks
        risk = assess_risks(user_rank=15000, recommendations={})
        assert len(risk.checklist) >= 3


class TestConsensus:

    def test_consensus_calculator(self):
        from gaokao.consensus.consensus_calculator import calculate_consensus
        from gaokao.consensus.parent_survey import ParentPreference
        parent = ParentPreference(
            stability_priority=4,
            income_priority=4,
            location_preference='省内',
        )
        report = calculate_consensus(
            parent=parent,
            student_holland_code='RIE',
            student_major_interests=['计算机', '软件工程'],
            student_excluded_majors=set(),
        )
        assert 0 <= report.consensus_rate <= 100
        assert hasattr(report, 'consensus_areas')

    def test_calculate_consensus_high(self):
        from gaokao.consensus.consensus_calculator import calculate_consensus
        from gaokao.consensus.parent_survey import ParentPreference
        parent = ParentPreference(
            stability_priority=5,
            income_priority=5,
            location_preference='省内',
        )
        report = calculate_consensus(
            parent=parent,
            student_holland_code='CRI',
            student_major_interests=['计算机', '软件工程', '会计学'],
            student_excluded_majors=set(),
        )
        assert report.consensus_rate > 30


class TestConfig:

    def test_registry_has_yunnan(self):
        from gaokao.config.registry import get_registry
        reg = get_registry()
        cfg = reg.get('yunnan')
        assert cfg is not None
        assert cfg.name == '云南省'
        assert cfg.gaokao_mode == '3+1+2'
