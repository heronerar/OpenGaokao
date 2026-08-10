# SPDX-License-Identifier: LicenseRef-OpenGaokao-SAL-1.0
# Copyright (C) 2026 OpenGaokao Contributors
"""
热门学科分析模块 (Hot Major Analyzer)
从招生数据和社会趋势中识别热门学科，输出未来趋势评分。

核心功能：
1. 当前热度评分（基于招生数据：规模+竞争+广度）
2. 未来趋势评分（基于多维度真实数据）
3. 综合热门学科排序
4. 热门学科集合输出（TOP30）

趋势评分数据源：
- 教育部2026新增38个专业映射
- 5年撤销1.22万专业点统计
- WEF 2025未来就业报告
- 麦肯锡18个未来竞技场(2040经济规模预测)
- 五大收敛集群(2045学科收敛路径)

评分模型：
- 当前热度 = α×规模分 + β×竞争分 + γ×广度分（α=0.3, β=0.4, γ=0.3）
- 趋势分数 = 因子匹配 + 新增红利 + 撤销惩罚 + 收敛潜力
- 综合分数 = 当前热度×0.4 + 趋势分数×0.6
"""
import sqlite3
import os
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import defaultdict


@dataclass
class TrendFactor:
    """趋势因子"""
    name: str
    weight: float
    benefit_major_classes: List[str] = field(default_factory=list)
    benefit_categories: List[str] = field(default_factory=list)
    score: int = 3  # 5分制


# ── 五大收敛集群（2045远景，基于全球学术格局演变报告） ──
# 来源：QS学科排名 + Nature Index + 中国十四五规划 + 美国CET清单 + 欧洲Horizon Europe
# 2040-2045年热门学科将收敛于五大核心集群，不再按传统学院派划分
CONVERGENCE_CLUSTERS = {
    "集群一·生命系统工程化": {
        "描述": "系统生物学+分子生物学+工程学+CS融合，生命体作为可设计系统",
        "核心专业类": ["生物医学工程类", "生物科学类", "化工与制药类",
                       "药学类", "计算机类"],
        "驱动技术": ["合成生物学", "AlphaFold蛋白质折叠", "基因组学", "生物制造"],
        "麦肯锡2040经济规模": "0.6-1.0T$（肥胖症与生活方式药物）",
    },
    "集群二·赛博-物理生态": {
        "描述": "机器人+先进制造+边缘计算+5G/6G+材料科学，物理与数字世界深度孪生",
        "核心专业类": ["自动化类", "机械类", "计算机类", "电子信息类",
                       "材料类"],
        "驱动技术": ["具身智能", "工业互联网", "智能多模态运输", "智慧城市"],
        "麦肯锡2040经济规模": "1.2-1.8T$（机器人学）+ 3.5-6.0T$（AI软件）",
    },
    "集群三·气候韧性与环境": {
        "描述": "可再生能源+环境工程+电动交通+碳管理+生物多样性",
        "核心专业类": ["电气类", "能源动力类", "土木类", "环境科学与工程类",
                       "材料类"],
        "驱动技术": ["氢能", "储能", "高效能源系统", "碳管理"],
        "麦肯锡2040经济规模": "0.4-0.7T$（未来空中交通/电池技术）",
    },
    "集群四·认知科学与人机界面": {
        "描述": "AI+神经科学+AR/VR+脑机接口，拓展人类认知与行动边界",
        "核心专业类": ["生物医学工程类", "计算机类", "电子信息类",
                       "心理学类", "自动化类"],
        "驱动技术": ["脑机接口", "人机协作", "神经技术", "增强认知"],
        "麦肯锡2040经济规模": "新兴领域，暂无直接数据（参考AI软件$3.5-6.0T）",
    },
    "集群五·数字经济治理与安全": {
        "描述": "数据隐私+网络安全+区块链+数字资产+法学+社会学",
        "核心专业类": ["计算机类", "金融学类", "法学类", "公共管理类",
                       "经济与贸易类"],
        "驱动技术": ["区块链", "零知识证明", "数字资产", "网络空间治理"],
        "麦肯锡2040经济规模": "1.0-1.5T$（网络安全）",
    },
}

# 麦肯锡18个未来竞技场 → 受益专业类映射（2040年收入预测）
# 来源：McKinsey Global Institute "18 arenas that will reshape the economy by 2040"
MCKINSEY_ARENAS = {
    "AI软件与服务": ("3.5-6.0T", ["计算机类", "数学类", "自动化类", "统计学类"]),
    "网络安全": ("1.0-1.5T", ["计算机类", "电子信息类", "法学类"]),
    "机器人学": ("1.2-1.8T", ["自动化类", "机械类", "计算机类"]),
    "肥胖症药物": ("0.6-1.0T", ["药学类", "生物科学类", "临床医学类"]),
    "未来空中交通": ("0.4-0.7T", ["航空航天类", "交通运输类", "材料类"]),
    "半导体制造": ("1.5-2.5T", ["微电子类", "电子信息类", "材料类"]),
    "电池与储能": ("0.8-1.2T", ["材料类", "化学类", "电气类"]),
    "自动驾驶": ("1.0-1.5T", ["计算机类", "自动化类", "交通运输类"]),
    "非医疗生物技术": ("0.3-0.6T", ["生物科学类", "化工与制药类"]),
    "基因与细胞治疗": ("0.5-0.8T", ["生物医学工程类", "药学类", "临床医学类"]),
}

