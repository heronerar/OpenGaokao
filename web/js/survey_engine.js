/**
 * survey_engine.js — 10 步引导式问卷引擎
 * 职责：步骤导航、题目渲染、条件分支、自动保存、表单验证
 */
window.SurveyEngine = (function() {
  'use strict';

  const STORAGE_KEY = 'opengaokao_survey';
  const STEP_COUNT = 10;

  let currentStep = 0;
  let answers = {};          // { q_id: value }
  let multiAnswers = {};     // { q_id: Set(value) }

  // ── 自动保存 ──
  function save() {
    const data = { step: currentStep, answers: {}, multi: {} };
    for (const k in answers) data.answers[k] = answers[k];
    for (const k in multiAnswers) data.multi[k] = [...multiAnswers[k]];
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(data)); } catch(e) {}
  }

  function load() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return false;
      const data = JSON.parse(raw);
      currentStep = data.step || 0;
      answers = data.answers || {};
      for (const k in (data.multi || {})) multiAnswers[k] = new Set(data.multi[k]);
      return true;
    } catch(e) { return false; }
  }

  function clear() {
    localStorage.removeItem(STORAGE_KEY);
    answers = {};
    multiAnswers = {};
    currentStep = 0;
  }

  // ── 科类判断 ──
  function getCategory() {
    return answers['q14_category'] || '';
  }
  function isHistory() { return getCategory().includes('历史'); }

  // ── 条件过滤 ──
  function shouldShow(q) {
    if (!q.condition) return true;
    return q.condition(getCategory());
  }

  // ── 渲染里程碑 ──
  function renderMilestones() {
    const nav = document.getElementById('milestones');
    if (!nav) return;
    const labels = ['身份','健康','成绩','学科','家庭','志愿','策略','职业','评估','性格'];
    let html = '';
    for (let i = 0; i < STEP_COUNT; i++) {
      const cls = i < currentStep ? 'done' : (i === currentStep ? 'active' : '');
      html += `<div class="milestone ${cls}">
        <div class="milestone-dot">${i < currentStep ? '✓' : (i + 1)}</div>
        <div class="milestone-label">${labels[i]}</div>
      </div>`;
    }
    nav.innerHTML = html;
  }

  // ── 渲染步骤元信息 ──
  function renderStepMeta() {
    const el = document.getElementById('step-meta');
    if (!el) return;
    const step = window.SURVEY_STEPS[currentStep];
    if (!step) return;
    const countVisible = countVisibleQuestions(step);
    const mins = Math.max(1, Math.ceil(countVisible / 6));
    el.innerHTML = `
      <h2 class="step-meta-title">${step.icon} ${step.title}</h2>
      <p class="step-meta-desc">${step.desc}</p>
      <div class="step-meta-stats">
        <span>${countVisible} 题</span><span>约 ${mins} 分钟</span>
      </div>`;
  }

  function countVisibleQuestions(step) {
    let n = 0;
    for (const g of (step.groups || [])) {
      if (g.condition && !g.condition(getCategory())) continue;
      for (const q of (g.questions || [])) {
        if (shouldShow(q)) n++;
      }
    }
    return n;
  }

  // ── 渲染题目区 ──
  function renderQuestions() {
    const main = document.getElementById('survey-main');
    if (!main) return;
    const step = window.SURVEY_STEPS[currentStep];
    if (!step) { main.innerHTML = ''; return; }

    let html = '';
    for (const g of (step.groups || [])) {
      if (g.condition && !g.condition(getCategory())) continue;
      const visibleQs = g.questions.filter(shouldShow);
      if (visibleQs.length === 0) continue;

      html += `<div class="question-group">`;
      if (g.title) html += `<div class="question-group-title">${g.title}${g.sub ? '<span style="font-weight:400;color:var(--text-muted);margin-left:8px;font-size:12px">' + g.sub + '</span>' : ''}</div>`;
      for (const q of visibleQs) {
        html += renderOneQuestion(q);
      }
      html += `</div>`;
    }

    // ── 在最后一步追加霍兰德 76 题（动态从 API 加载） ──
    if (currentStep === STEP_COUNT - 1) {
      html += `<div class="question-group" id="holland-group">
        <div class="question-group-title">🧭 兴趣偏好（迫选） <span style="font-weight:400;color:var(--text-muted);margin-left:8px;font-size:12px">每组选你更喜欢的那个；点击即选中并跳到下一组</span></div>
        <div id="holland-list"><div style="padding:24px;text-align:center;color:var(--text-muted)">正在加载 76 道兴趣题目…</div></div>
      </div>`;
    }

    main.innerHTML = html;
    bindEvents();

    if (currentStep === STEP_COUNT - 1) {
      loadHollandQuestions();
    }
  }

  // ── 霍兰德 76 题动态加载 ──
  let _hollandCache = null;
  async function loadHollandQuestions() {
    const target = document.getElementById('holland-list');
    if (!target) return;
    try {
      if (!_hollandCache) {
        const resp = await fetch('/api/holland');
        const data = await resp.json();
        _hollandCache = data.items || [];
      }
      let html = '';
      _hollandCache.forEach((q, i) => {
        const valA = answers[q.id] === 'A' ? ' selected' : '';
        const valB = answers[q.id] === 'B' ? ' selected' : '';
        html += `<div class="question" data-qid="${q.id}">
          <span class="q-title">${i + 1}. 你更愿意：</span>
          <div class="holland-pair" data-qid="${q.id}">
            <div class="holland-card${valA}" data-value="A">${esc(q.a_text)}</div>
            <div class="holland-or">或</div>
            <div class="holland-card${valB}" data-value="B">${esc(q.b_text)}</div>
          </div>
          <div class="q-error" id="err-${q.id}"></div>
        </div>`;
      });
      target.innerHTML = html;
      bindHollandEvents();
    } catch (e) {
      target.innerHTML = `<div style="padding:16px;color:var(--warning);text-align:center">
        ⚠️ 兴趣题目加载失败（${e.message}），将跳过性格匹配模块。<br>
        <span style="font-size:12px;color:var(--text-muted)">不影响基础推荐，但兴趣维度的个性化将缺失。</span>
      </div>`;
    }
  }

  function bindHollandEvents() {
    document.querySelectorAll('.holland-pair').forEach(pair => {
      pair.querySelectorAll('.holland-card').forEach(card => {
        card.addEventListener('click', () => {
          const qid = pair.dataset.qid;
          const val = card.dataset.value;
          pair.querySelectorAll('.holland-card').forEach(c => c.classList.remove('selected'));
          card.classList.add('selected');
          answers[qid] = val;
          save();
          // 自动滚到下一题
          const next = card.closest('.question').nextElementSibling;
          if (next && next.classList.contains('question')) {
            next.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
        });
      });
    });
  }

  function renderOneQuestion(q) {
    const req = q.required ? ' required' : '';
    const val = answers[q.id] || '';
    const hint = q.hint ? `<span class="q-hint">${q.hint}</span>` : '';
    let inputHtml = '';

    switch (q.type) {
      case 'text':
        inputHtml = `<input class="q-input" type="text" id="${q.id}" value="${esc(val)}" placeholder="${q.ph || ''}">`;
        break;

      case 'number':
        inputHtml = `<input class="q-input" type="number" id="${q.id}" value="${esc(val)}" placeholder="${q.ph || ''}" inputmode="numeric">`;
        break;

      case 'big-number':
        inputHtml = `<input class="q-input big-number" type="number" id="${q.id}" value="${esc(val)}" placeholder="${q.ph || ''}" inputmode="numeric">`;
        break;

      case 'date':
        inputHtml = `<input class="q-input" type="date" id="${q.id}" value="${esc(val)}">`;
        break;

      case 'select':
        inputHtml = `<select class="q-input" id="${q.id}">
          <option value="">请选择</option>
          ${(q.optsInline || []).map(o => `<option value="${esc(o.v)}" ${val === o.v ? 'selected' : ''}>${esc(o.l)}</option>`).join('')}
        </select>`;
        break;

      case 'radio': {
        const grid = (q.opts || []).length <= 3 ? '' : ((q.opts || []).length <= 6 ? ' grid-2' : ' grid-3');
        inputHtml = `<div class="q-options${grid}" data-qid="${q.id}">
          ${(q.opts || []).map(o => {
            const sel = val === o.v ? ' selected' : '';
            return `<div class="q-option${sel}" data-value="${esc(o.v)}">
              <span class="q-option-check"></span><span>${esc(o.l)}</span>
            </div>`;
          }).join('')}
        </div>`;
        break;
      }

      case 'multi-select': {
        const selected = multiAnswers[q.id] || new Set();
        inputHtml = `<div class="q-options" data-qid="${q.id}" data-multi="1">
          ${(q.opts || []).map(o => {
            const sel = selected.has(o.v) ? ' selected' : '';
            return `<div class="q-option multi${sel}" data-value="${esc(o.v)}">
              <span class="q-option-check"></span><span>${esc(o.l)}</span>
            </div>`;
          }).join('')}
        </div>`;
        break;
      }

      case 'likert': {
        const selectedVal = answers[q.id] ? parseInt(answers[q.id]) : 0;
        inputHtml = `<div class="likert" data-qid="${q.id}">
          ${[1,2,3,4,5].map(n => {
            const sel = selectedVal === n ? ' selected' : '';
            return `<button type="button" class="likert-item${sel}" data-value="${n}">${n}</button>`;
          }).join('')}
        </div>
        <div class="likert-scale-labels"><span>非常不符合</span><span>非常符合</span></div>`;
        break;
      }

      default:
        inputHtml = `<input class="q-input" type="text" id="${q.id}" value="${esc(val)}">`;
    }

    return `<div class="question${req}" data-qid="${q.id}">
      <span class="q-title">${q.label}</span>${hint}
      ${inputHtml}
      <div class="q-error" id="err-${q.id}"></div>
    </div>`;
  }

  function esc(s) { return String(s || '').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

  // ── 事件绑定 ──
  function bindEvents() {
    // 单选
    document.querySelectorAll('.q-options:not([data-multi])').forEach(container => {
      container.querySelectorAll('.q-option').forEach(opt => {
        opt.addEventListener('click', () => {
          const qid = container.dataset.qid;
          const val = opt.dataset.value;
          container.querySelectorAll('.q-option').forEach(o => o.classList.remove('selected'));
          opt.classList.add('selected');
          answers[qid] = val;
          save();
          clearError(qid);
        });
      });
    });

    // 多选
    document.querySelectorAll('.q-options[data-multi="1"]').forEach(container => {
      container.querySelectorAll('.q-option').forEach(opt => {
        opt.addEventListener('click', () => {
          const qid = container.dataset.qid;
          const val = opt.dataset.value;
          if (!multiAnswers[qid]) multiAnswers[qid] = new Set();
          if (multiAnswers[qid].has(val)) {
            multiAnswers[qid].delete(val);
            opt.classList.remove('selected');
          } else {
            multiAnswers[qid].add(val);
            opt.classList.add('selected');
          }
          answers[qid] = [...multiAnswers[qid]];
          save();
          clearError(qid);
        });
      });
    });

    // Likert（点击即确认 + 自动滚到下一题）
    document.querySelectorAll('.likert').forEach(container => {
      container.querySelectorAll('.likert-item').forEach(btn => {
        btn.addEventListener('click', () => {
          const qid = container.dataset.qid;
          const val = btn.dataset.value;
          container.querySelectorAll('.likert-item').forEach(b => b.classList.remove('selected'));
          btn.classList.add('selected');
          answers[qid] = val;
          save();
          clearError(qid);
          // 自动滚到下一题
          const nextQ = btn.closest('.question').nextElementSibling;
          if (nextQ && nextQ.classList.contains('question')) {
            nextQ.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
        });
      });
    });

    // 文本/数字/日期输入
    document.querySelectorAll('.q-input').forEach(input => {
      input.addEventListener('input', () => {
        answers[input.id] = input.value;
        save();
        clearError(input.id);
      });
      input.addEventListener('change', () => {
        answers[input.id] = input.value;
        save();
      });
    });
  }

  // ── 验证 ──
  function validateCurrentStep() {
    const step = window.SURVEY_STEPS[currentStep];
    if (!step) return true;
    let valid = true;
    for (const g of (step.groups || [])) {
      if (g.condition && !g.condition(getCategory())) continue;
      for (const q of (g.questions || [])) {
        if (!shouldShow(q) || !q.required) continue;
        const val = answers[q.id];
        const empty = val === undefined || val === null || val === '' || (Array.isArray(val) && val.length === 0);
        if (empty) {
          showError(q.id, '此项为必填');
          valid = false;
        }
      }
    }
    return valid;
  }

  function showError(qid, msg) {
    const err = document.getElementById('err-' + qid);
    const q = document.querySelector(`.question[data-qid="${qid}"]`);
    if (err) err.textContent = msg;
    if (q) q.classList.add('has-error');
  }

  function clearError(qid) {
    const err = document.getElementById('err-' + qid);
    const q = document.querySelector(`.question[data-qid="${qid}"]`);
    if (err) err.textContent = '';
    if (q) q.classList.remove('has-error');
  }

  // ── 步骤导航 ──
  function goStep(n) {
    if (n < 0 || n >= STEP_COUNT) return;
    currentStep = n;
    save();
    render();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function next() {
    if (!validateCurrentStep()) {
      // 滚到第一个错误
      const firstErr = document.querySelector('.question.has-error');
      if (firstErr) firstErr.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return false;
    }
    if (currentStep < STEP_COUNT - 1) {
      goStep(currentStep + 1);
      return false;
    }
    // 最后一步 → 提交
    return true;
  }

  function prev() {
    if (currentStep > 0) goStep(currentStep - 1);
  }

  function render() {
    renderMilestones();
    renderStepMeta();
    renderQuestions();

    // 更新进度和按钮
    const prog = document.getElementById('step-progress');
    if (prog) prog.textContent = `第 ${currentStep + 1}/${STEP_COUNT} 步`;

    const btnPrev = document.getElementById('btn-prev');
    if (btnPrev) btnPrev.disabled = currentStep === 0;

    const btnNext = document.getElementById('btn-next');
    if (btnNext) btnNext.textContent = currentStep === STEP_COUNT - 1 ? '🎯 生成推荐' : '下一步 →';
  }

  // ── 收集全部数据（供 API 提交） ──
  function collectAll() {
    const data = {};
    for (const k in answers) {
      data[k] = answers[k];
    }
    // 展开多选
    for (const k in multiAnswers) {
      data[k] = [...multiAnswers[k]];
    }
    return data;
  }

  // ── 初始化 ──
  function init() {
    const restored = load();
    render();
    return restored;
  }

  return { init, next, prev, goStep, render, save, clear, collectAll, getCategory, currentStep: () => currentStep };
})();
