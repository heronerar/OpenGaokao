/**
 * result_view.js — 推荐结果三 tab 视图
 * 优先使用 API 返回数据，API 不可用时回退 mock
 */
window.ResultView = (function() {
  'use strict';

  let lastResult = null;

  function render(apiResult) {
    // OG-F-28: 只渲染来自 /api/recommend 的真实响应；不存在则显示明确错误，
    // 绝不用虚构/示例数据冒充真实推荐（已删除前端 mock 兜底）。
    if (!apiResult) {
      renderUnavailable();
      return;
    }
    lastResult = apiResult;
    // OG-F-29: 若后端回退到示例库，持久横幅提示（非一闪即逝的 toast）
    renderDataSourceBanner(apiResult.data_source);
    renderRecommendations(apiResult);
    renderPipeline(apiResult);
    renderRisk(apiResult);
    renderAnalysis(apiResult);
  }

  function renderUnavailable() {
    const el = document.getElementById('tab-recommendations');
    if (el) {
      el.innerHTML = `<div style="padding:40px 20px;text-align:center;color:var(--text-muted)">
        <div style="font-size:40px">⚠️</div>
        <p style="margin-top:12px;font-size:16px;color:var(--text)">推荐服务暂时不可用</p>
        <p style="margin-top:6px">未能获取真实志愿方案。请稍后重试。</p>
        <p style="margin-top:6px;font-size:13px">本系统不会用示例或虚构数据冒充推荐。</p>
      </div>`;
    }
  }

  // OG-F-29: 数据来源横幅（示例库时持久红色提示）
  function renderDataSourceBanner(dataSource) {
    const host = document.getElementById('app-result');
    if (!host) return;
    let banner = document.getElementById('data-source-banner');
    if (dataSource === 'example') {
      if (!banner) {
        banner = document.createElement('div');
        banner.id = 'data-source-banner';
        banner.style.cssText = 'background:#c0392b;color:#fff;padding:10px 16px;'
          + 'font-size:14px;text-align:center;font-weight:600';
        host.insertBefore(banner, host.firstChild);
      }
      banner.textContent = '⚠️ 演示数据：当前结果基于内置示例库（example.db），非真实录取数据，不可用于实际填报。';
    } else if (banner) {
      banner.remove();
    }
  }

  function renderRecommendations(r) {
    const el = document.getElementById('tab-recommendations');
    if (!el) return;
    const sum = r.summary;
    let html = `<div class="summary-bar">
      <div class="summary-cell chong"><div class="summary-cell-label">冲</div><div class="summary-cell-count">${sum.chong}</div></div>
      <div class="summary-cell wen"><div class="summary-cell-label">稳</div><div class="summary-cell-count">${sum.wen}</div></div>
      <div class="summary-cell bao"><div class="summary-cell-label">保</div><div class="summary-cell-count">${sum.bao}</div></div>
      <div class="summary-cell dian"><div class="summary-cell-label">垫</div><div class="summary-cell-count">${sum.dian}</div></div>
    </div>`;

    const tiers = ['冲','稳','保','垫'];
    for (const t of tiers) {
      const cls = t === '冲' ? 'chong' : (t === '稳' ? 'wen' : (t === '保' ? 'bao' : 'dian'));
      const items = r.schools.filter(s => s.tier === t);
      if (!items.length) continue;
      html += `<div class="tier-group">
        <div class="tier-header ${cls}"><span class="tier-tag">${t}</span><span>${t}档推荐（${items.length}）</span></div>`;
      items.forEach((s, i) => html += renderSchool(s, cls, i));
      html += `</div>`;
    }
    el.innerHTML = html;
    bindExpand();
  }

  function renderSchool(s, cls, i) {
    return `<div class="rec-card ${cls}" data-i="${cls}-${i}">
      <div class="rec-card-head">
        <div class="rec-name">${esc(s.name)}</div>
        <div class="rec-prob ${cls}">${s.prob}%</div>
      </div>
      <div class="rec-meta">
        <span>📍 ${esc(s.loc)}</span>
        <span>🏫 ${esc(s.tier_label)}</span>
        <span>💰 ${s.tuition} 元/年</span>
      </div>
      <div class="rec-checks">
        ${(s.checks || []).map(c => `<span class="rec-check-badge ${c.ok ? '' : 'warn'}">${c.ok ? '✓' : '⚠'} ${esc(c.t)}</span>`).join('')}
      </div>
      <button type="button" class="rec-expand" data-target="${cls}-${i}">🔍 为什么推荐这所？ ↓</button>
      <div class="rec-detail hidden" id="detail-${cls}-${i}">
        <strong>推荐专业：</strong>
        <ul style="margin:6px 0 12px 18px">
          ${(s.majors || []).map(m => `<li><strong>${esc(m.n)}</strong> · 匹配分 ${m.score} · <span style="color:var(--text-muted)">${esc(m.r)}</span></li>`).join('')}
        </ul>
        <strong>概率说明：</strong>${s.prob}% 来自 2023-2025 年录取位次加权。预测位次基于过去 3 年最低录取位次趋势。
      </div>
    </div>`;
  }

  function bindExpand() {
    document.querySelectorAll('.rec-expand').forEach(btn => {
      btn.addEventListener('click', () => {
        const target = btn.dataset.target;
        const el = document.getElementById('detail-' + target);
        if (el) {
          el.classList.toggle('hidden');
          btn.textContent = el.classList.contains('hidden')
            ? '🔍 为什么推荐这所？ ↓'
            : '🔼 收起详情';
        }
      });
    });
  }

  function renderPipeline(r) {
    const el = document.getElementById('tab-pipeline');
    if (!el) return;
    let html = `<div style="margin-bottom:16px;padding:12px 16px;background:var(--primary-soft);border-radius:var(--radius-lg);color:var(--primary);font-size:14px;">
      📐 你的推荐是这样产生的：每一步都经过严格筛选和计算，可以追溯到具体数据源。
    </div>`;
    r.pipeline.forEach((step, i) => {
      const delta = step.exc > 0 ? `<span class="pipeline-step-delta">−${step.exc}</span>` : '';
      const inputStr = step.input > 1 ? `${step.input} → ` : '';
      html += `<div class="pipeline-step">
        <div class="pipeline-step-head">
          <span class="pipeline-step-icon">${step.icon}</span>
          <span class="pipeline-step-name">${i + 1}. ${esc(step.name)}</span>
          <span class="pipeline-step-stat">${inputStr}${step.output} ${delta}</span>
        </div>
        <div class="pipeline-step-body">
          ${esc(step.detail)}
          ${step.formula ? `<br><code style="font-size:11px;color:var(--text-muted);background:var(--surface);padding:2px 6px;border-radius:4px;margin-top:4px;display:inline-block">${esc(step.formula)}</code>` : ''}
          <br><span style="color:var(--text-muted);font-size:12px;">📋 数据源：${esc(step.src)}</span>
        </div>`;
      // 排除项详情
      if (step.excluded_items && step.excluded_items.length) {
        html += `<details class="pipeline-excluded" style="margin:4px 0 0 48px;font-size:12px;color:var(--text-muted)">
          <summary style="cursor:pointer;color:var(--warning)">查看 ${step.excluded_items.length} 个被排除的专业 👁️</summary>
          <ul style="margin:4px 0 0 16px">${step.excluded_items.map(item => `<li>${esc(typeof item === 'string' ? item : (item.name || item))}</li>`).join('')}</ul>
        </details>`;
      }
      html += `</div>`;
    });
    el.innerHTML = html;
  }

  function renderRisk(r) {
    const el = document.getElementById('tab-risk');
    if (!el) return;
    let html = '';
    r.risks.forEach(risk => {
      const emoji = risk.level === 'low' ? '🟢' : (risk.level === 'medium' ? '🟡' : '🔴');
      let metaHtml = '';
      if (risk.probability !== undefined) {
        metaHtml += `<span class="risk-meta-stat">📊 概率 ${risk.probability}%</span>`;
      }
      if (risk.wasted_rank !== undefined && risk.wasted_rank > 0) {
        metaHtml += `<span class="risk-meta-stat">📉 浪费位次 ${risk.wasted_rank.toLocaleString()}</span>`;
      }
      html += `<div class="risk-card ${risk.level}">
        <h4>${emoji} ${esc(risk.title)}${metaHtml ? `<div class="risk-meta">${metaHtml}</div>` : ''}</h4>
        <p>${esc(risk.body)}</p>`;
      if (risk.reasons && risk.reasons.length) {
        html += `<ul style="margin:4px 0 0 16px;font-size:13px">${risk.reasons.map(r => `<li>${esc(r)}</li>`).join('')}</ul>`;
      }
      html += `</div>`;
    });
    html += `<div class="checklist">
      <h4>📝 提交志愿前的最后检查</h4>
      ${r.checklist.map(item => `<div class="checklist-item">○ ${esc(item)}</div>`).join('')}
    </div>`;
    el.innerHTML = html;
  }

  function esc(s) { return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

  function switchTab(name) {
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'tab-' + name));
  }

  // ── 深度分析报告渲染 ──
  function renderAnalysis(r) {
    const el = document.getElementById('tab-analysis');
    if (!el) return;
    const a = r.analysis;
    if (!a) {
      el.innerHTML = `<div style="text-align:center;padding:48px 16px;color:var(--text-muted)">📋 分析报告未生成。<br>请确认后端已启动且问卷数据完整。</div>`;
      return;
    }

    let html = '';

    // ── 画像总览 ──
    html += `<div class="analysis-hero">
      <div class="analysis-hero-title">${esc(a.profileLabel)}</div>
      <div class="analysis-hero-sub">六维综合画像</div>
      <div class="analysis-radar-chart">
        ${(a.radar || []).map(d => `
          <div class="analysis-radar-bar">
            <div class="analysis-radar-label">${esc(d.name)}</div>
            <div class="analysis-radar-track"><div class="analysis-radar-fill" style="width:${d.score}%;background:${radarColor(d.score)}"></div></div>
            <div class="analysis-radar-val">${d.score} · ${esc(d.label)}</div>
          </div>
        `).join('')}
      </div>
    </div>`;

    // ── 各章节 ──
    (a.sections || []).forEach(sec => {
      html += `<div class="analysis-section">
        <div class="analysis-section-title">${sec.icon} ${esc(sec.title)}</div>
        <div class="analysis-section-summary">${esc(sec.summary)}</div>`;

      // 章节雷达
      if (sec.radar && sec.radar.length) {
        html += `<div class="analysis-radar-chart" style="margin-bottom:12px">`;
        sec.radar.forEach(d => {
          html += `<div class="analysis-radar-bar">
            <div class="analysis-radar-label">${esc(d.name)}</div>
            <div class="analysis-radar-track"><div class="analysis-radar-fill" style="width:${Math.max(d.score, 5)}%;background:${radarColor(d.score)}"></div></div>
            <div class="analysis-radar-val">${d.score} · ${esc(d.label)}</div>
          </div>`;
        });
        html += `</div>`;
      }

      // 详细条目
      (sec.items || []).forEach(item => {
        html += `<div class="analysis-item">
          <div class="analysis-item-head">
            <span class="analysis-item-dim">${esc(item.dimension)}</span>
            <span class="analysis-item-level">${esc(item.level)}</span>
          </div>
          <div class="analysis-item-desc">${esc(item.interpretation || item.detail || '')}</div>
        </div>`;
      });

      // 张力对
      (sec.tensions || []).forEach(t => {
        html += `<div class="analysis-tension">
          <span>⚡ 价值观张力：</span>${esc(t.text)}
        </div>`;
      });

      // 警告
      (sec.warnings || []).forEach(w => {
        html += `<div class="analysis-warn">${esc(w)}</div>`;
      });

      html += `</div>`;
    });

    // ── 综合建议清单 ──
    if (a.checklist && a.checklist.length) {
      html += `<div class="analysis-section" style="border-left:4px solid var(--success)">
        <div class="analysis-section-title">📝 综合建议清单</div>
        ${a.checklist.map(c => `<div class="checklist-item">○ ${esc(c)}</div>`).join('')}
      </div>`;
    }

    el.innerHTML = html;
  }

  function radarColor(score) {
    if (score >= 70) return 'var(--success)';
    if (score >= 40) return 'var(--primary)';
    return 'var(--warning)';
  }

  return { render, switchTab };
})();