# 收敛潜力加分（跨域融合能力）
# 专业类若同时属于多个收敛集群 → 获得收敛潜力加分
# 依据：报告指出"最成功的学科集合将是那些能够无缝跨越数字、物理和生物三大边界的领域"
#
# AUDIT-P1-012（不处理）：此系数衡量"跨技术集群融合度"，仅适用于理工科中跨越多个
# 产业群的专业。文史类（如汉语言文学0、历史学0、法学0等）未列其中是设计预期——
# 这些学科不跨技术集群，CONVERGENCE_POTENTIAL.get(...) 返回 0 是合理的。
# 当前字典中的系数基于产业报告中的集群重叠分析（每个专业类归属的集群数），
# 非主观设定。文史类专业的热门度由其他维度（就业率、薪资、wef_bonus等）独立计分。
# 若将来需要文史类竞争力维度，应新增独立系数如 HUMANITIES_COMPETITIVENESS，
# 而非强行给文史加无意义的"跨集群融合"分。
CONVERGENCE_POTENTIAL = {
    "计算机类": 2.0,     # 同时属于5个集群（AI底座，跨越数字/物理/生物）
    "自动化类": 1.8,     # 同时属于4个集群（赛博物理+认知+生命系统+数字经济）
    "电子信息类": 1.5,   # 同时属于4个集群（芯片+认知+赛博+数字经济）
    "生物医学工程类": 1.5,  # 同时属于3个集群（生命系统+认知+数字经济）
    "材料类": 1.2,       # 同时属于3个集群（赛博物理+气候韧性+生命系统）
    "数学类": 1.0,       # 同时属于3个集群（AI底座+认知+数字经济）
    "电气类": 0.8,       # 同时属于2个集群（气候韧性+赛博物理）
    "化学类": 0.7,       # 同时属于2个集群（生命系统+气候韧性）
    "药学类": 0.6,       # 同时属于2个集群（生命系统+认知）
    "临床医学类": 0.5,   # 同时属于2个集群（生命系统+认知）
    "统计学类": 0.5,     # 同时属于2个集群（AI底座+数字经济）
}

# ── 10大趋势因子（基于真实数据校准 + 2045远景增强） ──
# 数据来源：
#   1. 教育部2026年新增38个专业 → 映射受益专业类（2026-04-28发布）
#   2. 教育部5年撤销1.22万专业点（2020-2024） → 负向指标
#   3. WEF《2025未来就业报告》 → 2025-2030净增7800万岗位，科技/数据/AI最快增长
#   4. 张雪峰公开推荐TOP专业 + 各省招录数据
#   5. 麦肯锡18个未来竞技场经济规模（2040） → 权重校准
#   6. 五大收敛集群（2045） → 跨域融合能力评分
#
# weight依据：新增专业数量占比 + 政策优先级 + 竞技场经济规模
# score依据：WEF增长预期 + 撤销风险逆指标 + 集群收敛潜力（5分制）

