# SPDX-License-Identifier: LicenseRef-OpenGaokao-SAL-1.0
# Copyright (C) 2026 OpenGaokao Contributors
"""
家长偏好问卷（~15题）
与考生248题测评分离，独立完成。用于共识度计算。
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from .consensus_calculator import ParentPreference


# 家长问卷题目定义（15题，约5分钟完成）
PARENT_QUESTIONS = [
    {"id": "p1", "text": "您认为孩子未来的职业最需要什么？", "options": [
        "稳定（公务员/事业单位/国企）", "高收入（互联网/金融/创业）",
        "有创造空间（设计/艺术/科研）", "能帮助他人（医疗/教育/公益）"
    ]},
    {"id": "p2", "text": "孩子的工作稳定性对您有多重要？（1-5）", "options": [
        "1-完全不重要", "2-不太重要", "3-一般", "4-比较重要", "5-非常重要"
    ]},
    {"id": "p3", "text": "孩子的工作收入水平对您有多重要？（1-5）", "options": [
        "1-完全不重要", "2-不太重要", "3-一般", "4-比较重要", "5-非常重要"
    ]},
    {"id": "p4", "text": "您希望孩子在哪里读大学？", "options": [
        "必须在省内", "优先省内", "不限制地域", "优先一线城市", "必须离家近（3小时以内）"
    ]},
    {"id": "p5", "text": "您对孩子读研/深造的态度？", "options": [
        "必须读研", "优先读研", "看孩子意愿", "直接就业更好", "不限制"
    ]},
    {"id": "p6", "text": "您希望孩子从事什么行业？（可多选）", "options": [
        "信息技术/互联网", "金融/银行", "教育/培训", "医疗/健康",
        "法律/政务", "制造业/工程", "传媒/艺术", "能源/环保",
        "建筑/房地产", "社会服务/NGO", "不限制"
    ]},
    {"id": "p7", "text": "有没有您认为绝对不能选的专业方向？", "options": [
        "没有", "艺术类", "文史哲类", "农林类", "艰苦行业（矿/油/地质）",
        "有但不想说（下方填空）"
    ]},
    {"id": "p8", "text": "孩子选择专业时，您最看重什么？", "options": [
        "就业率", "薪资水平", "社会地位", "符合孩子兴趣",
        "符合家庭期望", "能继承家业/人脉"
    ]},
    {"id": "p9", "text": "如果孩子喜欢的专业您不认可，您会？", "options": [
        "坚决反对", "尝试说服孩子", "寻求折中方案", "尊重孩子选择", "不确定"
    ]},
    {"id": "p10", "text": "您对民办院校/独立学院的态度？", "options": [
        "绝对不能接受", "不太愿意但可以商量", "看专业实力", "无所谓", "不了解"
    ]},
    {"id": "p11", "text": "学费预算对您决策的影响？", "options": [
        "决定性因素（超出预算绝对不考虑）", "重要参考（可以适度突破）",
        "不太重要（孩子前途优先）", "经济不限制"
    ]},
    {"id": "p12", "text": "您觉得孩子的分数属于什么水平？", "options": [
        "远超预期", "符合预期", "略低于预期", "低于预期较多"
    ]},
    {"id": "p13", "text": "在选专业这件事上，您更倾向于？", "options": [
        "我帮孩子做决定（孩子还不懂事）", "我提供建议但最后孩子决定",
        "让孩子自己决定", "我们一起做决定（各占50%）"
    ]},
    {"id": "p14", "text": "您对AI推荐志愿的态度？", "options": [
        "完全信任", "可以参考但会验证", "不太信任", "完全不相信"
    ]},
    {"id": "p15", "text": "如果和孩子有分歧，您最可能妥协的方面是？", "options": [
        "地域（孩子出省也可以）", "专业（不强制某个专业）", "学校层次（不一定985/211）",
        "学费（可以适度提高预算）", "我不会妥协任何一项"
    ]},
]


def parse_parent_answers(answers: Dict[str, str]) -> ParentPreference:
    """
    解析家长15题答案 → ParentPreference 对象

    Args:
        answers: {"p1": "稳定（公务员/事业单位/国企）", "p2": "4", ...}
    """
    pref = ParentPreference()

    # p2: 稳定性 → 1-5映射
    p2 = answers.get('p2', '3')
    try:
        pref.stability_priority = float(p2[0])  # 取第一个字符
    except (ValueError, IndexError):
        pref.stability_priority = 3.0

    # p3: 收入 → 1-5映射
    p3 = answers.get('p3', '3')
    try:
        pref.income_priority = float(p3[0])
    except (ValueError, IndexError):
        pref.income_priority = 3.0

    # p4: 地域偏好
    p4 = answers.get('p4', '')
    loc_map = {
        '必须在省内': 'province_only',
        '优先省内': 'province_prefer',
        '不限制地域': 'no_limit',
        '优先一线城市': 'tier1_prefer',
        '必须离家近': 'near_home',
    }
    pref.location_preference = loc_map.get(p4.split(')')[-1] if ')' in p4 else p4, p4)

    # p6: 行业偏好（取第一个）
    p6 = answers.get('p6', '')
    pref.industry_preference = p6.split(',')[0].strip() if p6 else ''

    # p7: 禁止专业
    p7 = answers.get('p7', '')
    if p7 == '没有':
        pref.forbidden_majors = []
    elif '艺术类' in p7:
        pref.forbidden_majors.append('艺术类')
    elif '文史哲' in p7:
        pref.forbidden_majors.extend(['中国语言文学类', '历史学类', '哲学类'])
    elif '农林' in p7:
        pref.forbidden_majors.extend(['农学类', '林学类'])
    elif '艰苦' in p7:
        pref.forbidden_majors.extend(['矿业类', '地质类', '石油工程'])

    # p9: 分歧处理 → 风险容忍度
    p9 = answers.get('p9', '')
    if '坚决反对' in p9:
        pref.risk_tolerance = 'conservative'
    elif '折中' in p9:
        pref.risk_tolerance = 'balanced'
    else:
        pref.risk_tolerance = 'aggressive'

    # p13: 决策模式 → 风险容忍度补充
    p13 = answers.get('p13', '')
    if '帮孩子做决定' in p13:
        pref.risk_tolerance = 'conservative'

    # p15: 妥协方向 → 偏好可调性
    p15 = answers.get('p15', '')
    if '专业' in p15:
        # 家长对专业灵活 → 共识空间大
        pass
    if '地域' in p15:
        # 家长对地域灵活
        pref.location_preference = 'flexible'

    return pref


# ── 家长问卷 JSON 定义（用于前端渲染）──
PARENT_SURVEY_JSON = {
    "title": "家长志愿偏好问卷",
    "description": "15题 · 约5分钟 · 独立完成。帮您和孩子的志愿选择找到共同点。",
    "questions": PARENT_QUESTIONS,
}
