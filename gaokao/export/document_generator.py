# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""
文档生成器 (Document Generator) V3.0
生成志愿推荐方案的PDF/Excel/HTML/CSV报告。

核心功能：
1. 生成PDF报告（推荐方案+项目自编偏好问卷+问卷摘要）
2. 生成Excel表格（冲稳保院校列表+专业推荐）
3. 生成HTML预览（网页版报告）
4. 标准层: PDF图表增强（雷达图/趋势图/饼图）+ AI解读
"""
import json
import math
import os
import sqlite3
import html as _html_mod
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from dataclasses import asdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, '..', 'data', 'example.db')


def _h(v) -> str:
    """HTML 安全转义（F-5/P0-A2）：所有写入 HTML 报告的用户/数据库字段必须经过此函数。
    - None → '' 避免 'None' 字面量泄漏
    - 数字保留原样字符串
    - 字符串用 html.escape 转义 < > & " '
    """
    if v is None:
        return ''
    return _html_mod.escape(str(v), quote=True)


def _translate_term(term: str) -> str:
    """将技术术语翻译为家长可读语言"""
    mapping = {
        # 数据覆盖度
        'low': '数据有限（仅供参考）',
        'medium': '数据一般',
        'high': '数据充分',
        'none': '无历史数据',
        # 数据质量
        'sparse': '数据稀疏（仅供参考）',
        'adequate': '数据充足',
        'rich': '数据丰富',
        # 风险策略
        'aggressive': '积极型（冲档比例较高）',
        'balanced': '均衡型',
        'conservative': '稳健型（保档比例较高）',
        # 冲稳保分类
        'chong': '冲刺',
        'wen': '稳妥',
        'bao': '保底',
        # 征集志愿
        'collection': '征集志愿',
        # 置信度补充
        'probability': '录取概率',
        'confidence': '数据置信度',
        'predicted_rank': '预测位次',
        'trend': '位次趋势',
        # 推荐相关
        'recommendation': '推荐',
        'school_quality': '院校层次',
        'location': '所在城市',
        'tuition': '学费',
        'major': '专业',
        'school': '院校',
        'batch': '批次',
        'rank': '位次',
        'score': '分数',
        'category': '科类',
        'strategy': '策略',
        'risk_tolerance': '风险偏好',
    }
    return mapping.get(term, term)


def _get_confidence_display(confidence: str) -> str:
    """将置信度从英文翻译为中文"""
    return _translate_term(confidence)


_BATCH_NAME_MAP = {
    '提前本科批A段': '提前本科批A段（优师专项/免费定向）',
    '提前本科批B段': '提前本科批B段（军队/公安院校）',
    '提前本科批C段': '提前本科批C段（消防/招飞/航海）',
    '提前本科批D段': '提前本科批D段（公费师范生等）',
    '本科批A段': '本科批A段（高校专项计划）',
    '本科批B段': '本科批B段（普通本科）',
    '提前专科批A段': '提前专科批A段（专科免费定向）',
    '提前专科批B段': '提前专科批B段（定向军士）',
    '高职专科批': '高职专科批',
    '征集志愿': '征集志愿（补录阶段）',
}


def _translate_batch_name(batch: str) -> str:
    """将批次名称翻译为带说明的全称"""
    return _BATCH_NAME_MAP.get(batch, batch)

# ── 中文字体加载（跨平台兼容） ──
_CACHED_FONT_NAME = None

def _get_chinese_font() -> str:
    """
    尝试加载中文字体，返回字体名。

    优先级:
    1. Windows: C:\\Windows\\Fonts\\simsun.ttc
    2. Linux 系统字体: Noto Sans CJK / WenQuanYi / Microsoft YaHei (通过 win10-cursors 等包安装)
    3. macOS: /System/Library/Fonts/
    4. Fallback: Helvetica（不支持中文，但保证PDF可生成）
    """
    global _CACHED_FONT_NAME
    if _CACHED_FONT_NAME:
        return _CACHED_FONT_NAME

    candidates = [
        # Windows
        ('SimSun', r'C:\Windows\Fonts\simsun.ttc'),
        # Linux: Noto Sans CJK
        ('NotoSansCJK', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
        ('NotoSansCJK', '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc'),
        ('NotoSansCJK', '/usr/share/fonts/opentype/noto/NotoSansSC-Regular.otf'),
        # Linux: WenQuanYi Micro Hei
        ('WenQuanYiMicroHei', '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc'),
        # Linux: WenQuanYi Zen Hei
        ('WenQuanYiZenHei', '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'),
        # macOS
        ('PingFang', '/System/Library/Fonts/PingFang.ttc'),
        ('HiraginoSans', '/System/Library/Fonts/Heiti.ttc'),
        # Windows 备选（微软雅黑）
        ('MicrosoftYaHei', r'C:\Windows\Fonts\msyh.ttc'),
    ]

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for font_name, font_path in candidates:
        try:
            if os.path.exists(font_path):
                pdfmetrics.registerFont(TTFont(font_name, font_path))
                _CACHED_FONT_NAME = font_name
                return font_name
        except Exception:
            continue

    # 全部失败，使用 Helvetica
    _CACHED_FONT_NAME = 'Helvetica'
    return 'Helvetica'


def check_data_completeness(db_path: str, category: str, year: int = 2025
                            ) -> Tuple[bool, str, Dict]:
    """
    检查数据库完整性，返回 (ok, warning_message, details)
    category: '物理类'/'历史类'/'理科'/'文科'
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    c = conn.cursor()

    # 将科类别名映射到数据库标签
    aliases = {
        '物理类': ("物理", "物理类", "理科"),
        '历史类': ("历史", "历史类", "文科"),
        '物理': ("物理", "物理类", "理科"),
        '历史': ("历史", "历史类", "文科"),
        '理科': ("物理", "物理类", "理科"),
        '文科': ("历史", "历史类", "文科"),
    }
    subj_labels = aliases.get(category, (category,))
    in_clause = ','.join('?' for _ in subj_labels)

    c.execute(f'SELECT COUNT(*) FROM enroll_detail WHERE year=? AND subject_type IN ({in_clause})',
              [year] + list(subj_labels))
    total = c.fetchone()[0]

    c.execute(f'SELECT COUNT(*) FROM enroll_detail WHERE year=? AND subject_type IN ({in_clause}) AND min_rank IS NOT NULL',
              [year] + list(subj_labels))
    with_rank = c.fetchone()[0]

    # 获取学校数
    c.execute(f'SELECT COUNT(DISTINCT school_name) FROM enroll_detail WHERE year=? AND subject_type IN ({in_clause})',
              [year] + list(subj_labels))
    school_count = c.fetchone()[0]

    # 获取专业组数
    c.execute(f'SELECT COUNT(DISTINCT school_name || "|" || major_name) FROM enroll_detail WHERE year=? AND subject_type IN ({in_clause})',
              [year] + list(subj_labels))
    major_count = c.fetchone()[0]

    # 获取批次覆盖
    c.execute(f'SELECT DISTINCT batch FROM enroll_detail WHERE year=? AND subject_type IN ({in_clause}) ORDER BY batch',
              [year] + list(subj_labels))
    batches = [r[0] for r in c.fetchall()]

    conn.close()

    details = {
        'total_records': total,
        'with_rank': with_rank,
        'school_count': school_count,
        'major_count': major_count,
        'batches': batches,
        'rank_coverage': with_rank / total * 100 if total > 0 else 0,
    }

    # 告警条件
    warnings = []
    if total < 2000:
        warnings.append(f'⚠️ {year}年{category}仅{total}条记录，数据严重不足')
    elif total < 5000:
        warnings.append(f'⚠️ {year}年{category}仅{total}条记录，数据不完整')

    if with_rank < total * 0.5:
        warnings.append(f'⚠️ 有录取位次的记录仅{with_rank}条（{details["rank_coverage"]:.0f}%）')

    if len(batches) < 5:
        warnings.append(f'⚠️ 仅覆盖{len(batches)}个批次: {", ".join(batches[:5])}')

    if school_count < 50:
        warnings.append(f'⚠️ 仅覆盖{school_count}所院校')

    ok = len(warnings) == 0
    msg = '; '.join(warnings) if warnings else '数据覆盖正常'
    return ok, msg, details