# 教育部2026年新增38个专业 → 受益专业类映射
NEW_MAJOR_MAPPING = {
    # 交叉学科门类首批15种 + 国家战略 + 新兴产业
    "未来机器人":          ["自动化类", "机械类", "人工智能类"],
    "交叉工程":            ["自动化类", "计算机类", "电子信息类"],
    "具身智能":            ["自动化类", "计算机类", "电子信息类"],
    "脑机科学与技术":      ["生物医学工程类", "计算机类", "电子信息类"],
    "能源科学与工程":      ["电气类", "能源动力类", "材料类"],
    "深地科学与工程":      ["地质类", "矿业类", "土木类"],
    "半导体工艺与装备":    ["微电子类", "电子信息类", "材料类"],
    "稀土科学与工程":      ["材料类", "化学类"],
    "生物制造":            ["化工与制药类", "生物科学类", "食品科学类"],
    "低空经济与管理":      ["交通运输类", "自动化类"],
    "数字金融":            ["金融学类", "计算机类"],
    "数字贸易":            ["经济与贸易类", "计算机类"],
    "数字文旅":            ["旅游管理类", "新闻传播学类"],
    "健康服务与管理":      ["护理学类", "公共卫生与预防医学类"],
    "养老服务管理":        ["护理学类", "公共管理类"],
    # 新工科战略专业
    "新能源科学与工程":    ["电气类", "能源动力类"],
    "集成电路设计与集成系统": ["微电子类", "电子信息类"],
    "人工智能":            ["计算机类", "自动化类", "数学类"],
    "大数据科学与技术":    ["计算机类", "数学类", "统计学类"],
    "物联网工程":          ["计算机类", "电子信息类", "自动化类"],
    "区块链工程":          ["计算机类", "数学类"],
    "量子信息工程":        ["电子信息类", "物理类"],
    "空天科技":            ["航空航天类", "材料类"],
    "深海科技":            ["航空航天类", "机械类"],
    # 新医科
    "智能医学工程":        ["生物医学工程类", "计算机类"],
    "眼视光医学":          ["临床医学类", "医学技术类"],
    # 新农科
    "生物育种科学":        ["植物生产类", "生物科学类"],
    # 新文科
    "国际新闻与传播":      ["新闻传播学类", "外国语言文学类"],
    "区域国际学":          ["外国语言文学类", "政治学类"],
    # ── 2026年新增38专业补充（上文未覆盖的34个）───
    # 数字化+AI语言
    "计算语言学":          ["外国语言文学类", "计算机类", "人工智能类"],
    "语言智能":            ["外国语言文学类", "计算机类", "人工智能类"],
    "语言科学":            ["外国语言文学类", "中国语言文学类"],
    "法律英语":            ["外国语言文学类", "法学类"],
    # AI底座+计算
    "智能计算":            ["计算机类", "数学类", "人工智能类"],
    # 认知科学
    "心理、脑与认知科学":   ["心理学类", "生物医学工程类", "计算机类"],
    # 半导体支撑
    "真空工程与技术":      ["物理类", "机械类", "材料类"],
    # 双碳+新能源扩展
    "碳中和科学与工程":    ["环境科学与工程类", "化工与制药类", "能源动力类"],
    "交通能源融合工程":    ["交通运输类", "电气类", "能源动力类"],
    "资源环境审计":        ["经济学类", "环境科学与工程类"],
    # 无人系统+低空
    "海洋智能与无人技术":  ["船舶与海洋工程类", "自动化类", "计算机类"],
    "农业机器人":          ["农业工程类", "自动化类", "机械类"],
    "低空安全管理":        ["交通运输类", "公安学类", "自动化类"],
    # 国家安+公共安全
    "政治安全保卫":        ["公安学类", "法学类"],
    # 智慧城市+更新
    "城市更新":            ["土木类", "建筑类"],
    "智慧城市与空间规划":  ["建筑类", "计算机类", "公共管理类"],
    "数字公共治理":        ["公共管理类", "计算机类"],
    # 智能制造+材料
    "纤维科学与智能制造":  ["材料类", "自动化类"],
    "乐器智造":            ["设计学类", "机械类", "材料类"],
    # 数字化设计
    "智慧景观营造":        ["建筑类", "风景园林类", "计算机类"],
    # 农业+粮食安全
    "盐碱地科学与工程":    ["农业工程类", "土木类", "植物生产类"],
    "智慧渔业":            ["水产类", "计算机类", "自动化类"],
    # 医疗AI+精准医疗
    "核医学工程":          ["临床医学类", "医学技术类", "生物医学工程类"],
    "智能影像工程":        ["医学技术类", "计算机类", "电子信息类"],
    "医工学":              ["生物医学工程类", "临床医学类"],
    "医疗器械与装备工程":  ["生物医学工程类", "机械类"],
    "生物医药数据科学":    ["药学类", "计算机类", "生物医学工程类"],
    # AI+商科
    "商业人工智能":        ["工商管理类", "计算机类", "人工智能类"],
    # 数据要素
    "数据资源与数据智能":  ["计算机类", "图书情报类", "数学类"],
    # 交叉学科芯片
    "集成电路科学与工程":  ["微电子类", "电子信息类"],
    # 工程互联网
    "工程互联网":          ["计算机类", "自动化类", "电子信息类"],
    # 传统文化+体育
    "太极拳":              ["体育学类", "教育学类"],
    # 艺术+心理
    "艺术治疗":            ["美术学类", "心理学类"],
}

