# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""
行业强校识别（双轨制 + 分级）

主轨：school_info.syl_disciplines（双一流建设学科）— 教育部权威数据
补轨：INDUSTRY_STRONG_PATCH — 非双一流但行业认可度极高的院校手工清单

补丁分两层：
- national（全国话语权）：行业内全国第一/部委嫡系，全分数段都该奖励
- regional（区域强工科）：发达省会强工科，主要服务中分段考生（位次 30k-100k）

匹配规则：(学校命中) AND (推荐专业落在该校强势学科) → 返回 tier
"""

# tier 标记：
#   national = 全国行业话语权（如温州医科大学的眼视光医学，全国第一）
#   regional = 区域强工科（如浙江工业的化工，省内/区域就业辐射强）

INDUSTRY_STRONG_PATCH = {
    # ───── national: 金融财经类（全国校招认可度） ─────
    '江西财经大学':       {'tier': 'national', 'majors': ('会计', '金融', '审计', '财务', '税收', '经济'),       'industry': '金融财经'},
    '东北财经大学':       {'tier': 'national', 'majors': ('会计', '金融', '统计', '审计', '财务', '税收'),       'industry': '金融财经'},
    '上海立信会计金融学院': {'tier': 'national', 'majors': ('会计', '审计', '财务', '金融'),                     'industry': '金融财经'},
    '南京审计大学':       {'tier': 'national', 'majors': ('审计', '会计', '财务'),                              'industry': '金融财经'},

    # ───── national: 电子信息类（华为/中兴/三大运营商嫡系） ─────
    '杭州电子科技大学':   {'tier': 'national', 'majors': ('电子', '通信', '计算机', '软件', '集成电路', '自动化'), 'industry': '电子信息'},
    '重庆邮电大学':       {'tier': 'national', 'majors': ('通信', '电子', '计算机', '邮政', '网络'),             'industry': '电子信息'},
    '南京邮电大学':       {'tier': 'national', 'majors': ('通信', '电子', '计算机', '邮政', '网络'),             'industry': '电子信息'},

    # ───── national: 电力能源类（国家电网嫡系） ─────
    '上海电力大学':       {'tier': 'national', 'majors': ('电气', '能源', '电力', '热能', '新能源'),             'industry': '电力能源'},
    '南京工程学院':       {'tier': 'national', 'majors': ('电气', '能源', '电力', '自动化'),                     'industry': '电力能源'},
    '东北电力大学':       {'tier': 'national', 'majors': ('电气', '能源', '电力', '热能', '自动化'),             'industry': '电力能源'},

    # ───── national: 政法系统 ─────
    '西南政法大学':       {'tier': 'national', 'majors': ('法学', '侦查', '法律', '政治学', '行政'),             'industry': '政法'},
    '中国刑事警察学院':   {'tier': 'national', 'majors': ('侦查', '刑事', '警务', '公安', '禁毒'),               'industry': '政法'},

    # ───── national: 航海/航空 ─────
    '大连海事大学':       {'tier': 'national', 'majors': ('航海', '轮机', '物流', '海事', '船舶'),               'industry': '航海交通'},
    '中国民航大学':       {'tier': 'national', 'majors': ('航空', '飞行器', '空中交通', '飞行'),                 'industry': '航空'},
    '中国民用航空飞行学院': {'tier': 'national', 'majors': ('航空', '飞行', '空中交通'),                         'industry': '航空'},

    # ───── national: 外语翻译 ─────
    '西安外国语大学':     {'tier': 'national', 'majors': ('英语', '翻译', '外语', '德语', '法语', '俄语'),       'industry': '外语翻译'},
    '北京语言大学':       {'tier': 'national', 'majors': ('汉语', '对外汉语', '汉语国际', '语言'),               'industry': '外语翻译'},
    '天津外国语大学':     {'tier': 'national', 'majors': ('英语', '翻译', '外语', '德语', '日语'),               'industry': '外语翻译'},

    # ───── national: 医药类（学科评估A/A-、全国第一） ─────
    '温州医科大学':       {'tier': 'national', 'majors': ('眼视光', '眼科'),                                    'industry': '医药'},
    '徐州医科大学':       {'tier': 'national', 'majors': ('麻醉学',),                                           'industry': '医药'},
    '沈阳药科大学':       {'tier': 'national', 'majors': ('药学', '药剂', '制药', '药物', '中药'),               'industry': '医药'},
    '首都医科大学':       {'tier': 'national', 'majors': ('临床医学', '儿科', '口腔', '麻醉', '影像', '护理'),   'industry': '医药'},
    '南方医科大学':       {'tier': 'national', 'majors': ('临床医学', '基础医学', '中西医', '影像', '护理'),     'industry': '医药'},

    # ───── national: 铁路/军工/海关/建筑/重型机械/船舶/光电/有色冶金 ─────
    '石家庄铁道大学':     {'tier': 'national', 'majors': ('土木', '交通', '机械', '工程管理', '隧道', '桥梁'),   'industry': '铁路交通'},
    '中北大学':           {'tier': 'national', 'majors': ('武器', '弹药', '测控', '材料', '兵器'),               'industry': '军工'},
    '上海海关学院':       {'tier': 'national', 'majors': ('海关', '税收', '法学', '国际商务'),                   'industry': '海关'},
    '西安建筑科技大学':   {'tier': 'national', 'majors': ('建筑', '土木', '城乡规划', '风景园林', '环境'),       'industry': '建筑'},
    '燕山大学':           {'tier': 'national', 'majors': ('机械', '材料', '控制', '计算机', '冶金'),             'industry': '机械'},
    '江苏科技大学':       {'tier': 'national', 'majors': ('船舶', '海洋工程', '焊接', '机械'),                   'industry': '船舶'},
    '长春理工大学':       {'tier': 'national', 'majors': ('光学', '仪器', '光电', '机械', '电子'),               'industry': '光电'},
    '昆明理工大学':       {'tier': 'national', 'majors': ('冶金', '有色', '矿业', '材料', '环境'),               'industry': '有色冶金'},

    # ───── regional: 发达省会强工科（中分段考生的最优解） ─────
    # 数据来源：教育部学科评估B+/A-、地区头部企业校招白名单
    '浙江工业大学':       {'tier': 'regional', 'majors': ('化工', '化学', '机械', '控制', '计算机', '药学', '环境'), 'industry': '区域工科', 'region': '长三角'},
    '广东工业大学':       {'tier': 'regional', 'majors': ('机械', '控制', '计算机', '材料', '电子', '自动化'),     'industry': '区域工科', 'region': '珠三角'},
    '江苏大学':           {'tier': 'regional', 'majors': ('机械', '车辆', '流体', '农业工程', '能源'),             'industry': '区域工科', 'region': '苏南'},
    '河南科技大学':       {'tier': 'regional', 'majors': ('机械', '车辆', '农业机械', '材料'),                     'industry': '区域工科', 'region': '中部装备'},
    '山东科技大学':       {'tier': 'regional', 'majors': ('矿业', '机械', '采矿', '安全工程', '测绘'),             'industry': '区域工科', 'region': '山东工业'},
    '青岛科技大学':       {'tier': 'regional', 'majors': ('化工', '化学', '高分子', '橡胶', '材料'),               'industry': '区域工科', 'region': '青岛化工'},
    '武汉科技大学':       {'tier': 'regional', 'majors': ('冶金', '材料', '机械', '矿业'),                         'industry': '区域工科', 'region': '武汉钢铁'},
    '河北工业大学':       {'tier': 'regional', 'majors': ('电气', '机械', '材料', '化工', '控制'),                 'industry': '区域工科', 'region': '京津冀'},
}


def get_industry_strong_match(school_name: str, major_text: str,
                               syl_disciplines: str = '') -> str:
    """判断 (学校, 推荐专业) 是否命中行业强校组合

    Args:
        school_name: 学校名称
        major_text: 推荐专业拼接后的文本（如"电气工程及其自动化 能源与动力工程"）
        syl_disciplines: school_info.syl_disciplines 字段（双一流学科，"、" 分隔）

    Returns:
        'national' — 命中全国行业话语权强校组合
        'regional' — 命中区域强工科组合
        ''         — 未命中
    """
    if not major_text:
        return ''

    # 主轨：双一流学科匹配（视为 national 级）
    if syl_disciplines:
        for d in syl_disciplines.replace('、', ',').split(','):
            d = d.strip()
            if not d or len(d) < 2:
                continue
            core = d.split('及其')[0].split('与')[0].strip()
            if core and len(core) >= 2 and core in major_text:
                return 'national'

    # 补轨：手工清单匹配
    # P2-fix: 子串匹配会导致'电子'误匹配'电子商务'，改为精确匹配或完整词匹配
    def _major_match(keyword: str, text: str) -> bool:
        if keyword == text:
            return True
        # 仅当keyword是text的完整组成部分且不是其他专业名的子串时匹配
        # 例如：'电子信息工程' in '电子信息工程' → True；'电子' in '电子商务' → False
        if keyword in text:
            # 排除已知的误匹配对
            false_positives = {('电子', '电子商务'), ('电商', '电子商务'), ('计算机', '计算机网络')}
            if (keyword, text) in false_positives:
                return False
            return True
        return False

    patch = INDUSTRY_STRONG_PATCH.get(school_name)
    if patch and any(_major_match(kw, major_text) for kw in patch['majors']):
        return patch.get('tier', 'national')

    return ''
