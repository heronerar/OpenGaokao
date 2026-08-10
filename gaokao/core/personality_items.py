# SPDX-License-Identifier: LicenseRef-OpenGaokao-SAL-1.0
# Copyright (C) 2026 OpenGaokao Contributors
"""项目自编大五维度问卷 + RIASEC 风格兴趣问卷题目单一真源 — AUDIT-P0-011

设计原则：
- 50 + 76 题的"题目编号 → 题面"映射集中在此文件，避免问卷 JSON 与
  questionnaire_parser / personality_test 之间编号漂移。
- 题目编号严格对齐 `personality_test.PersonalityTestEngine.BIG_FIVE`
  与 `personality_test.RIASEC_PAIRS` 的题号定义。
- 物理类与历史类共享同一套问卷（偏好维度与科类无关）。
- 题面用学生友好的中文表述，控制在 20 字左右，避免影响作答信度。
- 反向计分题目（BIG_FIVE 的 '反向' 列表）需要在题面上保持自然，
  否则反向计分会失真；本文件以 IS_REVERSE 标记。

这些题面由项目自编，未经心理测量学验证，不是标准化心理量表，也不作诊断。
"""
from typing import Dict, List, Tuple

# ────────────────────────────────────────────────────────────
# 项目自编大五维度问卷（50 题）
# ────────────────────────────────────────────────────────────
# 维度: O 开放性 / C 尽责性 / E 外向性 / A 宜人性 / N 神经质
# 每维度 10 题（8 正向 + 2 反向），共 50 题
# 编号严格对齐 personality_test.PersonalityTestEngine.BIG_FIVE 配置