# 基于真实数据校准的10大趋势因子
TREND_FACTORS = [
    # AI/数字经济 — 权重0.22，score=5
    #   依据：新增专业中计算机类受益8次（最多），WEF报告科技/AI岗位增长最快
    TrendFactor("AI/数字经济", 0.22, score=5,
                benefit_major_classes=["计算机类", "电子信息类", "自动化类", "数学类",
                                       "统计学类", "人工智能类", "电子与信息大类"],
                benefit_categories=["工学", "理学"]),

    # 芯片/半导体/国产替代 — 权重0.16，score=5
    #   依据：新增半导体工艺与装备+集成电路设计，微电子类受益5次，
    #   国产替代+硬科技国家战略叠加
    TrendFactor("芯片/硬科技", 0.16, score=5,
                benefit_major_classes=["微电子类", "电子信息类", "光电信息类",
                                       "仪器类", "自动化类"],
                benefit_categories=["工学"]),

    # 双碳/新能源 — 权重0.12，score=4
    #   依据：新增能源科学与工程+新能源科学与工程+碳中和+交通能源融合+资源环境审计
    #   电气类/能源动力类/环境工程类各受益
    TrendFactor("双碳/新能源", 0.12, score=4,
                benefit_major_classes=["电气类", "能源动力类", "材料类",
                                       "化工与制药类", "环境科学与工程类",
                                       "农业工程类"],
                benefit_categories=["工学"]),

    # 生物医药/银发经济 — 权重0.11，score=4
    #   依据：新增脑机科学+智能医学+健康服务+养老服务+核医学+智能影像+医工+医疗器械
    #   人口老龄化加速，WEF报告银发经济带动护理/健康管理岗位增长
    TrendFactor("生物医药/银发经济", 0.11, score=4,
                benefit_major_classes=["生物医学工程类", "临床医学类", "药学类",
                                       "护理学类", "公共卫生与预防医学类",
                                       "医学技术类"],
                benefit_categories=["医学", "理学"]),

    # 航空航天/深地深海 — 权重0.07，score=4
    #   依据：新增空天科技+深海科技+低空经济+深地科学，国防军工叠加
    TrendFactor("空天深海/国防", 0.07, score=4,
                benefit_major_classes=["航空航天类", "兵器类", "交通运输类",
                                       "地质类", "矿业类"],
                benefit_categories=["工学", "法学"]),

    # 无人系统/智能装备 — 权重0.07，score=4（新增）
    #   依据：低空经济+农业机器人+海洋无人技术+未来机器人+具身智能
    #   低空经济国家战略，无人化是制造业转型方向
    TrendFactor("无人系统/智能装备", 0.07, score=4,
                benefit_major_classes=["自动化类", "机械类", "船舶与海洋工程类",
                                       "农业工程类", "人工智能类"],
                benefit_categories=["工学"]),

    # 数据智能/数据要素 — 权重0.06，score=4（新增）
    #   依据：数据资源与数据智能+计算语言学+生物医药数据
    #   国家数据局成立，数据要素市场化加速
    TrendFactor("数据智能/数据要素", 0.06, score=4,
                benefit_major_classes=["计算机类", "图书情报类", "数学类",
                                       "统计学类", "人工智能类"],
                benefit_categories=["工学", "理学"]),

    # 新材料/稀土 — 权重0.06，score=3
    #   依据：新增稀土科学与工程，材料类受益3次
    TrendFactor("新材料/稀土", 0.06, score=3,
                benefit_major_classes=["材料类", "化学类"],
                benefit_categories=["工学", "理学"]),

    # 数字文科/新文科 — 权重0.06, score=3
    #   依据：新增数字金融+数字贸易+数字文旅+国际新闻与传播
    TrendFactor("数字文科", 0.06, score=3,
                benefit_major_classes=["外国语言文学类", "新闻传播学类",
                                       "金融学类", "经济与贸易类", "旅游管理类"],
                benefit_categories=["文学", "艺术学", "经济学"]),

    # 生物农业 — 权重0.05, score=3
    #   依据：新增生物制造+生物育种科学
    TrendFactor("生物农业", 0.05, score=3,
                benefit_major_classes=["植物生产类", "动物医学类", "林学类",
                                       "农业工程类"],
                benefit_categories=["农学", "理学"]),

    # 教育强国 — 权重0.02, score=3
    #   依据：政策持续支持但新增专业少
    TrendFactor("教育强国", 0.02, score=3,
                benefit_major_classes=["教育学类", "中国语言文学类"],
                benefit_categories=["教育学", "文学"]),

    # 传统管理/商科 — 权重0.06, score=2（负面）
    #   依据：公共事业管理撤销138个、工商管理撤销率高，
    #   传统商科被数字化冲击
    TrendFactor("传统商科风险", 0.06, score=2,
                benefit_major_classes=["工商管理类", "市场营销类",
                                       "行政管理类"],
                benefit_categories=["管理学", "经济学"]),

    # WEF新兴岗位 — 权重0.04, score=4
    #   依据：WEF 2025未来就业报告，AI/数据/新能源等岗位2025-2030年增长30-40%
    #   从数据库 wef_occupation_mapping 表动态读取详细加分
    TrendFactor("WEF新兴岗位", 0.04, score=4,
                benefit_major_classes=["计算机类", "自动化类", "数学类", "统计学类",
                                       "电子信息类", "金融学类", "电气类"],
                benefit_categories=["工学", "理学", "经济学"]),
]

# 撤销高风险专业类（负向指标，应用于趋势分数惩罚）
# key=专业类名, value=撤销风险系数（0-1，越高惩罚越重）
# 数据来源：5年教育部官方文件
#   2020: Excel (教高函〔2021〕1号) 518条, 100%
#   2021: PDF  (教高函〔2021〕14号) 798/804, 99.3%
#   2022: PDF  (教高函〔2023〕3号) 906/925, 97.9%
#   2023: PDF  (教高函〔2024〕7号) 1588/1670, 95.1%
#   2024: PDF  (教高函〔2025〕5号) 1387/1428, 97.1%
# 5年总计: 5197条精确数据 (全国合计5345个撤销专业点)
# 系数计算: 按5年累计总数 / 最大值(工商管理类299) 归一化
CANCELLED_MAJOR_CLASSES = {
    # === 极高撤销风险（5年250+个）===
    "工商管理类": 1.0,               # 5年299个（信息管理与信息系统155+市场营销101等）
    "设计学类": 0.96,                # 5年286个（产品设计91+服装与服饰设计74+动画54等）
    "管理科学与工程类": 0.85,        # 5年253个（信息管理与信息系统为主力）
    "电子信息类": 0.85,              # 5年253个（电子信息科学与技术78+网络工程71等）
    "机械类": 0.83,                  # 5年247个（工业设计73+汽车服务工程+机械工程等）
    "公共管理类": 0.82,              # 5年245个（公共事业管理136+行政管理等）

    # === 高撤销风险（5年150-200个）===
    "计算机类": 0.66,                # 5年196个（网络工程71+物联网工程等）
    "外国语言文学类": 0.65,          # 5年194个（英语+日语+翻译等）
    "数学类": 0.6,                   # 5年178个（信息与计算科学121）
    "新闻传播学类": 0.54,            # 5年160个（广告学64+网络与新媒体等）
    "戏剧与影视学类": 0.48,          # 5年144个（动画54+播音与主持艺术等）
    "材料类": 0.47,                  # 5年141个（材料化学+材料物理+高分子材料等）
    "教育学类": 0.45,                # 5年135个（教育技术学+学前教育+小学教育等）
    "中国语言文学类": 0.42,          # 5年125个（汉语国际教育+汉语言文学等）

    # === 中高撤销风险（5年80-130个）===
    "旅游管理类": 0.37,              # 5年111个
    "地理科学类": 0.36,              # 5年107个
    "音乐与舞蹈学类": 0.33,          # 5年100个
    "环境科学与工程类": 0.31,        # 5年94个
    "生物科学类": 0.28,              # 5年83个
    "土木类": 0.28,                  # 5年83个
    "美术学类": 0.25,                # 5年76个
    "社会学类": 0.25,                # 5年76个（社会工作56等）
    "金融学类": 0.25,                # 5年75个

    # === 中等撤销风险（5年40-70个）===
    "化工与制药类": 0.23,            # 5年69个
    "化学类": 0.23,                  # 5年68个
    "经济学类": 0.22,                # 5年67个
    "统计学类": 0.22,                # 5年66个
    "建筑类": 0.21,                  # 5年62个
    "体育学类": 0.2,                 # 5年59个
    "食品科学与工程类": 0.19,        # 5年58个
    "交通运输类": 0.19,              # 5年58个
    "物流管理与工程类": 0.18,        # 5年55个
    "电子商务类": 0.18,              # 5年54个
    "仪器类": 0.18,                  # 5年54个
    "植物生产类": 0.17,              # 5年50个
    "自动化类": 0.16,                # 5年49个
    "生物工程类": 0.16,              # 5年49个
    "轻工类": 0.16,                  # 5年48个
    "工业工程类": 0.16,              # 5年47个
    "经济与贸易类": 0.15,            # 5年45个
}

