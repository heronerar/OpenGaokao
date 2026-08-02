# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""风险评估引擎 — 量化滑档/退档/高分低就风险"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class RiskAssessment:
    """风险评估结果"""
    slip_risk: str              # 滑档风险: low/medium/high
    slip_probability: float     # 滑档概率 0-1
    slip_detail: str            # 详细说明

    waste_risk: str             # 高分低就风险: low/medium/high
    waste_rank_diff: int        # 浪费位次
    waste_detail: str

    reject_risk: str            # 退档风险: low/medium/high
    reject_reasons: List[str]   # 退档原因列表
    reject_detail: str

    overall_risk: str           # 综合风险: low/medium/high
    recommendations: List[str]  # 风险缓解建议
    checklist: List[str] = field(default_factory=list)


def assess_risks(
    recommendations: Dict[str, List],
    user_rank: int,
    subject_type: str = '',
    has_medical_restriction: bool = False,
    accepts_adjustment: bool = True,
) -> RiskAssessment:
    """
    全面评估志愿组合风险

    Args:
        recommendations: 冲/稳/保/垫 推荐列表 (SchoolRecommendation objects)
        user_rank: 考生位次
        subject_type: 科类
        has_medical_restriction: 是否有体检限制
        accepts_adjustment: 是否服从调剂
    """
    bao_list = recommendations.get('保', [])
    chong_list = recommendations.get('冲', [])
    wen_list = recommendations.get('稳', [])
    dian_list = recommendations.get('垫', [])

    all_bao = list(bao_list) + list(dian_list)

    # ── 1. 滑档风险评估 ──
    slip_risk, slip_prob, slip_detail = _assess_slip_risk(
        all_bao, chong_list, user_rank
    )

    # ── 2. 高分低就风险评估 ──
    waste_risk, waste_diff, waste_detail = _assess_waste_risk(
        bao_list, wen_list, user_rank
    )

    # ── 3. 退档风险评估 ──
    reject_risk, reject_reasons, reject_detail = _assess_reject_risk(
        chong_list, has_medical_restriction, accepts_adjustment, subject_type
    )

    # ── 4. 综合风险 ──
    risk_levels = {'low': 1, 'medium': 2, 'high': 3}
    overall_score = max(
        risk_levels.get(slip_risk, 1),
        risk_levels.get(waste_risk, 1),
        risk_levels.get(reject_risk, 1),
    )
    overall = 'low' if overall_score == 1 else ('medium' if overall_score == 2 else 'high')

    # 风险缓解建议
    recs = _generate_recommendations(
        slip_risk, waste_risk, reject_risk, all_bao, user_rank
    )

    # 决策检查清单
    checklist = _generate_checklist(
        slip_risk, waste_risk, reject_risk, recommendations, accepts_adjustment
    )

    return RiskAssessment(
        slip_risk=slip_risk,
        slip_probability=slip_prob,
        slip_detail=slip_detail,
        waste_risk=waste_risk,
        waste_rank_diff=waste_diff,
        waste_detail=waste_detail,
        reject_risk=reject_risk,
        reject_reasons=reject_reasons,
        reject_detail=reject_detail,
        overall_risk=overall,
        recommendations=recs,
        checklist=checklist,
    )


def _assess_slip_risk(bao_list, chong_list, user_rank):
    """滑档风险评估：保底志愿的安全性"""
    if not bao_list:
        return 'high', 0.25, '⚠️ 无保底志愿，滑档风险极高。建议务必添加 ≥2 所录取概率 >85% 的院校作为保底。'

    # 统计保底概率
    bao_probs = [getattr(r, 'probability', 0) or 0 for r in bao_list]
    safe_bao = [p for p in bao_probs if p >= 90]
    risky_bao = [p for p in bao_probs if p < 85]

    safe_margin = max(bao_probs) if bao_probs else 0
    risky_count = len(risky_bao)

    if len(safe_bao) >= 3 and safe_margin >= 95:
        return ('low', 0.02,
            f'保底志愿充足（{len(safe_bao)}所概率≥90%），最大安全边际 {safe_margin:.0f}%，滑档风险低。')
    elif len(safe_bao) >= 1:
        return ('medium', 0.08,
            f'保底志愿有兜底（{len(safe_bao)}所概率≥90%），但数量偏少。建议再增加 1-2 所更深度的保底院校。')
    elif risky_count > 0:
        return ('medium', 0.15,
            f'保底志愿概率偏低（{risky_count}所 <85%），未能达到标准保底≥85%的门槛。建议替换为更深度的院校。')
    else:
        return ('high', 0.20,
            '保底志愿严重不足，存在较大滑档风险。强烈建议扩充保底志愿，目标录取概率 ≥90%。')


