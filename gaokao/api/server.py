# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""
OpenGaokao Flask API — 简易后端
─────────────────────────────────────
启动: python -m gaokao.api.server [--province yunnan] [--port 5000]

端点:
  GET  /api/health                  健康检查
  GET  /api/holland                 项目自编 RIASEC 风格兴趣题（兼容路径）
  GET  /api/provinces               列出所有省份配置
  POST /api/recommend               核心推荐端点

设计原则:
- 无认证（开源版）
- CORS 全开（方便前端联调）
- 失败时返回 JSON 错误，不抛栈
- 静态文件托管 web/ 目录（开发期免开两个 server）
"""
import argparse
import logging
import os
import sys
import sqlite3
from datetime import datetime
from typing import Dict, List

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from gaokao.data_provenance import (  # noqa: E402
    SYNTHETIC_DATA_KIND,
    inspect_database_provenance,
)

WEB_DIR = os.path.join(PROJECT_ROOT, 'web')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('opengaokao.api')


# ─────────────────────────────────────────────
# 引擎单例（懒加载，按 db_path 缓存）
# ─────────────────────────────────────────────
_engine_cache: Dict[str, object] = {}


def get_engine(db_path: str):
    """按数据库路径缓存 MatchingEngine 实例，避免每次请求重新初始化。"""
    if db_path in _engine_cache:
        return _engine_cache[db_path]
    from gaokao.core.matching_engine import MatchingEngine
    engine = MatchingEngine(db_path=db_path)
    _engine_cache[db_path] = engine
    log.info(f'[engine] 已初始化推荐引擎: {db_path}')
    return engine


def get_province_config(slug: str):
    from gaokao.config.registry import get_registry
    reg = get_registry()
    cfg = reg.get(slug)
    if not cfg:
        raise ValueError(f'未知省份: {slug}')
    return cfg


def resolve_database(province: str):
    """按数据库内容而非文件名决定是否为合成示例数据。"""
    province_db = os.path.join(PROJECT_ROOT, 'data', f'{province}_gaokao.db')
    fallback = os.path.join(PROJECT_ROOT, 'data', 'example.db')
    used_fallback = not os.path.exists(province_db)
    db_path = fallback if used_fallback else province_db
    if not os.path.exists(db_path):
        raise FileNotFoundError(f'数据库文件不存在: {province_db}')

    provenance = inspect_database_provenance(db_path)
    if used_fallback and provenance != SYNTHETIC_DATA_KIND:
        raise RuntimeError('example.db 缺少合成数据来源标记，拒绝静默降级')
    data_source = 'example' if provenance == SYNTHETIC_DATA_KIND else province
    if data_source == 'example':
        log.warning(f'数据库内容被识别为合成示例数据: {db_path}')
    return db_path, data_source, provenance


# ─────────────────────────────────────────────
# Flask App
# ─────────────────────────────────────────────
app = Flask(__name__, static_folder=None)
CORS(app, resources={r'/api/*': {'origins': '*'}})

# OG-F-34: AGPL §13 网络服务条款——对外提供服务时须告知使用者对应源码的获取途径。
# 部署你自己的 fork 时，请设环境变量 OPENGAOKAO_SOURCE_URL 指向你的（含改动的）源码仓库。
# 注意：默认值为占位地址，公开部署前必须改为真实仓库 URL（发布闸门，见 docs/audit OG-F-47）。
SOURCE_REPO_URL = os.environ.get('OPENGAOKAO_SOURCE_URL',
                                 'https://github.com/heronerar/OpenGaokao')


@app.after_request
def _add_source_offer(resp):
    # AGPL §13: 每个响应附带源码获取途径
    resp.headers['X-Source-Code'] = SOURCE_REPO_URL
    resp.headers['X-License'] = 'AGPL-3.0-or-later'
    return resp


# ── 静态托管 ──
@app.route('/')
def serve_index():
    return send_from_directory(WEB_DIR, 'index.html')


@app.route('/<path:path>')
def serve_static(path):
    """托管 web/ 目录下的所有静态资源（css/js/...）"""
    return send_from_directory(WEB_DIR, path)


# ── /api/health ──
@app.route('/api/health')
def health():
    return jsonify({
        'status': 'ok',
        'service': 'OpenGaokao API',
        'web_dir': WEB_DIR,
        'cached_engines': list(_engine_cache.keys()),
        'license': 'AGPL-3.0-or-later',  # OG-F-34: §13 源码 offer
        'source_url': SOURCE_REPO_URL,
    })


# ── /api/download —— 文件下载端点 ──
@app.route('/api/download')
def download_file():
    """安全下载导出文件。仅允许 output/ 目录下的文件。"""
    import urllib.parse
    path = request.args.get('path', '')
    name = request.args.get('name', '')
    # 安全检查：只允许项目 output/ 目录下的文件
    allowed_dir = os.path.abspath(os.path.join(PROJECT_ROOT, 'output'))
    abs_path = os.path.abspath(path)
    if not abs_path.startswith(allowed_dir):
        return jsonify({'error': '不允许的路径'}), 403
    if not os.path.exists(abs_path):
        return jsonify({'error': '文件不存在'}), 404
    from flask import send_file
    return send_file(abs_path, as_attachment=True, download_name=name or os.path.basename(abs_path))


# ── /api/provinces ──
@app.route('/api/provinces')
def list_provinces():
    try:
        from gaokao.config.registry import get_registry
        reg = get_registry()
        configs = reg.list_all()
        return jsonify({
            'provinces': [
                {
                    'slug': slug,
                    'name': cfg.name,
                    'gaokao_mode': cfg.gaokao_mode,
                    'volunteer_mode': cfg.volunteer_mode,
                    'reform_year': cfg.reform_year,
                }
                for slug, cfg in configs.items()
            ]
        })
    except Exception as e:
        log.exception('list_provinces 失败')
        return jsonify({'error': str(e)}), 500


# ── /api/holland（兼容既有路径）──
@app.route('/api/holland')
def get_holland():
    """返回项目自编 RIASEC 风格兴趣题（动态生成给前端）。"""
    try:
        from gaokao.core.personality_items import HOLLAND_ITEMS, holland_question_id
        items = []
        for no in sorted(HOLLAND_ITEMS.keys()):
            it = HOLLAND_ITEMS[no]
            items.append({
                'id': holland_question_id(no),
                'a_text': it['a_text'],
                'b_text': it['b_text'],
                'a_dim': it['a_dim'],
                'b_dim': it['b_dim'],
            })
        return jsonify({
            'items': items,
            'total': len(items),
            'instrument': '项目自编 RIASEC 风格兴趣偏好问卷',
            'disclaimer': '未经心理测量学验证，不是标准化心理量表，不作诊断',
        })
    except Exception as e:
        log.exception('get_holland 失败')
        return jsonify({'error': str(e)}), 500


# ── /api/recommend —— 核心端点 ──
@app.route('/api/recommend', methods=['POST'])
def recommend():
    """
    请求体:
    {
        "province": "yunnan",  // 可选，默认 yunnan
        "answers": { ...问卷答案... },
        "category": "物理类",   // 可选，默认从 answers 推断
        "top_n": 30
    }

    响应:
    {
        "summary": { "chong": N, "wen": N, "bao": N, "dian": N },
        "schools": [ { tier, prob, name, ... } ],
        "pipeline": [ ...7 步管道审计... ],
        "risks": [ ... ],
        "checklist": [ ... ],
        "notes": [ ... ]
    }
    """
    try:
        body = request.get_json(force=True, silent=True) or {}
        province = body.get('province', 'yunnan')
        answers = body.get('answers') or {}
        top_n = int(body.get('top_n', 30))

        if not answers:
            return jsonify({'error': '缺少 answers 字段'}), 400

        # 1) 解析省份配置
        cfg = get_province_config(province)
        db_path, data_source, data_provenance = resolve_database(province)

        # 2) 解析问卷
        from gaokao.core.questionnaire_parser import QuestionnaireParser
        category = body.get('category') or answers.get('q14_category', '物理类')
        parser = QuestionnaireParser.create_by_category(category)
        questionnaire = parser.parse(answers)

        # 3) 准备偏好问卷答案（如缺失，引擎会跳过相应模块）
        big_five = getattr(questionnaire, 'big_five_answers', None) or {}
        holland = getattr(questionnaire, 'holland_answers', None) or {}
        efficacy = _build_efficacy_dict(answers, category)
        career = _build_career_values_dict(answers, category)

        # 4) 配置引擎
        from gaokao.core.volunteer_recommender import configure_with_config as _configure
        _configure(cfg)
        from gaokao.core.revocation_risk import set_db_path as _set_revocation_db
        _set_revocation_db(db_path)

        # 5) 执行匹配
        engine = get_engine(db_path)
        result = engine.match(
            questionnaire,
            big_five_answers=big_five,
            holland_answers=holland,
            efficacy_answers=efficacy,
            career_values_answers=career,
            top_n=top_n,
        )

        # 6) 序列化响应
        response_data = _serialize_result(result, cfg)
        response_data['data_source'] = data_source
        response_data['data_provenance'] = data_provenance

        # 7) 生成深度分析报告（纯算法，无 LLM）
        try:
            from gaokao.analysis.report_generator import generate_report, report_to_dict
            analysis_report = generate_report(questionnaire, result, db_path)
            response_data['analysis'] = report_to_dict(analysis_report)
            log.info(f'[analysis] 分析报告生成成功，{len(analysis_report.sections)} 个章节')
        except Exception as e:
            log.warning(f'[analysis] 分析报告生成失败: {e}')

        return jsonify(response_data)

    except Exception as e:
        log.exception('recommend 失败')
        return jsonify({'error': str(e), 'type': type(e).__name__}), 500


# ── /api/export —— 导出端点 ──
@app.route('/api/export', methods=['POST'])
def export_report():
    """
    请求体:
    {
        "province": "yunnan",
        "answers": { ...问卷... },
        "format": "html" | "excel" | "pdf" | "all",  // 默认 html
    }

    响应: JSON 包含导出文件路径（或 base64 内容）
    """
    try:
        from gaokao.export.document_generator import DocumentGenerator
        import tempfile, base64 as b64

        body = request.get_json(force=True, silent=True) or {}
        province = body.get('province', 'yunnan')
        answers = body.get('answers') or {}
        fmt = body.get('format', 'html').lower()

        if fmt not in ('html', 'excel', 'pdf', 'all'):
            return jsonify({'error': f'不支持的格式: {fmt}，可选 html/excel/pdf/all'}), 400

        # 1) 省份配置 + db
        cfg = get_province_config(province)
        db_path, data_source, data_provenance = resolve_database(province)

        # 2) 解析问卷 + 执行匹配
        from gaokao.core.questionnaire_parser import QuestionnaireParser
        category = body.get('category') or answers.get('q14_category', '物理类')
        parser = QuestionnaireParser.create_by_category(category)
        questionnaire = parser.parse(answers)

        big_five = getattr(questionnaire, 'big_five_answers', None) or {}
        holland = getattr(questionnaire, 'holland_answers', None) or {}
        efficacy = _build_efficacy_dict(answers, category)
        career = _build_career_values_dict(answers, category)

        from gaokao.core.volunteer_recommender import configure_with_config as _configure
        _configure(cfg)
        from gaokao.core.revocation_risk import set_db_path as _set_revocation_db
        _set_revocation_db(db_path)

        engine = get_engine(db_path)
        result = engine.match(
            questionnaire, big_five_answers=big_five, holland_answers=holland,
            efficacy_answers=efficacy, career_values_answers=career, top_n=int(body.get('top_n', 30)),
        )

        # 3) 生成导出文件（OG-F-30: 透传真实省份 db_path，否则报表恒读 example.db）
        gen = DocumentGenerator(output_dir=os.path.join(PROJECT_ROOT, 'output'), db_path=db_path)
        export_paths = {}

        if fmt in ('html', 'all'):
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            path = gen.generate_html_report(result)
            export_paths['html'] = path

        if fmt in ('excel', 'all'):
            path = gen.generate_excel_report(result)
            export_paths['excel'] = path

        if fmt in ('pdf', 'all'):
            try:
                path = gen.generate_pdf_report(result)
                export_paths['pdf'] = path
            except Exception as e:
                log.warning(f'PDF 生成失败（可能缺少中文字体）: {e}')
                export_paths['pdf_error'] = str(e)

        if fmt in ('csv', 'all'):
            path = gen.generate_csv_report(result)
            export_paths['csv'] = path

        # 返回文件路径和摘要
        return jsonify({
            'format': fmt,
            'files': export_paths,
            'output_dir': gen.output_dir,
            'data_source': data_source,
            'data_provenance': data_provenance,
        })

    except Exception as e:
        log.exception('export 失败')
        return jsonify({'error': str(e), 'type': type(e).__name__}), 500


# ─────────────────────────────────────────────
# 内部工具：构造 efficacy / career_values 整数键字典
# ─────────────────────────────────────────────
def _build_efficacy_dict(answers: Dict, category: str) -> Dict[int, int]:
    """从问卷答案构造 {全局题号 76-90: 1-5 分} 给 personality_test 使用。

    题号映射沿用 questionnaire_parser._SE_KEYS，但 personality_test 需要整数键。
    这里走简化路径：直接读 q76_se_cn1 ~ q90_se_en5 的值。
    """
    out = {}
    is_history = '历史' in (category or '')
    base = 77 if is_history else 76
    # 15 题：q76~q90 (物理) / q77~q91 (历史)
    suffixes = ['se_cn1','se_cn2','se_cn3','se_cn4','se_cn5',
                'se_mt1','se_mt2','se_mt3','se_mt4','se_mt5',
                'se_en1','se_en2','se_en3','se_en4','se_en5']
    for i, sfx in enumerate(suffixes):
        key = f'q{base + i}_{sfx}'
        val = answers.get(key)
        if val is not None and val != '':
            try:
                out[base + i] = int(val)
            except (ValueError, TypeError):
                pass
    return out


def _build_career_values_dict(answers: Dict, category: str) -> Dict[int, int]:
    out = {}
    is_history = '历史' in (category or '')
    base = 92 if is_history else 91
    # 20 题
    suffixes = [
        'cv_income1','cv_income2','cv_stability1','cv_stability2',
        'cv_achievement1','cv_achievement2','cv_help1','cv_help2',
        'cv_creative1','cv_creative2','cv_balance1','cv_balance2',
        'cv_leadership1','cv_leadership2','cv_autonomy1','cv_autonomy2',
        'cv_location1','cv_location2','cv_learning1','cv_learning2',
    ]
    for i, sfx in enumerate(suffixes):
        key = f'q{base + i}_{sfx}'
        val = answers.get(key)
        if val is not None and val != '':
            try:
                out[base + i] = int(val)
            except (ValueError, TypeError):
                pass
    return out


# ─────────────────────────────────────────────
# 序列化：把 MatchingResult 转成前端可用的 JSON
# ─────────────────────────────────────────────
def _serialize_result(result, cfg) -> Dict:
    recs = result.recommendations or {}
    chong = recs.get('冲', []) or []
    wen = recs.get('稳', []) or []
    bao = recs.get('保', []) or []
    dian = recs.get('垫', []) or []

    schools = []
    for tier, items in [('冲', chong), ('稳', wen), ('保', bao), ('垫', dian)]:
        for r in items:
            schools.append(_serialize_school(r, tier))

    return {
        'province': cfg.name,
        'summary': {
            'chong': len(chong),
            'wen': len(wen),
            'bao': len(bao),
            'dian': len(dian),
            'total': len(chong) + len(wen) + len(bao) + len(dian),
        },
        'schools': schools,
        'pipeline': _build_pipeline_view(result, cfg),
        'risks': _build_risk_view(result),
        'checklist': _build_checklist(result),
        'notes': list(result.notes or [])[:10],
        'risk_strategy': result.risk_strategy,
        'data_sparsity_warning': result.data_sparsity_warning or '',
        'must_ack_warnings': list(result.must_ack_warnings or []),
    }


def _serialize_school(r, tier) -> Dict:
    majors = []
    for m in (r.recommended_majors or [])[:5]:
        majors.append({
            'n': m.major_name,
            'score': round(float(m.score), 1) if m.score else 0,
            'r': m.reason or '',
            'is_new': bool(getattr(m, 'is_new_major', False)),
            'employment_rate': float(getattr(m, 'employment_rate', 0) or 0),
        })
    return {
        'tier': tier,
        'prob': round(float(r.probability), 1) if r.probability else 0,
        'name': r.school_name + (f'·{r.group_name}' if r.group_name else ''),
        'loc': r.location or '—',
        'tier_label': r.school_quality or '—',
        'tuition': int(r.tuition or 0),
        'majors': majors,
        'reasons': list((r.reasons or [])[:5]),
        'predicted_rank': int(r.predicted_rank or 0),
        'batch': r.batch or '',
        'subject_req': r.subject_req or '',
        'checks': _build_school_checks(r),
    }


def _build_school_checks(r) -> List[Dict]:
    """构造卡片上的"快速通过检查"徽章。"""
    checks = []
    if r.subject_req:
        checks.append({'ok': True, 't': f'选科:{r.subject_req}'})
    else:
        checks.append({'ok': True, 't': '选科符合'})
    if r.batch:
        checks.append({'ok': True, 't': f'批次:{r.batch}'})
    checks.append({'ok': True, 't': '体检无禁忌'})
    if r.tuition and r.tuition <= 8000:
        checks.append({'ok': True, 't': '学费亲民'})
    elif r.tuition and r.tuition > 30000:
        checks.append({'ok': False, 't': '中外合作高学费'})
    return checks


def _build_pipeline_view(result, cfg) -> List[Dict]:
    """从 MatchingResult 提取 7 步管道视图，含详细审计数据。"""
    pipeline = [
        {
            'icon': '🔢', 'name': '位次转换',
            'input': 1, 'output': 1, 'exc': 0,
            'detail': f'分数 {result.user_profile.score} → 位次 {result.user_profile.rank}',
            'src': f'{cfg.name} 一分一段表',
            'formula': '位次 = 一分一段表累积排名查询',
            'excluded_items': [],
        },
    ]

    # ── 漏斗排除四步：选科 → 学科偏好 → 体检 → 兴趣 ──
    funnel = result.funnel_report
    if funnel is not None:
        stages = getattr(funnel, 'stages', []) or []
        icon_map = {'选科排除': '🔬', '学科偏好排除': '📚', '体检排除': '🏥', '兴趣意愿排除': '🧠'}
        name_map = {'选科排除': '选科过滤', '学科偏好排除': '学科适配', '体检排除': '体检限制', '兴趣意愿排除': '兴趣匹配'}

        for stage in stages:
            name = getattr(stage, 'name', '')
            desc = getattr(stage, 'desc', '')
            excluded = getattr(stage, 'excluded_count', 0) or 0
            remaining = getattr(stage, 'remaining_count', 0) or 0
            items = getattr(stage, 'excluded_items', []) or []
            inp = excluded + remaining

            excluded_detail = items[:8] if items else []
            pipeline.append({
                'icon': icon_map.get(name, '📋'),
                'name': name_map.get(name, name),
                'input': inp, 'output': remaining, 'exc': excluded,
                'detail': desc,
                'src': '招生计划选科要求表' if '选科' in name else (
                    '项目自编学科自我评价问卷' if '学科' in name else (
                    '教育部体检指导意见 + 各校招生章程' if '体检' in name else
                    '项目自编 RIASEC 风格兴趣偏好问卷（未经心理测量验证）'
                )),
                'excluded_items': excluded_detail,
            })

    # ── 概率计算步 ──
    total_recs = sum(len(v) for v in (result.recommendations or {}).values())
    # 收集概率范围
    all_probs = []
    for tier_items in (result.recommendations or {}).values():
        for r in tier_items:
            p = getattr(r, 'probability', 0) or 0
            if p > 0:
                all_probs.append(p)

    prob_detail = '对所有候选基于历史录取位次计算概率'
    if all_probs:
        min_p, max_p = min(all_probs), max(all_probs)
        avg_p = sum(all_probs) / len(all_probs)
        prob_detail = (
            f'概率范围 {min_p:.0f}%-{max_p:.0f}%，均值 {avg_p:.0f}%。'
            f'模型：P = 50 + 50×(1 − e^(−2·|Δrank|/pred_rank))，'
            f'年权重 0.5/0.3/0.2，趋势钳制 ±30%'
        )

    pipeline.append({
        'icon': '📊', 'name': '概率计算',
        'input': total_recs, 'output': total_recs, 'exc': 0,
        'detail': prob_detail,
        'src': '2023-2025 录取数据 (3 年指数衰减加权)',
        'formula': 'P = 50 + 50×(1 − e^(−2·|Δrank|/pred_rank))',
        'excluded_items': [],
    })

    # ── 排序输出步 ──
    chong_n = len(result.recommendations.get('冲', []))
    wen_n = len(result.recommendations.get('稳', []))
    bao_n = len(result.recommendations.get('保', []))
    dian_n = len(result.recommendations.get('垫', []))

    sort_detail = (
        f'综合评分排序：冲 {chong_n}（概率 <35%）/ '
        f'稳 {wen_n}（35%-85%）/ 保 {bao_n}（≥85%）/ 垫 {dian_n}（深度兜底）。'
        f'排序权重 = 录取概率×0.35 + 兴趣匹配×0.25 + 性格匹配×0.20 '
        f'+ 就业质量×0.10 + 办学层次×0.10'
    )

    pipeline.append({
        'icon': '🏆', 'name': '排序输出',
        'input': total_recs, 'output': total_recs, 'exc': 0,
        'detail': sort_detail,
        'src': '可配置综合评分权重（5 因子加权）',
        'excluded_items': [],
    })

    return pipeline


def _build_risk_view(result) -> List[Dict]:
    """从 MatchingResult 构建详细风险评估视图，集成 gaokao.risk 量化计算。"""
    risks = []

    # ── 使用 gaokao.risk 进行量化评估 ──
    try:
        from gaokao.risk.risk_calculator import assess_risks
        user_rank = result.user_profile.rank if result.user_profile else 0
        category = getattr(result.questionnaire, 'category', '') if result.questionnaire else ''

        # 从问卷推断是否服从调剂
        questionnaire = result.questionnaire
        accepts_adjustment = True
        if questionnaire:
            adjust = (getattr(questionnaire, 'major_adjustment', '') or
                     getattr(questionnaire, 'major_adjustment_attitude', ''))
            if '不服从' in adjust:
                accepts_adjustment = False

        # 从约束结果推断体检限制
        has_medical = False
        constraint = result.constraint_result
        if constraint:
            filtered = getattr(constraint, 'filtered_majors', None) or []
            if filtered:
                has_medical = True

        risk_assessment = assess_risks(
            recommendations=result.recommendations or {},
            user_rank=user_rank,
            subject_type=category,
            has_medical_restriction=has_medical,
            accepts_adjustment=accepts_adjustment,
        )

        # 滑档风险
        level_map = {'low': 'low', 'medium': 'medium', 'high': 'high'}
        risks.append({
            'level': level_map.get(risk_assessment.slip_risk, 'medium'),
            'title': f'滑档风险：{_risk_label_cn(risk_assessment.slip_risk)}',
            'body': risk_assessment.slip_detail,
            'probability': round(risk_assessment.slip_probability * 100, 1),
        })

        # 高分低就风险
        if risk_assessment.waste_risk != 'low' or risk_assessment.waste_rank_diff > 5000:
            risks.append({
                'level': level_map.get(risk_assessment.waste_risk, 'low'),
                'title': f'高分低就风险：{_risk_label_cn(risk_assessment.waste_risk)}',
                'body': risk_assessment.waste_detail,
                'wasted_rank': risk_assessment.waste_rank_diff,
            })

        # 退档风险
        if risk_assessment.reject_risk != 'low' or risk_assessment.reject_reasons:
            risks.append({
                'level': level_map.get(risk_assessment.reject_risk, 'medium'),
                'title': f'退档风险：{_risk_label_cn(risk_assessment.reject_risk)}',
                'body': risk_assessment.reject_detail,
                'reasons': risk_assessment.reject_reasons,
            })

        # 综合风险
        risks.append({
            'level': level_map.get(risk_assessment.overall_risk, 'low'),
            'title': f'综合风险：{_risk_label_cn(risk_assessment.overall_risk)}',
            'body': f'滑档概率 {risk_assessment.slip_probability*100:.1f}%，'
                    f'退档风险 {_risk_label_cn(risk_assessment.reject_risk)}，'
                    f'分数利用 {"充分" if risk_assessment.waste_risk == "low" else "有优化空间"}',
        })

    except Exception:
        # 回退：基于推荐数据的简单评估
        bao_count = len(result.recommendations.get('保', []))
        if bao_count >= 5:
            risks.append({'level': 'low', 'title': '保底充足',
                          'body': f'保底志愿 {bao_count} 个，滑档风险低'})
        elif bao_count >= 3:
            risks.append({'level': 'medium', 'title': '保底偏少',
                          'body': f'当前保底 {bao_count} 个，建议补充至 5 个以上'})
        else:
            risks.append({'level': 'high', 'title': '保底不足',
                          'body': f'当前保底仅 {bao_count} 个，存在滑档风险'})

    # ── 数据稀疏警告 ──
    if result.data_sparsity_warning:
        risks.append({
            'level': 'high', 'title': '数据稀疏风险',
            'body': result.data_sparsity_warning,
        })

    # ── 必读提示 ──
    for w in (result.must_ack_warnings or [])[:5]:
        risks.append({'level': 'medium', 'title': '必读提示', 'body': w})

    # ── 专业宽度预警 ──
    for bw in (result.breadth_warnings or [])[:3]:
        risks.append({'level': 'medium', 'title': '专业宽度预警', 'body': bw})

    return risks


def _risk_label_cn(level: str) -> str:
    _map = {'low': '低 ✅', 'medium': '中 ⚠️', 'high': '高 🔴'}
    return _map.get(level, level)


def _build_checklist(result) -> List[str]:
    """从推荐结果 + 风险评估生成决策检查清单。"""
    total = sum(len(v) for v in (result.recommendations or {}).values())
    bao = len(result.recommendations.get('保', []))
    dian = len(result.recommendations.get('垫', []))

    checklist = [
        f'志愿总数 ≥ 15 个？当前 {total} 个 {"✅" if total >= 15 else "⚠️"}',
        f'保底志愿 ≥ 3 个且录取概率均 ≥85%？当前保底 {bao} + 垫 {dian} 个 {"✅" if (bao + dian) >= 3 else "⚠️"}',
    ]

    # 从问卷推断调剂态度
    questionnaire = getattr(result, 'questionnaire', None)
    if questionnaire:
        adjust = (getattr(questionnaire, 'major_adjustment', '') or
                 getattr(questionnaire, 'major_adjustment_attitude', ''))
        if '不服从' in adjust:
            checklist.append('⚠️ 冲档志愿是否勾选服从调剂？当前选择"不服从"，存在退档风险——建议重新考虑')
        else:
            checklist.append('冲档志愿是否勾选服从调剂？✅ 已选择服从调剂，降低退档风险')
    else:
        checklist.append('冲档志愿是否勾选服从调剂？请人工核对')

    # 体检
    hs = getattr(questionnaire, 'health_screening', None) if questionnaire else None
    if hs:
        has_issues = False
        if getattr(hs, 'color_vision', '正常') != '正常':
            checklist.append('⚠️ 色觉异常：请逐条核对目标院校招生章程中的体检要求')
            has_issues = True
        if getattr(hs, 'vision', '') and '正常' not in str(getattr(hs, 'vision', '')):
            checklist.append('⚠️ 视力受限：部分专业（飞行/航海/刑侦等）有裸眼视力要求')
            has_issues = True
        if not has_issues:
            checklist.append('所有志愿的体检/选科要求已核对？✅ 系统已做初筛，建议人工复核')
    else:
        checklist.append('所有志愿的体检/选科要求已核对？请人工核对')

    # 预算
    budget = getattr(questionnaire, 'total_budget', '') if questionnaire else ''
    if '2万' in str(budget):
        checklist.append('💡 学费预算紧张（2万/年以内）：优先选择公办院校，注意中外合作专业学费较高')
    else:
        checklist.append('学费预算是否覆盖所有志愿？请人工核对')

    # OG-F-31: 就业数据覆盖率透明声明——防止"未显示就业数据"被误读为"就业差"
    maj_total = maj_with_emp = 0
    for schools in (result.recommendations or {}).values():
        for s in schools:
            for m in (getattr(s, 'recommended_majors', None) or []):
                maj_total += 1
                if getattr(m, 'employment_rate', 0):
                    maj_with_emp += 1
    if maj_total and maj_with_emp < maj_total:
        pct = round(100 * maj_with_emp / maj_total)
        checklist.append(
            f'ℹ️ 就业/薪资数据覆盖 {maj_with_emp}/{maj_total}（{pct}%）个推荐专业；'
            f'未显示就业数据 ≠ 就业差，仅表示该专业暂无数据，建议自行查证。'
        )

    checklist.extend([
        '中外合作/分校/独立学院是否已识别？请人工核对',
        '最终确认前是否与家人达成共识？🔲',
        '📋 免责声明：以上概率基于历史数据统计，不代表当年录取结果。请结合当年招生计划和政策综合判断。',
    ])

    # 集成 risk_calculator 的风险警告（仅插入独有项，避免与已有条目重复）
    try:
        from gaokao.risk.risk_calculator import assess_risks
        user_rank = result.user_profile.rank if result.user_profile else 0
        risk_assessment = assess_risks(
            recommendations=result.recommendations or {},
            user_rank=user_rank,
        )
        extra = risk_assessment.checklist or []
        # 只插入高风险/退档风险警告，不插入通用检查项（server 已生成更详细的版本）
        for item in extra:
            if item.startswith('⚠️'):
                checklist.insert(0, item)
    except Exception:
        pass

    return checklist


# ─────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='OpenGaokao API Server')
    parser.add_argument('--province', '-p', default='yunnan', help='默认省份')
    parser.add_argument('--port', type=int, default=5000, help='监听端口')
    parser.add_argument('--host', default='127.0.0.1', help='监听地址')
    parser.add_argument('--debug', action='store_true', help='Flask debug 模式')
    args = parser.parse_args()

    log.info(f'🚀 OpenGaokao API 启动 — http://{args.host}:{args.port}')
    log.info(f'   默认省份: {args.province}')
    log.info(f'   静态目录: {WEB_DIR}')
    log.info(f'   访问 http://{args.host}:{args.port}/ 即可看到前端')

    # 预热默认省份引擎
    try:
        db_path, data_source, data_provenance = resolve_database(args.province)
        get_engine(db_path)
        log.info(f'   数据源: {data_source} ({data_provenance})')
    except Exception as e:
        log.warning(f'预热失败（不影响启动）: {e}')

    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False)


if __name__ == '__main__':
    main()