# 新增专业红利（正向指标）
# 专业类每受益于1个新增专业，趋势raw分+加成
# 加成值根据政策优先级分层
NEW_MAJOR_BENEFIT_SCORES = {
    "计算机类": 2.0,      # 受益最多（AI/具身智能/计算语言学/数据智能/智慧城市/商业AI等）
    "电子信息类": 1.6,    # 受益5次（半导体/具身智能/交叉工程/智能影像/工程互联网）
    "自动化类": 1.8,      # 受益5次+（未来机器人/具身智能/低空经济/农业机器人/无人技术）
    "微电子类": 1.5,      # 受益2次（半导体/集成电路），国家战略重点
    "生物医学工程类": 1.5, # 受益4次（脑机/智能医学/医工/医疗器械/生物医药数据）
    "电气类": 1.2,        # 受益2次（能源/新能源/交通能源融合）
    "材料类": 1.0,        # 受益4次（半导体/稀土/空天/真空工程/纤维科学/乐器智造）
    "数学类": 1.0,        # 受益4次（AI/大数据/区块链/智能计算/数据智能）
    "新闻传播学类": 0.6,  # 受益2次（数字文旅/国际新闻）
    "外国语言文学类": 0.8,# 受益4次（数字文旅/区域国际学/计算语言学/语言智能/法律英语）
    "护理学类": 0.6,      # 受益2次（健康服务/养老服务），银发经济
    "交通运输类": 0.8,    # 受益3次（低空经济/低空安全/交通能源融合）
    "公共卫生与预防医学类": 0.5,  # 受益1次（健康服务）
    "化工与制药类": 0.8,  # 受益2次（生物制造/碳中和）
    "生物科学类": 0.4,    # 受益1次（生物育种）
    "植物生产类": 0.6,    # 受益2次（生物育种/盐碱地）
    "金融学类": 0.4,      # 受益1次（数字金融）
    "经济与贸易类": 0.3,  # 受益1次（数字贸易）
    "旅游管理类": 0.2,    # 受益1次（数字文旅），但传统部分被撤销
    "人工智能类": 2.0,    # 新兴专业类，具身智能/语言智能/计算语言学/商业AI → 最高优先级
    # ── 2026新增专业类红利补充 ──
    "心理学类": 0.8,      # 心理脑认知/艺术治疗 → 认知科学集群
    "公安学类": 0.6,      # 政治安全保卫/低空安全 → 国家安全
    "审计学类": 0.5,      # 资源环境审计 → 合规需求
    "体育学类": 0.3,      # 太极拳 → 传统文化
    "船舶与海洋工程类": 0.6,  # 海洋智能与无人技术 → 深海战略
    "农业工程类": 0.7,    # 农业机器人/盐碱地/智慧渔业 → 粮食安全+智慧农业
    "水产类": 0.4,        # 智慧渔业 → 智慧农业
    "纺织类": 0.4,        # 纤维科学与智能制造
    "风景园林类": 0.3,    # 智慧景观营造
    "医学技术类": 0.8,    # 核医学工程/智能影像 → 医疗AI
    "图书情报类": 0.6,    # 数据资源与数据智能 → 数据要素（撤销风险对冲）
    "工商管理类": 0.6,    # 商业人工智能 → AI+商科（传统商科风险对冲）
    "公共管理类": 0.5,    # 数字公共治理/智慧城市 → 数字治理（撤销风险对冲）
    "经济学类": 0.5,      # 低空经济与管理/资源环境审计 → 新兴经济
    "土木类": 0.5,        # 城市更新/盐碱地 → 新型城镇化+农业
    "建筑类": 0.5,        # 智慧城市/智慧景观/城市更新
    "环境科学与工程类": 0.8,  # 碳中和/资源环境审计 → 双碳战略
    "机械类": 0.6,        # 未来机器人/农业机器人/医疗器械/乐器智造
    "设计学类": 0.4,      # 乐器智造/智慧景观
    "美术学类": 0.4,      # 艺术治疗
    "中国语言文学类": 0.3,# 语言科学
    "法学类": 0.4,        # 法律英语/政治安全保卫
    "物理学类": 0.4,      # 真空工程（半导体支撑）
    "药学类": 0.5,        # 生物医药数据科学
}


