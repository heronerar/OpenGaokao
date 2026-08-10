# SPDX-License-Identifier: LicenseRef-OpenGaokao-SAL-1.0
# Copyright (C) 2026 OpenGaokao Contributors
"""
匹配审计器 (Matching Auditor)
包装 MatchingEngine.match()，在推荐执行过程中捕获 7 步管道的中间状态。

设计原则（"不重写，只包装"）:
- 不修改 MatchingEngine 的核心逻辑
- 在外部捕获能获取到的所有中间状态
- 对无法精确获取的步骤，从 MatchingResult 反推
"""
import traceback
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from .audit_trail import AuditTrail, AuditNode, create_empty_step, PIPELINE_STEPS


@dataclass
class AuditResult:
    """审计结果 — 既包含推荐结果也包含审计追踪"""
    match_result: Any              # MatchingResult
    audit_trail: AuditTrail        # 7步审计追踪
    risk_assessment: Any = None    # RiskAssessment（可选）
    consensus_report: Any = None   # ConsensusReport（可选）


def _build_user_context(questionnaire) -> Dict[str, Any]:
    """从 questionnaire 提取用户上下文"""
    return {
        'name': getattr(questionnaire, 'name', ''),
        'category': getattr(questionnaire, 'category', ''),
        'subject_combo': getattr(questionnaire, 'subject_combo', ''),
        'total_score': getattr(questionnaire, 'total_score', 0),
        'rank': getattr(questionnaire, 'rank', 0),
        'risk_tolerance': getattr(questionnaire, 'risk_tolerance', ''),
    }


def _step_rank_conversion(result, user_context) -> AuditNode:
    """Step 1: 位次转换"""
    node = create_empty_step(1)
    user_profile = getattr(result, 'user_profile', None)
    if user_profile:
        rank = getattr(user_profile, 'rank', 0) or 0
        score = getattr(user_profile, 'score', 0) or 0
        node.input_summary = f"原始分数：{user_context.get('total_score', '?')}分"
        node.output_summary = f"全省位次：{rank:,}名"
        node.formula = "位次 = 一分一段表累积排名查询"
        node.formula_params = {
            '原始分数': user_context.get('total_score', '?'),
            '科类': user_context.get('category', ''),
        }
        node.output_count = rank
        node.data_sources = [{
            'name': f"{user_context.get('category', '')}一分一段表",
        }]
    node.notes = ["位次比分数更稳定——不同年份的分数不可比，但位次可比。" if node.output_count else ""]
    return node


def _step_subject_filter(result) -> AuditNode:
    """Step 2: 选科过滤"""
    node = create_empty_step(2)
    funnel = getattr(result, 'funnel_report', None)
    if funnel and funnel.stages and len(funnel.stages) >= 1:
        stage = funnel.stages[0]
        node.excluded_count = stage.excluded_count or 0
        node.output_count = stage.remaining_count or 0
        node.excluded_items = [{'name': e, 'reason': '选科不匹配'} for e in (stage.excluded_items or [])]
        node.data_sources = [{'name': '招生计划选科要求表'}]
    return node


def _step_batch_filter(result) -> AuditNode:
    """Step 3: 批次过滤"""
    node = create_empty_step(3)
    # Get batch info from notes or result
    notes = getattr(result, 'notes', []) or []
    batch_notes = [n for n in notes if '批次' in n or '提前' in n or '专科' in n]
    if batch_notes:
        node.notes = batch_notes[:3]
    user_profile = getattr(result, 'user_profile', None)
    questionnaire = getattr(result, 'questionnaire', None)
    if questionnaire:
        batch = getattr(questionnaire, 'batch', '') or '本科普通批'
        node.output_summary = f"批次：{batch}"
        node.data_sources = [{'name': f'{batch}招生计划'}]
    return node


def _step_constraint_filter(result) -> AuditNode:
    """Step 4: 限制过滤（体检/政审/禁忌项）"""
    node = create_empty_step(4)
    constraint = getattr(result, 'constraint_result', None)
    if constraint:
        filtered = getattr(constraint, 'filtered_majors', []) or []
        node.excluded_items = [{'name': m, 'reason': '体检/限制条件不满足'} for m in filtered[:10]]
        node.excluded_count = len(filtered)
        node.notes = getattr(constraint, 'warnings', [])[:5]
        node.data_sources = [
            {'name': '教育部体检指导意见'},
            {'name': '各校招生章程'},
        ]
    funnel = getattr(result, 'funnel_report', None)
    if funnel and funnel.stages and len(funnel.stages) >= 3:
        stage = funnel.stages[2]
        if stage.excluded_count:
            node.output_count = stage.remaining_count or 0
            node.excluded_items.extend(
                [{'name': e, 'reason': '体检限制'} for e in (stage.excluded_items or [])]
            )
            node.excluded_count = (node.excluded_count or 0) + (stage.excluded_count or 0)
    return node


