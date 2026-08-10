# OpenGaokao 许可与发布契约

Current-License: LicenseRef-OpenGaokao-SAL-1.0
Historical-License-Exception: AGPL-3.0-or-later

候选状态：`READY_PENDING_EXTERNAL_RECEIPT`

目标模式：`源码可见、商业受限（source-available）`

## 当前许可证事实

- 根目录 `LICENSE` 是 OpenGaokao Source-Available License 1.0（简称
  `OpenGaokao-SAL-1.0`）。
- `License-Text-SHA256`：
  `94CA1C665A33F52F1800364A9DD33CFB5025825C9D00F2644DC9BC6AFAAE98FC`。
- `License-Text-Approval`：`OWNER_APPROVED`。许可人已在本项目会话中批准上述精确哈希。
- `Counsel-Review`：`NOT_COUNSEL_VERIFIED`。该派生发布文本不得称为律师复核版本。
- 律师确认边界仍只对应私有审阅原稿的精确字节，其 SHA-256 为
  `18405F7503A2F0732122BE6FF7E982C2D821948B75D28335E8E4338800965F69`；许可人报告的状态为
  `OWNER_REPORTED_COUNSEL_CONFIRMED_UNCHANGED`。

许可证只授予正文明确列出的个人非商业本地使用、必要运行副本、单一备份、本人本地修改、
合格课堂展示和合格非商业研究等有限权利。未经单独书面付费许可，不授予商业使用、商业托管、
SaaS、API 服务或利用受保护表达开发或提供竞争性产品和服务的权利。修改版不得向第三方再分发；
商业合同也不能突破许可证正文列明的绝对禁止事项。GitHub 站内查看、运行和 Fork 等平台权利以
GitHub 当期服务条款及许可证中的平台例外为准。

上述模式不是 OSI 认可的开源许可证。商业许可逐案协商；“可申请商业许可”不表示任何申请人
当然有权获得授权。

## 历史 AGPL 权利边界

取证只确认 `heronerar/OpenGaokao` 在 2026-08-02 发生过公开事件并产生过非零克隆，不能证明
公开窗口精确对应哪一个提交。项目把
`bf1805e6979b6c5022944ce58829e9f27fcabc0c` 及其祖先作为保守治理候选边界；这不是特定提交
必然曾公开的最终法律事实认定。

任何实际合法取得历史 AGPL 版本的人，已经取得的许可证权利不会被本次转为 SAL、仓库转私有、
删除引用或后续商业合同追溯撤回。新许可证只适用于明确标记的新发行内容。

## 权属和来源证据

许可人已经作出仓库外签名事实声明，SHA-256 为
`151B419A05D594493C7DA7D2293E5F47674A9070EAF938646663EFE36240AA3A`。声明覆盖最终发行范围和
下列 11 个曾披露来源风险的文件：

- `gaokao/core/constraint_checker.py`
- `gaokao/core/hot_major_analyzer.py`
- `gaokao/core/industry_strong_schools.py`
- `gaokao/core/industry_trends.py`
- `gaokao/core/matching_engine.py`
- `gaokao/core/revocation_risk.py`
- `gaokao/core/sparse_prior.py`
- `gaokao/core/subject_guidance.py`
- `gaokao/core/volunteer_recommender.py`
- `gaokao/export/document_generator.py`
- `provinces/yunnan/province.yaml`

许可人声明这些文件涉及的 PPT、报告摘要、排名、政策或规则映射及字体相关内容，均由本人独立
创作或持有可再许可授权，不属于职务、委托或共同作品，并可提供本地证据。该状态准确记为
`OWNER_ATTESTED_LOCAL_EVIDENCE_AVAILABLE`，不是 `INDEPENDENTLY_VERIFIED` 或
`COUNSEL_CLEARED`。

每个固定发行 Tag 还必须在仓库外生成逐文件 Rights BOM，覆盖该 Tag 所指提交的全部 blob，
并绑定每个文件的路径、Git blob、SHA-256、权属依据、来源风险和处理结论。BOM、许可人批准
回执和私有证据不得进入仓库。

## 数据与真实能力边界

公开发行只包含源码和可复现合成示例，不包含真实云南数据库、真实考生记录或数据库 sidecar。
`--ci` 验收证明的是合成演示路径，不证明真实云南推荐已验收、推荐结论适合个人使用或生产服务
已经持续运行。

真实云南数据若将来另行使用，必须在合法、私有的环境执行非 `--ci` 验收，并单独记录数据来源、
授权、时效和实际推荐结果。真实数据不进入公开 Git 仓库，也不是本次源码发行的前置条件。

## 主动接受与运行语义

CLI 和 Flask 服务只有在调用者显式传入 `--accept-license` 后才启动；缺少该参数时必须非零退出，
且服务不得绑定端口。该参数记录本次运行的主动选择，但不是对使用者身份的密码学证明，也不能
自动证明所有重大格式条款在所有法域均已完成提示说明。

服务只在对应进程存活期间可用；终端关闭、进程退出、设备重启或会话结束后，API 和 Web 入口
都会停止。恢复方式是重新运行带接受参数的现有 CLI 或 Flask 入口，本项目不默认安装开机自启。

## 固定发行门禁

机器策略位于 `licensing/publication-policy.json`。仓库内状态只能表示候选已经准备好接受外部
凭据，不能自我批准公开。每次发行必须提供仓库外 Rights BOM 和许可人批准 JSON，后者绑定：

- 目标仓库、最终 commit、tree 和固定 Tag；
- 根许可证与 Rights BOM 的 SHA-256；
- 源码加合成演示范围、真实云南数据排除及历史 AGPL 权利保留；
- 许可人决定、带时区批准时间和签名公钥哈希。