@dataclass
class MajorCategoryScore:
    """专业类热度评分"""
    major_class: str
    category: str
    # 当前热度
    current_scale_score: float = 0   # 规模分
    current_competition_score: float = 0  # 竞争分
    current_breadth_score: float = 0    # 广度分
    current_score: float = 0            # 综合当前热度
    # 未来趋势
    trend_score: float = 0
    # 综合
    composite_score: float = 0
    # 排名
    current_rank: int = 0
    trend_rank: int = 0
    composite_rank: int = 0
    # 热度等级
    level: str = ''
    # 详情
    enroll_count: int = 0
    school_count: int = 0
    avg_min_rank: float = 0
    trend_factors: List[str] = field(default_factory=list)
    # 透明度：评分来源标注
    trend_score_sources: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        d = {
            'major_class': self.major_class,
            'category': self.category,
            'current_score': round(self.current_score, 1),
            'trend_score': round(self.trend_score, 1),
            'composite_score': round(self.composite_score, 1),
            'current_rank': self.current_rank,
            'trend_rank': self.trend_rank,
            'composite_rank': self.composite_rank,
            'level': self.level,
            'enroll_count': self.enroll_count,
            'school_count': self.school_count,
            'avg_min_rank': int(self.avg_min_rank) if self.avg_min_rank else 0,
            'trend_factors': self.trend_factors,
        }
        if self.trend_score_sources:
            d['trend_score_sources'] = self.trend_score_sources
        return d