BIG_FIVE_ITEMS: Dict[int, Dict] = {
    # ── 开放性 O (1-10) ──
    1:  {'dim': 'O', 'reverse': False, 'text': '我喜欢探索新想法和不同的看法'},
    2:  {'dim': 'O', 'reverse': False, 'text': '艺术、音乐或文学常常打动我'},
    3:  {'dim': 'O', 'reverse': False, 'text': '我愿意尝试不熟悉的食物或体验'},
    4:  {'dim': 'O', 'reverse': False, 'text': '我对哲学或抽象议题感兴趣'},
    5:  {'dim': 'O', 'reverse': False, 'text': '我喜欢动手尝试解决新问题'},
    6:  {'dim': 'O', 'reverse': False, 'text': '我喜欢思考"如果换一种做法会怎样"'},
    7:  {'dim': 'O', 'reverse': True,  'text': '我更喜欢按惯例做事，避免变动'},
    8:  {'dim': 'O', 'reverse': True,  'text': '抽象的话题对我来说没有吸引力'},
    9:  {'dim': 'O', 'reverse': False, 'text': '我会主动了解不同文化或行业的知识'},
    10: {'dim': 'O', 'reverse': False, 'text': '我喜欢创造性的活动（写作/设计/艺术等）'},

    # ── 尽责性 C (11-20) ──
    11: {'dim': 'C', 'reverse': False, 'text': '我会把任务彻底完成，不留尾巴'},
    12: {'dim': 'C', 'reverse': False, 'text': '我倾向于提前规划而不是临时应对'},
    13: {'dim': 'C', 'reverse': False, 'text': '我重视秩序，物品归位让我安心'},
    14: {'dim': 'C', 'reverse': False, 'text': '我守时，承诺的事会按期完成'},
    15: {'dim': 'C', 'reverse': False, 'text': '面对长远目标我能保持耐心和坚持'},
    16: {'dim': 'C', 'reverse': True,  'text': '我容易拖延或半途而废'},
    17: {'dim': 'C', 'reverse': False, 'text': '我做决定前喜欢权衡利弊'},
    18: {'dim': 'C', 'reverse': True,  'text': '我有时会忽略细节、马虎处理'},
    19: {'dim': 'C', 'reverse': False, 'text': '我能严格自律，控制冲动'},
    20: {'dim': 'C', 'reverse': False, 'text': '我倾向于按计划行事，按部就班'},

    # ── 外向性 E (21-30) ──
    21: {'dim': 'E', 'reverse': False, 'text': '我喜欢和很多人一起参加活动'},
    22: {'dim': 'E', 'reverse': False, 'text': '在群体中我容易主动开口、活跃气氛'},
    23: {'dim': 'E', 'reverse': False, 'text': '我精力充沛，喜欢忙碌的节奏'},
    24: {'dim': 'E', 'reverse': False, 'text': '我容易结识新朋友'},
    25: {'dim': 'E', 'reverse': False, 'text': '我喜欢成为团队中受关注的人'},
    26: {'dim': 'E', 'reverse': False, 'text': '社交活动会让我感到充电而不是疲惫'},
    27: {'dim': 'E', 'reverse': True,  'text': '我更喜欢独处或小范围交流'},
    28: {'dim': 'E', 'reverse': True,  'text': '在陌生场合我会显得比较安静'},
    29: {'dim': 'E', 'reverse': False, 'text': '我习惯先表达想法，再细致斟酌'},
    30: {'dim': 'E', 'reverse': False, 'text': '我喜欢热闹、节奏快的环境'},

    # ── 宜人性 A (31-40) ──
    31: {'dim': 'A', 'reverse': False, 'text': '我习惯先体谅别人的处境'},
    32: {'dim': 'A', 'reverse': False, 'text': '我相信大多数人本质上是善意的'},
    33: {'dim': 'A', 'reverse': False, 'text': '我愿意帮别人，即使没有回报'},
    34: {'dim': 'A', 'reverse': False, 'text': '面对冲突我倾向于先寻求和解'},
    35: {'dim': 'A', 'reverse': False, 'text': '我会主动让步以维护团队和谐'},
    36: {'dim': 'A', 'reverse': False, 'text': '我对他人的情绪比较敏感'},
    37: {'dim': 'A', 'reverse': True,  'text': '我对别人会保持戒备和怀疑'},
    38: {'dim': 'A', 'reverse': True,  'text': '我倾向于直接指出对方的问题'},
    39: {'dim': 'A', 'reverse': False, 'text': '我能耐心倾听别人的倾诉'},
    40: {'dim': 'A', 'reverse': False, 'text': '我重视集体利益高于个人喜好'},

    # ── 神经质 N (41-50) ──
    41: {'dim': 'N', 'reverse': False, 'text': '我容易感到紧张或焦虑'},
    42: {'dim': 'N', 'reverse': False, 'text': '我的情绪起伏比较明显'},
    43: {'dim': 'N', 'reverse': False, 'text': '小事也会让我心烦很久'},
    44: {'dim': 'N', 'reverse': False, 'text': '我经常担心事情会出错'},
    45: {'dim': 'N', 'reverse': False, 'text': '压力大时我容易感到无力'},
    46: {'dim': 'N', 'reverse': False, 'text': '别人的批评会让我难过较长时间'},
    47: {'dim': 'N', 'reverse': True,  'text': '即使遇到困难我也能保持冷静'},
    48: {'dim': 'N', 'reverse': True,  'text': '我能很快从负面情绪中恢复'},
    49: {'dim': 'N', 'reverse': False, 'text': '我有时会无来由地情绪低落'},
    50: {'dim': 'N', 'reverse': False, 'text': '面对未知我容易感到不安'},
}

# ────────────────────────────────────────────────────────────
# 项目自编 RIASEC 风格兴趣偏好问卷（76 题，迫选 A/B）
# ────────────────────────────────────────────────────────────
# 维度: R 实际型 / I 研究型 / A 艺术型 / S 社会型 / E 企业型 / C 常规型
# 13 组配对，每组 6-7 题，编号严格对齐 personality_test.RIASEC_PAIRS

