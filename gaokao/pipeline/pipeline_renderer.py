# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""
决策管道 HTML 渲染器 (Pipeline Renderer)
将 AuditTrail → 人类可读的 HTML 片段，用于 Web 前端和 PDF 报告。

设计原则:
- 零 JavaScript 也能看懂（基础版纯 HTML）
- 渐进增强（JS 可用于交互如折叠/展开）
- 每个步骤有独立的卡片模板
- 移动端友好（响应式布局）
"""
from typing import Dict, List, Optional
from .audit_trail import AuditTrail, AuditNode, PIPELINE_STEPS


def _esc(v: str) -> str:
    """HTML 安全转义"""
    import html
    if v is None:
        return ''
    return html.escape(str(v), quote=True)


def _fmt_num(n: int) -> str:
    """格式化数字（加千分位）"""
    if n is None:
        return '—'
    return f'{n:,}'


def _prob_color(prob: float) -> str:
    """概率 → CSS 颜色类"""
    if prob >= 85:
        return 'bao'
    elif prob >= 35:
        return 'wen'
    else:
        return 'chong'


def render_pipeline_overview(trail: AuditTrail) -> str:
    """渲染管道概览 — 7步横向流程条"""
    steps_html = []
    for step in trail.steps:
        delta = step.excluded_count
        delta_str = f'<span class="delta">-{delta}</span>' if delta > 0 else ''
        steps_html.append(f'''
        <div class="pipeline-step" data-step="{step.step_index}">
            <div class="step-icon">{step.step_icon}</div>
            <div class="step-name">{_esc(step.step_name)}</div>
            <div class="step-count">
                {_fmt_num(step.output_count)}{delta_str}
            </div>
            <a href="#step-{step.step_index}" class="step-link">查看详情</a>
        </div>
        ''')
        if step.step_index < len(trail.steps):
            steps_html.append('<div class="pipeline-arrow">→</div>')

    return f'''
    <div class="pipeline-overview">
        <div class="pipeline-title">📐 你的推荐是如何生成的</div>
        <div class="pipeline-flow">
            {''.join(steps_html)}
        </div>
        <div class="pipeline-summary">
            初始候选 <strong>{_fmt_num(trail.total_initial)}</strong> 个 →
            最终推荐 <strong>{_fmt_num(trail.total_final)}</strong> 个
            （共排除 {_fmt_num(trail.total_excluded)} 个）
        </div>
    </div>
    '''


def render_step_card(step: AuditNode) -> str:
    """渲染单个步骤的详细卡片"""
    # 数据来源
    sources_html = ''
    if step.data_sources:
        items = []
        for src in step.data_sources:
            year_tag = f' <span class="tag">{_esc(src.get("year", ""))}</span>' if src.get('year') else ''
            items.append(f'<li>{_esc(src["name"])}{year_tag}</li>')
        sources_html = f'''
        <div class="step-sources">
            <strong>📋 数据来源：</strong>
            <ul>{''.join(items)}</ul>
        </div>'''

    # 公式
    formula_html = ''
    if step.formula:
        params_html = ''
        for k, v in step.formula_params.items():
            params_html += f'<li><code>{_esc(k)}</code> = {_esc(str(v))}</li>'
        formula_html = f'''
        <div class="step-formula">
            <strong>⚙️ 计算公式：</strong>
            <div class="formula-box"><code>{_esc(step.formula)}</code></div>
            <ul class="formula-params">{params_html}</ul>
        </div>'''

    # 详细数据表
    detail_html = ''
    if step.detail_items and len(step.detail_items) > 0:
        # 取第一个 item 的 keys 做表头
        headers = list(step.detail_items[0].keys())
        rows_html = []
        for row in step.detail_items[:20]:  # 最多20行
            cells = ''.join(f'<td>{_esc(str(row.get(h, "")))}</td>' for h in headers)
            rows_html.append(f'<tr>{cells}</tr>')
        detail_html = f'''
        <div class="step-detail-table">
            <table>
                <thead><tr>{"".join(f"<th>{_esc(h)}</th>" for h in headers)}</tr></thead>
                <tbody>{"".join(rows_html)}</tbody>
            </table>
        </div>'''

    # 排除项
    excluded_html = ''
    if step.excluded_items:
        items = []
        for ex in step.excluded_items[:10]:
            sev_class = ex.get('severity', 'info')
            items.append(
                f'<li class="excluded-{sev_class}">'
                f'<strong>{_esc(ex["name"])}</strong>: {_esc(ex["reason"])}'
                f'</li>'
            )
        excluded_html = f'''
        <div class="step-excluded">
            <strong>❌ 本轮排除 {step.excluded_count} 个：</strong>
            <ul>{''.join(items)}</ul>
            {f'<p class="more">...还有 {step.excluded_count - 10} 个</p>' if step.excluded_count > 10 else ''}
        </div>'''

    return f'''
    <div class="step-card" id="step-{step.step_index}">
        <div class="step-header">
            <span class="step-badge">{step.step_icon}</span>
            <h3>第{step.step_index}步：{_esc(step.step_name)}</h3>
            <span class="step-stats">
                输入 {step.input_count} 个 → 输出 {step.output_count} 个
                {f'（排除 {step.excluded_count} 个）' if step.excluded_count > 0 else ''}
            </span>
        </div>
        <div class="step-body">
            <p class="step-summary">{_esc(step.input_summary)}</p>
            {formula_html}
            {sources_html}
            {detail_html}
            {excluded_html}
        </div>
    </div>
    '''


def render_audit_trail(trail: AuditTrail) -> str:
    """渲染完整的审计追踪页面"""
    overview = render_pipeline_overview(trail)
    step_cards = ''.join(render_step_card(s) for s in trail.steps)

    return f'''
    <div class="audit-trail">
        {overview}
        <div class="step-cards">
            {step_cards}
        </div>
        <div class="audit-footer">
            <p>⏰ 生成时间：{_esc(trail.generated_at)}</p>
            <p>🔗 <a href="https://github.com/heronerar/OpenGaokao">查看完整算法源码</a></p>
            <p class="disclaimer">
                ⚠️ 免责声明：以上概率仅基于历史数据统计估算，不构成录取承诺。
                请结合当年招生计划和政策变化综合判断。
            </p>
        </div>
    </div>
    '''


def render_recommendation_card(school_rec) -> str:
    """
    渲染单个推荐卡片（五层可解释性）

    school_rec 是 SchoolRecommendation dataclass（从 matching_engine 来）
    """
    prob = getattr(school_rec, 'probability', 0) or 0
    color_class = _prob_color(prob)
    category = getattr(school_rec, 'category', '') or ''
    confidence = getattr(school_rec, 'confidence', '') or ''

    # 推荐专业列表
    majors = getattr(school_rec, 'recommended_majors', []) or []
    majors_html = ''
    if majors:
        items = []
        for m in majors[:5]:
            name = getattr(m, 'major_name', '') if hasattr(m, 'major_name') else str(m)
            score = getattr(m, 'score', 0) if hasattr(m, 'score') else 0
            reason = getattr(m, 'reason', '') if hasattr(m, 'reason') else ''
            items.append(
                f'<li><strong>{_esc(name)}</strong> '
                f'<span class="major-score">匹配度 {score:.0f}</span>'
                f'<span class="major-reason">{_esc(reason)}</span></li>'
            )
        majors_html = f'<ul class="recommended-majors">{''.join(items)}</ul>'

    # 理由
    reasons = getattr(school_rec, 'reasons', []) or []
    reasons_html = ''.join(f'<li>{_esc(r)}</li>' for r in reasons[:5])

    # 替代方案
    alts = getattr(school_rec, 'similar_alternatives', []) or []
    alts_html = ''
    if alts:
        alts_html = (
            f'<p class="alternatives">💡 替代方案：{_esc(", ".join(alts[:3]))}</p>'
        )

    return f'''
    <div class="recommendation-card {color_class}">
        <div class="card-header">
            <span class="category-badge {color_class}">
                {_esc(category)}
            </span>
            <h3>{_esc(school_rec.school_name)}</h3>
            <span class="probability {color_class}">{prob:.1f}%</span>
        </div>
        <div class="card-body">
            <div class="info-row">
                <span>📍 {_esc(school_rec.location or '—')}</span>
                <span>🏫 {_esc(school_rec.school_quality or '—')}</span>
                <span>💰 学费：{_fmt_num(getattr(school_rec, 'tuition', 0))}元/年</span>
                <span>📊 数据置信度：{_esc(confidence)}</span>
            </div>
            {majors_html}
            <div class="reasons">
                <strong>推荐理由：</strong>
                <ul>{reasons_html}</ul>
            </div>
            {alts_html}
        </div>
    </div>
    '''
