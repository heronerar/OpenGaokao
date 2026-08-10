# OpenGaokao — 源码可见的高考志愿推荐引擎

> **源码可见、商业受限。** 本仓库不是 OSI 开源软件。个人非商业本地使用须遵守
> [OpenGaokao SAL 1.0](LICENSE)；商业使用、商业托管及竞争性使用默认不获授权，须先取得
> 许可人的单独书面付费许可。修改版仅可由修改者本人本地使用，不得再分发。

Current-License: LicenseRef-OpenGaokao-SAL-1.0
Historical-License-Exception: AGPL-3.0-or-later
License-Text-SHA256: 94CA1C665A33F52F1800364A9DD33CFB5025825C9D00F2644DC9BC6AFAAE98FC
License-Text-Approval: OWNER_APPROVED
Counsel-Review: NOT_COUNSEL_VERIFIED

[![OpenGaokao SAL 1.0](https://img.shields.io/badge/license-OpenGaokao%20SAL%201.0-orange)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-green)]()
[![CI](https://github.com/heronerar/OpenGaokao/actions/workflows/ci.yml/badge.svg)](https://github.com/heronerar/OpenGaokao/actions/workflows/ci.yml)

**源码可审查 · 每一步可解释 · 本地隐私保护**

OpenGaokao 是一个高考志愿推荐引擎，面向 3+1+2 新高考模式设计。仓库当前包含**云南**配置；真实云南数据库不随代码分发。同为院校专业组模式的省份可按 YAML + 数据处理代码适配（见 docs/data-guide.md），其他志愿模式仍可能需要代码适配。
基于历史录取数据、项目自编偏好问卷和规则引擎，生成透明、可追溯、可审计的志愿推荐方案。

商业运营与第三方集成模块不在本仓库。来源、历史许可和当前发布边界见 [NOTICE](NOTICE) 与 [LICENSING.md](LICENSING.md)。

> ⚠️ **使用边界：** 当前为 Beta 阶段的本地决策辅助工具，不是教育考试机构官方系统，也不构成录取承诺。真实填报前必须核对当年考试院政策、招生计划和数据时效。

## 为什么让源码可见？

高考志愿是**一次性、高赌注、不可逆**的决策。家长需要的不只是推荐结果，更需要知道**为什么推荐**。

OpenGaokao 的核心理念：**"别信我，你来看代码。"**

## 核心特性

- 🔍 **透明推荐**：每条推荐都有完整的计算链条——从分数到位次到概率到排序，每一步可追溯
- 🧠 **多维偏好辅助**：项目自编大五维度、RIASEC 风格、学科自我评价和职业价值偏好问卷，用于专业匹配参考，不作心理诊断
- 🏠 **本地运行**：数据不出你的电脑，隐私安全
- ⚙️ **省份可配**：同模式省份可复用 YAML 配置与数据导入工具
- 🎯 **冲稳保分层**：基于指数衰减概率模型和公开阈值划分冲/稳/保

## 当前能力边界

| 能力 | 当前状态 |
|------|---------|
| 推荐逻辑 | 源码可审查的规则与固定算法，可在本地复现 |
| 数据 | 仓库只生成合成示例库；真实省份数据由使用者合法准备 |
| Web/API | Flask 本地开发入口，进程退出后即停止 |
| 偏好问卷 | 项目自编、未经心理测量验证，仅作方向参考 |
| 省份支持 | 仓库含云南配置；其他省份尚未验收 |

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/heronerar/OpenGaokao.git
cd OpenGaokao

# 2. 安装依赖
pip install -r requirements.txt

# 3. 生成可复现的合成示例库（真实数据库不随代码仓库分发）
python data/generate_example_db.py

# 4. 跑通示例数据（只用于演示，不是实际填报推荐）
python -m gaokao.cli --accept-license --province yunnan --example

# 5. 启动本地服务（真实云南推荐需要 data/yunnan_gaokao.db）
python -m gaokao.api.server --accept-license --province yunnan
# 访问 http://localhost:5000
```

当前支持的分发方式是**在克隆后的仓库根目录运行源码**。普通 wheel / PyPI 安装包尚未发布；不要把 `pip install .` 视为受支持的 Web/CLI 安装路径。

本项目当前是源码可见的开发型本地工具，不是常驻系统服务。上述命令运行期间，
Web 与 API 才可访问；关闭终端、按 `Ctrl+C`、退出进程或重启电脑后服务会停止，
再次执行同一条命令即可恢复。项目不默认配置开机自启动。

若 `data/yunnan_gaokao.db` 不存在，服务会降级到 `data/example.db`，页面将持续显示
红色“演示数据”警示；这类结果不可用于实际填报，也不能作为真实数据验收通过。
示例库同时写入内容级 `synthetic_example` 标记；即使复制或改名为
`yunnan_gaokao.db`，API、Web 与发版门禁仍会把它识别为演示数据。

## 运行验收与完成口径

真实入口验收会实际启动一个临时 Flask 进程，检查首页、核心推荐、数据源标识与
进程退出语义；任一项失败均以非零退出码结束：

```bash
# 要求使用真实云南数据库，example.db 降级会失败
python tests/test_e2e_api.py --province yunnan

# 发版单一门禁：语法、pytest、真实入口、数据、隐私与当前 SAL 全表面
python scripts/verify_release.py --province yunnan
```

只有明确验收演示路径时，才可显式使用
`--expect-data-source example`；它不等于真实推荐验收通过。

正式公开发布还要执行维护者门禁；该门禁要求提供不进入 Git 的私有 PII denylist，并扫描当前
待发布文件树以及由 `git rev-list --all` 枚举出的每个可达提交的文件内容；它不扫描提交作者、
提交消息、Tag 消息或 ref 名称：

```bash
python scripts/verify_release.py --ci --public-release \
  --pii-denylist <仓库外私有名单> \
  --rights-bom <仓库外最终逐文件权属清单> \
  --release-approval <仓库外许可人批准JSON>
```

这里的 `--ci` 固定验收不含私有省份数据库的“源码与合成演示包”，并须在不含 `.private/` 和真实省份库的
隔离候选工作树执行；若门禁发现真实库会失败并要求换工作树，不会移动或删除私有数据。真实
云南数据不随仓库发布，也不是该源码发行的产品能力前置；只有另行声称“真实云南推荐已验收”
时，才在私有环境执行不带 `--ci` 的本地验收，且不能用合成示例冒充。

`licensing/publication-policy.json` 只配置发布条件，不能在仓库内自我批准。每次正式发行仍须
由仓库外 Rights BOM 和许可人批准回执绑定最终许可证、权属证据、commit、tree 与固定 Tag，
再由许可人 SSH 签名 Tag 绑定这些哈希；缺少任一外部凭据时正式命令必须非零退出。完成口径见
[LICENSING.md](LICENSING.md)。

商业授权意向方可在本仓库公开后[新建联系 issue](https://github.com/heronerar/OpenGaokao/issues/new)，
标题写“商业授权联系”，正文只写非敏感的授权意向和回联方式；许可人 `heronerar` 再提供
私下沟通渠道。不要在公开 issue 中提交身份、合同、付款或税务材料。

## 目录结构

```
OpenGaokao/
├── gaokao/           # 核心引擎
│   ├── core/         # 算法（省份无关）
│   ├── pipeline/     # 决策管道可视化
│   ├── consensus/    # 家庭共识引擎
│   ├── risk/         # 风险评估引擎
│   ├── export/       # PDF/Excel/HTML生成
│   ├── api/          # Flask REST API
│   └── config/       # 配置系统
├── provinces/        # 省份配置（社区可贡献）
├── questionnaires/   # 问卷定义
├── docs/             # 文档
├── web/              # 前端
└── tests/            # 测试
```

## 数据边界

源码可见不等于招生数据可以再分发。本仓库不提供、销售或承诺交付任何真实省份数据库；
使用者须从合法来源自行准备数据，并遵守来源许可、考试院条款和个人信息保护要求。

## 许可证

- 当前发行适用 [`LicenseRef-OpenGaokao-SAL-1.0`](LICENSE)，它是定制的 source-available
  许可证，不是 OSI 开源许可证
- 历史 AGPL 版本的既有权利继续有效，不受当前发行追溯影响
- `data/example.db` 不进入 Git，由 `data/generate_example_db.py` 现场生成

真实省份数据库、商业数据包和任何考生记录均不随本代码仓库分发。贡献数据前请阅读 [贡献指南](CONTRIBUTING.md) 的来源、授权与隐私要求。

## 参与贡献

在独立贡献协议启用前暂停合并外部代码贡献；当前只接受 issue、复现材料和不包含第三方代码的
讨论。详情见 [CONTRIBUTING.md](CONTRIBUTING.md)，并确保发布门禁失败时不宣告完成。