def _assess_waste_risk(bao_list, wen_list, user_rank):
    """高分低就风险评估：是否浪费了太多位次"""
    if not bao_list:
        return 'low', 0, '无保底志愿，无法评估高分低就。'

    # 计算保底的平均预测位次
    bao_ranks = [getattr(r, 'predicted_rank', 0) or 0 for r in bao_list]
    if not bao_ranks or max(bao_ranks) == 0:
        return 'low', 0, '无足够位次数据。'

    avg_bao_rank = sum(bao_ranks) / len(bao_ranks)
    rank_diff = avg_bao_rank - user_rank

    if rank_diff < 5000:
        return ('low', max(0, int(rank_diff)),
            f'保底院校平均位次与你的位次差距仅 {int(rank_diff)} 名，分数利用较充分。')
    elif rank_diff < 20000:
        return ('medium', int(rank_diff),
            f'保底院校平均位次高出你的位次 {int(rank_diff)} 名，可能存在一定浪费。'
            f'可考虑替换部分保底为更匹配的院校。')
    else:
        return ('high', int(rank_diff),
            f'保底院校平均位次高出你的位次 {int(rank_diff)} 名，高分低就风险较高。'
            f'强烈建议调整保底志愿，选择录取位次更接近你实际位次的院校。')


def _assess_reject_risk(chong_list, has_medical, accepts_adjust, subject_type):
    """退档风险评估"""
    reasons = []

    if not accepts_adjust:
        reasons.append(
            '不服从专业调剂。投档后若所填专业分数不够又不服从调剂，将被直接退档，'
            '本批次后续志愿不再检索。'
        )

    if has_medical:
        reasons.append(
            '存在体检限制。部分专业可能因色觉/视力/身高不达标而被退档。'
        )

    if chong_list and not accepts_adjust:
        return ('high', reasons,
            f'⛔ 退档风险高：冲档志愿共{len(chong_list)}所，且不服从调剂。'
            f'一旦投档失败，本批次全部志愿作废。强烈建议勾选服从调剂。')
    elif reasons:
        return ('medium', reasons,
            f'存在 {len(reasons)} 项退档风险因素。录取后请密切关注学校通知。')
    else:
        return ('low', [],
            '已服从调剂，且无体检/政审等限制条件，退档风险较低。')


def _generate_recommendations(slip, waste, reject, bao_list, user_rank):
    """生成风险缓解建议"""
    recs = []
    if slip == 'high':
        recs.append('🔴 紧急：增加 ≥2 所录取概率 >90% 的保底院校')
        recs.append('🔴 检查保底志愿是否满足"录取概率 ≥85%"的标准')
    if waste == 'high':
        recs.append('🟡 建议：将部分保底院校替换为录取位次更接近你实际位次的选择')
    if reject == 'high':
        recs.append('🔴 紧急：建议所有冲档和稳档志愿勾选"服从专业调剂"')
    if not bao_list:
        recs.append('🔴 紧急：立刻添加保底志愿！')
    return recs


def _generate_checklist(slip, waste, reject, recs, accepts_adjust):
    """生成决策检查清单"""
    checklist = []
    total = sum(len(v) for v in recs.values())

    checklist.append(f'□ 志愿总数 ≥ 15 个？当前：{total} 个')
    checklist.append(f'□ 保底志愿 ≥ 3 个且录取概率均 ≥85%？')
    checklist.append(f'□ 冲档志愿是否勾选服从调剂？{"✅ 是" if accepts_adjust else "❌ 否"}')
    checklist.append(f'□ 所有志愿的体检/选科要求已核对？')
    checklist.append(f'□ 学费预算是否覆盖所有志愿？')
    checklist.append(f'□ 中外合作/分校/独立学院是否已识别？')
    checklist.append(f'□ 最终确认前是否与家人达成共识？')

    if slip == 'high':
        checklist.insert(0, '⚠️ 滑档高风险 — 请优先完成上述保底志愿检查后再提交')
    if reject == 'high':
        checklist.insert(0, '⚠️ 退档高风险 — 请仔细核对每所冲档院校的调剂政策')

    return checklist
