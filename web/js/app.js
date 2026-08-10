/**
 * app.js — OpenGaokao 前端入口
 * 连接 survey_engine（问卷模式）与 result_view（结果模式）
 * LicenseRef-OpenGaokao-SAL-1.0
 */
(function() {
  'use strict';

  // ── 等待 DOM 就绪 ──
  document.addEventListener('DOMContentLoaded', init);

  function init() {
    const appSurvey = document.getElementById('app-survey');
    const appResult = document.getElementById('app-result');
    const loading = document.getElementById('loading');

    // SAL 源码提示：另行获准部署时由 OPENGAOKAO_SOURCE_URL 指向对应源码位置。
    fetch('/api/health', { cache: 'no-store' })
      .then(resp => resp.ok ? resp.json() : null)
      .then(health => {
        if (!health || !health.source_url) return;
        document.querySelectorAll('[data-source-code]').forEach(link => {
          link.href = health.source_url;
        });
      })
      .catch(() => {});

    // ── 按钮绑定 ──
    document.getElementById('btn-prev').addEventListener('click', () => SurveyEngine.prev());
    document.getElementById('btn-next').addEventListener('click', handleNext);
    document.getElementById('btn-restart').addEventListener('click', handleRestart);
    document.getElementById('btn-pause').addEventListener('click', handlePause);
    document.getElementById('btn-reset').addEventListener('click', handleReset);
    document.getElementById('btn-export-html').addEventListener('click', () => handleExport('html'));
    document.getElementById('btn-export-excel').addEventListener('click', () => handleExport('excel'));

    // Tab 切换
    document.querySelectorAll('.tab').forEach(tab => {
      tab.addEventListener('click', () => {
        ResultView.switchTab(tab.dataset.tab);
      });
    });

    // ── 键盘快捷键 ──
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const target = e.target;
        // 文本/数字输入框按 Enter 触发下一步
        if (target.matches('.q-input:not(select)') && !target.matches('.big-number')) return;
        if (target.matches('select') || target.matches('.big-number')) return;
        // 在 Likert 或 radio 上按 Enter = 下一步
        if (!appSurvey.classList.contains('hidden')) {
          handleNext();
        }
      }
    });

    // ── 启动问卷引擎 ──
    const restored = SurveyEngine.init();
    if (restored) {
      showToast('↻ 已恢复上次的填写进度');
    }

    // ── 帮助函数 ──

    function handleNext() {
      if (!SurveyEngine.next()) return;  // 未通过验证或还在中间步骤
      // 最后一步：提交
      submitSurvey();
    }

    async function submitSurvey() {
      const data = SurveyEngine.collectAll();
      const category = SurveyEngine.getCategory();

      // 显示加载遮罩
      appSurvey.classList.add('hidden');
      loading.classList.remove('hidden');

      try {
        // ── 调用后端 API ──
        let result = null;
        try {
          const resp = await fetch('/api/recommend', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ answers: data, category, top_n: 30 }),
          });
          if (resp.ok) {
            result = await resp.json();
            if (result.error) {
              console.warn('API 返回错误:', result.error);
              showToast('⚠️ 推荐服务出错，请稍后重试');
              result = null;
            }
          } else {
            console.warn('API 状态码:', resp.status);
            showToast('⚠️ 后端未就绪，请稍后重试');
            result = null;
          }
        } catch (e) {
          console.warn('API 不可用:', e.message);
          showToast('⚠️ 后端未启动，无法生成推荐');
          result = null;
        }

        // ── 切换到结果视图 ──
        loading.classList.add('hidden');
        // OG-F-28: API 失败时绝不渲染虚构/示例推荐冒充真实方案
        if (!result) {
          appSurvey.classList.remove('hidden');
          alert('推荐服务暂时不可用，未能生成真实志愿方案。\n请稍后重试 —— 系统不会用示例或虚构数据冒充推荐。');
          return;
        }
        ResultView.render(result);
        switchMode('result');
      } catch (e) {
        loading.classList.add('hidden');
        appSurvey.classList.remove('hidden');
        alert('提交失败：' + e.message);
      }
    }

    function handleRestart() {
      if (!confirm('重新填写将清空当前推荐结果，确定？')) return;
      SurveyEngine.clear();
      switchMode('survey');
      SurveyEngine.init();
    }

    function handlePause() {
      SurveyEngine.save();
      showToast('💾 进度已保存，关闭浏览器后回来仍可使用');
    }

    function handleReset() {
      if (!confirm('确定要清除所有作答数据？不可恢复。')) return;
      SurveyEngine.clear();
      SurveyEngine.init();
      showToast('已重置');
    }

    function switchMode(mode) {
      if (mode === 'survey') {
        appSurvey.classList.remove('hidden');
        appResult.classList.add('hidden');
      } else {
        appSurvey.classList.add('hidden');
        appResult.classList.remove('hidden');
      }
    }

    async function handleExport(fmt) {
      const data = SurveyEngine.collectAll();
      const category = SurveyEngine.getCategory();
      const btn = document.getElementById('btn-export-' + fmt);
      const origText = btn.textContent;
      btn.textContent = '⏳ 生成中...';
      btn.disabled = true;
      try {
        const resp = await fetch('/api/export', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ answers: data, category, format: fmt }),
        });
        if (!resp.ok) {
          const err = await resp.json();
          showToast('❌ 导出失败: ' + (err.error || resp.status));
          return;
        }
        const result = await resp.json();
        // 触发浏览器下载
        const filePath = result.files?.[fmt];
        if (filePath) {
          const fileName = filePath.split('/').pop().split('\\').pop();
          window.open('/api/download?path=' + encodeURIComponent(filePath) + '&name=' + encodeURIComponent(fileName), '_blank');
          showToast('✅ ' + fmt.toUpperCase() + ' 报告已生成');
        }
      } catch (e) {
        showToast('❌ 导出失败: ' + e.message);
      } finally {
        btn.textContent = origText;
        btn.disabled = false;
      }
    }

    let toastTimer;

    function showToast(msg) {
      let el = document.getElementById('toast');
      if (!el) {
        el = document.createElement('div');
        el.id = 'toast';
        el.style.cssText = `
          position: fixed; bottom: 80px; left: 50%; transform: translateX(-50%);
          background: var(--text); color: #fff; padding: 10px 20px;
          border-radius: 999px; font-size: 14px; z-index: 999;
          transition: opacity .3s; opacity: 0; pointer-events: none;
          max-width: 90%; white-space: nowrap;
        `;
        document.body.appendChild(el);
      }
      el.textContent = msg;
      el.style.opacity = '1';
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => { el.style.opacity = '0'; }, 2500);
    }
  }
})();
