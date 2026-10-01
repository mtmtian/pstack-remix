# xagent 第二轮修复验收

日期：2026-10-01，Asia/Taipei。对应 PR #1，候选版本 `0.15.5-shared.6`。

上一轮审查的五项缺陷已修复。离线检查 76/76、五家执行器实测 49/49、Claude 与 Codex 主控各 10/10 通过。本轮六个主控子任务全部正常结束，无重试；此前 Claude→Gemini 的超时本轮没有复现。这次成功不代表已经定位历史超时原因或保证厂商持续可用。

## 修复与反向验证

| 问题 | 最终行为与验证依据 |
|---|---|
| `.GIT` 大小写别名可写 Git 元数据 | 输入路径与解析后路径都按大小写折叠检查 `.git`。真实 Git 仓库和 linked worktree 回归通过；本机实际 pi 0.99.2 的 tool-call hook 与 write 工具确认 `.GIT/config`、`.Git/config`、`.git/config` 均被拦截，普通文件仍可写。 |
| 非对象 JSON 留下未完成回执 | 先验证顶层对象和回复字段类型；`null`、数组、数值及无效字段均通过正常错误路径结束为 DROPOUT，保留退出信息和最终只读快照。真实 runner 配 stand-in CLI 的回归覆盖无效输出同时修改工作区的情况。 |
| staged/committed 测试改写绕过完整性门 | 工作树、index 和 HEAD 中的测试内容都与固定夹具哈希比较。旧门禁会放过的 staged/committed 反例现在失败。 |
| import 测试被误算为测试通过 | 回执只在原断言成功、测试前后源码哈希一致时写入。验收先核对回执与当前源码，再独立复验；单纯 import、断言失败、空标记、测试中改源码和过期回执均不能通过。 |
| 验证命令可能永久挂起 | 共用标准库进程 helper，为测试和 contract probe 设置 30 秒期限，超时返回 124、终止进程组并保留输出。真实进程回归覆盖忽略 TERM、后台子进程、输出管道被持有，以及主控结束后的无限循环；父验收与 harness 都能产出失败证据。 |

## 实际执行

| 检查 | 结果 | 命令 |
|---|---|---|
| 配置与 pi guard | PASS，19/19 | `node --test scripts/config.test.mjs scripts/xagent-pi-guard.test.mjs` |
| verdict | PASS，18/18 | `bash scripts/xagent-classify.test.sh` |
| runner 黑盒回归 | PASS，12/12 | `python3 -B scripts/xagent.test.py` |
| 固定测试与 worker 回执 | PASS，7/7 | `python3 -B scripts/xagent-e2e-verify.test.py` |
| 有界进程验证 | PASS，6/6 | `python3 -B scripts/e2e-process.test.py` |
| 主控验收回归 | PASS，14/14 | `python3 -B scripts/pstack-host-e2e.test.py` |
| 五家真实执行器 | PASS，49/49，exit 0 | `bash scripts/xagent-e2e.sh <new-vendor-run>` |
| Claude/Codex 主控 | PASS，各 10/10，合计 exit 0 | `python3 -B scripts/pstack-host-e2e.py <new-host-run>` |

五家执行器覆盖 Claude、Codex、Grok、Gemini、pi 的修复与只读评审，以及权限拒绝、嵌套拒绝、超时和 Codex 直接派发后的回收。16 份回执均已结束。离线 CLI 回归使用真实 Git 和进程，厂商由 stand-in 代替，不冒充真实模型调用。

两种主控均读取本地候选版本的 `swarm` 和 `interrogate`，自行解析实际共享策略：Claude 使用 pi writer 与 Codex/Gemini reviewer；Codex 使用 pi writer 与 Claude/Gemini reviewer。每个 worker/reviewer 使用独占的真实 worktree。两种主控都集成补丁、运行最终 helper，再由 harness 独立复验；原测试不变，普通均值、大浮点数和超出 float 范围的整数探针通过，主控回执和两家评审快照均绑定最终源码。Gemini 回执较简短，不能据此推断其详细推理或额外检查覆盖。

## 版本与复现边界

本轮记录的源码在测试期间保持不变；运行前后的 16 文件清单以及主控 harness 的 11 文件清单均匹配。随后只补充本记录、历史记录链接与中文 README 的验收状态。以下关键运行文件与提交内容一致：

| 文件 | SHA-256 |
|---|---|
| `bin/xagent` | `0d0f611a5135d02cc42c04b4ae59d47200c1e875066548bceb37e24ad7ec89d4` |
| `bin/xagent-pi-guard.ts` | `229e6d404b4d02a0273d5f4f6b842d5512122b91cc35cda65449e451c9c4f374` |
| `scripts/e2e-process.py` | `696724992a81ac4641cb0383aee55efb1d3499a16245ad3699fc1f8319ee2a75` |
| `scripts/xagent-e2e-verify.py` | `981726ad89a1e82c61c1f718f7f8e55dd0335a5b4057efe6aae90ef0ab2421ba` |
| `scripts/xagent-e2e.sh` | `820a2bd958f4744ce69f6546c94e2601f45f5c73bd7efdf2b94ec36a9364fdea` |
| `scripts/pstack-host-e2e.py` | `63e8d6afa6b1fdc709e5c1d03c28e34385900ab9a69d62c0e64ac5a4cc18a8d2` |

运行版本：Claude 2.1.286、Codex 0.159.2、Grok 1.0.44、agy 1.2.14、pi 0.99.2、Node 24.18.1、Python 3.14.7。源码要求 Python 3.9+、POSIX、Node 22.18+；Python 3.9 仅做语法兼容检查，未在该解释器运行。真实 E2E 另需支持 `-k` 的 `timeout`、相应 CLI 登录态和共享配置中的外部 worker/reviewer 条目。复跑使用新的空输出目录，且会调用厂商、消耗额度；测试不会更新全局策略或权限。

本地原始证据在 `.pstack/fixes/pr-1-round2/`：`runtime-red.log`、`vendor-r3-r4-red.log`、`host-timeout-red.json`、各套 green 日志、`pi-case-write-proof.json`、`e2e-vendors/`、`e2e-hosts/`、源码哈希清单及 `verification-summary.json`。保留了失败反例、运行日志和夹具 worktree，便于复核；该目录不随 PR 上传。仓库包含可重跑的脚本与本摘要。[上一轮记录](./xagent-2026-10-01.md)保留当时的失败结果。

本次没有安装、合并或发布插件。主会话退出/重启后的持久继续构建，以及完整 `arena`、`architect`、`poteto-mode` 长期编排仍未验收。pi guard、只读快照和验证进程组用于防误操作与有界检查，不构成对恶意项目代码的操作系统沙箱；脱离进程组的子进程不在组终止保证内。