def _step_probability(result) -> AuditNode:
    """Step 5: 概率计算"""
    node = create_empty_step(5)
    node.formula = "P = 50 + 50×(1 - e^(-2×Δrank/pred_rank))"
    node.formula_params = {
        '模型': '指数衰减概率模型',
        '权重': '近3年加权（0.5/0.3/0.2），趋势钳制±30%',
    }
    node.data_sources = [
        {'name': '2023-2025年录取数据'},
    ]
    # Count total schools with probability results
    recs = getattr(result, 'recommendations', {}) or {}
    total = sum(len(v) for v in recs.values())
    node.input_count = total
    node.output_count = total
    # Get probability range from recommendations
    all_probs = []
    for cat in ['冲', '稳', '保', '垫']:
        for r in recs.get(cat, []):
            all_probs.append(getattr(r, 'probability', 0))
    if all_probs:
        avg_prob = sum(all_probs) / len(all_probs)
        node.output_summary = f"平均录取概率：{avg_prob:.1f}%（{total}个候选）"
    return node


def _step_interest_match(result) -> AuditNode:
    """Step 6: 兴趣匹配"""
    node = create_empty_step(6)
    personality = getattr(result, 'personality_result', None)
    if personality:
        holland = getattr(personality, 'holland', None)
        if holland:
            holland_code = getattr(holland, 'code', '') or ''
            dims = getattr(holland, 'dimensions', {}) or {}
            dim_str = ', '.join(f"{k}={v}" for k, v in dims.items())
            node.output_summary = f"RIASEC 风格代码：{holland_code}（{dim_str}）"
            node.detail_items = [
                {'dim': k, 'score': str(v)} for k, v in dims.items()
            ]
        bfi = getattr(personality, 'big_five', None)
        if bfi:
            bfi_dims = getattr(bfi, 'dimensions', {}) or {}
            for k, v in bfi_dims.items():
                node.detail_items.append({'dim': f"大五维度-{k}", 'score': str(v)})
    node.data_sources = [
        {'name': '项目自编 RIASEC 风格兴趣偏好问卷（未经心理测量验证）'},
        {'name': '项目自编大五维度问卷（未经心理测量验证）'},
        {'name': '项目自编学科自我评价问卷'},
    ]
    return node


def _step_sort_output(result) -> AuditNode:
    """Step 7: 排序输出"""
    node = create_empty_step(7)
    recs = getattr(result, 'recommendations', {}) or {}
    total = sum(len(v) for v in recs.values())
    node.input_count = total
    node.output_count = total

    breakdown = []
    for cat in ['冲', '稳', '保', '垫']:
        items = recs.get(cat, [])
        if items:
            breakdown.append(f"{cat}: {len(items)}所")
    node.output_summary = '、'.join(breakdown) if breakdown else '无推荐'

    # Detail items per category
    detail = []
    for cat in ['冲', '稳', '保', '垫']:
        for r in recs.get(cat, []):
            prob = getattr(r, 'probability', 0) or 0
            detail.append({
                'category': cat,
                'school': getattr(r, 'school_name', ''),
                'probability': f"{prob:.1f}%",
                'quality': getattr(r, 'school_quality', ''),
                'location': getattr(r, 'location', ''),
            })
    node.detail_items = detail[:30]
    node.data_sources = [{'name': '综合排序权重配置'}]
    return node


def audit_match(
    engine,
    questionnaire,
    big_five_answers: Dict[int, int] = None,
    holland_answers: Dict[int, str] = None,
    efficacy_answers: Dict[int, int] = None,
    career_values_answers: Dict[int, int] = None,
    top_n: int = 80,
) -> AuditResult:
    """
    审计包装器：执行匹配并同步构建审计追踪。

    用法：
        result = audit_match(engine, questionnaire, big_five=..., ...)
        print(result.audit_trail.to_json())
    """
    user_context = _build_user_context(questionnaire)

    # 执行匹配
    match_result = engine.match(
        questionnaire,
        big_five_answers=big_five_answers,
        holland_answers=holland_answers,
        efficacy_answers=efficacy_answers,
        career_values_answers=career_values_answers,
        top_n=top_n,
    )

    # 构建7步审计追踪
    steps = []
    steps.append(_step_rank_conversion(match_result, user_context))
    steps.append(_step_subject_filter(match_result))
    steps.append(_step_batch_filter(match_result))
    steps.append(_step_constraint_filter(match_result))
    steps.append(_step_probability(match_result))
    steps.append(_step_interest_match(match_result))
    steps.append(_step_sort_output(match_result))

    # 汇总
    recs = getattr(match_result, 'recommendations', {}) or {}
    total_final = sum(len(v) for v in recs.values())

    trail = AuditTrail(
        user_context=user_context,
        province='',
        generated_at=__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        steps=steps,
        total_initial=steps[0].output_count if steps else 0,
        total_final=total_final,
        total_excluded=sum(s.excluded_count for s in steps),
    )

    return AuditResult(
        match_result=match_result,
        audit_trail=trail,
    )