固定 Tag 必须是指向最终 HEAD 的 SSH signed annotated tag，且 Tag 消息再次绑定批准 JSON、
Rights BOM 和许可证三个 SHA-256。许可人已授权为 OpenGaokao 生成仓库外专用密钥；当前公钥
指纹为 `SHA256:4YG/KaOdfRAXzuCJKQJhExYLf3hObWTnS6SrVb1Co5o`。该记录能证明发布材料由对应
私钥签名，但不是第三方身份认证或律师证明。

唯一正式公开发布验收命令是：

```bash
python scripts/verify_release.py --ci --public-release \
  --pii-denylist <仓库外私有名单> \
  --rights-bom <仓库外最终逐文件权属清单> \
  --release-approval <仓库外许可人批准JSON>
```

该命令必须在不含 `.private/`、真实省份数据库、数据库 sidecar、私钥或私有证据的隔离工作树
执行。任一哈希、Tag、提交、表面、测试、真实入口或外部凭据不符即非零退出。失败时不得公开，
也不得宣告完成。

受控门禁不能阻止 GitHub 管理员直接改可见性或同时篡改脚本、策略、CI 和信任材料的人恶意绕过；
因此正式公开前仍须核对目标仓库、远端 Tag、CI、Issues 和实际可见性。

## 持久纠错机制

| 层级 | 当前实现 | 机械阻断能力 |
|---|---|---|
| 原则/说明 | README、本文件记录真实入口、示例数据、律师边界、历史权利和失败关闭规则 | 不能；文字只提供交接依据 |
| 项目级持久契约 | `licensing/publication-policy.json` 分开许可文本、权属、目标发行与发布授权 | 可被门禁核验，但仓库内 JSON 不能自证许可人批准 |
| 机械门禁 | `scripts/verify_release.py`、`tests/test_release_gate.py`、CI、仓库外回执和 SSH 签名 Tag | 能在受控发布路径非零阻断 |

本项目不新增 `AGENTS.md` 或 `.codex/hooks.json`。问题集中在正式发行路径，已有发布脚本、测试、
CI 和外部凭据可以机械验证；再加纯文字 Hook 不能提高信任等级。若以后重复发生绕过发布命令
直接公开，再把 GitHub required check 或受保护环境作为下一层远端门禁。

## 审计台账

| ID | 级别 | 问题与本次结论 | 状态 |
|---|---|---|---|
| OG-F-82 | P1 | 单一许可状态掩盖法律文本、权属和发布阶段；已拆成独立机器状态 | closed |
| OG-F-83 | P1 | 私有律师原稿哈希不能外推到派生许可证；两份文本与哈希已分开 | closed |
| OG-F-84 | P2 | 权属、授权及组合自升级缺回归；已增加失败关闭测试 | closed |
| OG-F-85 | P1 | 历史候选边界曾被写成确定公开事实；已改为保守治理候选 | closed |
| OG-F-86/87 | P2 | 法律和权属状态曾存在第二套简称；活动状态使用 policy 精确值 | closed |
| OG-O-15 | P2 | 商业联系仅指向无联系方式账号；改为公开 issue 的非敏感回联请求 | remote check pending |
| OG-F-88 | P1 | 含未生效标记的律师原稿不能直接发布；已形成独立派生文本 | closed |
| OG-F-89 | P1 | 旧门禁没有正向可信路径；已加入外部回执与签名 Tag 路径 | code closed; real receipt required |
| OG-F-90 | P1 | 旧 Rights BOM 漂移且 11 项来源未关闭；已有本人声明，最终 BOM 按 Tag 重算 | owner-attested; final BOM required |
| OG-F-91 | P1 | 早期派生许可证存在授权与终止冲突；当前 260 行文本经多轮复审 | closed; not counsel-reviewed |
| OG-F-92 | P2 | 源码发行错误绑定真实云南数据；已拆分合成源码发行与私有真实数据验收 | closed |
| OG-F-93 | P1 | 正向路径只在理论夹具通过；现要求全树 BOM、真实 origin、Tag、时间和正式主流程 | closed by regression; real run required |
| OG-F-94 | P1 | 签名信任根不能由仓库自选；密钥在仓库外按许可人授权生成并记录指纹 | owner-authorized; not third-party verified |
| OG-F-95 | P1 | 三个许可文档曾允许视觉等价的冲突机器标记；现强制唯一规范行 | closed |
| OG-F-96 | P1 | `.private/` 仅本地忽略，可能误入发行树；现由 Git 忽略和发布树硬拒绝 | fixed; regression required |
| OG-F-97 | P1 | Windows 自动换行会改变获批许可证哈希；现固定根许可证为 LF | fixed; fresh checkout required |
| OG-F-98 | P1 | 缺失许可表面曾被静默跳过；现全部用户入口与包元数据均为必需项 | fixed; regression required |
| OG-F-99 | P1 | 许可证要求主动接受但真实入口没有机械动作；CLI/API 已增加显式参数 | fixed; real-entry test required |

## 商业授权联系

仓库公开且 Issues 已验证启用后，商业授权意向方可
[新建联系 issue](https://github.com/heronerar/OpenGaokao/issues/new)，标题写“商业授权联系”，
正文只写非敏感的授权意向和回联方式；许可人 `heronerar` 再提供私下沟通渠道。不要在公开
issue 提交真实姓名、身份证件、合同、付款或税务材料。入口不可用时，商业联系环节仍视为未完成。

本文件记录许可事实与发布契约，不取代根许可证，也不额外授予权利。