# 各维度的代表性活动描述池（用于自动生成 A/B 题面）
_RIASEC_ACTIVITIES: Dict[str, List[str]] = {
    'R': [
        '动手维修机械或电子设备', '在户外实地操作', '使用工具完成具体任务',
        '把零件组装成完整产品', '操控仪器或设备完成任务', '从事需要体力或动手能力的工作',
        '处理具体可见的成果', '参与工程实施而非纸面方案', '钻研机械原理并实际试验',
        '搭建实物模型而非只画图', '在生产/制造现场工作', '修理日常物品让它继续可用',
    ],
    'I': [
        '探究自然规律并提出假说', '解一道复杂的数学题', '查阅资料分析现象的成因',
        '设计实验验证一个想法', '阅读学术论文获取新知', '在数据中寻找规律',
        '推理一道逻辑题', '深入研究某个理论问题', '钻研未解决的科学难题',
        '用模型解释复杂现象', '为问题构建分析框架', '把现象抽象成原理',
    ],
    'A': [
        '创作绘画、音乐或文学作品', '设计独特的视觉作品', '编排一段舞台表演',
        '为产品做创意设计', '用文字表达自己的情感', '探索新颖的艺术风格',
        '即兴演奏或表演', '为活动设计创意主题', '通过作品传达想法',
        '尝试不同媒介进行创作', '改编经典作品赋予新意', '设计图书或海报的视觉风格',
    ],
    'S': [
        '帮助同学解决学习困难', '倾听他人的烦恼并给出建议', '志愿参与社区或公益活动',
        '辅导小朋友功课', '组织一次面向他人的活动', '关心朋友的情绪并陪伴',
        '为他人讲解知识', '在团体中协调成员关系', '为新成员提供入门指引',
        '陪伴老人或患者', '在心理咨询场景中提供支持', '通过教育影响他人成长',
    ],
    'E': [
        '召集团队并分工合作', '在辩论或谈判中说服他人', '组织一次有目标的活动',
        '推广一个项目或产品', '领导团队完成挑战', '在商业谈判中争取共识',
        '为团队设定明确目标', '面向公众发表演讲', '在比赛中担任队长',
        '为创业项目寻找资源', '处理团队内部的冲突', '在不确定环境中拍板决策',
    ],
    'C': [
        '整理数据并制作清晰报表', '按流程精确完成事务性工作', '维护账目让收支清楚',
        '把杂乱信息分类归档', '按既定规则核对资料', '为活动制定流程清单',
        '检查文件中的细节错误', '建立条理化的记录系统', '执行重复但精确的核对工作',
        '按规章制度处理事务', '把项目分解为可执行步骤', '审核数据并标记异常',
    ],
}


def _holland_text(dim_letter: str, idx_in_pool: int) -> str:
    """从维度活动池中按索引取题面，循环复用避免重复。"""
    pool = _RIASEC_ACTIVITIES[dim_letter]
    return pool[idx_in_pool % len(pool)]


# RIASEC_PAIRS 引自 personality_test.py，本文件需保持同步
_RIASEC_PAIRS_LOCAL: Dict[int, Tuple[str, str]] = {
    1: ('R', 'I'), 2: ('R', 'I'), 3: ('R', 'I'), 4: ('R', 'I'),
    5: ('R', 'I'), 6: ('R', 'I'), 7: ('R', 'I'),
    8: ('A', 'S'), 9: ('A', 'S'), 10: ('A', 'S'), 11: ('A', 'S'),
    12: ('A', 'S'), 13: ('A', 'S'),
    14: ('E', 'C'), 15: ('E', 'C'), 16: ('E', 'C'), 17: ('E', 'C'),
    18: ('E', 'C'), 19: ('E', 'C'),
    20: ('R', 'A'), 21: ('R', 'A'), 22: ('R', 'A'), 23: ('R', 'A'),
    24: ('R', 'A'), 25: ('R', 'A'),
    26: ('I', 'E'), 27: ('I', 'E'), 28: ('I', 'E'), 29: ('I', 'E'),
    30: ('I', 'E'), 31: ('I', 'E'),
    32: ('S', 'C'), 33: ('S', 'C'), 34: ('S', 'C'), 35: ('S', 'C'),
    36: ('S', 'C'), 37: ('S', 'C'),
    38: ('R', 'S'), 39: ('R', 'S'), 40: ('R', 'S'), 41: ('R', 'S'),
    42: ('R', 'S'), 43: ('R', 'S'),
    44: ('I', 'A'), 45: ('I', 'A'), 46: ('I', 'A'), 47: ('I', 'A'),
    48: ('I', 'A'), 49: ('I', 'A'),
    50: ('E', 'R'), 51: ('E', 'R'), 52: ('E', 'R'), 53: ('E', 'R'),
    54: ('E', 'R'), 55: ('E', 'R'),
    56: ('C', 'I'), 57: ('C', 'I'), 58: ('C', 'I'), 59: ('C', 'I'),
    60: ('C', 'I'), 61: ('C', 'I'),
    62: ('A', 'E'), 63: ('A', 'E'), 64: ('A', 'E'), 65: ('A', 'E'),
    66: ('A', 'E'), 67: ('A', 'E'),
    68: ('S', 'R'), 69: ('S', 'R'), 70: ('S', 'R'), 71: ('S', 'R'),
    72: ('S', 'R'), 73: ('S', 'R'),
    74: ('C', 'A'), 75: ('C', 'A'), 76: ('C', 'A'),
}


