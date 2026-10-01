# xagent 第二轮修复验收

日期：2026-10-01，Asia/Taipei。对应 PR #1，候选版本 `0.15.5-shared.6`。

原五项缺陷和收尾审查新增的 bytecode 缓存误判均已修复。离线检查 79/79、五家执行器实测 49/49、Codex 主控 10/10 通过。Claude 首次完整运行在 20 分钟上限结束，6/10；保持相同契约、断言、权限与策略，以 30 分钟上限独立重跑后 10/10 通过，其中 Gemini 经一次超时重试才完成。没有将首次完整运行写成全绿，也没有据此保证厂商持续可用。

## 修复与反向验证

| 问题 | 最终行为与验证依据 |
|---|---|
| `.GIT` 大小写别名可写 Git 元数据 | 输入路径与解析后路径都按大小写折叠检查 `.git`。真实 Git 仓库和 linked worktree 回归通过；本机实际 pi 0.99.2 的 tool-call hook 与 write 工具确认 `.GIT/config`、`.Git/config`、`.git/config` 均被拦截，普通文件仍可写。 |
| 非对象 JSON 留下未完成回执 | 先验证顶层对象和回复字段类型；`null`、数组、数值及无效字段均通过正常错误路径结束为 DROPOUT，保留退出信息和最终只读快照。真实 runner 配 stand-in CLI 的回归覆盖无效输出同时修改工作区的情况。 |
| staged/committed 测试改写绕过完整性门 | 工作树、index 和 HEAD 中的测试内容都与固定夹具哈希比较。旧门禁会放过的 staged/committed 反例现在失败。 |
| import 测试被误算为测试通过 | 回执只在原断言成功、测试前后源码哈希一致时写入。验收先核对回执与当前源码，再独立复验；单纯 import、断言失败、空标记、测试中改源码和过期回执均不能通过。 |
| 验证命令可能永久挂起 | 共用标准库进程 helper，为测试和 contract probe 设置 30 秒期限，超时返回 124、终止进程组并保留输出。真实进程回归覆盖忽略 TERM、后台子进程、输出管道被持有，以及主控结束后的无限循环；父验收与 harness 都能产出失败证据。 |
| 旧 `.pyc` 让错误的最终源码被接受 | 同秒、等长编辑可能继续读取旧缓存，`-B` 不能阻止读取。共享验证入口每次使用独立的临时 `PYTHONPYCACHEPREFIX`，同时禁止写 bytecode。真实缓存反例覆盖普通 CLI、父 verifier 和独立 contract；错误源码现在无法通过独立验证，worker 回执不能单独作为验收依据。 |

## 实际执行

| 检查 | 结果 | 命令 |
|---|---|---|
| 配置与 pi guard | PASS，19/19 | `node --test scripts/config.test.mjs scripts/xagent-pi-guard.test.mjs` |
| verdict | PASS，18/18 | `bash scripts/xagent-classify.test.sh` |
| runner 黑盒回归 | PASS，12/12 | `python3 -B scripts/xagent.test.py` |
| 固定测试与 worker 回执 | PASS，8/8 | `python3 -B scripts/xagent-e2e-verify.test.py` |
| 有界进程验证 | PASS，7/7 | `python3 -B scripts/e2e-process.test.py` |
| 主控验收回归 | PASS，15/15 | `python3 -B scripts/pstack-host-e2e.test.py` |
| 五家真实执行器 | PASS，49/49，exit 0 | `bash scripts/xagent-e2e.sh <new-vendor-run>` |
| Codex 主控 | PASS，10/10 | `python3 -B scripts/pstack-host-e2e.py <new-host-run>` |
| Claude 首次完整运行 | FAIL，6/10，主控 exit 124；两主控合计 exit 1 | 同上，默认外层上限 1200 秒 |
| Claude 独立重跑 | PASS，10/10，exit 0 | `python3 -B scripts/pstack-host-e2e.py <new-retry-run> --host claude --host-timeout 1800` |

五家执行器覆盖 Claude、Codex、Grok、Gemini、pi 的修复与只读评审，以及权限拒绝、嵌套拒绝、超时和 Codex 直接派发后的回收。16 份回执均已结束。离线 CLI 回归使用真实 Git 和进程，厂商由 stand-in 代替，不冒充真实模型调用。