class DocumentGenerator:
    """文档生成器 V3.0"""

    def __init__(self, output_dir: str = 'output', db_path: str = None):
        self.output_dir = output_dir
        # OG-F-30: 数据库路径必须由调用方按省传入；不传才退回模块默认（仅独立/示例用）。
        # 此前所有报表查询硬编码 self.db_path=example.db，导致导出的热门专业/院校画像恒读玩具库。
        self.db_path = db_path or DB_PATH
        self._trend_map_cache = None
        os.makedirs(output_dir, exist_ok=True)

    @staticmethod
    def _get_chong_wen_bao_ratio_note(matching_result, config: dict = None) -> str:
        """
        生成冲稳保比例差异说明：当实际分布与系统规定比例不一致时，解释原因。
        """
        if not matching_result or not matching_result.recommendations:
            return ''

        chong = len(matching_result.recommendations.get('冲', []))
        wen = len(matching_result.recommendations.get('稳', []))
        bao = len(matching_result.recommendations.get('保', []))
        total = chong + wen + bao
        if total == 0:
            return ''

        # 系统目标比例
        if config is None:
            config = {'chong_ratio': 0.15, 'wen_ratio': 0.55, 'bao_ratio': 0.30}

        actual_chong = chong / total
        actual_wen = wen / total
        actual_bao = bao / total

        target_chong = config.get('chong_ratio', 0.15)
        target_wen = config.get('wen_ratio', 0.55)
        target_bao = config.get('bao_ratio', 0.30)

        # 差异超过10个百分点才提示
        deviations = []
        if abs(actual_chong - target_chong) > 0.10:
            if actual_chong < target_chong:
                deviations.append(
                    f'冲档偏少（实际{chong}所/{actual_chong:.0%}，目标{target_chong:.0%}）：'
                    f'当前位次在该概率区间的冲刺学校较少，可能因位次偏高或目标行业较冷门。'
                )
            else:
                deviations.append(
                    f'冲档偏多（实际{chong}所/{actual_chong:.0%}，目标{target_chong:.0%}）：'
                    f'当前位次冲刺学校充裕，但请注意冲档存在落选风险。'
                )
        if abs(actual_wen - target_wen) > 0.10:
            if actual_wen < target_wen:
                deviations.append(
                    f'稳档偏少（实际{wen}所/{actual_wen:.0%}，目标{target_wen:.0%}）：'
                    f'当前位次在稳妥区间的学校较少，可能与地域/专业偏好过滤过严有关。'
                )
            else:
                deviations.append(
                    f'稳档偏多（实际{wen}所/{actual_wen:.0%}，目标{target_wen:.0%}）：'
                    f'稳妥区间学校充裕，是较为理想的填报状态。'
                )
        if abs(actual_bao - target_bao) > 0.10:
            if actual_bao < target_bao:
                deviations.append(
                    f'保档偏少（实际{bao}所/{actual_bao:.0%}，目标{target_bao:.0%}）：'
                    f'标准保底（≥85%概率）学校不足，可能与批次数据覆盖率或专业偏好限制有关。'
                    f'请务必自行补充保底志愿。'
                )
            else:
                deviations.append(
                    f'保档偏多（实际{bao}所/{actual_bao:.0%}，目标{target_bao:.0%}）：'
                    f'保底学校充裕，但请注意部分学校可能过于保守。'
                )

        if not deviations:
            return ''

        note = '冲稳保比例说明：'
        note += f'系统目标为冲{target_chong:.0%}/稳{target_wen:.0%}/保{target_bao:.0%}，'
        note += f'实际为冲{chong}所({actual_chong:.0%})/稳{wen}所({actual_wen:.0%})/保{bao}所({actual_bao:.0%})。'
        note += '差异原因如下：\n'
        note += '\n'.join(f'· {d}' for d in deviations)
        return note

    def generate_free_report(self, personality_result, output_path: str = None) -> str:
        """
        免费层：项目自编偏好问卷报告 + 志愿填报注意事项 + 流程文档
        增强版：大五维度雷达图 + RIASEC 风格柱状图 + 9科自我评价 + 行为解读 + 流程时间线
        """
        # AUDIT-P3-002: 防御性断言——免费层不应接收推荐结果
        import inspect
        frame = inspect.currentframe()
        if frame and frame.f_back:
            caller_locals = frame.f_back.f_locals
            if caller_locals.get('matching_result') is not None:
                raise ValueError('generate_free_report 不应接收 matching_result（免费层无推荐数据）')

        if output_path is None:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = os.path.join(
                self.output_dir,
                f'OpenGaokao偏好问卷报告_{ts}.pdf',
            )

        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
        )
        from reportlab.lib import colors
        from reportlab.graphics.shapes import Drawing, String, Rect, Group
        from reportlab.graphics.charts.barcharts import VerticalBarChart
        from reportlab.graphics.charts.lineplots import LinePlot
        from reportlab.graphics import renderPDF

        font_name = _get_chinese_font()

        doc = SimpleDocTemplate(
            output_path, pagesize=A4,
            rightMargin=20*mm, leftMargin=20*mm,
            topMargin=20*mm, bottomMargin=20*mm,
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'FreeTitle', parent=styles['Title'],
            fontName=font_name, fontSize=22, leading=28,
            textColor=colors.HexColor('#1a237e'), alignment=1,
        )
        heading_style = ParagraphStyle(
            'FreeHeading', parent=styles['Heading1'],
            fontName=font_name, fontSize=14, leading=20,
            textColor=colors.HexColor('#283593'), spaceAfter=10,
        )
        subheading_style = ParagraphStyle(
            'FreeSubHeading', parent=styles['Heading2'],
            fontName=font_name, fontSize=11, leading=16,
            textColor=colors.HexColor('#3949ab'), spaceAfter=6,
        )
        normal_style = ParagraphStyle(
            'FreeNormal', parent=styles['Normal'],
            fontName=font_name, fontSize=10, leading=14,
            textColor=colors.HexColor('#333333'), spaceAfter=4,
        )

        story = []
        p = personality_result

        # 表格单元格样式（Paragraph包裹防溢出）
        _cell_style = ParagraphStyle('FreeCell', fontName=font_name, fontSize=9, leading=11, textColor=colors.HexColor('#333333'))
        _cell_hdr = ParagraphStyle('FreeCellHdr', fontName=font_name, fontSize=9, leading=11, textColor=colors.white)

        def _c(text):
            return Paragraph(str(text) if text else '—', _cell_style)
        def _h(text):
            return Paragraph(str(text), _cell_hdr)

        # ── 封面 ──
        story.append(Spacer(1, 50*mm))
        story.append(Paragraph('OpenGaokao', ParagraphStyle(
            'Logo', fontName=font_name, fontSize=28,
            alignment=1, textColor=colors.HexColor('#1565C0'),
        )))
        story.append(Spacer(1, 8*mm))
        story.append(Paragraph('高考志愿推荐', ParagraphStyle(
            'FreeSubTitle', fontName=font_name, fontSize=14,
            alignment=1, textColor=colors.HexColor('#666666'),
        )))
        story.append(Spacer(1, 15*mm))
        # 个性化标题
        student_name = getattr(p, 'student_name', '考生') if p else '考生'
        story.append(Paragraph(f'{student_name}同学 偏好问卷辅助报告', title_style))
        story.append(Spacer(1, 10*mm))
        story.append(Paragraph('项目自编问卷，未经心理测量学验证，不作诊断', ParagraphStyle(
            'Subtitle', fontName=font_name, fontSize=12,
            alignment=1, textColor=colors.HexColor('#888888'),
        )))
        story.append(Spacer(1, 15*mm))
        holland_code = p.holland_code if p else '未测试'
        story.append(Paragraph(f'RIASEC 风格代码: {holland_code}', ParagraphStyle(
            'HCode', fontName=font_name, fontSize=14,
            alignment=1, textColor=colors.HexColor('#1a237e'),
        )))
        # 作答一致性指标（不是心理测量学效度）
        if p and hasattr(p, 'sd_score'):
            validity = int(p.sd_score / 4 * 100) if p.sd_score else 0
            story.append(Spacer(1, 5*mm))
            story.append(Paragraph(f'作答一致性指标: {validity}%', ParagraphStyle(
                'Validity', fontName=font_name, fontSize=11,
                alignment=1, textColor=colors.HexColor('#1565C0'),
            )))
        story.append(Spacer(1, 10*mm))
        story.append(Paragraph(f'报告生成日期：{datetime.now().strftime("%Y年%m月%d日")}', ParagraphStyle(
            'Date', fontName=font_name, fontSize=10,
            alignment=1, textColor=colors.HexColor('#999999'),
        )))

        story.append(PageBreak())

        # ── 一、项目自编大五维度问卷（雷达图 + 行为解读）──
        story.append(Paragraph('一、大五维度偏好（项目自编）', heading_style))

        if p and p.big_five:
            bf = p.big_five
            dims = [
                ('O', '开放性', bf.get('O', 3)),
                ('C', '尽责性', bf.get('C', 3)),
                ('E', '外向性', bf.get('E', 3)),
                ('A', '宜人性', bf.get('A', 3)),
                ('N', '神经质', bf.get('N', 3)),
            ]

            # 雷达图
            d = Drawing(200, 200)
            r_cx, r_cy, r_radius = 100, 100, 70
            from reportlab.graphics.shapes import Circle, Line, PolyLine
            # 同心圆
            for level in [0.2, 0.4, 0.6, 0.8, 1.0]:
                r = r_radius * level
                d.add(Circle(r_cx, r_cy, r,
                             fillColor=None, strokeColor=colors.HexColor('#e0e0e0'), strokeWidth=0.5))
            # 轴线和标签
            for i, (code, label, score) in enumerate(dims):
                angle = 2 * 3.14159 * i / 5 - 3.14159 / 2
                x_end = r_cx + r_radius * math.cos(angle)
                y_end = r_cy + r_radius * math.sin(angle)
                d.add(Line(r_cx, r_cy, x_end, y_end,
                           strokeColor=colors.HexColor('#cccccc'), strokeWidth=0.5))
                lx = r_cx + (r_radius + 18) * math.cos(angle)
                ly = r_cy + (r_radius + 18) * math.sin(angle)
                d.add(String(lx - 15, ly - 4, f'{label}({code})',
                             fontName=font_name, fontSize=7, fillColor=colors.HexColor('#333333')))
            # 数据多边形
            points = []
            for i, (code, label, score) in enumerate(dims):
                angle = 2 * 3.14159 * i / 5 - 3.14159 / 2
                r = r_radius * (score / 5.0)
                points.append((r_cx + r * math.cos(angle),
                               r_cy + r * math.sin(angle)))
            import itertools
            flat_points = list(itertools.chain.from_iterable(points))
            flat_points.append(points[0][0])
            flat_points.append(points[0][1])
            d.add(PolyLine(flat_points,
                           strokeColor=colors.HexColor('#1565C0'), strokeWidth=2))
            d.add(PolyLine(flat_points,
                           fillColor=colors.HexColor('#1565C0'), fillOpacity=0.15,
                           strokeColor=None))
            story.append(d)
            story.append(Spacer(1, 10))

            # 行为解读
            interpretations = {
                'O': {
                    'high': '开放性高 → 适合创新探索类专业：新闻学、艺术设计、心理学、社会学',
                    'low': '开放性低 → 适合规范化、结构化专业：会计、财务管理、档案管理',
                },
                'C': {
                    'high': '尽责性高 → 适合需要严谨态度的专业：医学、法学、会计、建筑',
                    'low': '尽责性低 → 适合灵活自主型专业：创意媒体、自由职业导向专业',
                },
                'E': {
                    'high': '外向性高 → 适合人际交往频繁专业：市场营销、旅游管理、师范类',
                    'low': '外向性低 → 适合独立研究型专业：计算机科学、数据分析、实验室研究',
                },
                'A': {
                    'high': '宜人性高 → 适合服务他人型专业：护理学、教育学、社会工作、心理学',
                    'low': '宜人性低 → 适合竞争分析型专业：法学、金融学、工商管理',
                },
                'N': {
                    'high': '神经质高 → 建议选择压力较低、节奏稳定的专业方向',
                    'low': '神经质低（情绪稳定） → 适合高压环境专业：临床医学、法学、应急管理',
                },
            }
            story.append(Paragraph('行为解读', subheading_style))
            for code, label, score in dims:
                level = 'high' if score >= 3.5 else 'low'
                interp = interpretations.get(code, {}).get(level, '')
                if interp:
                    story.append(Paragraph(f'· {label} {code}={score:.1f}：{interp}', normal_style))
            story.append(Spacer(1, 10))

        story.append(PageBreak())

        # ── 二、项目自编 RIASEC 风格兴趣偏好（柱状图 + 解读）──
        story.append(Paragraph('二、RIASEC 风格兴趣偏好（项目自编）', heading_style))

        if p:
            holland_scores = getattr(p, 'holland_scores', {}) or {}
            RIASEC = ['R', 'I', 'A', 'S', 'E', 'C']
            RIASEC_LABELS = {
                'R': '实际型', 'I': '研究型', 'A': '艺术型',
                'S': '社会型', 'E': '企业型', 'C': '常规型',
            }

            # 柱状图
            d2 = Drawing(200, 150)
            bc = VerticalBarChart()
            bc.x = 30
            bc.y = 20
            bc.height = 110
            bc.width = 140
            bc.data = [[holland_scores.get(c, 0) for c in RIASEC]]
            bc.categoryAxis.categoryNames = RIASEC
            bc.bars[0].fillColor = colors.HexColor('#1565C0')
            bc.strokeColor = colors.white
            bc.valueAxis.valueMin = 0
            bc.valueAxis.valueMax = 100
            bc.valueAxis.valueStep = 25
            bc.valueAxis.labels.fontSize = 7
            bc.categoryAxis.labels.fontSize = 7
            bc.categoryAxis.labels.fontName = font_name
            bc.valueAxis.labels.fontName = font_name
            d2.add(bc)
            story.append(d2)
            story.append(Spacer(1, 10))

            # 解读
            story.append(Paragraph(f'项目自编问卷生成的 RIASEC 风格代码为【{holland_code}】', ParagraphStyle(
                'HC', fontName=font_name, fontSize=12, leading=18,
                textColor=colors.HexColor('#1a237e'), alignment=1,
            )))
            holland_descriptions = {
                'R': '动手能力强，喜欢操作机械和工具，适合工程技术类职业',
                'I': '分析思考能力突出，喜欢探索未知，适合科学研究类职业',
                'A': '创新意识和审美追求强，适合艺术设计和创意类职业',
                'S': '人际交往能力好，喜欢帮助他人，适合教育服务类职业',
                'E': '领导力和目标导向强，适合管理和商务类职业',
                'C': '注重秩序和规则，擅长精细操作，适合财务和行政类职业',
            }
            for ch in holland_code:
                if ch in holland_descriptions:
                    story.append(Paragraph(
                        f'· {ch}（{RIASEC_LABELS.get(ch, "")}）：{holland_descriptions[ch]}',
                        normal_style,
                    ))
            story.append(Spacer(1, 10))

        story.append(PageBreak())

        # ── 三、学科自我评价（9科）──
        story.append(Paragraph('三、学科自我评价（项目自编，9科）', heading_style))

        if p:
            se = p.self_efficacy or {}
            subjects_9 = [
                ('chinese', '语文'), ('math', '数学'), ('english', '英语'),
                ('physics', '物理'), ('chemistry', '化学'), ('biology', '生物'),
                ('history', '历史'), ('politics', '政治'), ('geography', '地理'),
            ]

            # 学科自我评价表格
            efficacy_data = [[_h('科目'), _h('得分(1-5)'), _h('能力评估')]]
            for key, label in subjects_9:
                score = se.get(key, 0)
                if score >= 4:
                    level = '强项 → 可作为专业选择的优势基础'
                    level_color = '#2e7d32'
                elif score >= 3:
                    level = '中等 → 正常发挥即可'
                    level_color = '#f57c00'
                else:
                    level = '弱项 → 建议避开相关依赖专业'
                    level_color = '#c62828'
                efficacy_data.append([
                    _c(label), _c(f'{score:.1f}'),
                    Paragraph(level, ParagraphStyle(
                        f'EL{key}', fontName=font_name, fontSize=8,
                        leading=12, textColor=colors.HexColor(level_color),
                    )),
                ])
            efficacy_table = Table(efficacy_data, colWidths=[25*mm, 25*mm, 110*mm])
            efficacy_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e3f2fd')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(efficacy_table)
            story.append(Spacer(1, 10))

            # 强项分析
            strong_subjects = [(label, se.get(key, 0)) for key, label in subjects_9 if se.get(key, 0) >= 4]
            if strong_subjects:
                story.append(Paragraph('您的优势学科及对应专业方向：', subheading_style))
                major_mapping = {
                    '语文': '汉语言文学、新闻传播、教育学',
                    '数学': '数学、计算机科学、统计学、金融学',
                    '英语': '英语、翻译、国际贸易、外交学',
                    '物理': '物理学、机械工程、电子信息、航空航天',
                    '化学': '化学、化工、药学、材料科学',
                    '生物': '生物学、医学、农学、环境科学',
                    '历史': '历史学、考古学、博物馆学',
                    '政治': '政治学、法学、国际关系、行政管理',
                    '地理': '地理科学、城市规划、测绘工程',
                }
                for label, score in strong_subjects:
                    majors = major_mapping.get(label, '')
                    story.append(Paragraph(f'· {label}（{score:.1f}/5）→ {majors}', normal_style))

        story.append(PageBreak())

        # ── 四、专业推荐TOP10 ──
        story.append(Paragraph('四、专业推荐（TOP 10）', heading_style))

        if p and p.recommendations:
            for i, major in enumerate(p.recommendations[:10], 1):
                story.append(Paragraph(f'{i}. {major}', normal_style))
        else:
            story.append(Paragraph('暂无推荐数据', normal_style))

        story.append(Spacer(1, 15))

        # ── 五、志愿填报注意事项 ──
        story.append(Paragraph('五、志愿填报注意事项', heading_style))

        notes = [
            '1. <b>平行志愿规则</b>：分数优先、遵循志愿、一轮投档。一旦投档，后续志愿失效。',
            '2. <b>冲稳保策略</b>：冲刺院校占15-30%，稳妥院校占30-60%，保底院校占20-40%。',
            '3. <b>服从专业调剂（重要）</b>：云南新高考采用"院校专业组"模式，投档后若所填专业分数不够，<b>如不服从调剂将被直接退档</b>，本批次后续志愿不再检索。<b>建议在冲档志愿中勾选"服从专业调剂"</b>。',
            '3.1 <b>专业级差风险</b>：少数老牌强校（部分财经/政法/传统工科）在专业组内仍采用"专业级差"规则（第二志愿扣3分再排队），易调剂到组内最冷门专业。<b>填报前请查阅目标院校《招生章程》"专业录取规则"条款</b>，确认是"分数优先（无级差）"还是"专业级差"。若为级差，第一专业必须填报往年录取位次远低于自己当前位次的"绝对稳妥"专业。',
            '4. <b>体检限制</b>：色盲/色弱不能报考化学、医学、生物等专业；近视影响军校、飞行技术。',
            '5. <b>批次顺序</b>：提前批 → 本科批 → 专科批，各批次独立投档。',
            '6. <b>新高考选科要求</b>：3+1+2模式需确认选考科目与目标专业匹配。',
            '7. <b>学费差异</b>：中外合作办学（3-8万/年，4年总12-32万）、民办院校（1.5-3万/年）远高于公办（0.5-0.8万/年）。',
            '8. <b>中外合作办学限制</b>：学籍单独编码，几乎不能转入该校普通类专业；部分项目需赴海外完成2年学业。',
        ]
        for note in notes:
            story.append(Paragraph(note, normal_style))

        story.append(Spacer(1, 15))

        # ── 六、志愿填报完整流程 ──
        story.append(Paragraph('六、志愿填报完整流程', heading_style))

        steps = [
            ('第1步：高考出分', '查询一分一段表，确认自己的全省位次和分数段'),
            ('第2步：确定目标专业', '结合项目自编偏好问卷结果和个人兴趣，确定2-5个目标专业方向'),
            ('第3步：筛选院校', '根据位次筛选可报考的院校，分为冲/稳/保三个档次'),
            ('第4步：了解专业', '查询目标专业的核心课程、就业方向、深造路径和行业趋势'),
            ('第5步：核对体检', '确认体检结果不影响目标专业录取，注意色觉/视力/身高等限制'),
            ('第6步：排列志愿', '按冲稳保顺序排列志愿表，每个批次尽量填报满额'),
            ('第7步：提交确认', '仔细核对志愿信息后提交，注意各省截止时间不可修改'),
        ]
        step_data = [[_h('步骤'), _h('具体内容')]]
        step_data.extend([[_c(step), _c(desc)] for step, desc in steps])
        step_table = Table(step_data, colWidths=[40*mm, 120*mm])
        step_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1565C0')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#e3f2fd')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(step_table)

        story.append(Spacer(1, 15))

        # ── 七、样例院校展示（免费层非个性化预览）──
        story.append(Paragraph('七、样例院校展示', heading_style))
        story.append(Paragraph(
            '以下为系统可覆盖的部分院校样例（非个性化推荐）。'
            '完整流程可生成基于分数、位次和偏好问卷的冲/稳/保参考方案：',
            normal_style,
        ))
        story.append(Spacer(1, 5))
        try:
            _conn_preview = sqlite3.connect(self.db_path, check_same_thread=False)
            _cur_preview = _conn_preview.cursor()
            _cur_preview.execute(
                "SELECT DISTINCT school_name, location, school_level FROM v_enroll_detail "
                "WHERE subject_type=? AND min_rank IS NOT NULL ORDER BY min_rank DESC LIMIT 3",
                (getattr(p, 'category', '物理类'),),
            )
            _preview_schools = _cur_preview.fetchall()
            _conn_preview.close()
            if _preview_schools:
                preview_data = [[_h('序号'), _h('院校名称'), _h('地点'), _h('层级')]]
                for i, (sname, sloc, slevel) in enumerate(_preview_schools, 1):
                    preview_data.append([_c(str(i)), _c(sname), _c(sloc or '—'), _c(slevel or '—')])
                preview_table = Table(preview_data, colWidths=[15*mm, 60*mm, 45*mm, 40*mm])
                preview_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), font_name),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e3f2fd')),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                story.append(preview_table)
                story.append(Spacer(1, 5))
                story.append(Paragraph(
                    '<font size="8" color="#888888">↑ 以上为样例院校展示，非个性化推荐。升级后将基于您的分数/位次精确匹配冲/稳/保各档院校。</font>',
                    ParagraphStyle('PreviewNote', fontName=font_name, fontSize=8,
                                   leading=11, textColor=colors.HexColor('#888888')),
                ))
            else:
                story.append(Paragraph('暂无样例数据，升级后可获取精确匹配结果。', normal_style))
        except Exception:
            story.append(Paragraph('升级后可获取精确院校匹配数据。', normal_style))

        story.append(Spacer(1, 10))
        story.append(Paragraph(
            '<b>提示</b>：升级至数据层（¥899）可获取完整冲稳保数据表 + 禁忌项报告；'
            '升级至方案层（¥2999）可获取全量批次推荐 + AI个性化解读；'
            '升级至深度层（¥3999）可获取院校深度解析 + 城市产业分析 + 保研考研就业策略。',
            ParagraphStyle('Upsell', fontName=font_name, fontSize=9,
                           leading=14, textColor=colors.HexColor('#1565C0'),
                           alignment=1),
        ))

        doc.build(story)
        return output_path

    def generate_pdf_report(self, matching_result, output_path: str = None) -> str:
        if output_path is None:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = os.path.join(
                self.output_dir,
                f'志愿推荐方案_{matching_result.questionnaire.name}_{ts}.pdf',
            )

        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import mm, cm
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
                Image as PlatypusImage, Flowable,
            )
            from reportlab.lib import colors
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont

            font_name = _get_chinese_font()

            doc = SimpleDocTemplate(
                output_path, pagesize=A4,
                rightMargin=20*mm, leftMargin=20*mm,
                topMargin=20*mm, bottomMargin=20*mm,
            )

            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'CustomTitle', parent=styles['Title'],
                fontName=font_name, fontSize=24, leading=30,
                spaceAfter=30, alignment=1,
            )
            heading_style = ParagraphStyle(
                'CustomHeading', parent=styles['Heading1'],
                fontName=font_name, fontSize=16, leading=20,
                spaceAfter=12, textColor=colors.HexColor('#1a1a1a'),
            )
            subheading_style = ParagraphStyle(
                'CustomSubHeading', parent=styles['Heading2'],
                fontName=font_name, fontSize=12, leading=16,
                spaceAfter=8, textColor=colors.HexColor('#333333'),
            )
            normal_style = ParagraphStyle(
                'CustomNormal', parent=styles['Normal'],
                fontName=font_name, fontSize=10, leading=14, spaceAfter=6,
            )

            story = []
            # ── 封面 ──
            story.append(Spacer(1, 50*mm))
            story.append(Paragraph('OpenGaokao', ParagraphStyle(
                'CoverLogo', fontName=font_name, fontSize=28,
                alignment=1, textColor=colors.HexColor('#1565C0'),
            )))
            story.append(Spacer(1, 8*mm))
            story.append(Paragraph('高考志愿推荐', ParagraphStyle(
                'CoverSubTitle', fontName=font_name, fontSize=14,
                alignment=1, textColor=colors.HexColor('#666666'),
            )))
            story.append(Spacer(1, 15*mm))
            q = matching_result.questionnaire
            story.append(Paragraph(f'{q.name}同学 专属志愿规划方案', title_style))
            story.append(Spacer(1, 8*mm))
            story.append(Paragraph(
                f'{q.category} · {q.total_score}分 · 位次{q.rank}',
                ParagraphStyle('CoverInfo', fontName=font_name, fontSize=14,
                               alignment=1, textColor=colors.HexColor('#333333')),
            ))
            story.append(Spacer(1, 5*mm))
            story.append(Paragraph(
                '录取数据 + 项目自编偏好问卷（非心理诊断）',
                ParagraphStyle('CoverInfo2', fontName=font_name, fontSize=12,
                               alignment=1, textColor=colors.HexColor('#888888')),
            ))
            story.append(Spacer(1, 10*mm))
            story.append(Paragraph(
                f'报告生成日期：{datetime.now().strftime("%Y年%m月%d日")}',
                ParagraphStyle('CoverDate', fontName=font_name, fontSize=10,
                               alignment=1, textColor=colors.HexColor('#999999')),
            ))
            story.append(PageBreak())

            # 基本信息
            story.append(Paragraph('一、考生基本信息', heading_style))
            q = matching_result.questionnaire

            cell_style = ParagraphStyle('Cell', fontName=font_name, fontSize=10, leading=12, textColor=colors.HexColor('#333333'))
            cell_hdr = ParagraphStyle('CellHdr', fontName=font_name, fontSize=10, leading=12, textColor=colors.white)

            def _c(text):
                return Paragraph(str(text) if text else '—', cell_style)
            def _h(text):
                return Paragraph(str(text), cell_hdr)

            info_data = [
                [_c('姓名'), _c(q.name), _c('科类'), _c(q.category)],
                [_c('总分'), _c(str(q.total_score)), _c('位次'), _c(str(q.rank))],
                [_c('性别'), _c(q.gender), _c('本地标识码'), _c(q.exam_id or '—')],
            ]
            info_table = Table(
                info_data, colWidths=[30*mm, 50*mm, 30*mm, 50*mm],
            )
            info_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ]))
            story.append(info_table)
            story.append(Spacer(1, 15))

            # P1-4 必读告警区（合规要点 — 报告头部显著位置）
            must_ack = getattr(matching_result, 'must_ack_warnings', []) or []
            if must_ack:
                ack_title_style = ParagraphStyle(
                    'MustAckTitle', parent=heading_style,
                    fontName=font_name, fontSize=12, leading=16,
                    textColor=colors.HexColor('#c62828'),
                    spaceBefore=4, spaceAfter=6,
                )
                ack_body_style = ParagraphStyle(
                    'MustAckBody', parent=normal_style,
                    fontName=font_name, fontSize=9, leading=13,
                    textColor=colors.HexColor('#333333'),
                    leftIndent=10,
                    backColor=colors.HexColor('#ffebee'),
                    borderColor=colors.HexColor('#c62828'),
                    borderWidth=1, borderPadding=5,
                    spaceAfter=4,
                )
                story.append(Paragraph('📌 必读提示（请逐条阅读）', ack_title_style))
                for i, w in enumerate(must_ack, 1):
                    story.append(Paragraph(f'{i}. {w}', ack_body_style))
                story.append(Spacer(1, 10))

            # 项目自编偏好问卷结果 V3.0
            if matching_result.personality_result:
                story.append(Paragraph('二、偏好问卷结果（项目自编，非心理诊断）', heading_style))
                p = matching_result.personality_result

                bf = p.big_five
                personality_data = [
                    [_c('大五维度偏好'), _c(f"O={bf.get('O', 0)} C={bf.get('C', 0)} E={bf.get('E', 0)} A={bf.get('A', 0)} N={bf.get('N', 0)}"), _c('RIASEC 风格代码'), _c(p.holland_code)],
                    [_c('置信度'), _c(_translate_term(p.confidence)), _c('SD检测'), _c(f'{p.sd_score}/4')],
                ]
                personality_table = Table(
                    personality_data, colWidths=[30*mm, 50*mm, 30*mm, 50*mm],
                )
                personality_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), font_name),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                story.append(personality_table)
                story.append(Spacer(1, 10))

                # 学科自我评价
                se = p.self_efficacy or {}
                story.append(Paragraph('学科自我评价（项目自编）', subheading_style))
                story.append(Paragraph(
                    f"语文: {se.get('chinese', 0)}/5  "
                    f"数学: {se.get('math', 0)}/5  "
                    f"英语: {se.get('english', 0)}/5",
                    normal_style,
                ))
                story.append(Spacer(1, 10))

                # 职业价值偏好
                cv = p.career_values or {}
                story.append(Paragraph('职业价值偏好（项目自编）', subheading_style))
                for dim_name, dim_label in [
                    ('income', '收入水平'), ('stability', '工作稳定'),
                    ('achievement', '成就感'), ('help', '帮助他人'),
                    ('creative', '创造力'), ('balance', '工作生活平衡'),
                    ('leadership', '领导力'), ('autonomy', '独立性'),
                    ('location', '地域偏好'), ('learning', '持续学习'),
                ]:
                    story.append(Paragraph(
                        f"{dim_label}: {cv.get(dim_name, 0)}/5", normal_style,
                    ))
                story.append(Spacer(1, 10))

                # 专业推荐（融合用户意愿+项目自编偏好问卷）
                story.append(Paragraph('推荐专业（TOP 10）', subheading_style))
                _q = matching_result.questionnaire
                _seen_m = set()
                _merged = []
                if _q.vertical_majors:
                    for m in _q.vertical_majors:
                        if m != '都不考虑' and m not in _seen_m:
                            _seen_m.add(m)
                            _merged.append(f'{len(_merged)+1}. {m} ✓ 您的偏好')
                if _q.acceptable_majors:
                    for m in _q.acceptable_majors:
                        if m not in _seen_m:
                            _seen_m.add(m)
                            _merged.append(f'{len(_merged)+1}. {m} ✓ 您的偏好')
                # 补充偏好问卷方向（最多2个）
                _pc = 0
                for m in p.recommendations:
                    if m not in _seen_m and _pc < 2:
                        _seen_m.add(m)
                        _merged.append(f'{len(_merged)+1}. {m} ⚠️ 偏好问卷方向参考')
                        _pc += 1
                # 兜底：如果仍不足，显示剩余偏好问卷方向
                for m in p.recommendations:
                    if m not in _seen_m and len(_merged) < 10:
                        _seen_m.add(m)
                        _merged.append(f'{len(_merged)+1}. {m}')
                for line in _merged[:10]:
                    story.append(Paragraph(line, normal_style))
                story.append(Spacer(1, 15))

            # ── 标准层: 大五维度雷达图 ──
            if matching_result.personality_result:
                from reportlab.graphics.shapes import Drawing
                from reportlab.graphics import renderPDF

                p = matching_result.personality_result
                bf = p.big_five or {}

                # 创建雷达图Drawing
                d = Drawing(180, 180)
                from reportlab.graphics.shapes import (
                    Circle, Line, String, PolyLine, Group,
                )
                from reportlab.lib import colors

                g = Group()
                r_cx, r_cy = 90, 90
                r_radius = 60
                dims = [
                    ('E', '外向性'), ('A', '宜人性'),
                    ('C', '尽责性'), ('N', '神经质'), ('O', '开放性'),
                ]
                n = len(dims)
                angle_step = 2 * math.pi / n

                # 同心圆
                for r_level in [0.2, 0.4, 0.6, 0.8, 1.0]:
                    g.add(Circle(r_cx, r_cy, r_radius * r_level,
                                 strokeColor=colors.HexColor('#dddddd'),
                                 strokeWidth=0.3, fillColor=None))

                # 主轴
                for i in range(n):
                    angle = -math.pi / 2 + i * angle_step
                    x = r_cx + r_radius * math.cos(angle)
                    y = r_cy + r_radius * math.sin(angle)
                    g.add(Line(r_cx, r_cy, x, y,
                               strokeColor=colors.HexColor('#dddddd'), strokeWidth=0.3))
                    lx = r_cx + (r_radius + 14) * math.cos(angle)
                    ly = r_cy + (r_radius + 14) * math.sin(angle)
                    g.add(String(lx - 8, ly, dims[i][1],
                                 fontSize=8, fillColor=colors.HexColor('#333333')))

                # 数据多边形
                data_points = []
                for i, (key, label) in enumerate(dims):
                    angle = -math.pi / 2 + i * angle_step
                    raw = bf.get(key, 0)
                    normalized = min(raw / 5.0, 1.0)
                    x = r_cx + r_radius * normalized * math.cos(angle)
                    y = r_cy + r_radius * normalized * math.sin(angle)
                    data_points.append((x, y))

                if len(data_points) >= 3:
                    pts = list(data_points) + [data_points[0]]
                    # Flatten: [x1,y1,x2,y2,...]
                    flat = []
                    for p in pts:
                        flat.extend(p)
                    g.add(PolyLine(flat,
                                   strokeColor=colors.HexColor('#2196F3'),
                                   strokeWidth=2, fillColor=colors.HexColor('#2196F3'),
                                   fillOpacity=0.2,
                    ))
                    # 数据点
                    for x, y in data_points:
                        g.add(Circle(x, y, 3,
                                     strokeColor=colors.HexColor('#2196F3'),
                                     strokeWidth=1, fillColor=colors.HexColor('#2196F3')))

                d.add(g)

                # 自定义Flowable: 在PDF流中嵌入Drawing
                from reportlab.graphics import renderPDF

                class DrawingWrapper(Flowable):
                    def __init__(self, drawing, width, height):
                        Flowable.__init__(self)
                        self._d = drawing
                        self._w = width
                        self._h = height

                    def wrap(self, aW, aH):
                        return self._w, self._h

                    def draw(self):
                        renderPDF.draw(self._d, self.canv, 0, 0)

                story.append(Spacer(1, 10))
                story.append(Paragraph('大五维度偏好画像（非诊断）', subheading_style))
                story.append(Spacer(1, 5))
                story.append(DrawingWrapper(d, 180, 180))
                story.append(Spacer(1, 10))

            # ── 标准层: AI个性化解读 ──
            narratives = self._generate_ai_narrative(
                matching_result.personality_result,
                matching_result.recommendations,
                matching_result,
            )
            if narratives:
                story.append(Spacer(1, 5))
                story.append(Paragraph('AI个性化解读', subheading_style))
                for narrative in narratives:
                    story.append(Paragraph(f"· {narrative}", normal_style))
                story.append(Spacer(1, 15))

            # ── 禁忌项风险检测报告（新增）──
            cr = getattr(matching_result, 'constraint_result', None)
            if cr:
                story.append(Paragraph('三、禁忌项风险检测报告', heading_style))
                alert_red = ParagraphStyle(
                    'ConstraintAlert', parent=normal_style,
                    fontName=font_name, fontSize=10,
                    textColor=colors.HexColor('#c62828'), leading=15,
                )
                alert_green = ParagraphStyle(
                    'ConstraintOK', parent=normal_style,
                    fontName=font_name, fontSize=10,
                    textColor=colors.HexColor('#2e7d32'), leading=15,
                )
                if cr.hard_filtered:
                    story.append(Paragraph(
                        '<b>⚠️ 硬性过滤触发：体检结果不符合录取条件</b><br/>'
                        '系统已不予录取。建议联系体检医院复核结果，或咨询省招生考试院。',
                        alert_red,
                    ))
                else:
                    story.append(Paragraph('✅ 无硬性过滤项（不予录取类未发现）', alert_green))
                story.append(Spacer(1, 5))
                story.append(Paragraph('受限专业清单', subheading_style))
                if cr.filtered_majors:
                    restricted_rows = [['受限专业']]
                    for major in cr.filtered_majors[:15]:
                        restricted_rows.append([Paragraph(
                            f'⛔ {major}',
                            ParagraphStyle('RI', fontName=font_name, fontSize=9,
                                           leading=12, textColor=colors.HexColor('#c62828')),
                        )])
                    r_table = Table(restricted_rows, colWidths=[160*mm])
                    r_table.setStyle(TableStyle([
                        ('FONTNAME', (0, 0), (-1, -1), font_name),
                        ('FONTSIZE', (0, 0), (0, 0), 10),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#ffcdd2')),
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ffcdd2')),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('LEFTPADDING', (0, 0), (-1, -1), 8),
                    ]))
                    story.append(r_table)
                    story.append(Spacer(1, 5))
                    story.append(Paragraph(
                        f'共{len(cr.filtered_majors)}个专业受限，推荐方案已自动过滤。',
                        ParagraphStyle('RN', fontName=font_name, fontSize=9,
                                       leading=12, textColor=colors.HexColor('#666666')),
                    ))
                else:
                    story.append(Paragraph('无受限专业', normal_style))
                story.append(Spacer(1, 8))
                story.append(Paragraph('军警校报考资格', subheading_style))
                qual_data = [
                    ['警校资格', '✅ 合格' if cr.police_qualified else '❌ 不合格'],
                    ['军校资格', '✅ 合格' if cr.military_qualified else '❌ 不合格'],
                ]
                qual_table = Table(qual_data, colWidths=[40*mm, 80*mm])
                qual_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), font_name),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                story.append(qual_table)
                if cr.warnings:
                    story.append(Spacer(1, 8))
                    story.append(Paragraph('检测提示', subheading_style))
                    for warn in cr.warnings[:8]:
                        story.append(Paragraph(f'· {warn}', normal_style))
                story.append(Spacer(1, 10))

            # ── 家庭资源评估（新增）──
            fr = getattr(matching_result, 'family_resource_result', None)
            if fr:
                story.append(Paragraph('四、家庭资源评估', heading_style))
                rating_color_map = {'高': '#2e7d32', '中': '#f57c00', '低': '#c62828'}
                rating_style = ParagraphStyle(
                    'FamilyRating', parent=normal_style,
                    fontName=font_name, fontSize=24, leading=30,
                    alignment=1, textColor=colors.HexColor(rating_color_map.get(fr.rating, '#333333')),
                )
                story.append(Paragraph(f'家庭就业支持能力：<b>{fr.rating}</b>', rating_style))
                story.append(Spacer(1, 5))
                capital_data = [
                    ['资本类型', '得分', '说明'],
                    ['经济资本', f'{fr.economic_capital:.1f}/100', '家庭收入+学费承受力+实习机会'],
                    ['文化资本', f'{fr.cultural_capital:.1f}/100', '父母教育水平+家庭文化环境'],
                    ['社会资本', f'{fr.social_capital:.1f}/100', '父母职业阶层+社会网络'],
                    ['综合得分', f'{fr.total_score:.1f}/100', ''],
                ]
                capital_table = Table(capital_data, colWidths=[30*mm, 35*mm, 95*mm])
                capital_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), font_name),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e3f2fd')),
                    ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f5f5f5')),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                story.append(capital_table)
                story.append(Spacer(1, 8))
                if fr.suggestions:
                    story.append(Paragraph('专业选择建议', subheading_style))
                    for sug in fr.suggestions:
                        story.append(Paragraph(f'· {sug}', normal_style))
                    story.append(Spacer(1, 10))

            # 志愿偏好
            story.append(Paragraph('五、志愿偏好', heading_style))
            excluded = []
            if hasattr(q, 'vertical_majors') and '都不考虑' in (q.vertical_majors or []):
                excluded.append('垂直类专业')
            if q.medical_preference == '绝对不考虑':
                excluded.append('医学类')

            preference_data = [
                ['核心诉求', q.core_demand or '未定'],
                ['目标行业', ', '.join(q.target_industries) if q.target_industries else '未定'],
                ['可接受专业', ', '.join(q.acceptable_majors) if q.acceptable_majors else '未定'],
                ['排除专业', ', '.join(excluded) if excluded else '无'],
                ['稳定性偏好', f'{q.stability_preference}/5'],
                ['风险策略', _translate_term(matching_result.risk_strategy)],
            ]
            preference_table = Table(
                preference_data, colWidths=[40*mm, 120*mm],
            )
            preference_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(preference_table)
            story.append(Spacer(1, 15))

            # ── 意愿冲突检测 ──
            intention = getattr(matching_result, 'intention_profile', None)
            if intention and getattr(intention, 'conflicts', None):
                story.append(Paragraph('六、意愿冲突提示', heading_style))
                story.append(Spacer(1, 5))

                warning_style = ParagraphStyle(
                    'ConflictWarning', parent=normal_style,
                    fontName=font_name, fontSize=10,
                    textColor=colors.HexColor('#d32f2f'),
                )

                for conflict in intention.conflicts:
                    ctype = getattr(conflict, 'conflict_type', '')
                    cdesc = getattr(conflict, 'description', getattr(conflict, 'message', ''))
                    severity = getattr(conflict, 'severity', 'warning')

                    icon = '🔴' if severity == 'alert' else '🟡'
                    story.append(Paragraph(
                        f'{icon} [{ctype}] {cdesc}', warning_style,
                    ))
                story.append(Spacer(1, 15))

            # 推荐方案 — 按批次组织
            story.append(Paragraph('七、推荐方案', heading_style))

            # 导入批次配置
            from gaokao.core.volunteer_recommender import BATCH_ADMISSION_ORDER

            # 按批次分组
            batch_groups = {}
            for category in ['冲', '稳', '保', '垫']:
                for school in matching_result.recommendations.get(category, []):
                    school._chong_wen_bao = category
                    b = school.batch if school.batch else '其他'
                    if b not in batch_groups:
                        batch_groups[b] = []
                    batch_groups[b].append(school)

            # 按批次顺序输出
            def _batch_sort_key(key):
                if key in BATCH_ADMISSION_ORDER:
                    return BATCH_ADMISSION_ORDER.index(key)
                return 999

            sorted_batches = sorted(batch_groups.keys(), key=_batch_sort_key)

            for batch_idx, batch_key in enumerate(sorted_batches):
                schools = batch_groups[batch_key]
                story.append(Paragraph(f'4.{batch_idx+1} {batch_key}', subheading_style))

                # 冲稳保分组
                for category in ['冲', '稳', '保', '垫']:
                    cat_schools = [s for s in schools if getattr(s, '_chong_wen_bao', '') == category]
                    if not cat_schools:
                        continue
                    color_map = {'冲': '#E65100', '稳': '#1565C0', '保': '#2E7D32'}
                    cat_style = ParagraphStyle(
                        f'Cat_{batch_key}_{category}', parent=normal_style,
                        fontName=font_name, fontSize=11, leading=15,
                        spaceBefore=6, spaceAfter=4,
                        textColor=colors.HexColor(color_map.get(category, '#333')),
                    )
                    story.append(Paragraph(f'{category}（{len(cat_schools)}所）', cat_style))

                    # P0-2 闭环：保档若含垫，加红色警示段
                    if category == '保':
                        fallback_count = sum(1 for s in cat_schools if getattr(s, 'safety_warning', None))
                        if fallback_count > 0:
                            warn_style = ParagraphStyle(
                                f'BaoFallback_{batch_key}', parent=normal_style,
                                fontName=font_name, fontSize=9, leading=12,
                                textColor=colors.HexColor('#c62828'),
                                backColor=colors.HexColor('#fff3cd'),
                                borderColor=colors.HexColor('#f57c00'),
                                borderWidth=1, borderPadding=4,
                                spaceBefore=2, spaceAfter=4,
                            )
                            story.append(Paragraph(
                                f'⚠ 注意：本档含 {fallback_count} 所"垫"志愿（50%-85% 概率）。'
                                f'标准保底（≥85%）数量不足，请谨慎评估并优先填写"标准"行。',
                                warn_style,
                            ))

                    table_data = [
                        ['序号', '院校名称', '院校层级', '地点', '录取概率', '置信度', '兜底'],
                    ]
                    table_styles_extra = []
                    for i, school in enumerate(cat_schools[:15], 1):
                        tier_str = f"{school.tier_level} {school.tier_name}" if school.tier_level else school.school_quality
                        # P0-2 闭环：兜底类型列
                        if category == '保':
                            if getattr(school, 'safety_warning', None):
                                bao_cell = '⚠补充'
                                table_styles_extra.append(('TEXTCOLOR', (6, i), (6, i), colors.HexColor('#c62828')))
                                table_styles_extra.append(('FONTNAME', (6, i), (6, i), font_name))
                                table_styles_extra.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#fff8e1')))
                            else:
                                bao_cell = '标准'
                                table_styles_extra.append(('TEXTCOLOR', (6, i), (6, i), colors.HexColor('#2e7d32')))
                        else:
                            bao_cell = '—'
                        table_data.append([
                            str(i), school.school_name, tier_str,
                            school.location, f'{school.probability:.1f}%',
                            _get_confidence_display(school.confidence), bao_cell,
                        ])
                    table = Table(
                        table_data,
                        colWidths=[10*mm, 42*mm, 22*mm, 22*mm, 22*mm, 18*mm, 14*mm],
                    )
                    table.setStyle(TableStyle([
                        ('FONTNAME', (0, 0), (-1, -1), font_name),
                        ('FONTSIZE', (0, 0), (-1, -1), 8),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e0e0')),
                        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ] + table_styles_extra))
                    story.append(table)
                    story.append(Spacer(1, 8))

                # 推荐专业
                pro_majors = [s for s in schools if s.recommended_majors]
                if pro_majors:
                    story.append(Paragraph('推荐专业（TOP 3）', subheading_style))
                    for school in pro_majors[:3]:
                        parts = []
                        for m in school.recommended_majors[:3]:
                            tag = ' [2026新增]' if getattr(m, 'is_new_major', False) else ''
                            risk = getattr(m, 'revocation_risk', 'none')
                            risk_tag = ''
                            if risk == 'rising':
                                risk_tag = ' [撤销↑]'
                            elif risk == 'declining':
                                risk_tag = ' [撤销↓]'
                            emp_rate = getattr(m, 'employment_rate', 0)
                            avg_salary = getattr(m, 'avg_salary', 0)
                            emp_tag = ''
                            if emp_rate or avg_salary:
                                bits = []
                                if emp_rate:
                                    bits.append(f'就业{emp_rate*100:.0f}%')
                                if avg_salary:
                                    bits.append(f'{int(avg_salary)}元')
                                emp_tag = f' ({"/".join(bits)})'
                            parts.append(f'{m.major_name}{tag}{risk_tag}{emp_tag}')
                        ms = ', '.join(parts)
                        line = f'{school.school_name}: {ms}'
                        alts = getattr(school, 'similar_alternatives', []) or []
                        if alts:
                            line += f'<br/><font size="8" color="#666666">如不录取可考虑: {", ".join(alts[:3])}</font>'
                        story.append(Paragraph(line, normal_style))
                    story.append(Spacer(1, 6))

            # ── 标准层: 冲稳保饼图 ──
            chong_count = len(matching_result.recommendations.get('冲', []))
            wen_count = len(matching_result.recommendations.get('稳', []))
            bao_count = len(matching_result.recommendations.get('保', []))
            if chong_count + wen_count + bao_count > 0:
                story.append(Spacer(1, 10))
                story.append(Paragraph('冲稳保分布', subheading_style))
                story.append(Spacer(1, 5))

                from reportlab.graphics.shapes import Drawing
                from reportlab.graphics.charts.piecharts import Pie as PieShape
                from reportlab.graphics import renderPDF

                d_pie = Drawing(280, 140)
                pie = PieShape()
                pie.x = 20
                pie.y = 10
                pie.width = 100
                pie.height = 100
                pie.slices.strokeWidth = 1
                pie.slices.strokeColor = colors.white
                pie.data = [chong_count, wen_count, bao_count]
                pie.slices[0].fillColor = colors.HexColor('#4CAF50')
                pie.slices[1].fillColor = colors.HexColor('#2196F3')
                pie.slices[2].fillColor = colors.HexColor('#FF9800')
                d_pie.add(pie)

                # 总结文字
                total = chong_count + wen_count + bao_count
                pie_text = f'共推荐{total}所院校：冲刺{chong_count}所({chong_count*100//total if total else 0}%)、'
                pie_text += f'稳妥{wen_count}所({wen_count*100//total if total else 0}%)、'
                pie_text += f'保底{bao_count}所({bao_count*100//total if total else 0}%)'

                class DrawingWrapper2(Flowable):
                    def __init__(self, drawing, width, height):
                        Flowable.__init__(self)
                        self._d = drawing
                        self._w = width
                        self._h = height

                    def wrap(self, aW, aH):
                        return self._w, self._h

                    def draw(self):
                        renderPDF.draw(self._d, self.canv, 0, 0)

                story.append(DrawingWrapper2(d_pie, 280, 140))
                story.append(Spacer(1, 5))
                story.append(Paragraph(pie_text, normal_style))

                # 冲稳保比例差异说明（如有）
                from gaokao.core.volunteer_recommender import STRATEGY_CONFIGS
                strategy_cfg = STRATEGY_CONFIGS.get(
                    getattr(matching_result, 'risk_strategy', None),
                    STRATEGY_CONFIGS['balanced'],
                )
                ratio_note = self._get_chong_wen_bao_ratio_note(matching_result, strategy_cfg)
                if ratio_note:
                    story.append(Spacer(1, 5))
                    ratio_style = ParagraphStyle(
                        'RatioNote', fontName=font_name, fontSize=8, leading=11,
                        textColor=colors.HexColor('#d32f2f'),
                        spaceAfter=6,
                    )
                    for line in ratio_note.split('\n'):
                        story.append(Paragraph(line, ratio_style))

            # ── 标准层: 3年录取趋势表 ──
            story.append(Spacer(1, 10))
            story.append(Paragraph('三年录取趋势（推荐院校平均位次变化）', subheading_style))
            story.append(Spacer(1, 5))

            # 从推荐结果中提取趋势数据
            trend_data = []
            for category in ['冲', '稳', '保', '垫']:
                schools = matching_result.recommendations.get(category, [])
                for school in schools[:3]:  # 每个层级取前3所
                    year_records = []
                    try:
                        from gaokao.core.admission_probability import AdmissionProbability
                        ap = AdmissionProbability(db_path=self.db_path)
                        records = ap.get_history_records(
                            school.school_name, subject_type=getattr(q, 'category', '物理类')
                        )
                        for rec in records:
                            if rec.min_rank:
                                year_records.append((rec.year, rec.min_rank))
                        ap.close()
                    except Exception:
                        pass
                    if year_records:
                        year_records.sort()
                        trend_data.append([
                            school.school_name,
                            ' → '.join([f'{y}年{r}名' for y, r in year_records]),
                            # P1-fix: 位次数字越大=排名越差，所以 year_records[-1][1] > year_records[0][1] 表示下降
                            '下降' if year_records[-1][1] > year_records[0][1] else '上升',
                        ])

            if trend_data:
                trend_table_data = [['院校', '近3年位次', '趋势']]
                trend_table_data.extend(trend_data[:9])
                trend_table = Table(
                    trend_table_data,
                    colWidths=[40*mm, 90*mm, 30*mm],
                )
                trend_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), font_name),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e0e0')),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
                ]))
                story.append(trend_table)

            # ── 标准层: 推荐院校画像 ──
            story.append(Spacer(1, 10))
            story.append(Paragraph('推荐院校画像', subheading_style))
            story.append(Spacer(1, 5))
            try:
                from models.school_profile import SchoolProfileManager
                sp_mgr = SchoolProfileManager(db_path=self.db_path)
                profile_sections = []
                for category in ['冲', '稳', '保', '垫']:
                    schools = matching_result.recommendations.get(category, [])
                    for school in schools[:2]:  # 每层取前2所
                        prof = sp_mgr.get_profile(school.school_name)
                        if prof:
                            score = prof.compute_score()
                            tag_str = ' | '.join(prof.tags) if prof.tags else '普通本科'
                            strength = []
                            if prof.num_academicians: strength.append(f'院士{prof.num_academicians}人')
                            if prof.num_phd: strength.append(f'博士{prof.num_phd}个')
                            if prof.num_master: strength.append(f'硕士{prof.num_master}个')
                            if prof.advantage_disciplines: strength.append(f'双一流学科{len(prof.advantage_disciplines)}个')
                            if prof.key_disciplines: strength.append(f'重点学科{len(prof.key_disciplines)}个')
                            strength_str = ' | '.join(strength) if strength else '-'
                            profile_sections.append([
                                school.school_name,
                                tag_str,
                                strength_str,
                                f'{category} / {school.probability} / 评分{score}',
                            ])
                sp_mgr.close()
                if profile_sections:
                    prof_table_data = [['院校名称', '标签', '学术实力', '推荐信息']]
                    prof_table_data.extend(profile_sections)
                    prof_table = Table(
                        prof_table_data,
                        colWidths=[35*mm, 35*mm, 70*mm, 30*mm],
                    )
                    prof_table.setStyle(TableStyle([
                        ('FONTNAME', (0, 0), (-1, -1), font_name),
                        ('FONTSIZE', (0, 0), (-1, -1), 8),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8e8e8')),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
                    ]))
                    story.append(prof_table)
                else:
                    story.append(Paragraph('暂无详细画像数据', normal_style))
            except Exception:
                pass  # 容错：画像加载失败不影响报告生成

            # ── 标准层: 专业兴趣匹配度表 ──
            if matching_result.personality_result:
                story.append(Spacer(1, 10))
                story.append(Paragraph('专业兴趣匹配度', subheading_style))
                story.append(Spacer(1, 5))

                p = matching_result.personality_result
                holland_scores = p.holland_scores or {}
                RIASEC = ['R', 'I', 'A', 'S', 'E', 'C']
                RIASEC_LABELS = {
                    'R': '实际型', 'I': '研究型', 'A': '艺术型',
                    'S': '社会型', 'E': '企业型', 'C': '常规型',
                }

                # 构建热力表
                heatmap_data = [['维度', '分数', '匹配度']]
                for code in RIASEC:
                    score = holland_scores.get(code, 0)
                    pct = min(score, 100)
                    bar = '█' * (pct // 10) + '░' * (10 - pct // 10)
                    heatmap_data.append([
                        f'{code}({RIASEC_LABELS[code]})',
                        f'{score}/100',
                        bar,
                    ])

                heatmap_table = Table(
                    heatmap_data,
                    colWidths=[40*mm, 30*mm, 90*mm],
                )
                heatmap_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), font_name),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e0e0')),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                story.append(heatmap_table)

            # ── 热门学科趋势 ──
            story.append(Spacer(1, 10))
            story.append(Paragraph('热门学科趋势（2025-2045）', heading_style))
            story.append(Spacer(1, 5))
            try:
                from gaokao.core.hot_major_analyzer import HotMajorAnalyzer
                analyzer = HotMajorAnalyzer(db_path=self.db_path)
                hot_scores = analyzer.analyze(year=2025)

                # TOP10热门学科表
                hot_table_data = [
                    ['排名', '专业类', '门类', '综合', '当前', '趋势', '等级'],
                ]
                for s in hot_scores[:10]:
                    hot_table_data.append([
                        str(s.composite_rank),
                        s.major_class,
                        s.category,
                        f'{s.composite_score:.1f}',
                        f'{s.current_score:.1f}',
                        f'{s.trend_score:.1f}',
                        s.level,
                    ])
                hot_table = Table(
                    hot_table_data,
                    colWidths=[10*mm, 35*mm, 20*mm, 15*mm, 15*mm, 15*mm, 12*mm],
                )
                hot_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), font_name),
                    ('FONTSIZE', (0, 0), (-1, -1), 8),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1565C0')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                story.append(hot_table)
                story.append(Spacer(1, 8))
                story.append(Paragraph(
                    '数据源：教育部2026新增38专业 + 5年撤销1.22万专业点 + WEF 2025 + 麦肯锡2040 + 五大集群2045',
                    ParagraphStyle('Small', fontName=font_name, fontSize=7,
                                   leading=9, textColor=colors.HexColor('#888888')),
                ))
                story.append(Spacer(1, 4))
                story.append(Paragraph(
                    '透明度说明：[数据驱动] 新增/撤销专业、WEF 2025岗位增长 | [专家判断] 趋势因子权重、收敛集群评分',
                    ParagraphStyle('Tiny', fontName=font_name, fontSize=6.5,
                                   leading=8, textColor=colors.HexColor('#999999')),
                ))
            except Exception:
                pass  # 容错

            story.append(Spacer(1, 15))

            # ── 冲突检测告警（新增）──
            notes = getattr(matching_result, 'notes', [])
            pool_warning = getattr(matching_result, 'candidate_pool_warning', '') or ''
            if pool_warning:
                notes = list(notes) + [pool_warning]
            ds_warning = getattr(matching_result, 'data_sparsity_warning', '') or ''
            if ds_warning:
                notes = list(notes) + [f'⚠ 数据稀疏提示：{ds_warning}']
            if notes:
                story.append(Paragraph('九、冲突检测与预警', heading_style))
                for note in notes:
                    # 根据关键词判断告警级别
                    is_red = any(kw in note for kw in ['⚠️', '不予录取', '硬性过滤', '严重', '红色'])
                    is_orange = any(kw in note for kw in ['⛔', '受限', '过滤', '橙色', '过窄'])
                    if is_red:
                        note_style = ParagraphStyle(
                            'AlertRed', parent=normal_style,
                            fontName=font_name, fontSize=10, leading=15,
                            textColor=colors.HexColor('#c62828'),
                            leftIndent=10,
                        )
                        prefix = '🔴 '
                    elif is_orange:
                        note_style = ParagraphStyle(
                            'AlertOrange', parent=normal_style,
                            fontName=font_name, fontSize=10, leading=15,
                            textColor=colors.HexColor('#f57c00'),
                            leftIndent=10,
                        )
                        prefix = '🟠 '
                    else:
                        note_style = ParagraphStyle(
                            'AlertYellow', parent=normal_style,
                            fontName=font_name, fontSize=10, leading=15,
                            textColor=colors.HexColor('#795548'),
                            leftIndent=10,
                        )
                        prefix = '🟡 '
                    story.append(Paragraph(f'{prefix}{note}', note_style))
                    story.append(Spacer(1, 3))
                story.append(Spacer(1, 10))

            # ── 降档替代方案（新增）──
            has_alts = False
            for cat in ['冲', '稳', '保', '垫']:
                for school in matching_result.recommendations.get(cat, []):
                    if getattr(school, 'similar_alternatives', []):
                        has_alts = True
                        break
            if has_alts:
                story.append(Paragraph('十、降档替代方案', heading_style))
                story.append(Paragraph(
                    '以下专业如录取风险较大，可选择同专业类内录取门槛更低的替代方案：',
                    ParagraphStyle('AltIntro', fontName=font_name, fontSize=9,
                                   leading=12, textColor=colors.HexColor('#666666'),
                                   spaceAfter=8),
                ))
                alt_rows = [['首选专业', '录取概率', '替代专业（降档）']]
                for cat in ['冲', '稳', '保', '垫']:
                    for school in matching_result.recommendations.get(cat, []):
                        alts = getattr(school, 'similar_alternatives', [])
                        if alts and school.recommended_majors:
                            majors_str = ', '.join(
                                [m.major_name for m in school.recommended_majors[:2]]
                            )
                            alts_str = ' → '.join(alts[:3])
                            alt_rows.append([
                                f'{school.school_name}：{majors_str}',
                                f'{school.probability:.0f}%',
                                alts_str,
                            ])
                if len(alt_rows) > 1:
                    alt_table = Table(alt_rows, colWidths=[55*mm, 25*mm, 80*mm])
                    alt_table.setStyle(TableStyle([
                        ('FONTNAME', (0, 0), (-1, -1), font_name),
                        ('FONTSIZE', (0, 0), (-1, -1), 9),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8e8e8')),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ]))
                    story.append(alt_table)
                story.append(Spacer(1, 10))

            # ── 转专业与大类分流指南 ──
            story.append(Spacer(1, 15))
            story.append(Paragraph('十一、转专业与大类分流指南', heading_style))
            story.append(Spacer(1, 5))
            story.append(Paragraph(
                '以下信息基于国内高校通用政策，各院校具体规定请以招生章程和教务处公告为准。',
                ParagraphStyle('TransIntro', fontName=font_name, fontSize=9,
                               leading=12, textColor=colors.HexColor('#666666'),
                               spaceAfter=8),
            ))

            # 1. 转专业政策
            story.append(Paragraph('8.1 大学转专业政策概述', subheading_style))
            transfer_content = (
                '大多数高校在大一末或大二初开放转专业申请，但各校门槛差异显著：'
            )
            story.append(Paragraph(transfer_content, normal_style))

            transfer_rules = [
                ['政策类型', '说明', '代表院校'],
                ['零门槛转专业', '申请即转，无成绩限制', '中国科学技术大学、西安交通大学'],
                ['低门槛转专业', 'GPA达到基本要求即可（如≥3.0）', '武汉大学、中山大学、厦门大学'],
                ['中门槛转专业', 'GPA前20%-30% + 面试考核', '浙江大学、南京大学、同济大学'],
                ['高门槛转专业', 'GPA前10%-20% + 笔试+面试', '北京大学、清华大学、复旦大学'],
                ['受限转专业', '仅允许转出到特定方向或比例限制', '部分医学类/师范类院校'],
            ]
            tr_table = Table(transfer_rules, colWidths=[30*mm, 70*mm, 60*mm])
            tr_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e3f2fd')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(tr_table)
            story.append(Spacer(1, 8))

            story.append(Paragraph('转专业关键提示：', normal_style))
            tips = [
                '转专业窗口通常仅1-2次机会（大一末/大二初），错过不可再申请',
                '部分院校实行"转出无限制、转入有门槛"，即原专业不卡人但目标专业有名额竞争',
                '医学类、师范类、艺术类等特殊类型专业通常不可跨类转入',
                '转专业后可能面临学分不互认、需延长学制的风险',
            ]
            for tip in tips:
                story.append(Paragraph(f'· {tip}', normal_style))
            story.append(Spacer(1, 8))

            # 2. 大类招生分流
            story.append(Paragraph('8.2 大类招生与专业分流', subheading_style))
            da_flow_content = (
                '越来越多高校实行"大类招生"，即入学时按大类录取，大一末或大二再细分专业。'
                '分流方式直接影响最终专业去向，需重点关注：'
            )
            story.append(Paragraph(da_flow_content, normal_style))

            da_flow_rules = [
                ['分流方式', '说明', '风险等级'],
                ['纯大学成绩分流', '按大一GPA排名选择专业方向', '高风险：竞争激烈，可能滑落到不想要的方向'],
                ['高考成绩+大学成绩', '综合高考分数与大学成绩加权', '中风险：高考成绩占20%-40%'],
                ['志愿填报+综合评定', '参考个人意愿+面试/笔试表现', '中低风险：有一定自主权'],
                ['双向选择制', '学生申请+专业学院审核接收', '低风险但目标专业可能拒收'],
            ]
            df_table = Table(da_flow_rules, colWidths=[35*mm, 70*mm, 55*mm])
            df_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e3f2fd')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(df_table)
            story.append(Spacer(1, 8))

            story.append(Paragraph('大类分流关键提示：', normal_style))
            da_tips = [
                '重点班/实验班通常享有更优资源，但分流压力更大，"宽进严出"是常态',
                '大类内热门专业（如计算机类内的计算机科学）分流竞争通常最激烈',
                '部分院校大类分流时"保底"专业可能不是考生首选，需做好备选方案',
                '建议提前查询目标院校大类分流的具体文件（教务处/招生办官网可查）',
            ]
            for tip in da_tips:
                story.append(Paragraph(f'· {tip}', normal_style))
            story.append(Spacer(1, 8))

            # 3. 如何调研
            story.append(Paragraph('8.3 如何调研目标院校的转专业/分流政策', subheading_style))
            research_steps = [
                '第一步：访问目标院校招生官网，查看最新招生章程中关于"专业分流"和"转专业"的条款',
                '第二步：访问教务处官网，搜索"转专业管理办法"、"大类分流实施方案"等文件',
                '第三步：联系在校学长学姐，了解实际执行中的难度和名额分配情况',
                '第四步：关注该校近2-3年的转专业公示名单，了解实际转出/转入比例',
                '第五步：对于大类招生，确认分流时间节点、考核方式和往年分流结果',
            ]
            for i, step in enumerate(research_steps, 1):
                story.append(Paragraph(f'{step}', normal_style))
            story.append(Spacer(1, 10))

            # ── 注意事项（数据完整性告警 + 匹配说明）──
            story.append(Paragraph('注意事项', heading_style))
            ok, data_msg, _ = check_data_completeness(self.db_path, q.category)
            story.append(Paragraph(f'数据完整性: {data_msg}', ParagraphStyle(
                'DataWarning', fontName=font_name, fontSize=9,
                leading=12, spaceAfter=6,
                textColor=colors.HexColor('#d32f2f') if not ok else colors.HexColor('#2e7d32'),
            )))
            notes = getattr(matching_result, 'notes', [])
            if notes:
                story.append(Paragraph('匹配说明:', subheading_style))
                for note in notes:
                    story.append(Paragraph(f'· {note}', normal_style))
            story.append(Spacer(1, 15))

            # 使用建议
            story.append(Paragraph('使用建议', heading_style))
            disclaimer = Paragraph(
                '1. 本推荐方案基于2020-2025年录取数据 + 项目自编偏好问卷 + 其他问卷偏好生成；偏好问卷未经心理测量学验证，不作诊断。'
                '2. 冲档学校存在落选风险，建议在冲档志愿中勾选"服从专业调剂"以降低退档风险。'
                '3. 云南新高考"院校专业组"模式：投档后若所填专业分数不够，不服从调剂将被直接退档。'
                '4. 专业级差风险：少数老牌强校仍采用"专业级差"规则（第二志愿扣3分），易调剂到组内冷门，填报前请查阅目标院校《招生章程》"专业录取规则"条款。'
                '5. 最终志愿填报请以云南省招生考试院公布的2026年招生计划为准。'
                '6. 如有重大疑问，建议咨询专业志愿填报顾问。',
                normal_style,
            )
            story.append(disclaimer)

            doc.build(story)
            return output_path

        except ImportError:
            return self.generate_html_report(
                matching_result, output_path.replace('.pdf', '.html'),
            )

    def generate_data_pdf_report(self, matching_result, output_path: str = None) -> str:
        """
        数据层 PDF：免费层 + 禁忌项 + 家庭资源 + 冲稳保增强数据表
        结构化目录：封面 → 基本信息 → 项目自编偏好问卷 → 注意事项 → 流程 → 禁忌项 → 家庭资源 → 推荐数据 → 升级引导
        """
        if output_path is None:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = os.path.join(
                self.output_dir,
                f'志愿数据参考表_{matching_result.questionnaire.name}_{ts}.pdf',
            )

        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import mm
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
            )
            from reportlab.lib import colors

            font_name = _get_chinese_font()

            doc = SimpleDocTemplate(
                output_path, pagesize=A4,
                rightMargin=20*mm, leftMargin=20*mm,
                topMargin=20*mm, bottomMargin=20*mm,
            )

            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'DataTitle', parent=styles['Title'],
                fontName=font_name, fontSize=22, leading=28,
                textColor=colors.HexColor('#1565C0'), alignment=1,
            )
            heading_style = ParagraphStyle(
                'DataHeading', parent=styles['Heading1'],
                fontName=font_name, fontSize=14, leading=20,
                textColor=colors.HexColor('#283593'), spaceAfter=10,
            )
            subheading_style = ParagraphStyle(
                'DataSubHeading', parent=styles['Heading2'],
                fontName=font_name, fontSize=11, leading=16,
                textColor=colors.HexColor('#3949ab'), spaceAfter=6,
            )
            normal_style = ParagraphStyle(
                'DataNormal', parent=styles['Normal'],
                fontName=font_name, fontSize=10, leading=14,
                textColor=colors.HexColor('#333333'), spaceAfter=4,
            )
            # 表格单元格样式（Paragraph包裹防溢出）
            cell_style = ParagraphStyle(
                'DataCell', fontName=font_name, fontSize=8, leading=10,
                textColor=colors.HexColor('#333333'),
            )
            cell_header_style = ParagraphStyle(
                'DataCellHeader', fontName=font_name, fontSize=8, leading=10,
                textColor=colors.white,
            )

            story = []
            q = matching_result.questionnaire

            def _c(text):
                """Wrap cell text in Paragraph for auto word-wrap."""
                return Paragraph(str(text) if text else '—', cell_style)

            def _h(text):
                """Wrap header cell text in Paragraph."""
                return Paragraph(str(text), cell_header_style)

            # ═══════════════════ 封面 ═══════════════════
            story.append(Spacer(1, 50*mm))
            story.append(Paragraph('OpenGaokao', ParagraphStyle(
                'DataLogo', fontName=font_name, fontSize=28,
                alignment=1, textColor=colors.HexColor('#1565C0'),
            )))
            story.append(Spacer(1, 8*mm))
            story.append(Paragraph('高考志愿推荐', ParagraphStyle(
                'DataSubTitle', fontName=font_name, fontSize=14,
                alignment=1, textColor=colors.HexColor('#666666'),
            )))
            story.append(Spacer(1, 15*mm))
            story.append(Paragraph(f'{q.name}同学 志愿填报数据参考表', title_style))
            story.append(Spacer(1, 8*mm))
            story.append(Paragraph(
                f'{q.category} · {q.total_score}分 · 位次{q.rank}',
                ParagraphStyle('DataScore', fontName=font_name, fontSize=14,
                               alignment=1, textColor=colors.HexColor('#333333')),
            ))
            story.append(Spacer(1, 5*mm))
            story.append(Paragraph(
                '录取数据 + 项目自编偏好问卷（非心理诊断）',
                ParagraphStyle('DataTag', fontName=font_name, fontSize=12,
                               alignment=1, textColor=colors.HexColor('#888888')),
            ))
            story.append(Spacer(1, 10*mm))
            story.append(Paragraph(
                f'报告生成日期：{datetime.now().strftime("%Y年%m月%d日")}',
                ParagraphStyle('DataDate', fontName=font_name, fontSize=10,
                               alignment=1, textColor=colors.HexColor('#999999')),
            ))
            story.append(PageBreak())

            # ═══════════════════ 一、考生基本信息 ═══════════════════
            story.append(Paragraph('一、考生基本信息', heading_style))
            info_data = [
                [_c('姓名'), _c(q.name), _c('科类'), _c(q.category)],
                [_c('总分'), _c(str(q.total_score)), _c('位次'), _c(str(q.rank))],
                [_c('性别'), _c(q.gender), _c('本地标识码'), _c(q.exam_id or '—')],
            ]
            info_table = Table(info_data, colWidths=[30*mm, 50*mm, 30*mm, 50*mm])
            info_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(info_table)
            story.append(Spacer(1, 15))

            # ═══════════════════ 二、项目自编偏好问卷结果 ═══════════════════
            if matching_result.personality_result:
                story.append(Paragraph('二、偏好问卷结果（项目自编，非心理诊断）', heading_style))
                p = matching_result.personality_result
                bf = p.big_five
                personality_data = [
                    [_c('大五维度偏好'), _c(f"O={bf.get('O', 0)} C={bf.get('C', 0)} E={bf.get('E', 0)} A={bf.get('A', 0)} N={bf.get('N', 0)}"), _c('RIASEC 风格代码'), _c(p.holland_code)],
                    [_c('置信度'), _c(_translate_term(p.confidence)), _c('一致性检测'), _c(f'{p.sd_score}/4')],
                ]
                ptable = Table(personality_data, colWidths=[30*mm, 50*mm, 30*mm, 50*mm])
                ptable.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), font_name),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                story.append(ptable)
                story.append(Spacer(1, 15))

            # ═══════════════════ 三、志愿填报注意事项 ═══════════════════
            story.append(Paragraph('三、志愿填报注意事项', heading_style))

            # P1-4 (阶段14): 动态必读提示——基于本次问卷个体化生成
            must_ack = getattr(matching_result, 'must_ack_warnings', []) or []
            if must_ack:
                must_ack_style = ParagraphStyle(
                    'DataMustAck', parent=normal_style,
                    textColor=colors.HexColor('#C62828'), spaceAfter=6,
                )
                story.append(Paragraph('<b>⚠ 个体化必读提示（基于本次问卷动态生成）</b>', subheading_style))
                for idx, w in enumerate(must_ack, 1):
                    story.append(Paragraph(f'{idx}. {w}', must_ack_style))
                story.append(Spacer(1, 8))
                story.append(Paragraph('<b>通用注意事项：</b>', subheading_style))

            for note in [
                '1. <b>平行志愿规则</b>：分数优先、遵循志愿、一轮投档。一旦投档，后续志愿失效。',
                '2. <b>服从专业调剂</b>：云南新高考"院校专业组"模式，投档后不服从调剂将直接退档。',
                '3. <b>体检限制</b>：色盲/色弱不能报考化学、医学、生物等专业。',
                '4. <b>批次顺序</b>：提前批 → 本科批 → 专科批，各批次独立投档。',
                '5. <b>学费差异</b>：中外合作办学（3-8万/年）远高于公办（0.5-0.8万/年）。',
            ]:
                story.append(Paragraph(note, normal_style))
            story.append(Spacer(1, 15))

            # ═══════════════════ 四、志愿填报流程 ═══════════════════
            story.append(Paragraph('四、志愿填报流程', heading_style))
            steps = [
                ('第1步', '高考出分，查询一分一段表，确认位次'),
                ('第2步', '结合项目自编偏好问卷确定目标专业方向'),
                ('第3步', '根据位次筛选冲/稳/保院校'),
                ('第4步', '核对体检限制，排除受限专业'),
                ('第5步', '按冲稳保顺序排列志愿表'),
                ('第6步', '仔细核对后提交确认'),
            ]
            sdata = [[_h('步骤'), _h('内容')]]
            sdata.extend([[_c(s), _c(d)] for s, d in steps])
            stable = Table(sdata, colWidths=[25*mm, 135*mm])
            stable.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1565C0')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(stable)
            story.append(PageBreak())

            # ═══════════════════ 五、禁忌项检测报告 ═══════════════════
            story.append(Paragraph('五、禁忌项检测报告', heading_style))
            cr = matching_result.constraint_result
            if cr:
                # 资格判定
                qual_data = [
                    [_c('检测项目'), _c('结果')],
                    [_c('硬性过滤（不予录取）'), _c('是' if cr.hard_filtered else '否')],
                    [_c('警校资格'), _c('合格' if cr.police_qualified else '不合格')],
                    [_c('军校资格'), _c('合格' if cr.military_qualified else '不合格')],
                ]
                qtable = Table(qual_data, colWidths=[60*mm, 100*mm])
                hard_color = colors.HexColor('#c62828') if cr.hard_filtered else colors.HexColor('#2e7d32')
                qtable.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), font_name),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#e3f2fd')),
                    ('TEXTCOLOR', (1, 1), (1, 1), hard_color),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                story.append(qtable)
                story.append(Spacer(1, 10))

                # 受限专业
                if cr.filtered_majors:
                    story.append(Paragraph('受限专业清单（体检限制，不予录取）：', subheading_style))
                    for major in cr.filtered_majors:
                        story.append(Paragraph(f'· {major}', ParagraphStyle(
                            'RestrictedMajor', fontName=font_name, fontSize=10,
                            leading=14, textColor=colors.HexColor('#c62828'), spaceAfter=2,
                        )))
                else:
                    story.append(Paragraph('无受限专业', normal_style))

                # 警告
                if cr.warnings:
                    story.append(Spacer(1, 8))
                    story.append(Paragraph('检测警告：', subheading_style))
                    for warn in cr.warnings:
                        story.append(Paragraph(f'· {warn}', normal_style))
            else:
                story.append(Paragraph('未完成禁忌项检测（请补充体检数据）', normal_style))
            story.append(Spacer(1, 10))

            # ═══════════════════ 六、家庭资源评估 ═══════════════════
            story.append(Paragraph('六、家庭资源评估', heading_style))
            fr = matching_result.family_resource_result
            if fr:
                fr_data = [
                    [_c('评估维度'), _c('结果')],
                    [_c('综合评级'), _c(fr.rating)],
                    [_c('经济资本'), _c(f'{fr.economic_capital:.1f}/100')],
                    [_c('文化资本'), _c(f'{fr.cultural_capital:.1f}/100')],
                    [_c('社会资本'), _c(f'{fr.social_capital:.1f}/100')],
                    [_c('综合得分'), _c(f'{fr.total_score:.1f}/100')],
                ]
                fr_table = Table(fr_data, colWidths=[50*mm, 110*mm])
                rating_color = {'高': '#2E7D32', '中': '#FF8F00', '低': '#C62828'}.get(fr.rating, '#333333')
                fr_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), font_name),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#e3f2fd')),
                    ('TEXTCOLOR', (1, 1), (1, 1), colors.HexColor(rating_color)),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                story.append(fr_table)

                if fr.suggestions:
                    story.append(Spacer(1, 8))
                    story.append(Paragraph('专业选择建议：', subheading_style))
                    for sug in fr.suggestions:
                        story.append(Paragraph(f'· {sug}', normal_style))
            else:
                story.append(Paragraph('未完成家庭资源评估（请补充家庭信息）', normal_style))
            story.append(Spacer(1, 10))
            story.append(PageBreak())

            # ═══════════════════ 七、全量冲稳保垫推荐数据 ═══════════════════
            story.append(Paragraph('七、全量冲稳保垫推荐数据', heading_style))
            story.append(Spacer(1, 5))

            # 批量查询学费/就业/撤销数据
            _data_tuition = {}
            _data_emp = {}
            _data_revoke = {}
            _conn = None
            try:
                _conn = sqlite3.connect(self.db_path, check_same_thread=False)
                _cur = _conn.cursor()
                _all_majors = set()
                for _cat in ['冲', '稳', '保', '垫']:
                    for _s in matching_result.recommendations.get(_cat, []):
                        if _s.recommended_majors:
                            for _mp in _s.recommended_majors:
                                _all_majors.add(_mp.major_name)
                if _all_majors:
                    _ph = ','.join('?' * len(_all_majors))
                    _cur.execute(
                        f"SELECT major_name, tuition_year FROM major_catalog WHERE major_name IN ({_ph})",
                        list(_all_majors),
                    )
                    for _r in _cur.fetchall():
                        if _r[1]:
                            _data_tuition[_r[0]] = _r[1]
                    _cur.execute(
                        f"SELECT major_name, employment_rate, avg_salary_monthly FROM major_employment_stats WHERE major_name IN ({_ph})",
                        list(_all_majors),
                    )
                    for _r in _cur.fetchall():
                        _data_emp[_r[0]] = (_r[1], _r[2])
                    _cur.execute(
                        f"SELECT major_name, SUM(revoke_count) FROM major_revocation_stats WHERE major_name != '全国合计' AND major_name IN ({_ph}) GROUP BY major_name",
                        list(_all_majors),
                    )
                    for _r in _cur.fetchall():
                        _data_revoke[_r[0]] = _r[1]
            except Exception:
                pass
            finally:
                if _conn:
                    _conn.close()

            for category in ['冲', '稳', '保', '垫']:
                schools = matching_result.recommendations.get(category, [])
                if not schools:
                    continue
                cat_style = ParagraphStyle(
                    f'DataCat_{category}', parent=normal_style,
                    fontName=font_name, fontSize=11, leading=15,
                    textColor=colors.HexColor({'冲': '#E65100', '稳': '#1565C0', '保': '#2E7D32', '垫': '#8E24AA'}.get(category, '#333')),
                    spaceBefore=8, spaceAfter=4,
                )
                story.append(Paragraph(f'{category}（{len(schools)}所）', cat_style))

                tdata = [[_h('序号'), _h('院校名称'), _h('地点'), _h('录取概率'), _h('推荐专业'), _h('学费'), _h('就业/薪资'), _h('撤销预警'), _h('降档替代')]]
                for i, school in enumerate(schools[:20], 1):
                    majors = school.recommended_majors or []
                    majors_str = ', '.join([m.major_name for m in majors[:2]])

                    # 学费
                    tu = '—'
                    if majors:
                        tv = _data_tuition.get(majors[0].major_name)
                        if tv:
                            tu = f'{tv:.1f}万'
                        elif '中外合作' in school.school_quality:
                            tu = '3-8万'
                        elif '民办' in school.school_quality:
                            tu = '1.5-3万'
                        else:
                            tu = '0.5-0.8万'

                    # 就业/薪资
                    emp_str = '—'
                    if majors:
                        es = _data_emp.get(majors[0].major_name)
                        if es and es[0]:
                            salary_part = f'{int(es[1])}元' if es[1] else '—'
                            emp_str = f'{es[0]*100:.0f}% / {salary_part}'

                    # 撤销预警
                    revoke_str = '—'
                    for m in majors[:2]:
                        rc = _data_revoke.get(m.major_name, 0)
                        if rc > 5:
                            revoke_str = f'[撤销⚠{rc}所]'
                            break
                        elif rc > 0:
                            revoke_str = f'[撤销{rc}所]'

                    # 降档替代
                    alt_str = '—'
                    alts = getattr(school, 'similar_alternatives', []) or []
                    if alts:
                        alt_str = ', '.join(alts[:2])

                    tdata.append([
                        _c(str(i)), _c(school.school_name), _c(school.location or '—'),
                        _c(f'{school.probability:.1f}%'), _c(majors_str or '—'),
                        _c(tu), _c(emp_str), _c(revoke_str), _c(alt_str),
                    ])
                table = Table(tdata, colWidths=[10*mm, 32*mm, 22*mm, 18*mm, 35*mm, 16*mm, 20*mm, 22*mm, 25*mm])
                table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), font_name),
                    ('FONTSIZE', (0, 0), (-1, -1), 7),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1565C0')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
                ]))
                story.append(table)
                story.append(Spacer(1, 8))

            # ═══════════════════ 八、数据说明与升级引导 ═══════════════════
            story.append(Spacer(1, 15))
            story.append(Paragraph('数据说明', heading_style))
            story.append(Paragraph(
                '本报告基于2020-2025年录取数据 + 项目自编偏好问卷 + 其他问卷偏好生成；偏好问卷未经心理测量学验证，不作诊断。'
                '2025年为新高考首年，数据覆盖率有限，部分专业录取位次可能存在偏差。'
                '最终志愿填报请以云南省招生考试院公布的2026年招生计划为准。',
                normal_style,
            ))
            story.append(Spacer(1, 10))
            story.append(Paragraph(
                '升级至方案层（¥2999）可获取全量批次推荐 + AI个性化解读；'
                '升级至深度层（¥3999）可获取院校深度解析 + 城市产业分析 + 保研考研就业策略。',
                ParagraphStyle('DataUpsell', fontName=font_name, fontSize=10,
                               leading=16, textColor=colors.HexColor('#1565C0'),
                               alignment=1, spaceBefore=10),
            ))

            doc.build(story)
            return output_path

        except ImportError:
            return self.generate_html_report(
                matching_result, output_path.replace('.pdf', '.html'),
            )

    def generate_standard_pdf_report(self, matching_result, output_path: str = None) -> str:
        """
        方案层 PDF = 数据层内容 + 全量批次推荐结果 + AI 核心建议
        """
        if output_path is None:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = os.path.join(
                self.output_dir,
                f'志愿推荐方案_{matching_result.questionnaire.name}_{ts}.pdf',
            )

        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import mm, cm
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
                Image as PlatypusImage, Flowable,
            )
            from reportlab.lib import colors
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont

            font_name = _get_chinese_font()

            doc = SimpleDocTemplate(
                output_path, pagesize=A4,
                rightMargin=20*mm, leftMargin=20*mm,
                topMargin=20*mm, bottomMargin=20*mm,
            )

            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'StdTitle', parent=styles['Title'],
                fontName=font_name, fontSize=24, leading=30,
                spaceAfter=30, alignment=1,
            )
            heading_style = ParagraphStyle(
                'StdHeading', parent=styles['Heading1'],
                fontName=font_name, fontSize=16, leading=20,
                spaceAfter=12, textColor=colors.HexColor('#1a1a1a'),
            )
            subheading_style = ParagraphStyle(
                'StdSubHeading', parent=styles['Heading2'],
                fontName=font_name, fontSize=12, leading=16,
                spaceAfter=8, textColor=colors.HexColor('#333333'),
            )
            normal_style = ParagraphStyle(
                'StdNormal', parent=styles['Normal'],
                fontName=font_name, fontSize=10, leading=14, spaceAfter=6,
            )

            story = []
            q = matching_result.questionnaire

            # 表格单元格样式（Paragraph包裹防溢出）
            cell_style = ParagraphStyle(
                'StdCell', fontName=font_name, fontSize=8, leading=10,
                textColor=colors.HexColor('#333333'),
            )
            cell_header_style = ParagraphStyle(
                'StdCellHeader', fontName=font_name, fontSize=8, leading=10,
                textColor=colors.white,
            )

            def _c(text):
                return Paragraph(str(text) if text else '—', cell_style)

            def _h(text):
                return Paragraph(str(text), cell_header_style)

            # ── 封面 ──
            story.append(Spacer(1, 50*mm))
            story.append(Paragraph('OpenGaokao', ParagraphStyle(
                'StdLogo', fontName=font_name, fontSize=28,
                alignment=1, textColor=colors.HexColor('#1565C0'),
            )))
            story.append(Spacer(1, 8*mm))
            story.append(Paragraph('高考志愿推荐', ParagraphStyle(
                'StdSubTitle', fontName=font_name, fontSize=14,
                alignment=1, textColor=colors.HexColor('#666666'),
            )))
            story.append(Spacer(1, 15*mm))
            story.append(Paragraph(f'{q.name}同学 专属志愿推荐方案', title_style))
            story.append(Spacer(1, 8*mm))
            story.append(Paragraph(
                f'{q.category} · {q.total_score}分 · 位次{q.rank}',
                ParagraphStyle('StdScore', fontName=font_name, fontSize=14,
                               alignment=1, textColor=colors.HexColor('#333333')),
            ))
            story.append(Spacer(1, 5*mm))
            story.append(Paragraph(
                '录取数据 + 项目自编偏好问卷（非心理诊断）',
                ParagraphStyle('StdTag', fontName=font_name, fontSize=12,
                               alignment=1, textColor=colors.HexColor('#888888')),
            ))
            story.append(Spacer(1, 10*mm))
            story.append(Paragraph(
                f'报告生成日期：{datetime.now().strftime("%Y年%m月%d日")}',
                ParagraphStyle('StdDate', fontName=font_name, fontSize=10,
                               alignment=1, textColor=colors.HexColor('#999999')),
            ))
            story.append(PageBreak())

            # ═══════════════════ 基本信息 ═══════════════════
            story.append(Paragraph('一、考生基本信息', heading_style))
            info_data = [
                ['姓名', q.name, '科类', q.category],
                ['总分', str(q.total_score), '位次', str(q.rank)],
                ['性别', q.gender, '本地标识码', q.exam_id],
            ]
            info_table = Table(info_data, colWidths=[30*mm, 50*mm, 30*mm, 50*mm])
            info_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(info_table)
            story.append(Spacer(1, 15))

            # ═══════════════════ 意愿冲突检测 ═══════════════════
            ip = getattr(matching_result, 'intention_profile', None)
            if ip and getattr(ip, 'conflicts', None):
                story.append(Paragraph('二、意愿冲突检测', heading_style))
                for conflict in ip.conflicts:
                    sev_color = '#c62828' if getattr(conflict, 'severity', '') == 'high' else '#e65100'
                    warn_box = ParagraphStyle(
                        'ConflictWarn', fontName=font_name, fontSize=10, leading=15,
                        textColor=colors.HexColor(sev_color),
                        backColor=colors.HexColor('#fff3cd'),
                        borderColor=colors.HexColor('#f57c00'),
                        borderWidth=1, borderPadding=6,
                        spaceAfter=8,
                    )
                    story.append(Paragraph(
                        f'<b>⚠ {conflict.conflict_type}</b>：{conflict.description}<br/><font size="9">建议：{conflict.suggestion}</font>',
                        warn_box,
                    ))
                story.append(Spacer(1, 10))

            # ═══════════════════ AI 核心建议 ═══════════════════
            story.append(Paragraph('AI 核心建议', heading_style))
            story.append(Spacer(1, 5))

            # 使用已有 _generate_ai_narrative 生成解读
            narratives = self._generate_ai_narrative(
                matching_result.personality_result,
                matching_result.recommendations,
                matching_result,
            )

            # 构建结构化推荐
            _top_picks = []
            for cat in ['稳', '冲', '保']:
                schools = matching_result.recommendations.get(cat, [])
                if schools:
                    s = schools[0]
                    majors = ', '.join([m.major_name for m in (s.recommended_majors or [])[:2]])
                    _top_picks.append((cat, s, majors))

            p = matching_result.personality_result
            fr = getattr(matching_result, 'family_resource_result', None)
            fr_text = ''
            if fr:
                fr_text = f'、家庭资源（{_translate_term(fr.rating)}）'

            story.append(Paragraph(
                f'综合 {q.name} 同学的偏好问卷信号'
                f'（项目自编 RIASEC 风格代码 {p.holland_code if p else "未测"}）'
                f'、高考成绩（{q.total_score}分/位次{q.rank}）{fr_text}'
                f'及志愿偏好（目标行业：{", ".join(q.target_industries) if q.target_industries else "未定"}），',
                normal_style,
            ))
            story.append(Spacer(1, 5))
            story.append(Paragraph('系统综合评估后推荐：', normal_style))
            story.append(Spacer(1, 5))

            pick_labels = {'冲': '冲刺', '稳': '首选', '保': '保底'}
            for i, (cat, s, majors) in enumerate(_top_picks[:3], 1):
                label = pick_labels.get(cat, '推荐')
                reason_parts = []
                if p:
                    holland_hints = {'R': '实际型', 'I': '研究型', 'A': '艺术型', 'S': '社会型', 'E': '企业型', 'C': '常规型'}
                    top_h = holland_hints.get(p.holland_code[0] if p.holland_code else '', '')
                    if top_h:
                        reason_parts.append(f'与您的{top_h}类 RIASEC 风格偏好匹配')
                if fr and fr.rating == '高':
                    reason_parts.append('家庭资源支持')
                reason_str = ' · '.join(reason_parts) if reason_parts else '综合评估最优'

                story.append(Paragraph(
                    f'<b>★ {label}：</b>{s.school_name} · {majors}'
                    f'<br/>  录取概率 {s.probability:.0f}%（{cat}）{("· " + reason_str) if reason_str else ""}',
                    normal_style,
                ))
                story.append(Spacer(1, 3))

            if narratives:
                story.append(Spacer(1, 8))
                story.append(Paragraph('补充解读：', subheading_style))
                for nar in narratives[:3]:
                    story.append(Paragraph(f'· {nar}', normal_style))

            story.append(Spacer(1, 15))

            # ── 以下复用 generate_pdf_report 的推荐方案部分 ──

            # 项目自编偏好问卷
            if matching_result.personality_result:
                story.append(Paragraph('三、偏好问卷结果（项目自编，非心理诊断）', heading_style))
                p = matching_result.personality_result
                bf = p.big_five
                personality_data = [
                    [_c('大五维度偏好'), _c(f"O={bf.get('O', 0)} C={bf.get('C', 0)} E={bf.get('E', 0)} A={bf.get('A', 0)} N={bf.get('N', 0)}"), _c('RIASEC 风格代码'), _c(p.holland_code)],
                    [_c('置信度'), _c(_translate_term(p.confidence)), _c('一致性检测'), _c(f'{p.sd_score}/4')],
                ]
                ptable = Table(personality_data, colWidths=[30*mm, 50*mm, 30*mm, 50*mm])
                ptable.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), font_name),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                story.append(ptable)
                story.append(Spacer(1, 15))

            # 志愿偏好
            story.append(Paragraph('四、志愿偏好', heading_style))
            pref_data = [
                [_c('核心诉求'), _c(q.core_demand or '未定')],
                [_c('目标行业'), _c(', '.join(q.target_industries) if q.target_industries else '未定')],
                [_c('可接受专业'), _c(', '.join(q.acceptable_majors) if q.acceptable_majors else '未定')],
                [_c('稳定性偏好'), _c(f'{q.stability_preference}/5')],
                [_c('风险策略'), _c(_translate_term(matching_result.risk_strategy))],
            ]
            pref_table = Table(pref_data, colWidths=[40*mm, 120*mm])
            pref_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(pref_table)
            story.append(Spacer(1, 15))

            # 推荐方案 — 按批次组织
            story.append(Paragraph('五、推荐方案', heading_style))
            from gaokao.core.volunteer_recommender import BATCH_ADMISSION_ORDER

            batch_groups = {}
            for category in ['冲', '稳', '保', '垫']:
                for school in matching_result.recommendations.get(category, []):
                    school._chong_wen_bao = category
                    b = school.batch if school.batch else '其他'
                    if b not in batch_groups:
                        batch_groups[b] = []
                    batch_groups[b].append(school)

            def _batch_sort_key(key):
                if key in BATCH_ADMISSION_ORDER:
                    return BATCH_ADMISSION_ORDER.index(key)
                return 999

            sorted_batches = sorted(batch_groups.keys(), key=_batch_sort_key)

            for batch_idx, batch_key in enumerate(sorted_batches):
                schools = batch_groups[batch_key]
                story.append(Paragraph(f'5.{batch_idx+1} {batch_key}', subheading_style))

                for category in ['冲', '稳', '保', '垫']:
                    cat_schools = [s for s in schools if getattr(s, '_chong_wen_bao', '') == category]
                    if not cat_schools:
                        continue
                    color_map = {'冲': '#E65100', '稳': '#1565C0', '保': '#2E7D32'}
                    cat_style = ParagraphStyle(
                        f'StdCat_{batch_key}_{category}', parent=normal_style,
                        fontName=font_name, fontSize=11, leading=15,
                        spaceBefore=6, spaceAfter=4,
                        textColor=colors.HexColor(color_map.get(category, '#333')),
                    )
                    story.append(Paragraph(f'{category}（{len(cat_schools)}所）', cat_style))

                    if category == '保':
                        fallback_count = sum(1 for s in cat_schools if getattr(s, 'safety_warning', None))
                        if fallback_count > 0:
                            warn_style = ParagraphStyle(
                                f'StdBaoFallback_{batch_key}', parent=normal_style,
                                fontName=font_name, fontSize=9, leading=12,
                                textColor=colors.HexColor('#c62828'),
                                backColor=colors.HexColor('#fff3cd'),
                                borderColor=colors.HexColor('#f57c00'),
                                borderWidth=1, borderPadding=4,
                                spaceBefore=2, spaceAfter=4,
                            )
                            story.append(Paragraph(
                                f'⚠ 注意：本档含 {fallback_count} 所"垫"志愿（50%-85% 概率）。'
                                f'标准保底（≥85%概率）数量不足，请谨慎评估并优先填写"标准"行。',
                                warn_style,
                            ))

                    table_data = [[_h('序号'), _h('院校名称'), _h('院校层级'), _h('地点'), _h('录取概率'), _h('置信度'), _h('兜底')]]
                    table_styles_extra = []
                    for i, school in enumerate(cat_schools[:15], 1):
                        tier_str = f"{school.tier_level} {school.tier_name}" if school.tier_level else school.school_quality
                        if category == '保':
                            if getattr(school, 'safety_warning', None):
                                bao_cell = '⚠补充'
                                table_styles_extra.append(('TEXTCOLOR', (6, i), (6, i), colors.HexColor('#c62828')))
                                table_styles_extra.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#fff8e1')))
                            else:
                                bao_cell = '标准'
                                table_styles_extra.append(('TEXTCOLOR', (6, i), (6, i), colors.HexColor('#2e7d32')))
                        else:
                            bao_cell = '—'
                        table_data.append([
                            _c(str(i)), _c(school.school_name), _c(tier_str),
                            _c(school.location), _c(f'{school.probability:.1f}%'),
                            _c(_get_confidence_display(school.confidence)), _c(bao_cell),
                        ])
                    table = Table(table_data, colWidths=[10*mm, 42*mm, 22*mm, 22*mm, 22*mm, 18*mm, 14*mm])
                    table.setStyle(TableStyle([
                        ('FONTNAME', (0, 0), (-1, -1), font_name),
                        ('FONTSIZE', (0, 0), (-1, -1), 8),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e0e0')),
                        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ] + table_styles_extra))
                    story.append(table)
                    story.append(Spacer(1, 8))

                # 推荐专业
                pro_majors = [s for s in schools if s.recommended_majors]
                if pro_majors:
                    story.append(Paragraph('推荐专业（TOP 3）', subheading_style))
                    for school in pro_majors[:3]:
                        parts = []
                        for m in school.recommended_majors[:3]:
                            tag = ' [2026新增]' if getattr(m, 'is_new_major', False) else ''
                            risk = getattr(m, 'revocation_risk', 'none')
                            risk_tag = ''
                            if risk == 'rising':
                                risk_tag = ' [撤销↑]'
                            elif risk == 'declining':
                                risk_tag = ' [撤销↓]'
                            emp_rate = getattr(m, 'employment_rate', 0)
                            avg_salary = getattr(m, 'avg_salary', 0)
                            emp_tag = ''
                            if emp_rate or avg_salary:
                                bits = []
                                if emp_rate:
                                    bits.append(f'就业{emp_rate*100:.0f}%')
                                if avg_salary:
                                    bits.append(f'{int(avg_salary)}元')
                                emp_tag = f' ({"/".join(bits)})'
                            parts.append(f'{m.major_name}{tag}{risk_tag}{emp_tag}')
                        ms = ', '.join(parts)
                        line = f'{school.school_name}: {ms}'
                        alts = getattr(school, 'similar_alternatives', []) or []
                        if alts:
                            line += f'<br/><font size="8" color="#666666">如不录取可考虑: {", ".join(alts[:3])}</font>'
                        story.append(Paragraph(line, normal_style))
                    story.append(Spacer(1, 6))

            # 冲稳保分布饼图
            chong_count = len(matching_result.recommendations.get('冲', []))
            wen_count = len(matching_result.recommendations.get('稳', []))
            bao_count = len(matching_result.recommendations.get('保', []))
            if chong_count + wen_count + bao_count > 0:
                story.append(Spacer(1, 10))
                story.append(Paragraph('冲稳保分布', subheading_style))
                story.append(Spacer(1, 5))

                from reportlab.graphics.shapes import Drawing
                from reportlab.graphics.charts.piecharts import Pie as PieShape
                from reportlab.graphics import renderPDF

                d_pie = Drawing(280, 140)
                pie = PieShape()
                pie.x = 20; pie.y = 10; pie.width = 100; pie.height = 100
                pie.slices.strokeWidth = 1; pie.slices.strokeColor = colors.white
                pie.data = [chong_count, wen_count, bao_count]
                pie.slices[0].fillColor = colors.HexColor('#4CAF50')
                pie.slices[1].fillColor = colors.HexColor('#2196F3')
                pie.slices[2].fillColor = colors.HexColor('#FF9800')
                d_pie.add(pie)

                total = chong_count + wen_count + bao_count
                pie_text = f'共推荐{total}所院校：冲刺{chong_count}所({chong_count*100//total if total else 0}%)、'
                pie_text += f'稳妥{wen_count}所({wen_count*100//total if total else 0}%)、'
                pie_text += f'保底{bao_count}所({bao_count*100//total if total else 0}%)'

                class DrawingWrapperStd(Flowable):
                    def __init__(self, drawing, width, height):
                        Flowable.__init__(self)
                        self._d = drawing; self._w = width; self._h = height
                    def wrap(self, aW, aH):
                        return self._w, self._h
                    def draw(self):
                        renderPDF.draw(self._d, self.canv, 0, 0)

                story.append(DrawingWrapperStd(d_pie, 280, 140))
                story.append(Spacer(1, 5))
                story.append(Paragraph(pie_text, normal_style))

            # ═══════════════════ 推荐院校画像 ═══════════════════
            story.append(PageBreak())
            story.append(Paragraph('推荐院校画像（TOP 5）', heading_style))
            _top5 = []
            for cat in ['稳', '冲', '保']:
                for s in matching_result.recommendations.get(cat, []):
                    _top5.append(s)
                    if len(_top5) >= 5:
                        break
                if len(_top5) >= 5:
                    break
            for i, school in enumerate(_top5, 1):
                story.append(Paragraph(f'{i}. {school.school_name}', subheading_style))
                profile_items = [
                    [_c('院校层级'), _c(school.tier_name if school.tier_name else school.school_quality)],
                    [_c('地点'), _c(school.location or '—')],
                    [_c('录取概率'), _c(f'{school.probability:.1f}%')],
                    [_c('推荐专业'), _c(', '.join([m.major_name for m in (school.recommended_majors or [])[:3]]))],
                ]
                ptable = Table(profile_items, colWidths=[30*mm, 130*mm])
                ptable.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), font_name),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f5f5f5')),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                story.append(ptable)
                story.append(Spacer(1, 6))

            # ═══════════════════ 专业兴趣匹配度 ═══════════════════
            story.append(Spacer(1, 10))
            story.append(Paragraph('专业兴趣匹配度', heading_style))
            p = matching_result.personality_result
            if p and getattr(p, 'holland_scores', None):
                holland_names = ['实际型(R)', '研究型(I)', '艺术型(A)', '社会型(S)', '企业型(E)', '常规型(C)']
                RIASEC = ['R', 'I', 'A', 'S', 'E', 'C']
                match_data = [[_h('维度'), _h('得分'), _h('匹配专业')]]
                for name, code in zip(holland_names, RIASEC):
                    score = p.holland_scores.get(code, 0)
                    s = float(score) if isinstance(score, (int, float)) else 0
                    level = '高' if s >= 60 else ('中' if s >= 40 else '低')
                    match_data.append([_c(name), _c(f'{s:.0f} ({level})'), _c('见推荐方案')])
                mtable = Table(match_data, colWidths=[40*mm, 30*mm, 90*mm])
                mtable.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), font_name),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e3f2fd')),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                story.append(mtable)
            else:
                story.append(Paragraph('RIASEC 风格兴趣评分数据暂无', normal_style))

            # ═══════════════════ 热门学科趋势 ═══════════════════
            story.append(Spacer(1, 10))
            story.append(Paragraph('热门学科趋势（2025-2045）', heading_style))
            story.append(Paragraph('基于WEF《2025未来就业报告》岗位增长预测：', normal_style))
            hot_rising = [
                'AI与机器学习专家', '大数据分析师', '信息安全专家',
                '可再生能源工程师', '农业技术专家', '心理健康咨询师',
            ]
            hot_declining = [
                '数据录入员', '行政秘书', '传统制造业工人',
                '会计/簿记员', '传统零售销售', '银行出纳',
            ]
            rise_data = [[_h('上升学科'), _h('驱动因素')]]
            rise_data.extend([[_c(m), _c('产业升级/数字化/碳中和')]])
            for m in hot_rising:
                rise_data.append([_c(f'▲ {m}'), _c('')])
            rtable = Table(rise_data, colWidths=[60*mm, 100*mm])
            rtable.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#c8e6c9')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(rtable)
            story.append(Spacer(1, 6))
            fall_data = [[_h('衰退学科'), _h('原因')]]
            for m in hot_declining:
                fall_data.append([_c(f'▼ {m}'), _c('AI自动化/数字化替代')])
            ftable = Table(fall_data, colWidths=[60*mm, 100*mm])
            ftable.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ffcdd2')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(ftable)

            # ═══════════════════ 转专业政策指引 ═══════════════════
            story.append(Spacer(1, 10))
            story.append(Paragraph('转专业政策指引', heading_style))
            story.append(Paragraph('各层次院校转专业难度参考：', normal_style))
            trans_data = [
                [_h('院校层次'), _h('难度'), _h('常见要求')],
                [_c('985/双一流'), _c('★★★★★'), _c('GPA前10%+面试+笔试，部分专业不接受转入')],
                [_c('211'), _c('★★★★'), _c('GPA前20%+转专业考试')],
                [_c('普通本科'), _c('★★★'), _c('GPA前30%+申请审批')],
                [_c('民办/独立学院'), _c('★★'), _c('相对宽松，申请即可')],
            ]
            ttable = Table(trans_data, colWidths=[35*mm, 25*mm, 100*mm])
            ttable.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e3f2fd')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(ttable)
            story.append(Spacer(1, 8))
            story.append(Paragraph(
                '<b>建议：</b>入学后尽早了解目标院校转专业政策，如录取专业不理想，应在大一上学期即开始准备转专业申请。'
                '大类招生专业的分流通常在大一末或大二初，需提前了解分流规则。',
                normal_style,
            ))

            # ═══════════════════ 使用建议 ═══════════════════
            story.append(Spacer(1, 15))
            story.append(Paragraph('使用建议', heading_style))
            disclaimer = Paragraph(
                '1. 本推荐方案基于2020-2025年录取数据 + 项目自编偏好问卷 + 其他问卷偏好生成；偏好问卷未经心理测量学验证，不作诊断。'
                '2. 冲档学校存在落选风险，建议在冲档志愿中勾选"服从专业调剂"以降低退档风险。'
                '3. 云南新高考"院校专业组"模式：投档后若所填专业分数不够，不服从调剂将被直接退档。'
                '4. 专业级差风险：少数老牌强校仍采用"专业级差"规则（第二志愿扣3分），易调剂到组内冷门，填报前请查阅目标院校《招生章程》"专业录取规则"条款。'
                '5. 最终志愿填报请以云南省招生考试院公布的2026年招生计划为准。'
                '6. 如有重大疑问，建议咨询专业志愿填报顾问。',
                normal_style,
            )
            story.append(disclaimer)

            doc.build(story)
            return output_path

        except ImportError:
            return self.generate_html_report(
                matching_result, output_path.replace('.pdf', '.html'),
            )

    def generate_tier4_pdf(self, matching_result, output_path: str = None,
                           consultant_name: str = '',
                           consultant_notes: str = '') -> str:
        """
        深度层 品牌化PDF报告书（纸质版）
        包含：封面 + 页眉水印 + 报告正文 + 签名页
        """
        if output_path is None:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = os.path.join(
                self.output_dir,
                f'OpenGaokao_志愿规划书_{matching_result.questionnaire.name}_{ts}.pdf',
            )

        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import mm, cm
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
                Flowable, BaseDocTemplate, PageTemplate, Frame,
            )
            from reportlab.lib import colors
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.pdfbase.pdfmetrics import registerFontFamily

            font_name = _get_chinese_font()

            doc = SimpleDocTemplate(
                output_path, pagesize=A4,
                rightMargin=20*mm, leftMargin=20*mm,
                topMargin=25*mm, bottomMargin=20*mm,
            )

            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'CustomTitle', parent=styles['Title'],
                fontName=font_name, fontSize=24, leading=30,
                spaceAfter=30, alignment=1,
            )
            heading_style = ParagraphStyle(
                'CustomHeading', parent=styles['Heading1'],
                fontName=font_name, fontSize=16, leading=20,
                spaceAfter=12, textColor=colors.HexColor('#1a1a1a'),
            )
            subheading_style = ParagraphStyle(
                'CustomSubHeading', parent=styles['Heading2'],
                fontName=font_name, fontSize=12, leading=16,
                spaceAfter=8, textColor=colors.HexColor('#333333'),
            )
            normal_style = ParagraphStyle(
                'CustomNormal', parent=styles['Normal'],
                fontName=font_name, fontSize=10, leading=14, spaceAfter=6,
            )
            cover_style = ParagraphStyle(
                'CoverTitle', parent=styles['Title'],
                fontName=font_name, fontSize=32, leading=40,
                alignment=1, textColor=colors.HexColor('#1a1a1a'),
            )
            cover_sub_style = ParagraphStyle(
                'CoverSub', parent=styles['Normal'],
                fontName=font_name, fontSize=16, leading=22,
                alignment=1, textColor=colors.HexColor('#666666'),
            )

            story = []

            # ── 封面 ──
            story.append(Spacer(1, 60*mm))
            story.append(Paragraph('OpenGaokao', ParagraphStyle(
                'Logo', fontName=font_name, fontSize=28,
                alignment=1, textColor=colors.HexColor('#1565C0'),
            )))
            story.append(Spacer(1, 8*mm))
            story.append(Paragraph('高考志愿推荐', ParagraphStyle(
                'T4SubTitle', fontName=font_name, fontSize=14,
                alignment=1, textColor=colors.HexColor('#666666'),
            )))
            story.append(Spacer(1, 15*mm))

            q = matching_result.questionnaire
            story.append(Paragraph(f'{q.name}同学 专属志愿规划报告书', cover_style))
            story.append(Spacer(1, 10*mm))
            story.append(Paragraph(
                f'{q.category} · {q.total_score}分 · 第{q.rank}名',
                ParagraphStyle('T4Score', fontName=font_name, fontSize=14,
                               alignment=1, textColor=colors.HexColor('#333333')),
            ))
            story.append(Spacer(1, 5*mm))
            story.append(Paragraph(
                '录取数据 + 项目自编偏好问卷（非心理诊断）',
                ParagraphStyle('T4Tag', fontName=font_name, fontSize=12,
                               alignment=1, textColor=colors.HexColor('#888888')),
            ))
            story.append(Spacer(1, 15*mm))
            cover_info = [
                ['考生姓名', q.name],
                ['本地标识码', q.exam_id if q.exam_id else '—'],
                ['总分', f'{q.total_score}分'],
                ['位次', f'第{q.rank}名'],
                ['科类', q.category],
                ['高考年份', str(getattr(q, 'gaokao_year', 2026))],
            ]
            cover_table = Table(
                cover_info, colWidths=[40*mm, 80*mm],
            )
            cover_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 12),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f5f5f5')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
            ]))
            story.append(cover_table)
            story.append(Spacer(1, 20*mm))
            story.append(Paragraph(
                f'报告生成日期：{datetime.now().strftime("%Y年%m月%d日")}',
                ParagraphStyle('Date', fontName=font_name, fontSize=11,
                               alignment=1, textColor=colors.HexColor('#888888')),
            ))

            story.append(PageBreak())

            # ── 页眉水印 ──
            def header_footer(canvas, doc):
                canvas.saveState()
                canvas.setFont(font_name, 8)
                canvas.setFillColor(colors.HexColor('#bbbbbb'))
                canvas.drawString(20*mm, A4[1] - 15*mm, 'OpenGaokao 高考志愿规划')
                if hasattr(doc, '_exam_id') and doc._exam_id:
                    canvas.drawRightString(
                        A4[0] - 20*mm, A4[1] - 15*mm,
                        f'本地标识码：{doc._exam_id}',
                    )
                canvas.restoreState()

            # ── 正文 ──
            story.append(Paragraph('一、考生基本信息', heading_style))
            info_data = [
                ['姓名', q.name, '科类', q.category],
                ['总分', str(q.total_score), '位次', str(q.rank)],
                ['性别', q.gender, '本地标识码', q.exam_id],
            ]
            info_table = Table(
                info_data, colWidths=[30*mm, 50*mm, 30*mm, 50*mm],
            )
            info_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(info_table)
            story.append(Spacer(1, 15))

            # 项目自编偏好问卷结果
            if matching_result.personality_result:
                story.append(Paragraph('二、偏好问卷结果（项目自编，非心理诊断）', heading_style))
                p = matching_result.personality_result
                bf = p.big_five
                personality_data = [
                    [
                        '大五维度偏好',
                        f"O={bf.get('O', 0)} C={bf.get('C', 0)} "
                        f"E={bf.get('E', 0)} A={bf.get('A', 0)} N={bf.get('N', 0)}",
                        'RIASEC 风格代码', p.holland_code,
                    ],
                    ['置信度', p.confidence, 'SD检测', f'{p.sd_score}/4'],
                ]
                personality_table = Table(
                    personality_data, colWidths=[30*mm, 50*mm, 30*mm, 50*mm],
                )
                personality_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), font_name),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                story.append(personality_table)
                story.append(Spacer(1, 15))

            # 志愿偏好
            story.append(Paragraph('三、志愿偏好', heading_style))
            preference_data = [
                ['核心诉求', q.core_demand or '未定'],
                ['稳定性偏好', f'{q.stability_preference}/5'],
                ['风险策略', _translate_term(matching_result.risk_strategy)],
            ]
            pref_table = Table(
                preference_data, colWidths=[40*mm, 120*mm],
            )
            pref_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(pref_table)
            story.append(Spacer(1, 15))

            # 推荐方案 — 按批次组织
            story.append(Paragraph('四、推荐方案', heading_style))
            from gaokao.core.volunteer_recommender import BATCH_ADMISSION_ORDER

            batch_groups = {}
            for category in ['冲', '稳', '保', '垫']:
                for school in matching_result.recommendations.get(category, []):
                    school._chong_wen_bao = category
                    b = school.batch if school.batch else '其他'
                    if b not in batch_groups:
                        batch_groups[b] = []
                    batch_groups[b].append(school)

            def _batch_sort_key(key):
                if key in BATCH_ADMISSION_ORDER:
                    return BATCH_ADMISSION_ORDER.index(key)
                return 999

            sorted_batches = sorted(batch_groups.keys(), key=_batch_sort_key)

            for batch_idx, batch_key in enumerate(sorted_batches):
                schools = batch_groups[batch_key]
                story.append(Paragraph(f'4.{batch_idx+1} {batch_key}', subheading_style))

                for category in ['冲', '稳', '保', '垫']:
                    cat_schools = [s for s in schools if getattr(s, '_chong_wen_bao', '') == category]
                    if not cat_schools:
                        continue
                    color_map = {'冲': '#E65100', '稳': '#1565C0', '保': '#2E7D32'}
                    cat_style = ParagraphStyle(
                        f'T4Cat_{batch_key}_{category}', parent=normal_style,
                        fontName=font_name, fontSize=11, leading=15,
                        spaceBefore=6, spaceAfter=4,
                        textColor=colors.HexColor(color_map.get(category, '#333')),
                    )
                    story.append(Paragraph(f'{category}（{len(cat_schools)}所）', cat_style))

                    # P0-2 闭环：保档若含垫，加红色警示段
                    if category == '保':
                        fallback_count = sum(1 for s in cat_schools if getattr(s, 'safety_warning', None))
                        if fallback_count > 0:
                            warn_style = ParagraphStyle(
                                f'BaoFallback_{batch_key}', parent=normal_style,
                                fontName=font_name, fontSize=9, leading=12,
                                textColor=colors.HexColor('#c62828'),
                                backColor=colors.HexColor('#fff3cd'),
                                borderColor=colors.HexColor('#f57c00'),
                                borderWidth=1, borderPadding=4,
                                spaceBefore=2, spaceAfter=4,
                            )
                            story.append(Paragraph(
                                f'⚠ 注意：本档含 {fallback_count} 所"垫"志愿（50%-85% 概率）。'
                                f'标准保底（≥85%）数量不足，请谨慎评估并优先填写"标准"行。',
                                warn_style,
                            ))

                    table_data = [
                        ['序号', '院校名称', '院校层级', '地点', '录取概率', '置信度', '兜底'],
                    ]
                    table_styles_extra = []
                    for i, school in enumerate(cat_schools[:15], 1):
                        tier_str = f"{school.tier_level} {school.tier_name}" if school.tier_level else school.school_quality
                        # P0-2 闭环：兜底类型列
                        if category == '保':
                            if getattr(school, 'safety_warning', None):
                                bao_cell = '⚠补充'
                                table_styles_extra.append(('TEXTCOLOR', (6, i), (6, i), colors.HexColor('#c62828')))
                                table_styles_extra.append(('FONTNAME', (6, i), (6, i), font_name))
                                table_styles_extra.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#fff8e1')))
                            else:
                                bao_cell = '标准'
                                table_styles_extra.append(('TEXTCOLOR', (6, i), (6, i), colors.HexColor('#2e7d32')))
                        else:
                            bao_cell = '—'
                        table_data.append([
                            str(i), school.school_name, tier_str,
                            school.location, f'{school.probability:.1f}%',
                            _get_confidence_display(school.confidence), bao_cell,
                        ])
                    table = Table(
                        table_data,
                        colWidths=[10*mm, 42*mm, 22*mm, 22*mm, 22*mm, 18*mm, 14*mm],
                    )
                    table.setStyle(TableStyle([
                        ('FONTNAME', (0, 0), (-1, -1), font_name),
                        ('FONTSIZE', (0, 0), (-1, -1), 8),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e0e0')),
                        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ] + table_styles_extra))
                    story.append(table)
                    story.append(Spacer(1, 8))

            # AI个性化解读
            narratives = self._generate_ai_narrative(
                matching_result.personality_result,
                matching_result.recommendations,
                matching_result,
            )
            if narratives:
                story.append(Paragraph('五、AI个性化解读', heading_style))
                for narrative in narratives:
                    story.append(Paragraph(f"· {narrative}", normal_style))
                story.append(Spacer(1, 10))

            # ══════════════════════════════════════
            # 深度层专属：四大深度解析
            # ══════════════════════════════════════

            # ── 推荐院校TOP5深度解析 ──
            story.append(Paragraph('六、推荐院校深度解析', heading_style))
            story.append(Spacer(1, 5))
            _top_schools = []
            for cat in ['冲', '稳', '保', '垫']:
                for school in matching_result.recommendations.get(cat, []):
                    _top_schools.append((cat, school))
                    if len(_top_schools) >= 5:
                        break
                if len(_top_schools) >= 5:
                    break

            for cat, school in _top_schools[:5]:
                story.append(Paragraph(
                    f'{school.school_name}（{cat}档，录取概率{school.probability:.0f}%）',
                    subheading_style,
                ))
                # 从数据库查询详情
                _conn = None
                try:
                    _conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    _cur = _conn.cursor()
                    _cur.execute(
                        "SELECT school_level, location, tuition_year, website, established_year "
                        "FROM enroll_detail WHERE school_name=? LIMIT 1",
                        (school.school_name,),
                    )
                    _row = _cur.fetchone()
                except Exception:
                    _row = None
                finally:
                    if _conn:
                        _conn.close()

                tier_display = f"{school.tier_level} {school.tier_name}" if school.tier_level else school.school_quality
                if _row:
                    school_info = [
                        ['院校等级', _row[0] or tier_display],
                        ['地理位置', _row[1] or school.location],
                        ['学费', f'{_row[2]}元/年' if _row[2] else '—'],
                        ['官网', _row[3] or '—'],
                        ['建校年份', str(_row[4]) if _row[4] else '—'],
                    ]
                else:
                    school_info = [
                        ['院校等级', tier_display],
                        ['地理位置', school.location],
                    ]
                si_table = Table(school_info, colWidths=[30*mm, 130*mm])
                si_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), font_name),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e0e0e0')),
                    ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f5f5f5')),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('TOPPADDING', (0, 0), (-1, -1), 3),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ]))
                story.append(si_table)

                # 推荐专业
                if school.recommended_majors:
                    majors_str = ', '.join([
                        m.major_name + (' [2026新增]' if getattr(m, 'is_new_major', False) else '')
                        for m in school.recommended_majors[:3]
                    ])
                    story.append(Paragraph(f'推荐专业：{majors_str}', normal_style))

                # 替代专业
                alts = getattr(school, 'similar_alternatives', [])
                if alts:
                    story.append(Paragraph(
                        f'替代专业：{" → ".join(alts[:3])}',
                        ParagraphStyle('Alt', fontName=font_name, fontSize=9,
                                       leading=12, textColor=colors.HexColor('#666666')),
                    ))
                story.append(Spacer(1, 8))

            story.append(Spacer(1, 10))

            # ── 推荐专业TOP5深度解析 ──
            story.append(Paragraph('七、推荐专业深度解析', heading_style))
            story.append(Spacer(1, 5))
            _all_majors_seen = set()
            _top_majors = []
            for cat in ['冲', '稳', '保', '垫']:
                for school in matching_result.recommendations.get(cat, []):
                    for mp in (school.recommended_majors or []):
                        if mp.major_name not in _all_majors_seen:
                            _all_majors_seen.add(mp.major_name)
                            _top_majors.append(mp)
                            if len(_top_majors) >= 5:
                                break
                    if len(_top_majors) >= 5:
                        break
                if len(_top_majors) >= 5:
                    break

            for mp in _top_majors[:5]:
                story.append(Paragraph(mp.major_name, subheading_style))
                # 从major_catalog查询
                _conn = None
                try:
                    _conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    _cur = _conn.cursor()
                    _cur.execute(
                        "SELECT core_courses, employment_direction, further_study_path, industry_trend "
                        "FROM major_catalog WHERE major_name=? LIMIT 1",
                        (mp.major_name,),
                    )
                    _row = _cur.fetchone()
                except Exception:
                    _row = None
                finally:
                    if _conn:
                        _conn.close()

                if _row:
                    major_info = []
                    if _row[0]:
                        major_info.append(['核心课程', _row[0]])
                    if _row[1]:
                        major_info.append(['就业方向', _row[1]])
                    if _row[2]:
                        major_info.append(['深造路径', _row[2]])
                    if _row[3]:
                        major_info.append(['行业趋势', _row[3]])
                    if major_info:
                        mi_table = Table(major_info, colWidths=[30*mm, 130*mm])
                        mi_table.setStyle(TableStyle([
                            ('FONTNAME', (0, 0), (-1, -1), font_name),
                            ('FONTSIZE', (0, 0), (-1, -1), 9),
                            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e0e0e0')),
                            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f5f5f5')),
                            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                            ('TOPPADDING', (0, 0), (-1, -1), 3),
                            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                        ]))
                        story.append(mi_table)
                        continue
                story.append(Paragraph('暂无详细数据', normal_style))
                story.append(Spacer(1, 5))

            story.append(Spacer(1, 10))

            # ── 城市深度解析 ──
            story.append(Paragraph('八、推荐院校所在城市解析', heading_style))
            story.append(Spacer(1, 5))
            _cities = set()
            for cat in ['冲', '稳', '保', '垫']:
                for school in matching_result.recommendations.get(cat, []):
                    loc = school.location or ''
                    # 提取省份
                    for province in ['北京', '上海', '广东', '江苏', '浙江', '四川', '云南',
                                     '湖北', '湖南', '山东', '天津', '重庆', '广西', '贵州',
                                     '河北', '福建', '河南', '安徽', '陕西', '山西']:
                        if province in loc:
                            _cities.add(province)
                            break

            city_details = {
                '北京': {
                    'intro': '首都，全国政治/文化/科技中心，高校数量全国第一（清华/北大/人大等90余所）',
                    'industries': '重点产业：互联网（字节/百度/美团）、金融（央行/四大行总部）、央企总部、文化传媒、生物医药、航空航天',
                    'companies': '代表企业：字节跳动、百度、美团、京东、小米、中国银行、中国移动、中国航天科技集团',
                    'cost': '生活成本：高（租房 3000-6000/月，餐饮 30-80/餐）',
                },
                '上海': {
                    'intro': '国际金融中心，全球城市，高校密集（复旦/交大/同济等60余所）',
                    'industries': '重点产业：金融（证券/期货/保险）、半导体（中芯国际）、汽车（上汽/特斯拉）、生物医药、人工智能',
                    'companies': '代表企业：拼多多、哔哩哔哩、携程、中芯国际、特斯拉、上海医药、交通银行',
                    'cost': '生活成本：高（租房 2500-5500/月，餐饮 25-70/餐）',
                },
                '广东': {
                    'intro': '粤港澳大湾区核心，制造业/科技/外贸全国领先，高校增长迅速',
                    'industries': '重点产业：电子制造（华为/中兴/OPPO/vivo）、互联网（腾讯/网易）、新能源汽车（比亚迪）、跨境电商',
                    'companies': '代表企业：华为、腾讯、比亚迪、大疆、OPPO、vivo、中兴、格力',
                    'cost': '生活成本：深圳/广州高（租房 2000-4500/月），珠三角其他城市中等',
                },
                '江苏': {
                    'intro': '经济强省，GDP全国第二，制造业/IT/新能源产业发达',
                    'industries': '重点产业：半导体（无锡/南京）、新能源（常州/苏州）、智能制造、生物医药、软件外包',
                    'companies': '代表企业：恒力集团、沙钢集团、中天钢铁、南瑞集团、药明康德、长电科技',
                    'cost': '生活成本：南京偏高（租房 1500-3000/月），苏州/无锡中等',
                },
                '浙江': {
                    'intro': '数字经济标杆省份，民营经济活跃，创业氛围浓厚',
                    'industries': '重点产业：电商/互联网（阿里/网易）、智能制造、新材料、生命健康、海洋经济',
                    'companies': '代表企业：阿里巴巴、网易、吉利汽车、海康威视、大华股份、万向集团',
                    'cost': '生活成本：杭州偏高（租房 1800-3500/月），宁波/温州中等',
                },
                '四川': {
                    'intro': '西南中心，成都为国家中心城市，IT/游戏/消费产业活跃',
                    'industries': '重点产业：电子信息（成都高新区）、游戏开发（全国第四大游戏产业中心）、航空航天、食品饮料',
                    'companies': '代表企业：腾讯成都、京东成都、华为成研所、长虹、五粮液、通威太阳能',
                    'cost': '生活成本：中等（租房 1000-2500/月，餐饮 15-40/餐），宜居城市',
                },
                '云南': {
                    'intro': '本地就业为主，面向南亚东南亚辐射中心',
                    'industries': '重点产业：旅游文化、烟草、矿业、绿色能源（水电/光伏）、高原特色农业、生物医药',
                    'companies': '代表企业：云南白药、红塔集团、云天化、云天物流、云铝股份',
                    'cost': '生活成本：中低（租房 800-2000/月），昆明稍高',
                },
                '湖北': {
                    'intro': '教育强省（武汉高校数量全国第三），光谷科技产业集群',
                    'industries': '重点产业：光电子信息（光谷）、汽车制造（东风）、生物医药、钢铁冶金',
                    'companies': '代表企业：东风汽车、长江存储、高德红外、烽火通信、人福医药',
                    'cost': '生活成本：中等（租房 1000-2200/月）',
                },
                '湖南': {
                    'intro': '长沙为国家消费中心城市，房价低宜居，工程机械产业全国领先',
                    'industries': '重点产业：工程机械（三一/中联）、文化传媒（湖南广电）、新材料、电子信息',
                    'companies': '代表企业：三一重工、中联重科、蓝思科技、楚天科技、芒果TV',
                    'cost': '生活成本：低（租房 800-1800/月），房价收入比全国最低之一',
                },
                '山东': {
                    'intro': '工业大省，GDP全国第三，制造业/海洋经济/农业科技强',
                    'industries': '重点产业：装备制造（潍柴/海尔）、海洋科技、化工、家电制造、农业科技',
                    'companies': '代表企业：海尔、海信、潍柴动力、万华化学、歌尔股份、浪潮集团',
                    'cost': '生活成本：中等（租房 800-1800/月），青岛稍高',
                },
                '天津': {
                    'intro': '北方港口城市，直辖市，制造业/港口物流发达',
                    'industries': '重点产业：航空航天（空客A320总装）、石油化工、港口物流、生物医药',
                    'companies': '代表企业：空客天津、一汽丰田、天士力、渤海银行、天津港集团',
                    'cost': '生活成本：中等偏高（低于北京，租房 1200-2500/月）',
                },
                '重庆': {
                    'intro': '西南工业中心，直辖市，制造业/IT/汽车产业发达',
                    'industries': '重点产业：汽车制造（长安/力帆）、电子信息（惠普/广达笔电基地）、装备制造、跨境电商',
                    'companies': '代表企业：长安汽车、赛力斯、重庆钢铁、力帆科技、龙湖集团',
                    'cost': '生活成本：中等（租房 800-2000/月），美食之都',
                },
                '广西': {
                    'intro': '东盟贸易窗口，北部湾经济区，区域交通枢纽',
                    'industries': '重点产业：有色金属（铝业）、糖业、汽车制造（上汽通用五菱）、跨境贸易',
                    'companies': '代表企业：上汽通用五菱、柳钢集团、柳工集团、北部湾港',
                    'cost': '生活成本：中低（租房 600-1500/月），南宁稍高',
                },
                '贵州': {
                    'intro': '大数据产业发展快（贵阳·中国数谷），但整体就业市场偏小',
                    'industries': '重点产业：大数据（苹果/华为数据中心）、白酒（茅台）、能源（煤电/水电）、旅游',
                    'companies': '代表企业：贵州茅台、老干妈、贵州能源集团、云上贵州',
                    'cost': '生活成本：低（租房 600-1200/月），贵阳稍高',
                },
                '河北': {
                    'intro': '环京津冀区域，雄安新区建设带动区域发展',
                    'industries': '重点产业：钢铁（河钢）、装备制造、化工、现代农业、雄安基建',
                    'companies': '代表企业：河钢集团、长城汽车、华北制药、冀中能源',
                    'cost': '生活成本：中等偏低（租房 600-1500/月），考公考研氛围浓厚',
                },
            }
            for city in sorted(_cities):
                story.append(Paragraph(f'{city}', subheading_style))
                cd = city_details.get(city)
                if cd:
                    story.append(Paragraph(cd['intro'], normal_style))
                    story.append(Paragraph(cd['industries'], normal_style))
                    story.append(Paragraph(cd['companies'], normal_style))
                    story.append(Paragraph(cd['cost'], normal_style))
                else:
                    story.append(Paragraph('暂无该城市详细分析', normal_style))
            if not _cities:
                story.append(Paragraph('暂无城市数据', normal_style))
            story.append(Spacer(1, 10))

            # ── 求学指南 ──
            story.append(Paragraph('九、大学四年规划指南', heading_style))
            story.append(Spacer(1, 5))
            guide_sections = [
                ('大一：适应与探索',
                 '· 了解大学学习方式和专业要求\n'
                 '· 参加社团活动，扩展人际网络\n'
                 '· 探索专业兴趣方向，尝试不同课程\n'
                 '· 关注转专业和辅修政策（如需要）'),
                ('大二：专业深耕',
                 '· 打好专业基础课程\n'
                 '· 开始准备考研/考证/实习\n'
                 '· 关注学科竞赛和科研项目\n'
                 '· 建立专业人脉（学长学姐、导师）'),
                ('大三：能力提升',
                 '· 确定就业/考研/出国方向\n'
                 '· 考研：开始系统复习\n'
                 '· 就业：积极实习，积累工作经验\n'
                 '· 考取相关职业资格证书'),
                ('大四：冲刺阶段',
                 '· 考研：冲刺复习+报名\n'
                 '· 就业：秋季校园招聘+简历投递\n'
                 '· 完成毕业设计/论文\n'
                 '· 做好从校园到职场的过渡准备'),
            ]
            for title, content in guide_sections:
                story.append(Paragraph(title, subheading_style))
                story.append(Paragraph(content.replace('\n', '<br/>'), normal_style))
                story.append(Spacer(1, 5))

            story.append(Spacer(1, 10))

            # ── 保研·考研·就业策略（深度层专属）──
            story.append(Paragraph('十、保研·考研·就业策略', heading_style))
            story.append(Spacer(1, 5))

            # 10.1 保研策略
            story.append(Paragraph('10.1 保研策略', subheading_style))
            story.append(Paragraph(
                '保研是本科毕业直接获得研究生推免资格的途径，各层次高校保研率差异显著：',
                normal_style,
            ))
            baoyan_data = [
                ['学校层次', '保研率', '代表院校', '核心要求'],
                ['985 高校', '20%-35%', '清华/北大/华科', 'GPA 前 30%，科研/竞赛加分'],
                ['211 高校', '10%-20%', '云南大学/贵州大学', 'GPA 前 15%，无挂科记录'],
                ['普通本科', '2%-5%', '各省地方院校', 'GPA 前 3%，英语六级优先'],
                ['民办/独立学院', '1%-2%', '各省民办本科', 'GPA 前 1%，竞争极为激烈'],
            ]
            by_table = Table(baoyan_data, colWidths=[25*mm, 20*mm, 45*mm, 70*mm])
            by_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e3f2fd')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(by_table)
            story.append(Spacer(1, 5))
            story.append(Paragraph(
                '· 关键节点：大一打基础（GPA最重要）、大二出成绩（争取科研/竞赛加分）、大三冲排名（确定保研资格）'
                '<br/>· 科研加分：参与导师项目 > 发表论文 > 学科竞赛获奖（互联网+/挑战杯/数学建模）'
                '<br/>· 英语要求：多数院校要求 CET-6 ≥ 425 分或 CET-4 ≥ 490 分',
                normal_style,
            ))
            story.append(Spacer(1, 8))

            # 10.2 考研策略
            story.append(Paragraph('10.2 考研策略', subheading_style))
            story.append(Paragraph(
                '考研是全国统一考试的研究生入学考试，时间线固定：',
                normal_style,
            ))
            kaoyan_timeline = [
                '大三下（3-6月）：确定目标院校+专业，开始系统复习（数学/英语/政治/专业课）',
                '大三暑假（7-8月）：强化复习阶段，每天学习 8-10 小时',
                '大四上（9-10月）：考研报名 + 冲刺复习',
                '大四上（12月）：全国统一初试',
                '大四下（次年3-4月）：复试（笔试+面试），部分院校需调剂',
            ]
            for step in kaoyan_timeline:
                story.append(Paragraph(f'· {step}', normal_style))
            story.append(Spacer(1, 5))
            story.append(Paragraph(
                '· 专业选择：本专业深造（复试优势大）vs 跨专业（需提前 1-2 年准备）'
                '<br/>· 院校选择：本校（熟悉环境）/ 同层次（难度适中）/ 冲刺 985（竞争激烈）'
                '<br/>· 近年趋势：考研报名人数连续两年下降，但热门专业（计算机/金融/法学）竞争比仍高达 10:1 以上',
                normal_style,
            ))
            story.append(Spacer(1, 8))

            # 10.3 就业策略
            story.append(Paragraph('10.3 就业策略', subheading_style))
            story.append(Paragraph(
                '校招是应届生求职最高效的通道，错过校招窗口期将大幅增加求职难度：',
                normal_style,
            ))
            jiuye_timeline = [
                '大四上 9-11 月：秋季校园招聘（最重要，岗位最多，竞争相对小）',
                '大四上 12-1月：国考/省考报名 + 部分企业补录',
                '大四下 3-5 月：春季校园招聘（岗位较少，为最后窗口期）',
                '大四下 6-7 月：毕业派遣，签订三方协议',
            ]
            for step in jiuye_timeline:
                story.append(Paragraph(f'· {step}', normal_style))
            story.append(Spacer(1, 5))

            # 行业差异化建议
            q_t4 = matching_result.questionnaire
            if q_t4.target_industries:
                ind = q_t4.target_industries[0]
                industry_advice = {
                    '信息技术/互联网': '· 技术岗（开发/算法）：重视项目经验，GitHub 和竞赛成绩比 GPA 更重要<br/>· 非技术岗（产品/运营）：实习经历和产品 Sense 是核心<br/>· 秋招时间线：8月开始提前批，9-10月正式批',
                    '医疗健康': '· 临床方向：本科 5 年 + 规培 3 年，整体周期长，建议做好读研准备<br/>· 护理方向：就业率接近 100%，三甲医院编制竞争激烈<br/>· 医学影像/检验：技术门槛高，本科就业相对容易',
                    '先进制造': '· 工科专业对口性强，实习/项目经验是核心<br/>· 国企（中船/中航/中车）看重学校背景和党员身份<br/>· 民企（华为/比亚迪/宁德时代）看重技术能力',
                    '金融/银行': '· 银行校招：秋招 9月开始，看重学校层次（985/211优先）+ 实习<br/>· 券商/基金：基本要求硕士 + CPA/CFA，本科直接进入难度极大<br/>· 考公对口岗位：税务局/审计局/财政局',
                    '教育/师范': '· 公费师范生：毕业直接分配，但有服务期限制<br/>· 非公费师范：需参加教师编制考试，竞争比 5:1-15:1<br/>· 少子化趋势下，学前/小学教师需求下降，建议关注高中/职教方向',
                }
                advice = industry_advice.get(ind, f'· 关注{ind}行业的秋招时间线和核心能力要求，提前准备简历和面试')
                story.append(Paragraph(f'针对您关注的"{ind}"行业：', normal_style))
                story.append(Paragraph(advice.replace('\n', '<br/>'), normal_style))
            story.append(Spacer(1, 5))

            # 家庭资源差异化建议
            fr_t4 = getattr(matching_result, 'family_resource_result', None)
            if fr_t4:
                if fr_t4.rating == '高':
                    story.append(Paragraph(
                        '· 家庭资源充裕：可考虑出国交换/中外合作办学/海外研究生等路径，'
                        '拓展国际视野。同时可利用家庭人脉获取优质实习机会。',
                        normal_style,
                    ))
                elif fr_t4.rating == '低':
                    story.append(Paragraph(
                        '· 家庭资源有限：建议优先选择技术壁垒高、个人能力主导的专业方向，'
                        '关注国家助学贷款和奖助学金项目。考研是改变职业起点的重要途径。',
                        normal_style,
                    ))

            story.append(Spacer(1, 10))

            # ── 家庭资源匹配深度分析 ──
            fr = getattr(matching_result, 'family_resource_result', None)
            if fr:
                story.append(Paragraph('十、家庭资源与专业选择匹配分析', heading_style))
                story.append(Spacer(1, 5))
                story.append(Paragraph(
                    f'家庭就业支持能力评级：<b>{fr.rating}</b>（综合得分{fr.total_score:.1f}/100）',
                    normal_style,
                ))
                # 对每个推荐专业的匹配度分析
                story.append(Spacer(1, 5))
                story.append(Paragraph('各推荐专业与家庭资源匹配度：', subheading_style))
                for cat in ['冲', '稳', '保', '垫']:
                    for school in matching_result.recommendations.get(cat, []):
                        for mp in (school.recommended_majors or [])[:1]:
                            match_level = '高' if fr.rating == '高' else ('中' if fr.rating == '中' else '低')
                            match_desc = ''
                            if fr.rating == '高':
                                match_desc = '家庭资源充足，可自由选择任何专业方向'
                            elif fr.rating == '中':
                                match_desc = '建议以个人能力为主，适度利用家庭人脉资源'
                            else:
                                if '中外合作' in school.school_name or '中外合作' in school.school_quality:
                                    match_desc = '⚠️ 家庭资源有限 + 高学费专业，建议谨慎考虑投入产出比'
                                else:
                                    match_desc = '建议选择技术壁垒高、个人能力主导的专业方向'
                            story.append(Paragraph(
                                f'· {school.school_name} - {mp.major_name}：匹配度{match_level} — {match_desc}',
                                normal_style,
                            ))
                story.append(Spacer(1, 10))

            # ── 禁忌项风险规避建议 ──
            cr = getattr(matching_result, 'constraint_result', None)
            if cr:
                story.append(Paragraph('十一、禁忌项风险规避建议', heading_style))
                story.append(Spacer(1, 5))
                if cr.filtered_majors:
                    story.append(Paragraph(
                        f'您有{len(cr.filtered_majors)}个专业受限。以下是规避建议：',
                        normal_style,
                    ))
                    story.append(Spacer(1, 3))
                    # 针对常见受限专业的替代建议
                    restricted_major_advice = {
                        '化学类': '可考虑应用化学（部分院校不限色觉）或化工工艺管理方向',
                        '药学类': '可考虑药学管理、医药营销等非实验方向',
                        '生物科学类': '可考虑生物信息学（计算方向）或生物科技管理',
                        '医学类': '可考虑医学信息管理、公共卫生管理、医疗器械等非临床方向',
                        '农学类': '可考虑农业经济管理、农产品营销等管理方向',
                        '地质学类': '可考虑地理信息系统（GIS）等计算方向',
                        '材料类': '可考虑材料工程管理、材料贸易等方向',
                        '环境类': '可考虑环境工程管理、环保咨询等方向',
                        '食品类': '可考虑食品质量管理、食品安全监管等方向',
                        '公安技术类': '可考虑信息安全、计算机科学与技术（非公安方向）',
                        '天文学': '可考虑物理学（理论方向）或数据科学',
                        '摄影': '可考虑数字媒体技术、视觉传达设计（部分院校不限色觉）',
                        '交通运输': '可考虑物流管理、交通工程规划等方向',
                        '美术': '可考虑数字媒体艺术、工业设计等计算方向',
                        '艺术设计': '可考虑UI/UX设计、产品设计等数字方向',
                        '心理学': '可考虑应用心理学（非实验方向）或人力资源管理',
                        '飞行技术': '可考虑交通运输管理、航空服务管理等方向',
                        '航海技术': '可考虑港口物流管理、国际贸易等方向',
                        '消防工程': '可考虑安全工程、应急管理等方向',
                        '刑事科学技术': '可考虑法学、信息安全等方向',
                        '轮机工程': '可考虑机械工程、船舶与海洋工程（非航海方向）',
                        '民族传统体育': '可考虑体育教育、运动训练等方向',
                        '体育教育': '可考虑运动人体科学、体育管理等方向',
                        '公安学类': '可考虑法学、行政管理、社会学等方向',
                        '侦查学': '可考虑法学、信息安全、计算机等方向',
                        '治安学': '可考虑行政管理、法学、社会学等方向',
                    }
                    for major in cr.filtered_majors[:10]:
                        advice = None
                        for key, val in restricted_major_advice.items():
                            if key in major:
                                advice = val
                                break
                        if advice:
                            story.append(Paragraph(
                                f'· {major} → {advice}', normal_style,
                            ))
                        else:
                            story.append(Paragraph(
                                f'· {major} → 建议选择与受限专业相关但无体检要求的专业方向',
                                normal_style,
                            ))
                if not cr.police_qualified or not cr.military_qualified:
                    story.append(Spacer(1, 5))
                    if not cr.police_qualified:
                        story.append(Paragraph(
                            '⛔ 警校资格不合格 — 可考虑法学、行政管理、计算机等替代方向',
                            ParagraphStyle('PoliceWarn', fontName=font_name, fontSize=9,
                                           leading=12, textColor=colors.HexColor('#c62828')),
                        ))
                    if not cr.military_qualified:
                        story.append(Paragraph(
                            '⛔ 军校资格不合格 — 可考虑普通院校的国防相关专业（如信息安全）',
                            ParagraphStyle('MilitaryWarn', fontName=font_name, fontSize=9,
                                           leading=12, textColor=colors.HexColor('#c62828')),
                        ))
                story.append(Spacer(1, 10))

            # ── 转专业与大类分流深度指南（深度层专属）──
            story.append(Paragraph('十二、转专业与大类分流深度解析', heading_style))
            story.append(Spacer(1, 5))
            story.append(Paragraph(
                '转专业和大类分流是大学期间两次重要的专业调整机会，'
                '但各校政策差异巨大，信息不对称可能导致错误决策。',
                ParagraphStyle('TransIntro2', fontName=font_name, fontSize=9,
                               leading=12, textColor=colors.HexColor('#666666'),
                               spaceAfter=8),
            ))

            # 1. 转专业政策
            story.append(Paragraph('12.1 转专业政策全景', subheading_style))
            story.append(Paragraph(
                '转专业是第一次调整机会，但门槛因校而异。以下为典型分层：',
                normal_style,
            ))
            transfer_rules2 = [
                ['层级', '代表院校', '转专业门槛', '成功率估计'],
                ['零门槛', '中国科学技术大学、西安交通大学', '申请即可，无成绩/GPA要求', '70%+'],
                ['低门槛', '武汉大学、中山大学、厦门大学', 'GPA≥3.0或无前30%限制', '50%-70%'],
                ['中门槛', '浙江大学、南京大学、同济大学', 'GPA前20%-30% + 面试', '20%-40%'],
                ['高门槛', '北京大学、清华大学、复旦大学', 'GPA前10% + 笔试+面试', '5%-15%'],
                ['特殊限制', '医学类/师范类院校', '不可跨类转或仅限同大类内转', '10%-30%'],
            ]
            tr_table2 = Table(transfer_rules2, colWidths=[20*mm, 30*mm, 55*mm, 25*mm])
            tr_table2.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e3f2fd')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(tr_table2)
            story.append(Spacer(1, 8))

            # 2. 重点班冰山
            story.append(Paragraph('12.2 重点班/实验班背后的冰山', subheading_style))
            story.append(Paragraph(
                '部分院校的"重点班"或"实验班"看似光鲜，但背后隐藏着分流压力、'
                '竞争强度等不公开信息：',
                normal_style,
            ))
            ice_points = [
                '分流压力：部分重点班实行"末位淘汰制"，大一GPA排名末位10%-20%学生会被分流到普通班',
                '竞争强度：重点班内学生普遍为各省高分考生，"宁为鸡头不为凤尾"效应显著',
                '资源倾斜：重点班通常享有优先选课、优先保研、优先出国等资源优势',
                '退出机制：部分重点班退出后只能去"兜底"专业，可能比直接录取的普通班还差',
                '信息不对称：招生简章通常只宣传优势，不提及淘汰率和退出路径',
            ]
            for point in ice_points:
                story.append(Paragraph(f'· {point}', normal_style))
            story.append(Spacer(1, 8))

            # 3. 大类分流
            story.append(Paragraph('12.3 大类招生分流详解', subheading_style))
            story.append(Paragraph(
                '大类招生是第二次调整机会（或被调整），需重点关注以下问题：',
                normal_style,
            ))

            da_flow_questions = [
                '分流时间节点：大一末分流还是大二末？越早分流，准备时间越短',
                '分流标准：纯GPA排名？综合评定（GPA+志愿+面试）？还是高考成绩占一定权重？',
                '热门专业容量：大类内计算机/金融等热门专业每年容纳多少人？是否有名额上限？',
                '保底专业：若未被第一志愿接收，会被分配到什么专业？是否可接受？',
                '历年分流数据：该校是否公开往年各专业分流人数和最低GPA要求？',
                '跨大类转专业：大类分流后是否还能跨大类转专业？（通常更难）',
            ]
            for _dq in da_flow_questions:
                story.append(Paragraph(f'· {_dq}', normal_style))
            story.append(Spacer(1, 8))

            # 4. 推荐院校转专业政策调研指引
            story.append(Paragraph('12.4 推荐院校转专业政策调研指引', subheading_style))
            story.append(Paragraph(
                '建议对以下推荐院校逐一调研其转专业/分流政策：',
                normal_style,
            ))
            for cat in ['冲', '稳', '保', '垫']:
                for school in matching_result.recommendations.get(cat, []):
                    story.append(Paragraph(
                        f'· {school.school_name}（{cat}档）— 请访问该校教务处官网搜索"转专业管理办法"',
                        normal_style,
                    ))
                    if len(matching_result.recommendations.get(cat, [])) > 3:
                        break
                break  # 只列出"冲"档院校作为调研示例

            research_steps2 = [
                '建议：访问目标院校招生网 → 查看招生章程中"专业分流"条款 → 访问教务处搜索转专业文件 → 联系在校学长学姐了解实际执行情况',
                '重点关注：转专业开放时间、GPA要求、名额限制、热门专业竞争情况、历年实际转出比例',
                '对于大类招生院校：确认分流时间节点、考核方式和往年各专业接收人数',
            ]
            for step in research_steps2:
                story.append(Paragraph(f'· {step}', normal_style))
            story.append(Spacer(1, 10))

            # 咨询师备注
            if consultant_notes:
                story.append(Paragraph('十四、咨询师意见', heading_style))
                story.append(Paragraph(consultant_notes, normal_style))
                story.append(Spacer(1, 10))

            # ── 热门学科趋势 ──
            try:
                from gaokao.core.hot_major_analyzer import HotMajorAnalyzer
                analyzer = HotMajorAnalyzer(db_path=self.db_path)
                hot_scores = analyzer.analyze(year=2025)

                story.append(Paragraph('十三、热门学科趋势（2025-2045）', heading_style))
                story.append(Spacer(1, 5))

                hot_table_data = [
                    ['排名', '专业类', '门类', '综合', '当前', '趋势', '等级'],
                ]
                for s in hot_scores[:10]:
                    hot_table_data.append([
                        str(s.composite_rank),
                        s.major_class,
                        s.category,
                        f'{s.composite_score:.1f}',
                        f'{s.current_score:.1f}',
                        f'{s.trend_score:.1f}',
                        s.level,
                    ])
                hot_table = Table(
                    hot_table_data,
                    colWidths=[10*mm, 35*mm, 20*mm, 15*mm, 15*mm, 15*mm, 12*mm],
                )
                hot_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), font_name),
                    ('FONTSIZE', (0, 0), (-1, -1), 8),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1565C0')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                story.append(hot_table)
                story.append(Spacer(1, 5))
                story.append(Paragraph(
                    '数据源：教育部2026新增38专业 + 5年撤销1.22万专业点 + WEF 2025 + 麦肯锡2040 + 五大集群2045',
                    ParagraphStyle('Small', fontName=font_name, fontSize=7,
                                   leading=9, textColor=colors.HexColor('#888888')),
                ))
                story.append(Spacer(1, 4))
                story.append(Paragraph(
                    '透明度说明：[数据驱动] 新增/撤销专业、WEF 2025岗位增长 | [专家判断] 趋势因子权重、收敛集群评分',
                    ParagraphStyle('Tiny', fontName=font_name, fontSize=6.5,
                                   leading=8, textColor=colors.HexColor('#999999')),
                ))
            except Exception:
                pass

            story.append(Spacer(1, 10))

            # ── 数据完整性告警 + 签名页 ──
            story.append(PageBreak())

            # 报告编号
            import hashlib
            _report_hash = hashlib.md5(f'{q.name}{q.exam_id}{q.total_score}{q.rank}'.encode()).hexdigest()[:8].upper()
            report_id = f'YGC-{datetime.now().strftime("%Y%m%d")}-{_report_hash}'

            story.append(Paragraph('OpenGaokao 志愿规划报告书', heading_style))
            story.append(Paragraph(f'报告编号：{report_id}', ParagraphStyle(
                'ReportId', fontName=font_name, fontSize=11, leading=16,
                textColor=colors.HexColor('#666666'), spaceAfter=15,
            )))

            # 数据源声明
            story.append(Paragraph('数据源声明', subheading_style))
            story.append(Paragraph(
                '本报告使用以下数据源：'
                '1. 2020-2025年云南省高考录取数据（院校投档线、专业录取明细）；'
                '2. 2025年云南省招生计划数据（院校专业组目录）；'
                '3. WEF 2025《未来就业报告》岗位增长预测；'
                '4. 麦可思2024年大学生就业质量报告（就业率/起薪）；'
                '5. 2020-2024年全国高校专业撤销数据；'
                '6. 项目自编偏好问卷结果（大五维度、RIASEC 风格、学科自我评价、职业价值偏好；未经心理测量学验证，不作诊断）。',
                normal_style,
            ))
            story.append(Spacer(1, 10))

            # 数据完整性
            ok, data_msg, _ = check_data_completeness(self.db_path, q.category)
            story.append(Paragraph('数据完整性', subheading_style))
            story.append(Paragraph(data_msg, ParagraphStyle(
                'DataWarning', fontName=font_name, fontSize=10,
                leading=14, spaceAfter=6,
                textColor=colors.HexColor('#d32f2f') if not ok else colors.HexColor('#2e7d32'),
            )))
            notes = getattr(matching_result, 'notes', [])
            if notes:
                story.append(Paragraph('匹配说明:', subheading_style))
                for note in notes:
                    story.append(Paragraph(f'· {note}', normal_style))
            story.append(Spacer(1, 15))

            # 完整免责声明
            story.append(Paragraph('免责声明', subheading_style))
            disclaimer_items = [
                '1. 本推荐方案基于历史录取数据 + 项目自编偏好问卷 + 其他问卷偏好生成；偏好问卷未经心理测量学验证、不作诊断，仅供参考。',
                '2. 录取概率为统计模型预测值，不代表实际录取结果。高考录取受当年报考人数、招生计划变化等多种因素影响。',
                '3. 冲档学校存在落选风险，建议在冲档志愿中勾选"服从专业调剂"以降低退档风险。',
                '4. 云南新高考"院校专业组"模式：投档后若所填专业分数不够，不服从调剂将被直接退档。',
                '5. 专业级差风险：少数老牌强校仍采用"专业级差"规则，填报前请查阅目标院校《招生章程》。',
                '6. 最终志愿填报请以云南省招生考试院公布的2026年招生计划为准。',
                '7. 本报告不构成任何形式的录取保证，因使用本报告产生的任何后果由使用者自行承担。',
            ]
            for item in disclaimer_items:
                story.append(Paragraph(f'· {item}', normal_style))
            story.append(Spacer(1, 25*mm))

            # ═══════════════════ 签名页 ═══════════════════
            story.append(Paragraph('确认签字', heading_style))
            story.append(Spacer(1, 15*mm))
            sig_data = [
                ['考生签字', '________________________', '日期', '____年__月__日'],
                ['家长/监护人签字', '________________________', '日期', '____年__月__日'],
            ]
            if consultant_name:
                sig_data.append([
                    '交付老师签字', '________________________', '日期', '____年__月__日',
                ])
            sig_data.append([
                '总部审核', '________________________', '日期', '____年__月__日',
            ])
            sig_table = Table(
                sig_data, colWidths=[35*mm, 55*mm, 20*mm, 50*mm],
            )
            sig_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 11),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ]))
            story.append(sig_table)
            story.append(Spacer(1, 20*mm))
            story.append(Paragraph(
                'OpenGaokao · 高考志愿智能推荐',
                ParagraphStyle('Footer', fontName=font_name, fontSize=9,
                               alignment=1, textColor=colors.HexColor('#999999')),
            ))

            # 页眉水印：把exam_id存入doc
            doc._exam_id = q.exam_id if q else ''
            doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
            return output_path

        except Exception as e:
            raise RuntimeError(
                f'深度层 PDF 生成异常：{e}。深度层必须交付品牌化 PDF，'
                f'不得静默降级为 HTML。请联系技术支持。'
            )

    def generate_excel_report(self, matching_result, output_path: str = None,
                              tier: str = 'standard') -> str:
        """生成 Excel 报告（P1-6：按 tier 差异化内容）
        - data:    仅「完整数据」Sheet（全量冲稳保数据）
        - standard: 考生信息（快速查看）+ 完整数据 + 免责声明 Sheet
        - deep:    考生信息 + 完整数据（含就业/深造/撤销深度分析）+ 免责声明 + 院校详情
        """
        if output_path is None:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = os.path.join(
                self.output_dir,
                f'志愿推荐方案_{matching_result.questionnaire.name}_{ts}.xlsx',
            )

        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

            wb = Workbook()

            # Sheet 1: 基本信息
            ws1 = wb.active
            ws1.title = '考生信息'
            ws1.merge_cells('A1:F1')
            ws1['A1'] = '高考志愿智能推荐方案'
            ws1['A1'].font = Font(size=16, bold=True)
            ws1['A1'].alignment = Alignment(horizontal='center')

            q = matching_result.questionnaire
            info = [
                ['姓名', q.name, '科类', q.category, '总分', q.total_score],
                ['位次', q.rank, '性别', q.gender, '本地标识码', q.exam_id],
            ]
            for i, row in enumerate(info, 3):
                for j, val in enumerate(row):
                    cell = ws1.cell(row=i, column=j+1, value=val)
                    if j % 2 == 0:
                        cell.fill = PatternFill(
                            start_color='F0F0F0', end_color='F0F0F0',
                            fill_type='solid',
                        )
                        cell.font = Font(bold=True)

            # P1-4 必读提示区（合规要点）
            must_ack = getattr(matching_result, 'must_ack_warnings', []) or []
            if must_ack:
                start_row = 6
                ws1.merge_cells(f'A{start_row}:F{start_row}')
                cell = ws1.cell(row=start_row, column=1, value='📌 必读提示（请逐条阅读）')
                cell.font = Font(size=12, bold=True, color='FFFFFF')
                cell.fill = PatternFill(start_color='C62828', end_color='C62828', fill_type='solid')
                cell.alignment = Alignment(horizontal='center')
                for idx, w in enumerate(must_ack, 1):
                    r = start_row + idx
                    ws1.merge_cells(f'A{r}:F{r}')
                    cell = ws1.cell(row=r, column=1, value=f'{idx}. {w}')
                    cell.fill = PatternFill(start_color='FFEBEE', end_color='FFEBEE', fill_type='solid')
                    cell.alignment = Alignment(wrap_text=True, vertical='top')
                    ws1.row_dimensions[r].height = 30

            # ── Sheet 考生信息：基本信息 + 快速查看 ──
            _major_tuition = {}  # 提前初始化，避免下方引用时报 UnboundLocalError

            # data 层仅完整数据，跳过快速查看
            if tier != 'data':
                # 基本信息已在上方写入(ws1)，下面追加快速查看数据
                quick_start_row = 10 if not must_ack else start_row + len(must_ack) + 2
                ws1.merge_cells(f'A{quick_start_row}:G{quick_start_row}')
                ws1.cell(row=quick_start_row, column=1, value=f'{q.name} 同学 · 快速查看（{q.total_score}分/位次{q.rank}）').font = Font(size=14, bold=True)

                quick_headers = ['序号', '冲/稳/保/垫', '院校名称', '地点', '录取概率', '推荐专业', '学费(万/年)']
                hdr_row = quick_start_row + 1
                for j, h in enumerate(quick_headers):
                    cell = ws1.cell(row=hdr_row, column=j+1, value=h)
                    cell.font = Font(bold=True, color='FFFFFF')
                    cell.fill = PatternFill(start_color='1565C0', end_color='1565C0', fill_type='solid')
                    cell.alignment = Alignment(horizontal='center')

                # 条件格式填充色
                fill_green = PatternFill(start_color='C8E6C9', end_color='C8E6C9', fill_type='solid')
                fill_yellow = PatternFill(start_color='FFF9C4', end_color='FFF9C4', fill_type='solid')
                fill_red = PatternFill(start_color='FFCDD2', end_color='FFCDD2', fill_type='solid')

                qrow = hdr_row + 1
                for category in ['冲', '稳', '保', '垫']:
                    schools = matching_result.recommendations.get(category, [])
                    for i, school in enumerate(schools, 1):
                        majors_str = ', '.join([m.major_name for m in (school.recommended_majors or [])[:2]])
                        # 学费估算
                        tu = ''
                        if school.recommended_majors:
                            tu_val = _major_tuition.get(school.recommended_majors[0].major_name)
                            if tu_val:
                                tu = f'{tu_val:.2f}'
                            elif '中外合作' in school.school_quality:
                                tu = '3.0-8.0'
                            elif '民办' in school.school_quality:
                                tu = '1.5-3.0'
                            else:
                                tu = '0.5-0.8'

                        row_vals = [i, category, school.school_name, school.location or '—',
                                    f'{school.probability:.1f}%', majors_str or '—', tu]
                        for j, val in enumerate(row_vals):
                            cell = ws1.cell(row=qrow, column=j+1, value=val)
                            cell.alignment = Alignment(vertical='center')
                        # 概率条件格式
                        prob_cell = ws1.cell(row=qrow, column=5)
                        if school.probability >= 80:
                            for c in range(1, 8):
                                ws1.cell(row=qrow, column=c).fill = fill_green
                        elif school.probability >= 50:
                            for c in range(1, 8):
                                ws1.cell(row=qrow, column=c).fill = fill_yellow
                        else:
                            for c in range(1, 8):
                                ws1.cell(row=qrow, column=c).fill = fill_red
                        qrow += 1

            # data 层不需要考生信息 sheet（仅保留完整数据），但必读提示必须保留
            if tier == 'data':
                must_ack = getattr(matching_result, 'must_ack_warnings', []) or []
                if must_ack:
                    ws_warn = wb.create_sheet('必读提示', 0)
                    ws_warn.merge_cells('A1:F1')
                    cell = ws_warn.cell(row=1, column=1, value='📌 必读提示（请逐条阅读）')
                    cell.font = Font(size=12, bold=True, color='FFFFFF')
                    cell.fill = PatternFill(start_color='C62828', end_color='C62828', fill_type='solid')
                    cell.alignment = Alignment(horizontal='center')
                    ws_warn.row_dimensions[1].height = 26
                    for idx, w in enumerate(must_ack, 1):
                        r = 1 + idx
                        ws_warn.merge_cells(f'A{r}:F{r}')
                        c = ws_warn.cell(row=r, column=1, value=f'{idx}. {w}')
                        c.fill = PatternFill(start_color='FFEBEE', end_color='FFEBEE', fill_type='solid')
                        c.alignment = Alignment(wrap_text=True, vertical='top')
                        ws_warn.row_dimensions[r].height = 30
                    ws_warn.column_dimensions['A'].width = 80
                wb.remove(ws1)

            # Sheet 1: 完整数据（原推荐方案）
            ws2 = wb.create_sheet('完整数据')
            ws2.merge_cells('A1:R1')
            ws2['A1'] = '冲稳保推荐方案（含禁忌项标识 + 兜底类型）'
            ws2['A1'].font = Font(size=14, bold=True)

            headers = [
                '序号', '类别', '兜底类型', '院校名称', '院校层级', '地点', '批次',
                '录取概率', '置信度', '禁忌标识',
                '撤销预警', '推荐专业', '可替代专业', '学费(万/年)',
                '就业率', '起薪(元/月)',
                '就业信息', '深造建议',
            ]
            for j, header in enumerate(headers):
                cell = ws2.cell(row=3, column=j+1, value=header)
                cell.font = Font(bold=True, color='FFFFFF')
                cell.fill = PatternFill(
                    start_color='1565C0', end_color='1565C0', fill_type='solid',
                )
                cell.alignment = Alignment(horizontal='center')

            # 批量查询就业/深造信息
            _major_notes = {}
            _major_tuition = {}
            _major_emp_stats = {}
            if matching_result.recommendations:
                _conn = None
                try:
                    _all_majors = set()
                    for _cat in ['冲', '稳', '保', '垫']:
                        for _s in matching_result.recommendations.get(_cat, []):
                            if _s.recommended_majors:
                                for _mp in _s.recommended_majors:
                                    _all_majors.add(_mp.major_name)
                    if _all_majors:
                        _ph = ','.join('?' * len(_all_majors))
                        _conn = sqlite3.connect(self.db_path, check_same_thread=False)
                        _cur = _conn.cursor()
                        _cur.execute(
                            f"SELECT major_name, employment_note, further_study_note, tuition_year FROM major_catalog WHERE major_name IN ({_ph})",
                            list(_all_majors),
                        )
                        for _r in _cur.fetchall():
                            _major_notes[_r[0]] = (_r[1], _r[2])
                            _major_tuition[_r[0]] = _r[3] if len(_r) > 3 else None
                        # 查询就业统计数据
                        _cur.execute(
                            f"SELECT major_name, employment_rate, avg_salary_monthly FROM major_employment_stats WHERE major_name IN ({_ph})",
                            list(_all_majors),
                        )
                        for _r in _cur.fetchall():
                            _major_emp_stats[_r[0]] = (_r[1], _r[2])
                except Exception:
                    pass
                finally:
                    if _conn:
                        _conn.close()

            # 构建禁忌专业集合（来自 constraint_result）
            _restricted_majors = set()
            if matching_result.constraint_result and matching_result.constraint_result.filtered_majors:
                _restricted_majors = set(matching_result.constraint_result.filtered_majors)

            # 批量查询专业撤销数据
            _major_revocation = {}
            if matching_result.recommendations:
                try:
                    _all_majors2 = set()
                    for _cat in ['冲', '稳', '保', '垫']:
                        for _s in matching_result.recommendations.get(_cat, []):
                            if _s.recommended_majors:
                                for _mp in _s.recommended_majors:
                                    _all_majors2.add(_mp.major_name)
                    if _all_majors2:
                        _ph2 = ','.join('?' * len(_all_majors2))
                        _conn2 = sqlite3.connect(self.db_path, check_same_thread=False)
                        _cur2 = _conn2.cursor()
                        _cur2.execute(
                            f"SELECT major_name, SUM(revoke_count) as total_revoked FROM major_revocation_stats WHERE major_name IN ({_ph2}) AND major_name != '全国合计' GROUP BY major_name",
                            list(_all_majors2),
                        )
                        for _r2 in _cur2.fetchall():
                            _major_revocation[_r2[0]] = _r2[1]
                        _conn2.close()
                except Exception:
                    pass

            # 条件格式填充色
            fill_chong = PatternFill(start_color='FFF9C4', end_color='FFF9C4', fill_type='solid')  # 黄
            fill_wen = PatternFill(start_color='C8E6C9', end_color='C8E6C9', fill_type='solid')  # 绿
            fill_bao = PatternFill(start_color='BBDEFB', end_color='BBDEFB', fill_type='solid')  # 蓝
            font_red = Font(color='FF0000', bold=True)
            font_green = Font(color='2E7D32')
            fill_category = {'冲': fill_chong, '稳': fill_wen, '保': fill_bao}

            row_num = 4
            for category in ['冲', '稳', '保', '垫']:
                schools = matching_result.recommendations.get(category, [])
                for i, school in enumerate(schools, 1):
                    majors_list = school.recommended_majors or []
                    # 新专业标记
                    def _major_display(m):
                        tag = ' [2026新增]' if getattr(m, 'is_new_major', False) else ''
                        return m.major_name + tag
                    majors_str = ', '.join([_major_display(m) for m in majors_list[:3]])
                    alts_str = ', '.join(getattr(school, 'similar_alternatives', [])[:3])

                    # 禁忌标识：检查推荐专业是否在受限列表中
                    has_restriction = any(m.major_name in _restricted_majors for m in majors_list)
                    restriction_tag = '⚠️ 受限' if has_restriction else '✅ 无限制'

            # 撤销预警：按"学校-专业"组合查询风险等级
                    revocation_warnings = []
                    for _mp in majors_list[:3]:
                        from gaokao.core.revocation_risk import get_revocation_risk
                        risk = get_revocation_risk(_mp.major_name, school.school_name)
                        if risk['level'] == 3:
                            revocation_warnings.append(f'{_mp.major_name}: 该校已停招')
                        elif risk['level'] == 2:
                            tb = risk['details'].get('tier_breakdown', {})
                            revocation_warnings.append(
                                f'{_mp.major_name}: 985/211院校共撤销{tb.get("985", 0)+tb.get("211", 0)}所，建议关注该专业质量'
                            )
                        elif risk['level'] == 1:
                            total = risk['details'].get('tier_breakdown', {}).get('普通', 0)
                            revocation_warnings.append(
                                f'{_mp.major_name}: 普通院校撤销较多({total}所)，该校仍在正常招生'
                            )
                    rev_str = ' | '.join(revocation_warnings) if revocation_warnings else '无撤销风险'

                    # 学费估算
                    tuition_val = ''
                    if majors_list:
                        tuition = _major_tuition.get(majors_list[0].major_name)
                        if tuition:
                            tuition_val = f'{tuition:.2f}'
                        elif '中外合作' in school.school_quality or '中外合作' in school.school_name:
                            tuition_val = '3.0-8.0'
                        elif '民办' in school.school_quality:
                            tuition_val = '1.5-3.0'
                        else:
                            tuition_val = '0.5-0.8'

                    # 批次
                    batch_str = getattr(school, 'batch', '')

                    # 就业/深造
                    emp_notes = []
                    study_notes = []
                    for _mp in majors_list[:3]:
                        _n = _major_notes.get(_mp.major_name)
                        if _n:
                            if _n[0]:
                                emp_notes.append(f'{_mp.major_name}: {_n[0][:80]}')
                            if _n[1]:
                                study_notes.append(f'{_mp.major_name}: {_n[1][:60]}')
                    emp_str = ' | '.join(emp_notes[:2])
                    study_str = ' | '.join(study_notes[:2])

                    # 就业率 / 起薪
                    emp_rate_str = ''
                    salary_str = ''
                    if majors_list:
                        _es = _major_emp_stats.get(majors_list[0].major_name)
                        if _es:
                            emp_rate_str = f'{_es[0]:.1%}' if _es[0] else ''
                            salary_str = str(_es[1]) if _es[1] else ''

                    # 写入行
                    # P0-2 闭环：兜底类型列
                    if category == '保':
                        bao_type_str = '⚠ 垫' if getattr(school, 'safety_warning', None) else '标准'
                    else:
                        bao_type_str = '—'
                    ws2.cell(row=row_num, column=1, value=i)
                    ws2.cell(row=row_num, column=2, value=category)
                    ws2.cell(row=row_num, column=3, value=bao_type_str)
                    ws2.cell(row=row_num, column=4, value=school.school_name)
                    ws2.cell(row=row_num, column=5, value=f"{school.tier_level} {school.tier_name}" if school.tier_level else school.school_quality)
                    ws2.cell(row=row_num, column=6, value=school.location)
                    ws2.cell(row=row_num, column=7, value=batch_str)
                    ws2.cell(row=row_num, column=8, value=f'{school.probability:.1f}%')
                    ws2.cell(row=row_num, column=9, value=school.confidence)
                    ws2.cell(row=row_num, column=10, value=restriction_tag)
                    ws2.cell(row=row_num, column=11, value=rev_str)
                    ws2.cell(row=row_num, column=12, value=majors_str)
                    ws2.cell(row=row_num, column=13, value=alts_str)
                    ws2.cell(row=row_num, column=14, value=tuition_val)
                    ws2.cell(row=row_num, column=15, value=emp_rate_str)
                    ws2.cell(row=row_num, column=16, value=salary_str)
                    ws2.cell(row=row_num, column=17, value=emp_str)
                    ws2.cell(row=row_num, column=18, value=study_str)

                    # 条件格式：行底色
                    row_fill = fill_category.get(category, None)
                    if row_fill:
                        for col in range(1, 19):
                            ws2.cell(row=row_num, column=col).fill = row_fill

                    # P0-2 闭环：垫用红色字体
                    if category == '保' and getattr(school, 'safety_warning', None):
                        ws2.cell(row=row_num, column=3).font = Font(color='C62828', bold=True)

                    # 撤销预警橙色高亮（列号 +1）
                    if revocation_warnings:
                        ws2.cell(row=row_num, column=11).font = Font(color='E65100', bold=True)

                    # 禁忌标识红色字体（列号 +1）
                    if has_restriction:
                        ws2.cell(row=row_num, column=10).font = font_red
                    else:
                        ws2.cell(row=row_num, column=10).font = font_green

                    row_num += 1

            # 自动筛选
            ws2.auto_filter.ref = f'A3:R{max(3, row_num - 1)}'

            # ── P1-6: tier 差异化 ──
            # data 层：仅完整数据 Sheet（已完成）
            # standard 层：加免责声明 Sheet
            if tier == 'standard':
                ws_d = wb.create_sheet('免责声明')
                ws_d.merge_cells('A1:H1')
                ws_d['A1'] = '免责声明'
                ws_d['A1'].font = Font(size=14, bold=True)
                disclaimer_items = [
                    '1. 本推荐方案基于历史录取数据 + 问卷偏好智能生成，仅供参考。',
                    '2. 录取概率为统计模型预测值，不代表实际录取结果。',
                    '3. 冲档学校存在落选风险，建议在冲档志愿中勾选"服从专业调剂"。',
                    '4. 云南新高考"院校专业组"模式：投档后若专业分数不够，不服从调剂将被退档。',
                    '5. 最终志愿填报请以云南省招生考试院公布的招生计划为准。',
                    '6. 因使用本报告产生的任何后果由使用者自行承担。',
                ]
                for idx, item in enumerate(disclaimer_items, 2):
                    ws_d.cell(row=idx, column=1, value=item).alignment = Alignment(wrap_text=True)
                    ws_d.row_dimensions[idx].height = 25

            # deep 层：加院校详情 Sheet + 免责声明
            if tier == 'deep':
                ws_detail = wb.create_sheet('院校详情')
                ws_detail.merge_cells('A1:G1')
                ws_detail['A1'] = '院校深度解析（深度层专属）'
                ws_detail['A1'].font = Font(size=14, bold=True)
                detail_headers = ['序号', '院校名称', '地点', '985/211/双一流', '学费范围', '优势专业', '备注']
                for j, h in enumerate(detail_headers, 1):
                    c = ws_detail.cell(row=2, column=j, value=h)
                    c.font = Font(bold=True, color='FFFFFF')
                    c.fill = PatternFill(start_color='FF1565C0', end_color='FF1565C0', fill_type='solid')

                drow = 3
                d_idx = 1
                for category in ['冲', '稳', '保', '垫']:
                    schools = matching_result.recommendations.get(category, [])
                    for school in schools:
                        majors_list = school.recommended_majors or []
                        majors_str = ', '.join([m.major_name for m in majors_list[:3]])
                        tier_str = f"{school.tier_level} {school.tier_name}" if school.tier_level else school.school_quality
                        ws_detail.cell(row=drow, column=1, value=d_idx)
                        ws_detail.cell(row=drow, column=2, value=school.school_name)
                        ws_detail.cell(row=drow, column=3, value=school.location or '—')
                        ws_detail.cell(row=drow, column=4, value=tier_str)
                        ws_detail.cell(row=drow, column=5, value='')  # 学费范围（后续可扩展）
                        ws_detail.cell(row=drow, column=6, value=majors_str)
                        ws_detail.cell(row=drow, column=7, value=f'[{category}] 概率 {school.probability:.1f}%')
                        drow += 1
                        d_idx += 1

                # deep 层免责声明
                ws_dd = wb.create_sheet('免责声明')
                ws_dd.merge_cells('A1:H1')
                ws_dd['A1'] = '免责声明（深度层）'
                ws_dd['A1'].font = Font(size=14, bold=True)
                deep_disclaimer = [
                    '1. 本规划书基于历史录取数据 + 项目自编偏好问卷 + 其他问卷偏好 + 就业趋势生成；偏好问卷未经心理测量学验证、不作诊断，仅供参考。',
                    '2. 录取概率为统计模型预测值，不代表实际录取结果。',
                    '3. 冲档学校存在落选风险，请充分评估后决策。',
                    '4. 院校专业组模式下，不服从专业调剂将面临退档风险。',
                    '5. 本报告不构成任何形式的录取保证或就业承诺。',
                    '6. 因使用本报告产生的任何后果由使用者自行承担。',
                    '7. 如有重大疑问，建议咨询专业志愿填报顾问或招生办。',
                ]
                for idx, item in enumerate(deep_disclaimer, 2):
                    ws_dd.cell(row=idx, column=1, value=item).alignment = Alignment(wrap_text=True)
                    ws_dd.row_dimensions[idx].height = 25

            wb.save(output_path)
            return output_path

        except ImportError:
            return self.generate_csv_report(
                matching_result, output_path.replace('.xlsx', '.csv'),
            )

    def generate_html_report(self, matching_result, output_path: str = None) -> str:
        if output_path is None:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = os.path.join(
                self.output_dir,
                f'志愿推荐方案_{matching_result.questionnaire.name}_{ts}.html',
            )

        q = matching_result.questionnaire
        p = matching_result.personality_result

        html = '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n'
        html += '    <meta charset="UTF-8">\n'
        html += '    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        html += f'    <title>高考志愿智能推荐方案 - {_h(q.name)}</title>\n'
        html += """    <style>
        body { font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); min-height: 100vh; }
        .container { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); }
        h1 { text-align: center; color: #1a1a1a; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; font-size: 24px; }
        h2 { color: #4CAF50; margin-top: 30px; border-left: 4px solid #4CAF50; padding-left: 10px; }
        h3 { color: #555; }
        .chong { background: #ffebee; color: #c62828; padding: 3px 10px; border-radius: 12px; font-weight: bold; font-size: 13px; display: inline-block; }
        .wen { background: #fff3e0; color: #e65100; padding: 3px 10px; border-radius: 12px; font-weight: bold; font-size: 13px; display: inline-block; }
        .bao { background: #e8f5e9; color: #2e7d32; padding: 3px 10px; border-radius: 12px; font-weight: bold; font-size: 13px; display: inline-block; }
        /* P2-fix: 补充HTML报告中引用的CSS类 */
        .chong-tag { background: #ffebee; color: #c62828; padding: 3px 10px; border-radius: 12px; font-weight: bold; font-size: 13px; display: inline-block; }
        .wen-tag { background: #fff3e0; color: #e65100; padding: 3px 10px; border-radius: 12px; font-weight: bold; font-size: 13px; display: inline-block; }
        .bao-tag { background: #e8f5e9; color: #2e7d32; padding: 3px 10px; border-radius: 12px; font-weight: bold; font-size: 13px; display: inline-block; }
        .summary-box { background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 8px; padding: 15px; margin: 15px 0; }
        .info-table { width: 100%; border-collapse: collapse; margin: 15px 0; }
        .info-table th, .info-table td { border: 1px solid #ddd; padding: 10px; text-align: left; }
        .info-table th { background-color: #f0f0f0; font-weight: bold; width: 120px; }
        .school-table { width: 100%; border-collapse: collapse; margin: 15px 0; border-radius: 8px; overflow: hidden; }
        .school-table th { background-color: #4CAF50; color: white; padding: 12px; text-align: left; }
        .school-table td { border: 1px solid #ddd; padding: 10px; }
        .school-table tr:nth-child(even) { background-color: #f9f9f9; }
        .school-table tr:hover { background-color: #f0f7ff; }
        .major-list { background: #f9f9f9; padding: 15px; border-radius: 5px; margin: 10px 0; }
        .dim-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 10px 0; }
        .dim-item { padding: 8px; background: #f9f9f9; border-radius: 4px; }
        .disclaimer { margin-top: 30px; padding: 15px; background: #e8f5e9; border: 1px solid #a5d6a7; border-radius: 5px; color: #2e7d32; }
        .conflict-warning { color: #d32f2f; background: #fff3cd; padding: 8px; margin: 5px 0; border-radius: 4px; font-size: 14px; }
        .alt-major { color: #666666; font-size: 12px; }
        .major-note { color: #888888; font-size: 12px; }
        .narrative-section { background: #f0f7ff; padding: 15px; border-radius: 8px; margin: 15px 0; border-left: 4px solid #2196F3; }
        .narrative { color: #333; line-height: 1.8; margin: 8px 0; }
        .compare-table { width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 13px; }
        .compare-table th { background-color: #2196F3; color: white; padding: 10px 8px; text-align: center; }
        .compare-table td { border: 1px solid #ddd; padding: 8px; text-align: center; }
        .compare-table tr:nth-child(even) { background-color: #f9f9f9; }
        .compare-table .compare-label { background-color: #e3f2fd; font-weight: bold; text-align: left; width: 100px; }
        </style>\n</head>\n<body>\n"""
        html += '    <div class="container">\n'
        html += '        <h1>高考志愿智能推荐方案</h1>\n'
        html += '        <h2>一、考生基本信息</h2>\n'
        html += '        <table class="info-table">\n'
        html += f'            <tr><th>姓名</th><td>{_h(q.name)}</td><th>科类</th><td>{_h(q.category)}</td></tr>\n'
        html += f'            <tr><th>总分</th><td>{_h(q.total_score)}</td><th>位次</th><td>{_h(q.rank)}</td></tr>\n'
        html += f'            <tr><th>性别</th><td>{_h(q.gender)}</td><th>本地标识码</th><td>{_h(q.exam_id)}</td></tr>\n'
        html += '        </table>\n'

        if p:
            bf = p.big_five
            se = p.self_efficacy or {}
            cv = p.career_values or {}

            # 格式化分数：0.0显示为"未作答"
            def _fmt(v):
                return '未作答' if v == 0 else f'{v}'

            html += f"""        <h2>二、偏好问卷结果（项目自编，非心理诊断）</h2>
        <table class="info-table">
            <tr><th>大五维度偏好</th><td colspan="3">O={bf.get('O', 0)} C={bf.get('C', 0)} E={bf.get('E', 0)} A={bf.get('A', 0)} N={bf.get('N', 0)}</td></tr>
            <tr><th>RIASEC 风格代码</th><td>{p.holland_code}</td><th>置信度</th><td>{p.confidence}</td></tr>
            <tr><th>SD检测</th><td>{p.sd_score}/4</td><th></th><td></td></tr>
        </table>

        <h3>学科自我评价（项目自编）</h3>
        <table class="info-table">
            <tr><th>语文</th><td>{_fmt(se.get('chinese', 0))}/5</td><th>数学</th><td>{_fmt(se.get('math', 0))}/5</td><th>英语</th><td>{_fmt(se.get('english', 0))}/5</td></tr>
        </table>

        <h3>职业价值偏好（项目自编）</h3>
        <table class="info-table">"""
            dim_labels = {
                'income': '收入水平', 'stability': '工作稳定',
                'achievement': '成就感', 'help': '帮助他人',
                'creative': '创造力', 'balance': '工作生活平衡',
                'leadership': '领导力', 'autonomy': '独立性',
                'location': '地域偏好', 'learning': '持续学习',
            }
            for key, label in dim_labels.items():
                html += f'<tr><th>{label}</th><td>{_fmt(cv.get(key, 0))}/5</td></tr>\n'
            # 推荐专业（融合用户意愿+项目自编偏好问卷）
        merged_majors = []
        if hasattr(matching_result, 'user_profile') and matching_result.questionnaire:
            # 使用匹配引擎的融合推荐（已从 _generate_recommendations 中获取）
            # 这里从问卷意愿+行业映射手动构建展示列表
            q_obj = matching_result.questionnaire
            _seen = set()
            def _add(m, src=''):
                if m and m not in _seen:
                    _seen.add(m)
                    merged_majors.append((m, src))
            if q_obj.vertical_majors:
                for m in q_obj.vertical_majors:
                    if m != '都不考虑':
                        _add(m, 'explicit')
            if q_obj.acceptable_majors:
                for m in q_obj.acceptable_majors:
                    _add(m, 'explicit')
            # 补充偏好问卷方向（最多2个；未作答时 p 为 None）
            if p is not None and p.recommendations:
                count = 0
                for m in p.recommendations:
                    if m not in _seen and count < 2:
                        _add(m, 'personality')
                        count += 1

        _src_labels = {
            'explicit': '✓ 您的偏好',
            'personality': '⚠️ 偏好问卷方向参考',
        }

        def _fmt_major_line(major_tuple):
            m, src = major_tuple
            label = _src_labels.get(src, '')
            return f'{m} {label}' if label else m

        html += """        </table>

        <h3>推荐专业（TOP 10）</h3>
        <div class="major-list">
            """ + ', '.join(
                [f'{i}. {_fmt_major_line(m)}' for i, m in enumerate(merged_majors[:10], 1)]
            ) + """
        </div>"""

        html += """        <h2>三、志愿偏好</h2>
        <table class="info-table">
            <tr><th>核心诉求</th><td>""" + _h(q.core_demand or '未定') + """</td></tr>
            <tr><th>目标行业</th><td>""" + _h(
                ', '.join(q.target_industries) if q.target_industries else '未定'
            ) + """</td></tr>
            <tr><th>可接受专业</th><td>""" + _h(
                ', '.join(q.acceptable_majors) if q.acceptable_majors else '未定'
            ) + """</td></tr>
            <tr><th>稳定性偏好</th><td>""" + _h(str(q.stability_preference)) + """/5</td></tr>
            <tr><th>风险策略</th><td>""" + _h(_translate_term(matching_result.risk_strategy)) + """</td></tr>
        </table>

        <h2>四、AI个性化解读</h2>
        <div class="narrative-section">
"""
        # AI解读
        p = matching_result.personality_result
        if p:
            narratives = self._generate_ai_narrative(
                p, matching_result.recommendations, matching_result,
            )
            if narratives:
                for narrative in narratives:
                    html += f'            <p class="narrative">{_h(narrative)}</p>\n'
            else:
                html += '            <p class="narrative">暂无个性化解读。</p>\n'
        html += """        </div>

        <h2>五、推荐方案</h2>
"""

        # 意愿冲突检测
        intention = getattr(matching_result, 'intention_profile', None)
        if intention and getattr(intention, 'conflicts', None):
            html += '        <h2 style="color:#d32f2f;">⚠️ 意愿冲突提示</h2>\n'
            for conflict in intention.conflicts:
                ctype = getattr(conflict, 'conflict_type', '')
                cdesc = getattr(conflict, 'description', '')
                severity = getattr(conflict, 'severity', 'warning')
                icon = '🔴' if severity == 'alert' else '🟡'
                html += f'        <div class="conflict-warning">{icon} [{_h(ctype)}] {_h(cdesc)}</div>\n'

        # 推荐方案 — 按批次组织
        from gaokao.core.volunteer_recommender import BATCH_ADMISSION_ORDER

        # 冲稳保比例差异说明（如有）
        from gaokao.core.volunteer_recommender import STRATEGY_CONFIGS
        strategy_cfg_html = STRATEGY_CONFIGS.get(
            getattr(matching_result, 'risk_strategy', None),
            STRATEGY_CONFIGS['balanced'],
        )
        ratio_note_html = self._get_chong_wen_bao_ratio_note(matching_result, strategy_cfg_html)
        if ratio_note_html:
            chong_c = len(matching_result.recommendations.get('冲', []))
            wen_c = len(matching_result.recommendations.get('稳', []))
            bao_c = len(matching_result.recommendations.get('保', []))
            total_c = chong_c + wen_c + bao_c
            html += f"""        <h2>四.0 冲稳保分布</h2>
        <div class="summary-box">
            <p>共推荐 <strong>{total_c}</strong> 所院校：
            <span class="chong-tag">冲刺 {chong_c} 所</span>、
            <span class="wen-tag">稳妥 {wen_c} 所</span>、
            <span class="bao-tag">保底 {bao_c} 所</span></p>
            <div class="ratio-explanation">{ratio_note_html.replace(chr(10), '<br>')}</div>
        </div>
"""

        batch_groups = {}
        for category in ['冲', '稳', '保', '垫']:
            for school in matching_result.recommendations.get(category, []):
                school._chong_wen_bao = category
                b = school.batch if school.batch else '其他'
                if b not in batch_groups:
                    batch_groups[b] = []
                batch_groups[b].append(school)

        def _batch_sort_key(key):
            if key in BATCH_ADMISSION_ORDER:
                return BATCH_ADMISSION_ORDER.index(key)
            return 999

        sorted_batches = sorted(batch_groups.keys(), key=_batch_sort_key)

        for batch_idx, batch_key in enumerate(sorted_batches):
            schools = batch_groups[batch_key]

            # 批次信息
            batch_info_parts = [f'<h2>四.{batch_idx+1} {batch_key}']
            batch_info_parts.append('</h2>')
            html += ''.join(batch_info_parts)

            for category in ['冲', '稳', '保', '垫']:
                cat_schools = [s for s in schools if getattr(s, '_chong_wen_bao', '') == category]
                if not cat_schools:
                    continue
                css_class = {'冲': 'chong', '稳': 'wen', '保': 'bao'}.get(category, '')

                html += f'<h3 class="{css_class}">{category}（{len(cat_schools)}所）</h3>'

                # P0-2 闭环：保档若含 50%-85% 垫，整段加红色警示框
                if category == '保':
                    fallback_count = sum(1 for s in cat_schools if getattr(s, 'safety_warning', None))
                    if fallback_count > 0:
                        html += (
                            '<div style="background:#fff3cd; border:2px solid #f57c00;'
                            ' padding:12px; margin:10px 0; border-radius:4px;">'
                            f'<strong style="color:#c62828;">⚠ 注意：本档含 {fallback_count} 所"垫"志愿</strong>'
                            '<br><span style="color:#5c4037; font-size:13px;">'
                            '标准保底（≥85% 概率）数量不足，系统补充了 50%-85% 概率的学校作为兜底。'
                            '这类志愿安全性低于标准保底，<strong>请谨慎评估并优先填写标准保底</strong>。'
                            '</span></div>'
                        )

                html += '<table class="school-table">'
                html += '<tr><th>序号</th><th>院校名称</th><th>院校层级</th><th>地点</th><th>选科要求</th><th>录取概率</th><th>置信度</th><th>兜底类型</th></tr>'
                for i, school in enumerate(cat_schools[:15], 1):
                    tier_str = f"{school.tier_level} {school.tier_name}" if school.tier_level else school.school_quality
                    # 专业组模式：显示 "学校名 (01专业组)"
                    group_label = ''
                    if getattr(school, 'group_name', ''):
                        group_label = f' ({school.group_name})'
                    elif getattr(school, 'group_code', ''):
                        group_label = f' ({school.group_code}专业组)'
                    subj_req = getattr(school, 'subject_req', '') or '—'
                    # P0-2: 兜底类型标签
                    bao_type_cell = '—'
                    row_bg = ''
                    if category == '保':
                        if getattr(school, 'safety_warning', None):
                            bao_type_cell = '<span style="color:#c62828; font-weight:bold;">⚠ 垫</span>'
                            row_bg = ' style="background:#fff8e1;"'
                        else:
                            bao_type_cell = '<span style="color:#2e7d32;">标准</span>'
                    html += (
                        f'<tr{row_bg}><td>{i}</td><td>{_h(school.school_name)}{_h(group_label)}</td>'
                        f'<td>{_h(tier_str)}</td><td>{_h(school.location)}</td>'
                        f'<td>{_h(subj_req)}</td>'
                        f'<td>{school.probability:.1f}%</td><td>{_h(school.confidence)}</td>'
                        f'<td>{bao_type_cell}</td></tr>'
                    )
                html += '</table>'

                # 推荐专业
                pro_majors = [s for s in cat_schools if s.recommended_majors]
                if pro_majors:
                    html += '<div class="major-list"><strong>推荐专业（TOP 3）：</strong><br>'
                    for school in pro_majors[:3]:
                        parts = []
                        for m in school.recommended_majors[:3]:
                            # reason 包含来源标注，如 "您的明确偏好（TOP1）"
                            reason = getattr(m, 'reason', '') or ''
                            src_tag = ''
                            if '您的明确偏好' in reason:
                                src_tag = ' ✓'
                            elif '性格推断' in reason or '偏好问卷' in reason:
                                src_tag = ' ⚠️'
                            # C4: 撤销风险标签
                            risk_tag = ''
                            risk = getattr(m, 'revocation_risk', 'none')
                            if risk == 'rising':
                                risk_tag = ' <span style="color:#c62828">[撤销↑]</span>'
                            elif risk == 'declining':
                                risk_tag = ' <span style="color:#2e7d32">[撤销↓]</span>'
                            # C5: 就业率/薪资
                            emp_tag = ''
                            emp_rate = getattr(m, 'employment_rate', 0)
                            avg_salary = getattr(m, 'avg_salary', 0)
                            if emp_rate or avg_salary:
                                bits = []
                                if emp_rate:
                                    bits.append(f'就业率{emp_rate*100:.0f}%')
                                if avg_salary:
                                    bits.append(f'起薪{int(avg_salary)}元')
                                emp_tag = f' <span class="major-note">({"/".join(bits)})</span>'
                            parts.append(f'{_h(m.major_name)}{src_tag}{risk_tag}{emp_tag}')
                        ms = ', '.join(parts)
                        # C6: 降档备选
                        alt_html = ''
                        alts = getattr(school, 'similar_alternatives', []) or []
                        if alts:
                            alt_html = f'<br><span class="alt-major">如不录取可考虑: {_h(", ".join(alts[:3]))}</span>'
                        html += f'{_h(school.school_name)}: {ms}{alt_html}<br>'
                    html += '</div>'

        # ── 同档位学校对比 ──
        wen_schools = []
        for cat in ['冲', '稳', '保', '垫']:
            for s in matching_result.recommendations.get(cat, []):
                if cat == '稳':
                    wen_schools.append(s)
        if len(wen_schools) >= 2:
            # 选取概率最接近的3-5所
            wen_schools.sort(key=lambda s: s.probability)
            compare_schools = wen_schools[:5]
            html += '        <h2>五.1 稳档学校对比</h2>\n'
            html += '        <table class="compare-table">\n'
            headers = ['对比维度'] + [s.school_name for s in compare_schools]
            html += '<tr>' + ''.join(f'<th>{_h(h)}</th>' for h in headers) + '</tr>\n'
            rows = [
                ('录取概率', [f'{s.probability:.1f}%' for s in compare_schools]),
                ('学校层级', [f'{s.tier_level} {s.tier_name}'.strip() for s in compare_schools]),
                ('地点', [s.location or '—' for s in compare_schools]),
                ('推荐专业', [', '.join(m.major_name for m in s.recommended_majors[:2]) for s in compare_schools]),
                ('学费', [f'{s.tuition:.0f}元/年' if (s.tuition or 0) > 0 else '—' for s in compare_schools]),
            ]
            for label, values in rows:
                html += '<tr>'
                html += f'<td class="compare-label">{_h(label)}</td>'
                for v in values:
                    html += f'<td>{_h(v)}</td>'
                html += '</tr>\n'
            html += '</table>\n'

        # 数据完整性告警 + 注意事项
        ok, data_msg, _ = check_data_completeness(self.db_path, q.category)
        alert_color = '#d32f2f' if not ok else '#2e7d32'
        html += f'        <h2 style="color:{alert_color};">⚠️ 数据完整性: {_h(data_msg)}</h2>\n'

        # P1-4 必读告警区（合规要点）
        must_ack = getattr(matching_result, 'must_ack_warnings', []) or []
        if must_ack:
            html += (
                '        <div style="background:#ffebee; border:2px solid #c62828;'
                ' border-radius:6px; padding:14px; margin:18px 0;">'
                '<h3 style="color:#c62828; margin:0 0 8px 0;">📌 必读提示（请逐条阅读）</h3>'
                '<ol style="margin:0; padding-left:20px; line-height:1.8; color:#333;">'
            )
            for w in must_ack:
                html += f'<li>{_h(w)}</li>'
            html += '</ol></div>\n'

        # Step 3: 数据稀疏预警（历史类 2025 年首年新高考）
        ds_warning = getattr(matching_result, 'data_sparsity_warning', '') or ''
        if ds_warning:
            html += (
                '        <div style="background:#ffebee; border-left:4px solid #c62828;'
                ' padding:12px; margin:15px 0; border-radius:4px;">'
                f'<strong style="color:#c62828;">⚠ 数据稀疏提示：</strong>'
                f'<span style="color:#333; line-height:1.6;">{_h(ds_warning)}</span>'
                '</div>\n'
            )

        notes = getattr(matching_result, 'notes', [])
        if notes:
            html += '        <h2>注意事项</h2>\n        <ul>\n'
            for note in notes:
                html += f'            <li>{_h(note)}</li>\n'
            html += '        </ul>\n'

        # C7: 专业宽度预警（独立章节）
        breadth_warnings = getattr(matching_result, 'breadth_warnings', []) or []
        if breadth_warnings:
            html += '        <h2 style="color:#c62828;">⚠ 专业宽度预警</h2>\n        <ul>\n'
            for w in breadth_warnings:
                html += f'            <li>{_h(w)}</li>\n'
            html += '        </ul>\n'

        # C9: 候选池不足预警
        pool_warning = getattr(matching_result, 'candidate_pool_warning', '') or ''
        if pool_warning:
            html += f'        <div class="conflict-warning">{_h(pool_warning)}</div>\n'

        # C3: 意愿画像（来自 intention_inference）
        intention_profile = getattr(matching_result, 'intention_profile', None)
        if intention_profile is not None:
            ip_summary = getattr(intention_profile, 'summary', None) or getattr(intention_profile, 'narrative', None)
            if ip_summary:
                html += '        <h2>意愿画像</h2>\n'
                html += f'        <div class="narrative-section"><p class="narrative">{_h(ip_summary)}</p></div>\n'

        html += """        <div class="sop-checklist" style="margin-top: 30px; padding: 20px; background: #f5f9ff; border-left: 4px solid #2563eb; border-radius: 4px;">
            <h3 style="color: #1e40af; margin-top: 0;">✅ 志愿填报最终核对清单（提交前必查 20 项）</h3>
            <p style="color: #555; font-size: 13px; margin-bottom: 12px;">系统已基于您的问卷数据完成大部分筛查，但以下 20 项需要您在提交志愿前亲自核对一遍（系统无法替代您查阅招生章程）。</p>

            <h4 style="color: #1e40af;">阶段一：数据基准与硬性约束（5项）</h4>
            <ol style="line-height: 1.8;">
                <li>查阅《云南省2026年一分一段表》，确认自己的精确绝对位次（含同分小分排序）</li>
                <li>逐一核对所有志愿组的"选考科目要求"是否与自己选科100%匹配（重点排查"物理+化学"双限）</li>
                <li>查阅目标院校《招生章程》，确认视力、色觉、身高未触碰"体检一票否决"条款</li>
                <li>确认单科成绩（如英语、数学）达到目标专业最低门槛（少数高校如外语类、中外合作有要求）</li>
                <li>确认目标院校在云南的招生计划（防止部分专业组今年停招或新增）</li>
            </ol>

            <h4 style="color: #1e40af;">阶段二：宏观梯度与微观排布（5项）</h4>
            <ol start="6" style="line-height: 1.8;">
                <li>40个本科批B段志愿组是否按"冲(15%) / 稳(55%) / 保(30%)"梯度排列</li>
                <li>志愿组之间是否存在"位次倒挂"（排在后面的志愿组，往年录取位次反而高于前面）</li>
                <li>每个志愿组内的10个专业，是否按"喜爱度+往年录取分"双重降序排列</li>
                <li>每个志愿组的第9、第10个专业，是否填报了该组往年录取分最低的专业以防调剂</li>
                <li><strong>致命开关：40个院校专业组是否<u>全部</u>勾选了"服从专业调剂"</strong></li>
            </ol>

            <h4 style="color: #1e40af;">阶段三：隐蔽陷阱与资本风控（5项）</h4>
            <ol start="11" style="line-height: 1.8;">
                <li><strong>专业级差排雷</strong>：确认目标院校在组内分配专业时采用"分数优先"还是"专业级差"（若为级差，第一专业必须绝对稳妥）</li>
                <li><strong>校区排雷</strong>：核查目标专业组的具体办学校区（警惕异地校区，毕业证标注可能不同）</li>
                <li><strong>分段计费排雷</strong>：核查目标专业（特别是软件工程、集成电路）是否存在"大三大四学费暴涨至1.6万+"</li>
                <li><strong>中外合作风控</strong>：若填报，确认家庭现金流可支撑4年学费（12-32万），且明确知晓几乎无法转入该校普通类专业</li>
                <li><strong>定向契约风控</strong>：若填报"定向生/公费师范生/优师计划"，确认毕业后违约成本及服务期（通常6年）</li>
            </ol>

            <h4 style="color: #1e40af;">阶段四：尽职调查与最终复核（5项）</h4>
            <ol start="16" style="line-height: 1.8;">
                <li>查阅目标院校教务处官网《本科生转专业实施细则》，确认转专业的GPA门槛、容量、是否限制文转理</li>
                <li>目标专业组内是否排除了所有"宁可退档复读也绝对不读"的极端排斥专业</li>
                <li>查阅目标院校官方《毕业生就业质量年度报告》（剔除"灵活就业"水分，看真实"协议就业率"）</li>
                <li>确认目标院校真实的"升学率（保研率+考研率）"</li>
                <li><strong>提交前由考生本人与家长<u>双人交叉核对</u>所有"院校代码"与"专业组代码"</strong></li>
            </ol>
        </div>
        <div class="disclaimer">
            <strong>📋 使用建议：</strong><br>
            1. 本推荐方案基于2020-2025年录取数据 + 项目自编偏好问卷 + 其他问卷偏好生成；偏好问卷未经心理测量学验证，不作诊断。<br>
            2. 冲档学校存在落选风险，建议在冲档志愿中勾选"服从专业调剂"以降低退档风险。<br>
            3. 云南新高考"院校专业组"模式：投档后若所填专业分数不够，不服从调剂将被直接退档。<br>
            4. <strong>专业级差风险</strong>：少数老牌强校仍采用"专业级差"规则（第二志愿扣3分），易调剂到组内冷门，填报前请查阅目标院校《招生章程》"专业录取规则"条款。<br>
            5. 最终志愿填报请以云南省招生考试院公布的2026年招生计划为准。<br>
            6. 如有重大疑问，建议咨询专业志愿填报顾问。
        </div>
    </div>
</body>
</html>"""

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        return output_path

    def generate_csv_report(self, matching_result, output_path: str = None) -> str:
        if output_path is None:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = os.path.join(
                self.output_dir,
                f'志愿推荐方案_{matching_result.questionnaire.name}_{ts}.csv',
            )

        import csv
        with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            # P1-7: 统一免责声明（CSV 头部）
            writer.writerow(['⚠️ 免责声明'])
            writer.writerow([
                '本推荐方案基于历史录取数据和算法模型生成，仅供参考，不构成任何报考建议。'
                '实际录取结果受多种因素影响，请以云南省招生考试院官方公布为准。'
                '冲档学校存在落选风险，建议勾选"服从专业调剂"以降低退档风险。'
            ])
            writer.writerow([])

            writer.writerow(['高考志愿智能推荐方案'])
            q = matching_result.questionnaire
            writer.writerow([
                '姓名', q.name, '科类', q.category,
                '总分', q.total_score, '位次', q.rank,
            ])
            writer.writerow([])
            # P1-4 必读提示
            must_ack = getattr(matching_result, 'must_ack_warnings', []) or []
            if must_ack:
                writer.writerow(['📌 必读提示（请逐条阅读）'])
                for idx, w in enumerate(must_ack, 1):
                    writer.writerow([f'{idx}.', w])
                writer.writerow([])
            writer.writerow(['序号', '批次', '类别', '兜底类型', '院校名称', '院校层级', '地点', '录取概率', '置信度',
                             '推荐专业(TOP3)', '撤销风险', '就业率', '起薪(元/月)', '降档备选'])

            row_num = 1
            for category in ['冲', '稳', '保', '垫']:
                schools = matching_result.recommendations.get(category, [])
                for i, school in enumerate(schools, 1):
                    tier_str = f"{school.tier_level} {school.tier_name}" if school.tier_level else school.school_quality
                    majors = school.recommended_majors or []
                    majors_str = ', '.join([m.major_name for m in majors[:3]])
                    risks = [getattr(m, 'revocation_risk', 'none') for m in majors[:3]]
                    risk_str = ', '.join([r for r in risks if r and r != 'none']) or '无'
                    emp_rate = next((getattr(m, 'employment_rate', 0) for m in majors if getattr(m, 'employment_rate', 0)), 0)
                    salary = next((getattr(m, 'avg_salary', 0) for m in majors if getattr(m, 'avg_salary', 0)), 0)
                    alts = getattr(school, 'similar_alternatives', []) or []
                    alts_str = ', '.join(alts[:3])
                    # P0-2 闭环：兜底类型
                    if category == '保':
                        bao_type_str = '垫(<85%)' if getattr(school, 'safety_warning', None) else '标准(>=85%)'
                    else:
                        bao_type_str = '—'
                    writer.writerow([
                        i, school.batch if school.batch else '其他', category, bao_type_str,
                        school.school_name, tier_str,
                        school.location, f'{school.probability:.1f}%',
                        school.confidence,
                        majors_str, risk_str,
                        f'{emp_rate*100:.0f}%' if emp_rate else '',
                        int(salary) if salary else '',
                        alts_str,
                    ])
        return output_path

    # ── 标准层: PDF图表增强 ──

    def _draw_radar_chart(self, canvas, big_five: dict, cx: float, cy: float,
                          radius: float, font_name: str):
        """绘制项目自编大五维度偏好雷达图（五边形）。"""
        from reportlab.lib import colors

        dims = [
            ('E', '外向性'), ('A', '宜人性'),
            ('C', '尽责性'), ('N', '神经质'), ('O', '开放性'),
        ]
        n = len(dims)
        angle_step = 2 * math.pi / n

        # 同心圆
        for r_level in [0.2, 0.4, 0.6, 0.8, 1.0]:
            canvas.circle(cx, cy, radius * r_level, stroke=1, fill=0)
            canvas.setFont(font_name, 7)
            canvas.setFillColor(colors.gray)
            canvas.drawCentredString(cx + 2, cy + radius * r_level + 1, str(int(r_level * 100)) + '%')

        # 主轴
        for i in range(n):
            angle = -math.pi / 2 + i * angle_step
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            canvas.setStrokeColor(colors.grey)
            canvas.setLineWidth(0.3)
            canvas.line(cx, cy, x, y)
            # 标签
            lx = cx + (radius + 12) * math.cos(angle)
            ly = cy + (radius + 12) * math.sin(angle)
            canvas.setFont(font_name, 8)
            canvas.setFillColor(colors.HexColor('#333333'))
            canvas.drawCentredString(lx, ly, dims[i][1])

        # 数据多边形
        scores = []
        for i, (key, label) in enumerate(dims):
            angle = -math.pi / 2 + i * angle_step
            raw = big_five.get(key, 50)
            normalized = min(raw / 100.0, 1.0)
            x = cx + radius * normalized * math.cos(angle)
            y = cy + radius * normalized * math.sin(angle)
            scores.append((x, y))

        if len(scores) >= 3:
            canvas.setLineWidth(2)
            canvas.setStrokeColor(colors.HexColor('#2196F3'))
            canvas.setFillColor(colors.HexColor('#2196F3', alpha=0.2))
            canvas.polygon([p[0] for p in scores], [p[1] for p in scores], stroke=1, fill=1)

            # 数据点
            for x, y in scores:
                canvas.circle(x, y, 3, stroke=1, fill=1)

    def _draw_pie_chart(self, canvas, chong_count: int, wen_count: int,
                        bao_count: int, cx: float, cy: float,
                        radius: float, font_name: str):
        """绘制冲稳保饼图"""
        from reportlab.lib import colors
        from reportlab.graphics.shapes import Drawing, Pie as PieShape, DrawingRenderer

        total = chong_count + wen_count + bao_count
        if total == 0:
            return

        # 使用reportlab.graphics.charts绘制饼图
        d = Drawing(120, 120)
        pie = PieShape()
        pie.x = 15
        pie.y = 5
        pie.width = 90
        pie.height = 90
        pie.slices.strokeWidth = 0.5
        pie.slices.strokeColor = colors.white
        pie.slices.label_visible = False
        pie.data = [chong_count, wen_count, bao_count]
        pie.slice_labels = [f'冲({chong_count})', f'稳({wen_count})', f'保({bao_count})']
        pie.slices.labelFont = font_name
        pie.slices.labelFontSize = 8
        pie.slices[0].fillColor = colors.HexColor('#4CAF50')
        pie.slices[1].fillColor = colors.HexColor('#2196F3')
        pie.slices[2].fillColor = colors.HexColor('#FF9800')
        d.add(pie)

        from reportlab.graphics import renderPDF
        renderPDF.draw(d, canvas, cx - 60, cy - 50)

    def _draw_trend_chart(self, canvas, school_records: list,
                          cx: float, cy: float, width: float,
                          height: float, font_name: str):
        """绘制3年位次趋势折线图
        school_records: [(year, rank), ...]
        """
        from reportlab.lib import colors

        if len(school_records) < 2:
            return

        # 坐标轴
        margin_left = 35
        margin_bottom = 20
        margin_top = 10
        margin_right = 10
        plot_w = width - margin_left - margin_right
        plot_h = height - margin_bottom - margin_top

        x0 = cx + margin_left
        y0 = cy + margin_bottom
        x1 = cx + width - margin_right
        y1 = cy + plot_h

        years = [r[0] for r in school_records]
        ranks = [r[1] for r in school_records]
        min_rank = min(ranks)
        max_rank = max(ranks)
        if min_rank == max_rank:
            max_rank = min_rank + 1000

        # 画坐标轴
        canvas.setLineWidth(1)
        canvas.line(x0, y0, x1, y0)
        canvas.line(x0, y0, x0, y1)

        # 数据折线
        points = []
        for i, (year, rank) in enumerate(school_records):
            px = x0 + (i / max(len(years) - 1, 1)) * plot_w
            py = y0 + ((rank - min_rank) / (max_rank - min_rank)) * plot_h
            points.append((px, py))

        if len(points) >= 2:
            canvas.setLineWidth(2)
            canvas.setStrokeColor(colors.HexColor('#E91E63'))
            canvas.setFillColor(colors.HexColor('#E91E63', alpha=0.15))
            canvas.polyLine(points)
            # 填充区域
            fill_points = [(points[0][0], y0)] + points + [(points[-1][0], y0)]
            xs = [p[0] for p in fill_points]
            ys = [p[1] for p in fill_points]
            canvas.setFillColor(colors.HexColor('#E91E63', alpha=0.1))
            canvas.polygon(xs, ys, stroke=0, fill=1)

        # 数据点
        for px, py in points:
            canvas.circle(px, py, 3, stroke=1, fill=1)

        # Y轴标签
        canvas.setFont(font_name, 7)
        canvas.setFillColor(colors.gray)
        canvas.drawRightString(x0 - 3, y0, str(min_rank))
        canvas.drawRightString(x0 - 3, y1, str(max_rank))

        # X轴标签
        canvas.drawCentredString(x0, y0 - 8, str(years[0]))
        canvas.drawCentredString(x1, y0 - 8, str(years[-1]))

    def _generate_ai_narrative(self, personality_result, recommendations: dict, matching_result=None) -> List[str]:
        """生成AI个性化解读（洞察型，非数据翻译）"""
        narratives = []
        if not personality_result or not matching_result:
            return narratives

        q = matching_result.questionnaire
        up = matching_result.user_profile
        if not up:
            return narratives  # P2-fix: 防御性检查，防止user_profile为None时后续访问崩溃
        fr = getattr(matching_result, 'family_resource_result', None)

        # ── 1. 偏好问卷×专业匹配度 ──
        holland_code = personality_result.holland_code
        # RIASEC 风格代码对应的专业倾向
        holland_major_hints = {
            'R': ['机械', '电气', '土木', '自动化', '车辆', '航空'],
            'I': ['计算机', '数学', '物理', '化学', '生物', '数据', '研究'],
            'A': ['设计', '艺术', '建筑', '传媒', '新闻', '动画'],
            'S': ['教育', '心理', '护理', '社工', '医学', '师范'],
            'E': ['金融', '管理', '市场', '工商', '经济', '法学'],
            'C': ['会计', '财务', '统计', '审计', '档案', '信息'],
        }
        holland_inferred_majors = []
        for c in holland_code:
            holland_inferred_majors.extend(holland_major_hints.get(c, []))

        # 用户明确意愿专业
        explicit_majors = []
        if q.vertical_majors:
            explicit_majors.extend([m for m in q.vertical_majors if m != '都不考虑'])
        if q.acceptable_majors:
            explicit_majors.extend(q.acceptable_majors)
        explicit_majors = list(dict.fromkeys(explicit_majors))  # 去重保序

        if explicit_majors and holland_inferred_majors:
            # 检查是否匹配
            matched = []
            for em in explicit_majors:
                for hint in holland_inferred_majors:
                    if hint in em or em in hint:
                        matched.append(em)
                        break
            if len(matched) >= len(explicit_majors) * 0.5:
                narratives.append(
                    f"项目自编问卷生成的 RIASEC 风格代码为【{holland_code}】，与您明确的"
                    f"{matched[0]}方向高度匹配，偏好问卷信号与个人意愿一致。"
                )
            else:
                inferred_hints = ', '.join(holland_inferred_majors[:3])
                narratives.append(
                    f"项目自编问卷生成的 RIASEC 风格代码为【{holland_code}】，方向信号偏向{inferred_hints}，"
                    f"而您明确偏好{explicit_majors[0]}，两者存在一定差异。"
                    f"建议关注交叉领域或做好专业调剂准备。"
                )
        elif explicit_majors:
            narratives.append(
                f"您明确偏好{explicit_majors[0]}方向，"
                f"系统已将其作为推荐专业的最高优先级。"
            )

        # ── 2. 风险具体化 ──
        chong = recommendations.get('冲', [])
        wen = recommendations.get('稳', [])
        bao = recommendations.get('保', [])

        # 冲档风险
        risky_chong = [s for s in chong if s.probability < 35]
        if risky_chong:
            s = risky_chong[0]
            narratives.append(
                f"冲档中{s.school_name}录取概率约{s.probability:.0f}%，"
                f"存在较大不确定性，建议搭配充足的稳档和保档院校。"
            )

        # 保底不足
        if len(bao) < 3:
            narratives.append(
                f"保底院校偏少（仅{len(bao)}所），建议适当放宽专业或地域偏好以增加保底选择。"
            )

        # 专业组调剂风险
        if up.excluded_majors and chong:
            narratives.append(
                "⚠️ 您排除了部分专业方向，冲档院校若专业组内包含被排除专业，"
                "存在被调剂到不感兴趣专业的风险，请仔细查阅该校专业组构成。"
            )

        # ── 3. 家庭资源×策略 ──
        if fr and fr.rating == '高':
            budget = q.total_budget or ''
            if '100万' in budget or '50万' in budget:
                narratives.append(
                    f"您的家庭就业资源充裕（预算{budget}），"
                    f"建议优先选择有海外交流项目、双学位项目的院校，为后续出国深造铺路。"
                )
            else:
                narratives.append(
                    "您的家庭就业资源较充裕，可适当考虑中外合作办学或国际交流项目。"
                )
        elif fr and fr.rating == '低':
            narratives.append(
                "系统已自动为您筛选了学费较低的院校，建议关注国家助学贷款政策和奖助学金项目。"
                "专业选择上优先技术壁垒高、个人能力主导的方向。"
            )

        # ── 4. 行业趋势与个人匹配 ──
        if q.target_industries:
            industry = q.target_industries[0]
            # 简单趋势提示
            hot_industries = ['信息技术/互联网', '医疗/健康', '制造业/工程']
            rising_industries = ['能源/环保', '金融/银行']
            if industry in hot_industries:
                narratives.append(
                    f"您关注的'{industry}'是当前热门就业方向，"
                    f"近三年在云南的录取竞争持续加剧，但您的基础学科背景与该行业需求匹配。"
                )
            elif industry in rising_industries:
                narratives.append(
                    f"您关注的'{industry}'正处于转型上升期，"
                    f"建议关注该领域的新兴交叉专业（如新能源+计算机、金融科技等）。"
                )

        return narratives

    # ── 批模式报告（覆盖所有批次+专业组）──

    def generate_batch_pdf_report(self, batch_plan: Dict, output_path: str = None) -> str:
        """生成批模式PDF报告（覆盖所有批次）"""
        if output_path is None:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = os.path.join(
                self.output_dir,
                f'批模式推荐方案_{batch_plan.get("user", {}).get("name", "考生")}_{ts}.pdf',
            )
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import mm
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Flowable,
            )
            from reportlab.lib import colors
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont

            font_name = _get_chinese_font()

            doc = SimpleDocTemplate(
                output_path, pagesize=A4,
                rightMargin=20*mm, leftMargin=20*mm,
                topMargin=20*mm, bottomMargin=20*mm,
            )
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'CustomTitle', parent=styles['Title'],
                fontName=font_name, fontSize=20, leading=26,
                spaceAfter=20, alignment=1,
            )
            heading_style = ParagraphStyle(
                'CustomHeading', parent=styles['Heading1'],
                fontName=font_name, fontSize=14, leading=18,
                spaceAfter=10, textColor=colors.HexColor('#1a1a1a'),
            )
            subheading_style = ParagraphStyle(
                'CustomSubHeading', parent=styles['Heading2'],
                fontName=font_name, fontSize=11, leading=14,
                spaceAfter=6, textColor=colors.HexColor('#333333'),
            )
            normal_style = ParagraphStyle(
                'CustomNormal', parent=styles['Normal'],
                fontName=font_name, fontSize=9, leading=12, spaceAfter=4,
            )
            warning_style = ParagraphStyle(
                'Warning', fontName=font_name, fontSize=9,
                textColor=colors.HexColor('#d32f2f'), spaceAfter=6,
            )

            story = []
            user = batch_plan.get('user', {})
            story.append(Paragraph('高考志愿推荐方案（全批次模式）', title_style))
            story.append(Paragraph(
                f'{_h(user.get("name", ""))} · {_h(user.get("score", 0))}分 · '
                f'位次{_h(user.get("rank", 0))} · {_h(user.get("category", ""))}',
                normal_style,
            ))
            story.append(Spacer(1, 15))

            # 数据完整性
            ok, data_msg, _ = check_data_completeness(self.db_path, user.get('category', '物理类'))
            story.append(Paragraph(f'⚠️ 数据: {data_msg}', warning_style if not ok else normal_style))

            # 批次录取顺序
            admission_order = batch_plan.get('admission_order', [])
            if admission_order:
                story.append(Paragraph('批次录取顺序', subheading_style))
                # admission_order 可能是字符串列表或 dict 列表
                names = []
                for b in admission_order:
                    names.append(b.get('name', '') if isinstance(b, dict) else str(b))
                story.append(Paragraph(' → '.join(names), normal_style))
                story.append(Spacer(1, 10))

            # 逐批次输出
            batches = batch_plan.get('batches', {})
            for batch_key in list(batches.keys()):
                bd = batches[batch_key]
                story.append(Paragraph(f"{bd.get('name', batch_key)}（{bd.get('method', '')}，{bd.get('volunteer_count', 0)}个志愿）", heading_style))

                for cat_label in ['冲', '稳', '保', '垫']:
                    schools = bd.get(cat_label, [])
                    if not schools:
                        continue
                    story.append(Paragraph(f'  {cat_label}（{bd.get(f"{cat_label.lower()}_count", len(schools))}所）', subheading_style))
                    table_data = [['#', '院校', '层级', '地点', '概率', '置信度']]
                    for i, s in enumerate(schools[:10], 1):
                        prob_display = s.get('probability_raw')
                        if prob_display is not None:
                            prob_display = f"{prob_display:.1f}%"
                        else:
                            prob_display = s.get('probability', '')
                        tier_str = f"{s.get('tier_level', '')} {s.get('tier_name', '')}" if s.get('tier_level') else s.get('school_quality', '')
                        table_data.append([
                            str(i), s.get('school_name', ''),
                            tier_str, s.get('location', ''),
                            prob_display, s.get('confidence', ''),
                        ])
                    table = Table(
                        table_data,
                        colWidths=[10*mm, 50*mm, 25*mm, 25*mm, 20*mm, 20*mm],
                    )
                    table.setStyle(TableStyle([
                        ('FONTNAME', (0, 0), (-1, -1), font_name),
                        ('FONTSIZE', (0, 0), (-1, -1), 8),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e0e0')),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ]))
                    story.append(table)
                    story.append(Spacer(1, 8))

                story.append(PageBreak())

            # ── 批模式：学校画像汇总 ──
            story.append(Paragraph('推荐院校画像汇总', heading_style))
            story.append(Spacer(1, 5))
            try:
                from models.school_profile import SchoolProfileManager
                sp_mgr = SchoolProfileManager(db_path=self.db_path)
                seen = set()
                prof_rows = []
                for bk, bd in batches.items():
                    for cat in ['冲', '稳', '保', '垫']:
                        for s in bd.get(cat, []):
                            sn = s.get('school_name', '')
                            if sn and sn not in seen:
                                seen.add(sn)
                                prof = sp_mgr.get_profile(sn)
                                if prof:
                                    score = prof.compute_score()
                                    tag_str = ' | '.join(prof.tags) if prof.tags else '-'
                                    strength = []
                                    if prof.num_academicians: strength.append(f'院士{prof.num_academicians}')
                                    if prof.num_phd: strength.append(f'博士{prof.num_phd}')
                                    if prof.num_master: strength.append(f'硕士{prof.num_master}')
                                    strength_str = ' | '.join(strength) if strength else '-'
                                    prof_rows.append([sn, tag_str, strength_str, f'评分:{score}'])
                sp_mgr.close()
                if prof_rows:
                    pt_data = [['院校', '标签', '学术实力', '综合评分']]
                    pt_data.extend(prof_rows[:30])  # 最多30所
                    pt = Table(pt_data, colWidths=[45*mm, 35*mm, 65*mm, 25*mm])
                    pt.setStyle(TableStyle([
                        ('FONTNAME', (0, 0), (-1, -1), font_name),
                        ('FONTSIZE', (0, 0), (-1, -1), 8),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e0e0')),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ]))
                    story.append(pt)
            except Exception:
                pass

            # 数据告警
            ok, data_msg, details = check_data_completeness(self.db_path, user.get('category', '物理类'))
            if not ok:
                story.append(PageBreak())
                story.append(Paragraph('数据完整性说明', heading_style))
                story.append(Paragraph(
                    f'记录数: {details["total_records"]} | 有位次: {details["with_rank"]} | '
                    f'院校: {details["school_count"]} | 专业组: {details["major_count"]} | '
                    f'批次覆盖: {len(details["batches"])}',
                    normal_style,
                ))
                story.append(Paragraph(data_msg, warning_style))

            doc.build(story)
            return output_path
        except Exception:
            return self.generate_batch_html_report(batch_plan, output_path.replace('.pdf', '.html'))

    def generate_batch_html_report(self, batch_plan: Dict, output_path: str = None) -> str:
        """生成批模式HTML报告（覆盖所有批次）"""
        if output_path is None:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = os.path.join(
                self.output_dir,
                f'批模式推荐方案_{batch_plan.get("user", {}).get("name", "考生")}_{ts}.html',
            )

        user = batch_plan.get('user', {})
        ok, data_msg, details = check_data_completeness(
            self.db_path, user.get('category', '物理类'))

        alert_color = '#d32f2f' if not ok else '#2e7d32'
        html = '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n'
        html += f'    <meta charset="UTF-8">\n    <title>批模式推荐 - {_h(user.get("name", ""))}</title>\n'
        html += """    <style>
        body { font-family: "Microsoft YaHei", Arial, sans-serif; max-width: 1200px; margin: 0; padding: 20px; background: #f5f5f5; }
        .container { background: white; padding: 20px; border-radius: 8px; }
        h1 { text-align: center; color: #333; }
        h2 { color: #4CAF50; border-bottom: 2px solid #4CAF50; padding-bottom: 5px; margin-top: 30px; }
        h3 { color: #666; }
        table { width: 100%; border-collapse: collapse; margin: 10px 0; }
        th { background: #4CAF50; color: white; padding: 8px; text-align: left; }
        td { border: 1px solid #ddd; padding: 6px 8px; }
        tr:nth-child(even) { background: #f9f9f9; }
        .alert { background: #fff3cd; border: 1px solid #ffc107; padding: 10px; border-radius: 5px; color: #856404; margin: 10px 0; }
        .data-warn { color: """ + alert_color + """; font-weight: bold; }
        .batch-summary { display: flex; gap: 10px; flex-wrap: wrap; margin: 10px 0; }
        .batch-card { background: #f0f0f0; padding: 8px 12px; border-radius: 5px; font-size: 12px; }
        </style>\n</head>\n<body>\n"""
        html += '    <div class="container">\n'
        html += f'    <h1>高考志愿推荐方案（全批次模式）</h1>\n'
        html += f'    <p><strong>{_h(user.get("name", ""))}</strong> · {_h(user.get("score", 0))}分 · 位次{_h(user.get("rank", 0))} · {_h(user.get("category", ""))}</p>\n'
        html += f'    <p class="data-warn">⚠️ 数据完整性: {_h(data_msg)}</p>\n'

        # 批次录取顺序
        admission_order = batch_plan.get('admission_order', [])
        if admission_order:
            html += '    <h2>批次录取顺序</h2>\n'
            names = [b.get("name", "") if isinstance(b, dict) else str(b) for b in admission_order]
            html += f'    <p>{_h(" → ".join(names))}</p>\n'

        # 批次汇总
        batch_summary = batch_plan.get('batch_summary', {})
        if batch_summary:
            html += '    <h2>批次汇总</h2>\n    <div class="batch-summary">\n'
            for bn, bd in batch_summary.items():
                html += f'        <div class="batch-card"><strong>{_h(bn)}</strong>: 冲{bd.get("chong", 0)} 稳{bd.get("wen", 0)} 保{bd.get("bao", 0)} (共{bd.get("total", 0)})</div>\n'
            html += '    </div>\n'

        # 逐批次输出
        batches = batch_plan.get('batches', {})
        for batch_key, bd in batches.items():
            html += f'    <h2>{_h(bd.get("name", batch_key))}（{_h(bd.get("method", ""))}，{bd.get("volunteer_count", 0)}个志愿）</h2>\n'

            for cat_label in ['冲', '稳', '保', '垫']:
                schools = bd.get(cat_label, [])
                if not schools:
                    continue
                cat_class = {'冲': 'chong', '稳': 'wen', '保': 'bao'}.get(cat_label, '')
                html += f'    <h3 class="{cat_class}">{cat_label}（{bd.get(f"{cat_label.lower()}_count", len(schools))}所）</h3>\n'
                html += '    <table><tr><th>#</th><th>院校</th><th>层级</th><th>地点</th><th>概率</th><th>置信度</th></tr>\n'
                for i, s in enumerate(schools[:10], 1):
                    tier_str = f"{s.get('tier_level', '')} {s.get('tier_name', '')}" if s.get('tier_level') else s.get('school_quality', '')
                    html += (f'        <tr><td>{i}</td><td>{_h(s.get("school_name", ""))}</td>'
                             f'<td>{_h(tier_str)}</td><td>{_h(s.get("location", ""))}</td>'
                             f'<td>{_h(s.get("probability", ""))}</td><td>{_h(s.get("confidence", ""))}</td></tr>\n')
                html += '    </table>\n'

        # 数据完整性详情
        html += f'    <div class="alert">\n'
        html += f'        <strong>数据完整性:</strong> {_h(data_msg)}<br>\n'
        html += f'        记录数: {details["total_records"]} | 有位次: {details["with_rank"]} | '
        html += f'院校: {details["school_count"]} | 专业组: {details["major_count"]} | '
        html += f'批次: {_h(", ".join(details.get("batches", [])))}\n'
        html += f'    </div>\n'

        html += '    </div>\n</body>\n</html>'
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        return output_path


    def generate_all(self, matching_result, base_name: str = None) -> Dict[str, str]:
        if base_name is None:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            base_name = f'志愿推荐方案_{matching_result.questionnaire.name}_{ts}'

        results = {}
        try:
            pdf_path = self.generate_pdf_report(
                matching_result, os.path.join(self.output_dir, f'{base_name}.pdf'),
            )
            results['PDF'] = pdf_path
        except Exception as e:
            print(f'PDF生成失败: {e}')

        try:
            excel_path = self.generate_excel_report(
                matching_result, os.path.join(self.output_dir, f'{base_name}.xlsx'),
            )
            results['Excel'] = excel_path
        except Exception as e:
            print(f'Excel生成失败: {e}')

        html_path = self.generate_html_report(
            matching_result, os.path.join(self.output_dir, f'{base_name}.html'),
        )
        results['HTML'] = html_path

        return results


def main():
    """测试用例 V3.0"""
    from gaokao.core.matching_engine import MatchingEngine
    from gaokao.core.questionnaire_parser import QuestionnaireParser

    print('=' * 70)
    print('文档生成器 V3.0 测试')
    print('=' * 70)

    engine = MatchingEngine()
    parser = QuestionnaireParser.create_by_category('物理类')

    test_data = {
        'q1_name': '张三', 'q2_gender': '男',
        'q5_exam_id': '5301002026000001', 'q6_phone': '13800138000',
        'q9_color_vision': '无色盲色弱', 'q10_vision': '视力正常',
        'q12_total_score': 580, 'q13_rank': 15000,
        'q14_category': '物理类',
        'q43_core_demand': '专业实力优先',
        'q45_target_industries': ['信息技术/互联网'],
        'q49_acceptable_majors': ['工学类', '理学类'],
        'q56_province_preference': '优先出省',
        'q60_stability_preference': 3,
        'q68_stress_tolerance': '中等压力',
        'q74_decision_control': '自己决定，参考家长意见',
    }

    questionnaire = parser.parse(test_data)

    big_five_answers = {i: 4 for i in range(1, 51)}
    holland_answers = {i: 'A' if i % 2 == 0 else 'B' for i in range(1, 77)}
    efficacy_answers = {
        76: 4, 77: 4, 78: 3, 79: 4, 80: 4,
        81: 5, 82: 4, 83: 4, 84: 5, 85: 4,
        86: 3, 87: 3, 88: 4, 89: 3, 90: 4,
    }
    career_values_answers = {
        91: 3, 92: 3, 93: 3, 94: 3, 95: 4, 96: 4,
        97: 3, 98: 3, 99: 4, 100: 4, 101: 3, 102: 3,
        103: 3, 104: 3, 105: 3, 106: 3, 107: 4, 108: 4,
        109: 4, 110: 4,
    }

    result = engine.match(
        questionnaire, big_five_answers, holland_answers,
        efficacy_answers, career_values_answers, top_n=15,
    )

    generator = DocumentGenerator(output_dir='output')

    print('\n生成HTML报告...')
    print(f'HTML报告已生成: {generator.generate_html_report(result)}')

    print('\n生成Excel报告...')
    try:
        print(f'Excel报告已生成: {generator.generate_excel_report(result)}')
    except Exception as e:
        print(f'Excel生成失败: {e}')

    engine.close()
    print('\n' + '=' * 70)
    print('测试完成！')


if __name__ == '__main__':
    main()