def _build_holland_items() -> Dict[int, Dict]:
    """根据 RIASEC_PAIRS 生成 76 道迫选题（A/B 题面 + 维度标签）。"""
    items: Dict[int, Dict] = {}
    # 各维度被用作 A/B 的累计计数，用于在池中循环取不同活动
    cnt: Dict[str, int] = {d: 0 for d in 'RIASEC'}
    for q_no, (a_dim, b_dim) in sorted(_RIASEC_PAIRS_LOCAL.items()):
        a_text = _holland_text(a_dim, cnt[a_dim])
        b_text = _holland_text(b_dim, cnt[b_dim])
        cnt[a_dim] += 1
        cnt[b_dim] += 1
        items[q_no] = {
            'a_dim': a_dim, 'b_dim': b_dim,
            'a_text': a_text, 'b_text': b_text,
        }
    return items


HOLLAND_ITEMS: Dict[int, Dict] = _build_holland_items()


# ────────────────────────────────────────────────────────────
# 问卷 JSON 题目 ID 命名规范
# ────────────────────────────────────────────────────────────
# 与现有 q1-q124 的"全局编号"分离，避免影响既有题号。
# 大五:   bf01..bf50
# RIASEC 风格兴趣偏好: h01..h76（兼容既有 ID）

def big_five_question_id(local_no: int) -> str:
    return f'bf{local_no:02d}'


def holland_question_id(local_no: int) -> str:
    return f'h{local_no:02d}'


# ────────────────────────────────────────────────────────────
# 校验：编号一致性（启动时调用）
# ────────────────────────────────────────────────────────────

def assert_items_consistent_with_engine():
    """启动期断言：题目编号与 personality_test 引擎配置一致。

    引擎读取的题号必须在本文件中存在，否则问卷维度会静默跳过。
    """
    from .personality_test import (
        PersonalityTestEngine, RIASEC_PAIRS as _ENGINE_RIASEC,
    )
    # 项目自编大五维度问卷
    for dim, qs in PersonalityTestEngine.BIG_FIVE.items():
        for q in qs['正向'] + qs['反向']:
            assert q in BIG_FIVE_ITEMS, (
                f'大五维度题号 {q} (维度 {dim}) 在 personality_items.py 中缺失'
            )
    # RIASEC 风格兴趣偏好（HOLLAND_ITEMS 为兼容既有接口保留）
    for q_no, (a, b) in _ENGINE_RIASEC.items():
        assert q_no in HOLLAND_ITEMS, f'RIASEC 风格题号 {q_no} 在 personality_items.py 中缺失'
        item = HOLLAND_ITEMS[q_no]
        assert (item['a_dim'], item['b_dim']) == (a, b), (
            f'RIASEC 风格题号 {q_no} 配对不一致：items={item["a_dim"]}/{item["b_dim"]} '
            f'vs engine={a}/{b}'
        )
    return True


if __name__ == '__main__':
    assert_items_consistent_with_engine()
    print(f'项目自编大五维度问卷: {len(BIG_FIVE_ITEMS)} 题')
    print(f'项目自编 RIASEC 风格兴趣偏好问卷: {len(HOLLAND_ITEMS)} 题')
    print('提示：未经心理测量学验证，不作诊断')
    print('一致性校验通过')