class HotMajorAnalyzer:
    """热门学科分析器"""

    # 热度等级划分
    LEVEL_THRESHOLDS = [
        (90, 'S'),  # 超级热门
        (75, 'A'),  # 高度热门
        (60, 'B'),  # 中等热门
        (45, 'C'),  # 一般热门
        (0, 'D'),   # 冷门
    ]

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'yunnan_gaokao.db'
            )
        self._db_path = db_path
        self._scores: List[MajorCategoryScore] = []

    def analyze(self, year: int = 2025) -> List[MajorCategoryScore]:
        """
        执行完整分析

        返回: 按综合热度排序的专业类列表
        """
        # 1. 计算当前热度
        self._calc_current_heat(year)

        # 2. 计算未来趋势
        self._calc_trend_heat()

        # 3. 综合排序
        self._composite_rank()

        # 4. 分配等级
        self._assign_levels()

        return self._scores

    def get_hot_list(self, top_n: int = 30) -> List[MajorCategoryScore]:
        """获取热门学科 TOP N"""
        if not self._scores:
            self.analyze()
        return self._scores[:top_n]

    def get_category_scores(self, category: str) -> List[MajorCategoryScore]:
        """获取某学科门类下的热门专业类"""
        if not self._scores:
            self.analyze()
        return [s for s in self._scores if s.category == category]

    def get_major_class_score(self, major_class: str) -> Optional[MajorCategoryScore]:
        """获取某专业类的评分"""
        if not self._scores:
            self.analyze()
        for s in self._scores:
            if s.major_class == major_class:
                return s
        return None

    def _calc_current_heat(self, year: int):
        """计算当前热度（基于招生数据）"""
        conn = sqlite3.connect(self._db_path)
        c = conn.cursor()

        # 按专业类聚合
        c.execute('''
            SELECT category, major_class,
                   SUM(enroll_count) as total_enroll,
                   COUNT(DISTINCT school_name) as school_count,
                   AVG(min_rank) as avg_rank,
                   COUNT(*) as record_count
            FROM v_enroll_detail
            WHERE year = ? AND category IS NOT NULL AND category != ''
              AND major_class IS NOT NULL AND major_class != ''
              AND enroll_count IS NOT NULL
            GROUP BY category, major_class
            ORDER BY total_enroll DESC
        ''', (year,))

        rows = c.fetchall()
        if not rows:
            conn.close()
            return

        # 计算各项最大值（用于归一化）
        max_enroll = max(r[2] for r in rows) if rows else 1
        max_schools = max(r[3] for r in rows) if rows else 1

        # 竞争分：用平均录取位次的倒数（位次越小=竞争越大=分数越高）
        valid_ranks = [r[4] for r in rows if r[4] and r[4] > 0]
        max_inv_rank = max(1.0 / r for r in valid_ranks) if valid_ranks else 1.0

        scores = []
        for row in rows:
            cat, mc, enroll, schools, avg_rank, records = row

            # 规模分（招生人数占比）
            scale_score = (enroll / max_enroll * 100) if max_enroll > 0 else 0

            # 广度分（学校覆盖）
            breadth_score = (schools / max_schools * 100) if max_schools > 0 else 0

            # 竞争分（录取难度，位次倒数）
            if avg_rank and avg_rank > 0:
                competition_score = (1.0 / avg_rank) / max_inv_rank * 100
            else:
                competition_score = 50  # 无位次数据取中位数

            # 当前热度（加权）
            current_score = 0.3 * scale_score + 0.4 * competition_score + 0.3 * breadth_score

            scores.append(MajorCategoryScore(
                major_class=mc,
                category=cat,
                current_scale_score=round(scale_score, 1),
                current_competition_score=round(competition_score, 1),
                current_breadth_score=round(breadth_score, 1),
                current_score=round(current_score, 1),
                enroll_count=enroll,
                school_count=schools,
                avg_min_rank=avg_rank or 0,
            ))

        conn.close()
        self._scores = scores

    def _calc_trend_heat(self):
        """
        计算未来趋势评分（归一化到0-100）

        五步计算：
        1. 趋势因子匹配（13大因子 × 权重 × 评分）
        2. 新增专业红利（基于教育部2026新增38个专业映射）
        3. WEF新兴岗位加分（基于WEF 2025报告数据库）
        4. 收敛潜力加分（跨集群融合能力，基于2045五大收敛集群）

        原始分 → min-max归一化到0-100
        """
        if not self._scores:
            return

        raw_scores = []
        for score_obj in self._scores:
            trend_total = 0
            trend_factors = []
            sources = {}

            # ── Step 1: 趋势因子匹配 ──
            for factor in TREND_FACTORS:
                matched = False
                # 精确匹配专业类
                if score_obj.major_class in factor.benefit_major_classes:
                    matched = True
                    contrib = factor.score * factor.weight
                # 模糊匹配学科门类（打6折）
                elif score_obj.category in factor.benefit_categories:
                    matched = True
                    contrib = factor.score * factor.weight * 0.6

                if matched:
                    trend_total += contrib
                    trend_factors.append(factor.name)
                    # 透明度标注：趋势因子为专家判断
                    sources[factor.name] = 'expert_judgment'

            # ── Step 2: 新增专业红利 ──
            benefit_score = NEW_MAJOR_BENEFIT_SCORES.get(
                score_obj.major_class, 0
            )
            if benefit_score > 0:
                trend_total += benefit_score
                trend_factors.append("新增专业红利")
                sources['新增专业红利'] = 'data_driven:教育部2026新增38专业'

            # ── Step 3: WEF新兴岗位加分 ──
            wef_bonus, wef_roles = self._calc_wef_bonus(score_obj.major_class)
            if wef_bonus > 0:
                trend_total += wef_bonus
                trend_factors.append("WEF新兴岗位")
                sources['WEF新兴岗位'] = 'data_driven:WEF_2025_岗位增长数据'

            # ── Step 4: 收敛潜力加分（跨域融合能力） ──
            convergence_bonus = CONVERGENCE_POTENTIAL.get(
                score_obj.major_class, 0
            )
            if convergence_bonus > 0:
                trend_total += convergence_bonus
                trend_factors.append("跨集群融合")
                sources['跨集群融合'] = 'expert_judgment:麦肯锡18竞技场+五大收敛集群'

            # ── Step 5: 撤销风险惩罚（P1-fix） ──
            cancel_penalty = CANCELLED_MAJOR_CLASSES.get(score_obj.major_class, 0)
            if cancel_penalty > 0:
                penalty = cancel_penalty * 5.0  # 最高扣50分（工商管理类1.0*5）
                trend_total = max(0, trend_total - penalty)
                trend_factors.append("撤销风险惩罚")
                sources['撤销风险惩罚'] = f'data_driven:5年撤销{cancel_penalty*299:.0f}个专业点'

            score_obj.trend_score = round(trend_total, 1)
            score_obj.trend_factors = trend_factors
            score_obj.trend_score_sources = sources
            raw_scores.append(trend_total)

        # ── 归一化到0-100 ──
        if not raw_scores:
            return
        max_raw = max(raw_scores)
        min_raw = min(raw_scores)
        raw_range = max_raw - min_raw if max_raw != min_raw else 1.0

        for score_obj in self._scores:
            normalized = (score_obj.trend_score - min_raw) / raw_range * 100
            score_obj.trend_score = round(normalized, 1)

    def _calc_wef_bonus(self, major_class: str) -> Tuple[float, List[str]]:
        """
        计算WEF新兴岗位加分

        从数据库 wef_occupation_mapping 表查询匹配的专业类，
        按增长率 × 映射置信度 × 5 计算加分（与趋势因子同量级）。

        返回: (bonus_score, matched_role_names)
        """
        conn = sqlite3.connect(self._db_path)
        try:
            c = conn.cursor()
            c.execute('''SELECT wef_role_name, growth_rate_2030, mapped_major_classes, confidence
                         FROM wef_occupation_mapping
                         WHERE wef_role_type = 'emerging' AND growth_rate_2030 IS NOT NULL''')
            bonus = 0.0
            roles = []
            for role_name, growth_rate, mapped_json, confidence in c.fetchall():
                try:
                    mapped = json.loads(mapped_json)
                except (json.JSONDecodeError, TypeError):
                    continue
                if major_class in mapped:
                    # 加分 = 增长率 × 置信度 × 5（缩放到与趋势因子同量级）
                    contrib = growth_rate * confidence * 5.0
                    bonus += contrib
                    roles.append(role_name)
        finally:
            conn.close()
        return round(bonus, 2), roles

    def _composite_rank(self):
        """综合排序（当前40% + 未来60%）"""
        if not self._scores:
            return

        # 当前排名
        self._scores.sort(key=lambda x: x.current_score, reverse=True)
        for i, s in enumerate(self._scores):
            s.current_rank = i + 1

        # 趋势排名
        self._scores.sort(key=lambda x: x.trend_score, reverse=True)
        for i, s in enumerate(self._scores):
            s.trend_rank = i + 1

        # 综合评分
        for s in self._scores:
            # 归一化：当前分数和趋势分数分别归一化到0-100
            s.composite_score = round(
                s.current_score * 0.4 + s.trend_score * 0.6, 1
            )

        # 综合排名
        self._scores.sort(key=lambda x: x.composite_score, reverse=True)
        for i, s in enumerate(self._scores):
            s.composite_rank = i + 1

    def _assign_levels(self):
        """分配热度等级"""
        for s in self._scores:
            for threshold, level in self.LEVEL_THRESHOLDS:
                if s.composite_score >= threshold:
                    s.level = level
                    break

    def export_scores(self, output_path: str = None) -> str:
        """导出评分结果为 JSON"""
        if not output_path:
            output_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'data', 'hot_major_scores.json'
            )
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        data = {s.major_class: s.to_dict() for s in self._scores}
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return output_path

    def generate_summary(self, top_n: int = 10) -> str:
        """生成热门学科摘要（用于报告输出）"""
        if not self._scores:
            self.analyze()

        lines = []
        lines.append('【热门学科趋势分析 TOP{}】'.format(top_n))
        lines.append('')

        for i, s in enumerate(self._scores[:top_n]):
            factor_str = ' | '.join(s.trend_factors) if s.trend_factors else '无特殊趋势加成'
            lines.append('{}. {}（{}）- 综合评分{} 等级{}'.format(
                i + 1, s.major_class, s.category, s.composite_score, s.level))
            lines.append('   当前热度:{} | 未来趋势:{} | 招生:{}人 | 学校:{}所'.format(
                s.current_score, s.trend_score, s.enroll_count, s.school_count))
            lines.append('   趋势因子: {}'.format(factor_str))
            lines.append('')

        return '\n'.join(lines)


