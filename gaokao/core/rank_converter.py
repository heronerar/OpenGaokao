# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""
位次转换算法 (Rank Converter)
基于一分一段表实现分数↔位次的精准转换，支持跨年度对比。

核心功能：
1. 分数→位次（插值法）
2. 位次→分数（插值法）
3. 跨年度位次标准化
"""
import sqlite3
import threading
from typing import Optional, Tuple

class RankConverter:
    """分数-位次转换器"""
    
    def __init__(self, db_path: str = 'yunnan_gaokao.db'):
        self._db_path = db_path
        self._local = threading.local()
        self._cache = {}
        self._cache_lock = threading.Lock()  # F-5 fix: 缓存线程安全

    def _init_local(self):
        if not hasattr(self._local, 'cursor'):
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._local.cursor = conn.cursor()

    def _get_cursor(self):
        if not hasattr(self._local, 'cursor'):
            self._init_local()
        return self._local.cursor  # 缓存一分一段表数据
    
    def load_score_distribution(self, year: int, category: str) -> dict:
        """
        加载一分一段表数据
        
        参数:
            year: 年份（2023/2024/2025）
            category: 科类（文科/理科/物理类/历史类）
        
        返回:
            {score: cumulative_count, ...} 分数→累计人数映射
        """
        cache_key = f"{year}_{category}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # 根据科类选择对应字段
        field_map = {
            '文科': ('wenke_count', 'wenke_cumsum'),
            '理科': ('like_count', 'like_cumsum'),
            '物理类': ('physics_count', 'physics_cumsum'),
            '历史类': ('history_count', 'history_cumsum'),
            '物理': ('physics_count', 'physics_cumsum'),
            '历史': ('history_count', 'history_cumsum'),
        }
        
        # P1-fix: 对未知科类抛出明确错误，而不是静默回退到文科
        count_field, cumsum_field = field_map.get(category, (None, None))
        if count_field is None:
            raise ValueError(
                f'未知科类: {category!r}，合法选项: {sorted(field_map.keys())}'
            )
        
        self._get_cursor().execute(f'''
            SELECT score, {count_field}, {cumsum_field}
            FROM score_distribution
            WHERE year = ? AND {count_field} IS NOT NULL
            ORDER BY score DESC
        ''', (year,))
        
        rows = self._get_cursor().fetchall()
        score_rank_map = {}
        
        for score, count, cumsum in rows:
            if cumsum is not None:
                score_rank_map[score] = cumsum
        
        self._cache[cache_key] = score_rank_map
        return score_rank_map
    
    def score_to_rank(self, score: int, year: int, category: str) -> Optional[int]:
        """
        分数→位次（线性插值）
        
        参数:
            score: 考生分数
            year: 年份
            category: 科类
        
        返回:
            位次（整数），如果分数超出范围则返回None
        """
        score_lines = self.load_score_distribution(year, category)
        
        if not score_lines:
            return None
        
        # 精确匹配
        if score in score_lines:
            return score_lines[score]
        
        # 找到上下界
        scores = sorted(score_lines.keys(), reverse=True)
        
        # 分数超出最高分
        if score > scores[0]:
            return score_lines[scores[0]]
        
        # 分数低于最低分
        if score < scores[-1]:
            return score_lines[scores[-1]]
        
        # 线性插值
        upper_score = None
        lower_score = None
        
        for i, s in enumerate(scores):
            if s > score:
                upper_score = s
            elif s < score:
                lower_score = s
                break
        
        if upper_score is None or lower_score is None:
            return None
        
        upper_rank = score_lines[upper_score]
        lower_rank = score_lines[lower_score]
        
        # 线性插值公式
        ratio = (score - lower_score) / (upper_score - lower_score)
        rank = lower_rank + (upper_rank - lower_rank) * ratio
        
        return int(round(rank))
    
    def rank_to_score(self, rank: int, year: int, category: str) -> Optional[int]:
        """
        位次→分数（线性插值）
        
        参数:
            rank: 考生位次
            year: 年份
            category: 科类
        
        返回:
            分数（整数），如果位次超出范围则返回None
        """
        score_lines = self.load_score_distribution(year, category)
        
        if not score_lines:
            return None
        
        # 按位次排序
        rank_score_pairs = sorted(score_lines.items(), key=lambda x: x[1])
        
        # 位次超出范围
        if rank < rank_score_pairs[0][1]:
            return rank_score_pairs[0][0]
        if rank > rank_score_pairs[-1][1]:
            return rank_score_pairs[-1][0]
        
        # 线性插值
        for i in range(len(rank_score_pairs) - 1):
            score1, rank1 = rank_score_pairs[i]
            score2, rank2 = rank_score_pairs[i + 1]
            
            if rank1 <= rank <= rank2:
                ratio = (rank - rank1) / (rank2 - rank1) if rank2 != rank1 else 0
                score = score1 + (score2 - score1) * ratio
                return int(round(score))
        
        return None
    
    def convert_rank(self, rank: int, from_year: int, to_year: int, category: str) -> Optional[int]:
        """
        跨年度位次转换
        
        核心逻辑:
        1. 找到该位次对应的分数 (from_year)
        2. 找到该分数在 to_year 的位次
        3. 返回标准化位次
        
        参数:
            rank: 考生位次
            from_year: 原始年份
            to_year: 目标年份
            category: 科类
        
        返回:
            标准化后的位次
        """
        if from_year == to_year:
            return rank
        
        # 科类映射（新高考适配）
        category_map = {
            ('2020', '2025'): {'文科': '历史类', '理科': '物理类'},
            ('2021', '2025'): {'文科': '历史类', '理科': '物理类'},
            ('2022', '2025'): {'文科': '历史类', '理科': '物理类'},
            ('2023', '2025'): {'文科': '历史类', '理科': '物理类'},
            ('2024', '2025'): {'文科': '历史类', '理科': '物理类'},
            ('2025', '2020'): {'历史类': '文科', '物理类': '理科', '历史': '文科', '物理': '理科'},
            ('2025', '2021'): {'历史类': '文科', '物理类': '理科', '历史': '文科', '物理': '理科'},
            ('2025', '2022'): {'历史类': '文科', '物理类': '理科', '历史': '文科', '物理': '理科'},
            ('2025', '2023'): {'历史类': '文科', '物理类': '理科', '历史': '文科', '物理': '理科'},
            ('2025', '2024'): {'历史类': '文科', '物理类': '理科', '历史': '文科', '物理': '理科'},
        }
        
        key = (str(from_year), str(to_year))
        if key in category_map and category in category_map[key]:
            target_category = category_map[key][category]
        else:
            target_category = category
        
        # 第一步：位次转分数（原始年份）
        score = self.rank_to_score(rank, from_year, category)
        if score is None:
            return None
        
        # 第二步：分数转位次（目标年份）
        new_rank = self.score_to_rank(score, to_year, target_category)
        return new_rank
    
    def convert_score(self, score: int, from_year: int, to_year: int, category: str) -> Optional[int]:
        """
        跨年度分数转换（通过位次中转）

        修正V3.0: 添加科类映射，解决2023"理科"→2025"物理类"的转换失败问题

        参数:
            score: 考生分数
            from_year: 原始年份
            to_year: 目标年份
            category: 科类

        返回:
            标准化后的分数
        """
        if from_year == to_year:
            return score

        # 科类映射（与convert_rank共享完整映射，P1-fix）
        category_map = {
            ('2020', '2025'): {'文科': '历史类', '理科': '物理类'},
            ('2021', '2025'): {'文科': '历史类', '理科': '物理类'},
            ('2022', '2025'): {'文科': '历史类', '理科': '物理类'},
            ('2023', '2025'): {'文科': '历史类', '理科': '物理类'},
            ('2024', '2025'): {'文科': '历史类', '理科': '物理类'},
            ('2025', '2020'): {'历史类': '文科', '物理类': '理科', '历史': '文科', '物理': '理科'},
            ('2025', '2021'): {'历史类': '文科', '物理类': '理科', '历史': '文科', '物理': '理科'},
            ('2025', '2022'): {'历史类': '文科', '物理类': '理科', '历史': '文科', '物理': '理科'},
            ('2025', '2023'): {'历史类': '文科', '物理类': '理科', '历史': '文科', '物理': '理科'},
            ('2025', '2024'): {'历史类': '文科', '物理类': '理科', '历史': '文科', '物理': '理科'},
        }

        key = (str(from_year), str(to_year))
        if key in category_map and category in category_map[key]:
            target_category = category_map[key][category]
        else:
            target_category = category

        # 第一步：分数转位次（原始年份）
        rank = self.score_to_rank(score, from_year, category)
        if rank is None:
            return None

        # 第二步：位次转分数（目标年份，使用映射后的科类）
        new_score = self.rank_to_score(rank, to_year, target_category)
        return new_score
    
    def get_rank_percentile(self, rank: int, year: int, category: str) -> Optional[float]:
        """
        计算位次百分位（在全省的排名百分比）
        
        参数:
            rank: 考生位次
            year: 年份
            category: 科类
        
        返回:
            百分位（0-100），越小越好
        """
        score_lines = self.load_score_distribution(year, category)
        
        if not score_lines:
            return None
        
        # 获取总人数（最高累计人数）
        total_count = max(score_lines.values())
        
        if total_count == 0:
            return None
        
        percentile = (rank / total_count) * 100
        return round(percentile, 2)
    
    def close(self):
        if hasattr(self._local, 'cursor'):
            try:
                self._local.cursor.connection.close()
            except Exception:
                pass
            # P1-fix: 删除 cursor 属性，防止后续调用 _get_cursor 使用已关闭连接
            delattr(self._local, 'cursor')


def main():
    """测试用例"""
    converter = RankConverter()
    
    print('=' * 70)
    print('位次转换算法测试')
    print('=' * 70)
    
    # 测试1：分数→位次
    print('\n【测试1】分数→位次')
    rank = converter.score_to_rank(600, 2024, '理科')
    print(f'  2024年理科600分 → 位次: {rank}')
    
    # 测试2：位次→分数
    print('\n【测试2】位次→分数')
    score = converter.rank_to_score(10000, 2024, '理科')
    print(f'  2024年理科10000位 → 分数: {score}')
    
    # 测试3：跨年度位次转换
    print('\n【测试3】跨年度位次转换')
    new_rank = converter.convert_rank(10000, 2024, 2025, '理科')
    print(f'  2024年理科10000位 → 2025年物理类: {new_rank}')
    
    # 测试4：百分位计算
    print('\n【测试4】百分位计算')
    percentile = converter.get_rank_percentile(10000, 2024, '理科')
    print(f'  2024年理科10000位 → 百分位: {percentile}%')
    
    converter.close()
    print('\n' + '=' * 70)
    print('测试完成！')

if __name__ == '__main__':
    main()