两种主控均读取本地候选版本的 `swarm` 和 `interrogate`，自行解析实际共享策略：Claude 使用 pi writer 与 Codex/Gemini reviewer；Codex 使用 pi writer 与 Claude/Gemini reviewer。每个 worker/reviewer 使用独占的真实 worktree。通过的两条主控路径都集成补丁、运行最终 helper，再由 harness 独立复验；原测试不变，普通均值、大浮点数和超出 float 范围的整数探针通过，主控回执和两家评审快照均绑定最终源码。这些检查不等同于对任意数值类型的完整正确性证明。

Claude 首次运行的 reviewer 提出了有限复数兼容性、超大整数与复数混合输入的表示问题。主控进行了两轮修正并重新评审，但第三轮 Gemini 因 headless command 权限被拒绝而没有输出；Codex reviewer 随外层超时被取消。9 个子任务全部有终态，原测试和独立数值探针仍 exit 0，但最终评审、主控最终回执与完整完成声明缺失，因此保留 FAIL。独立重跑中，Gemini 首次 241.14 秒超时，唯一一次重试在 217.13 秒返回 PASS；4 份回执全部结束，最终验收 10/10。提高的是已有参数控制的外层运行预算，每个 worker 仍限 240 秒和一次重试，每个验证命令仍限 30 秒。

## 版本与复现边界

缓存修复后的真实运行期间源码保持不变；运行前后的 28 文件清单以及主控 harness 的 11 文件清单均匹配。随后只补充本记录、中文 README 的验收状态与 ADAPTATION 的说明措辞。以下关键运行文件与提交内容一致：

| 文件 | SHA-256 |
|---|---|
| `bin/xagent` | `0d0f611a5135d02cc42c04b4ae59d47200c1e875066548bceb37e24ad7ec89d4` |
| `bin/xagent-pi-guard.ts` | `229e6d404b4d02a0273d5f4f6b842d5512122b91cc35cda65449e451c9c4f374` |
| `scripts/e2e-process.py` | `aff0c4698419ff2bb36068d1560e9c6ac5c602034b868902e4109852119b64c5` |
| `scripts/xagent-e2e-verify.py` | `981726ad89a1e82c61c1f718f7f8e55dd0335a5b4057efe6aae90ef0ab2421ba` |
| `scripts/xagent-e2e.sh` | `820a2bd958f4744ce69f6546c94e2601f45f5c73bd7efdf2b94ec36a9364fdea` |
| `scripts/pstack-host-e2e.py` | `63e8d6afa6b1fdc709e5c1d03c28e34385900ab9a69d62c0e64ac5a4cc18a8d2` |

运行版本：Claude 2.1.286、Codex 0.159.2、Grok 1.0.44、agy 1.2.14、pi 0.99.2、Node 24.18.1、Python 3.14.7。源码要求 Python 3.9+、POSIX、Node 22.18+；Python 3.9 仅做语法兼容检查，未在该解释器运行。真实 E2E 另需支持 `-k` 的 `timeout`、相应 CLI 登录态和共享配置中的外部 worker/reviewer 条目。复跑使用新的空输出目录，且会调用厂商、消耗额度；测试不会更新全局策略或权限。

本地原始证据分为三组：`.pstack/fixes/pr-1-round2/` 保存原五项缺陷的 red/green 日志、实际 pi 写保护证明及早期实测；`.pstack/reviews/pr-1-0582380/` 保存收尾审查、缓存误判红测和三套受影响回归；`.pstack/fixes/pr-1-final/` 保存缓存修复后的 `e2e-vendors/`、`e2e-hosts/`、`e2e-claude-retry/`、源码哈希和 `verification-summary.json`。失败反例、首次失败和重跑材料均保留，未被成功结果覆盖。夹具与日志为本机证据，不随 PR 上传；仓库包含可重跑脚本与本摘要。[上一轮记录](./xagent-2026-10-01.md)保留更早版本的失败结果。

本次没有安装、合并或发布插件。主会话退出/重启后的持久继续构建，以及完整 `arena`、`architect`、`poteto-mode` 长期编排仍未验收。pi guard、只读快照和验证进程组用于防误操作与有界检查，不构成对恶意项目代码的操作系统沙箱；脱离进程组的子进程不在组终止保证内。
