# 贡献新省份

OpenGaokao 的省份支持通过 YAML 配置文件实现。贡献新省份**不需要写 Python 代码**。

## 快速开始（5分钟）

### 1. 复制模板

```bash
cp -r provinces/_template provinces/{your_province}
```

### 2. 修改 `provinces/{your_province}/province.yaml`

必填字段：

```yaml
name: "XX省"
slug: "xx"                    # 小写英文，如 "sichuan"
gaokao_mode: "3+1+2"         # 3+1+2 / 3+3 / 文理分科
volunteer_mode: "group"      # group(院校专业组) / major(专业+院校) / old(旧高考)
reform_year: 2025            # 新高考改革年份
```

关键配置项：

| 配置 | 说明 |
|------|------|
| `batches` | 批次设置：提前批、本科批、专科批的志愿数量、投档方式、冲稳保比例 |
| `thresholds` | 冲稳保概率阈值（各省可能不同） |
| `score_segments` | 分数段划分（影响排序策略） |
| `category` | 科类标签映射（新旧高考兼容） |

### 3. 准备数据

数据格式见 [数据接入指南](../docs/data-guide.md)。

最低要求：
- 一分一段表（当年）
- 院校专业组投档线（当年）
- 招生计划（当年）
- 院校基础信息

### 4. 验证

```bash
# 检查配置是否正确加载
python -m gaokao.cli --province {your_province} --check-config

# 生成并用合成示例数据跑通完整流程
python data/generate_example_db.py
python -m gaokao.cli --province {your_province} --example
```

### 5. 提交 PR

提交包含：
- `provinces/{your_province}/province.yaml`（配置）
- `provinces/{your_province}/__init__.py`（空文件，标记为省份包）
- 数据转换/校验代码和来源说明（如有）

不要提交真实数据库或任何考生级记录。数据贡献必须附来源 URL、年份、许可/使用条款和
可再分发依据；完整要求见 [CONTRIBUTING.md](../CONTRIBUTING.md)。

## 省份类型差异

### 院校专业组模式（group）

适用省份：云南、广东、江苏、福建、湖北、湖南 等（3+1+2 省份）

- 一个院校有多个专业组，每个专业组有独立投档线
- 专业组内有调剂（服从=组内调剂，不服从=退档）
- 需要 `score_line_{year}` 表包含 `group_code` 字段

### 专业+院校模式（major）

适用省份：浙江、山东、辽宁、河北、重庆 等

- 一个专业一个志愿，无调剂
- 推荐逻辑不同：按专业排序而非按学校排序
- 需要实现 `MajorRecommender` 策略

### 旧高考模式（old）

适用省份：未改革的省份

- 文理分科，一本/二本多批次
- 需兼容旧标签（理科/文科）到新标签（物理/历史）的映射