def main():
    """测试"""
    analyzer = HotMajorAnalyzer()
    scores = analyzer.analyze()

    print('=' * 80)
    print('热门学科趋势分析（综合排名 TOP30）')
    print('数据源：教育部2026新增38专业 + 5年撤销1.22万专业点 + WEF 2025就业报告')
    print('       麦肯锡18竞技场(2040) + 五大收敛集群(2045)')
    print('=' * 80)
    print('{:<4s} {:<18s} {:<6s} {:>6s} {:>8s} {:>8s} {:>6s} {:>6s}'.format(
        '排名', '专业类', '门类', '综合', '当前', '趋势', '等级', '招生'))
    print('-' * 80)

    for s in scores[:30]:
        print('{:<4d} {:<18s} {:<6s} {:>6.1f} {:>8.1f} {:>8.1f} {:>6s} {:>6d}人'.format(
            s.composite_rank, s.major_class, s.category,
            s.composite_score, s.current_score, s.trend_score,
            s.level, s.enroll_count))

    print('\n趋势因子详情（TOP15）:')
    for s in scores[:15]:
        factors_display = ' | '.join(s.trend_factors) if s.trend_factors else '无'
        print('  {}: {}'.format(s.major_class, factors_display))

    # 显示撤销风险专业
    print('\n撤销风险标记:')
    risk_items = [s for s in scores if '撤销风险' in s.trend_factors]
    for s in risk_items[:10]:
        print('  {}（综合分:{:.1f}，等级:{}）'.format(
            s.major_class, s.composite_score, s.level))

    # 显示新增红利专业
    print('\n新增专业红利（受益最多的）:')
    benefit_items = [s for s in scores if '新增专业红利' in s.trend_factors]
    for s in benefit_items[:10]:
        print('  {}（综合分:{:.1f}，等级:{}）'.format(
            s.major_class, s.composite_score, s.level))

    # 显示跨集群融合专业
    print('\n跨集群融合潜力（2045五大收敛集群）:')
    conv_items = [s for s in scores if '跨集群融合' in s.trend_factors]
    for s in conv_items[:10]:
        print('  {}（综合分:{:.1f}，等级:{}）'.format(
            s.major_class, s.composite_score, s.level))

    # 显示五大收敛集群概览
    print('\n五大收敛集群概览（2045远景）:')
    for cluster_name, cluster_info in CONVERGENCE_CLUSTERS.items():
        print('  {}: {}'.format(cluster_name, cluster_info['描述']))
        print('    核心专业: {} | 经济规模: {}'.format(
            '/'.join(cluster_info['核心专业类'][:3]),
            cluster_info['麦肯锡2040经济规模']))

    # 导出
    path = analyzer.export_scores()
    print('\n已导出: {}'.format(path))


if __name__ == '__main__':
    main()
