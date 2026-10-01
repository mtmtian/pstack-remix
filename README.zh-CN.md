# pstack：Codex 与 Claude Code 共用的工程工作流

[English](./README.md) | 简体中文

一份源码、一份配置，分别接入 Codex 和 Claude Code 的原生能力。你描述任务和验收条件，pstack 选择相应流程，组织调查、设计、实现、评审与验证。

这是一个独立维护的本地适配版本，基于 Lauren Tan 以 MIT 协议发布的上游 pstack 0.15.5，跟踪提交 [`12d587df`](https://github.com/cursor/plugins/tree/12d587dfb20741cafc376c42c696c5f6e2a64487/pstack)。本项目不由 Lauren Tan、Cursor、OpenAI 或 Anthropic 维护。

两种主控共用 **48 个技能、23 个流程模板**、工程原则、Agent 提示词和 Node 工具。插件清单和少量运行时适配负责处理主控差异。仓库名为 `pstack-remix`；为兼容已有安装，Codex 插件名仍为 `pstack-codex`，Claude Code 插件名为 `pstack`。

## 安装与快速开始

需要 Git、Node.js 22.18 或更新版本，以及要使用的主控 CLI。跨厂商派发还需要 POSIX 环境、Python 3.9+ 和对应 Agent CLI 的登录态。普通使用不需要安装 Bun；仅在开发、测试或重建 TypeScript 工具时需要它。

每台机器只克隆一份源码，再让所需主控注册同一个目录：

```sh
mkdir -p "$HOME/plugins"
git clone https://github.com/mtmtian/pstack-remix.git "$HOME/plugins/pstack-codex"
cd "$HOME/plugins/pstack-codex"
```

安装 Codex 插件：

```sh
codex plugin marketplace add "$PWD"
codex plugin add pstack-codex@pstack-local
```

安装 Claude Code 插件：

```sh
claude plugin marketplace add "$PWD"
claude plugin install pstack@pstack-local --scope user
```

只需安装你实际使用的主控。每个主控的 marketplace 注册一次即可；插件缓存是安装生成物，维护源码时编辑 checkout。已有 `pstack-codex@personal` 安装且指向同一份源码的，可以继续使用原注册，不必再装一份。

| 用途 | Codex | Claude Code |
|---|---|---|
| 开始任务 | `$pstack-codex:poteto-mode` | `/pstack:poteto-mode` |
| 配置角色与模型 | `$pstack-codex:setup-pstack` | `/pstack:setup-pstack` |
| 直接发起评审 | `$pstack-codex:interrogate` | `/pstack:interrogate` |

例如，在 Codex 中输入：

```text
$pstack-codex:poteto-mode 这个 PR 中的列表在静止时每隔 750ms 就会发生滚动偏移。
先复现，再定位根因、修复并验证。
```

在 Claude Code 中输入：

```text
/pstack:poteto-mode 这个 PR 中的列表在静止时每隔 750ms 就会发生滚动偏移。
先复现，再定位根因、修复并验证。
```

完整安装、更新和已有环境迁移说明见[安装指南](./docs/guide/01-setup.md)。源码更新后还需要刷新插件，并在新会话中检查发现结果。

## 共享配置

配置保存在 `~/.config/pstack/config.json`，独立于两个主控的插件缓存。未配置的角色默认继承当前主会话，不需要先选择一套模型；worker 接收主控解析后的策略，也不需要重复执行 setup。

查看各主控最终采用的配置：

```sh
node bin/config.mjs show --host codex
node bin/config.mjs show --host claude
```

共享配置可以指定角色、评审组和推理强度。具体模型 ID 放在对应主控的配置中，由该主控的可用能力决定能否使用；`hosts.codex` 或 `hosts.claude` 的设置优先于共享设置。这样可以共用策略，又不把一家厂商的模型 ID 传给另一家。

需要修改偏好时调用 `setup-pstack`。已有选择会保留，除非你要求调整。源码仓库不包含个人配置、凭据、会话日志或插件缓存。详见[共享运行时约定](./references/runtime.md)。

## 日常使用：从 poteto-mode 开始

[`poteto-mode`](./skills/poteto-mode/SKILL.md) 是主要入口。你通常只需说明目标、约束和完成条件，不必手动串联所有技能。下面使用 `$技能名` 作为简写；实际调用时使用上面的主控前缀。

它会根据任务：

1. 选择[流程模板](./skills/poteto-mode/playbooks/)，把模板步骤放入待办列表。
2. 在各步骤需要时调用调查、设计、并行实现、评审和验证技能。
3. 汇总实际结果、证据及尚未解决的问题。

在同一会话中启用后，`poteto-mode` 会持续按任务需要应用，直到你明确退出。它是会话指令，不会修改全局模式或自动创建目标任务。

<details>
<summary>查看全部 23 个流程模板</summary>

| 流程 | 适用场景 |
|---|---|
| [调查 investigation](./skills/poteto-mode/playbooks/investigation.md) | 只读了解某个机制、设计原因或现状。 |
| [修复 bug](./skills/poteto-mode/playbooks/bug-fix.md) | 先复现缺陷，定位根因，再修复并以运行证据验证。 |
| [性能优化 perf](./skills/poteto-mode/playbooks/perf-issue.md) | 针对已测量的慢点建立基线，追踪并验证改进。 |
| [持续优化 hillclimb](./skills/poteto-mode/playbooks/hillclimb.md) | 围绕一个指标与目标循环提出假设、前后测量，每个接受的改进单独提交。 |
| [运行时排查 runtime forensics](./skills/poteto-mode/playbooks/runtime-forensics.md) | 用插桩分析内存泄漏、空闲 CPU 占用、交互故障等实时现象。 |
| [采样分析 trace forensics](./skills/poteto-mode/playbooks/trace-forensics.md) | 分析 cpuprofile、trace、spindump、heap snapshot 等已采集的性能数据。 |
| [功能开发 feature](./skills/poteto-mode/playbooks/feature.md) | 从明确的数据结构出发，开发或修改行为。 |
| [重构 refactoring](./skills/poteto-mode/playbooks/refactoring.md) | 保持外部行为，调整内部结构。 |
| [原型 prototype](./skills/poteto-mode/playbooks/prototype.md) | 用低成本原型验证设计选择，或通过实际运行比较方案。 |
| [视觉对齐 visual parity](./skills/poteto-mode/playbooks/visual-parity.md) | 对照目标实现检查和修正 UI 视觉差异。 |
| [技能编写 authoring a skill](./skills/poteto-mode/playbooks/authoring-a-skill.md) | 编写或修改 `SKILL.md`。 |
| [行为评估 eval](./skills/poteto-mode/playbooks/eval.md) | 用盲评比较技能或提示词变化对 Agent 行为的影响。 |
| [PR 跟进 babysit](./skills/poteto-mode/playbooks/babysit.md) | 处理冲突、评审讨论和 CI，使 PR 或提交栈达到可合并状态。 |
| [交付 shipping](./skills/poteto-mode/playbooks/shipping.md) | 独立复核已通过验证的提交栈；具备相应授权和工具后，再从底向上交付。 |
| [持续执行 autonomous run](./skills/poteto-mode/playbooks/autonomous-run.md) | 在授权范围内持续推进一个长任务，直到满足完成条件。 |
| [项目编排 orchestrate](./skills/poteto-mode/playbooks/orchestrate.md) | 由一个协调会话管理跨多天、多 PR 和多个子 Agent 的项目。 |
| [独立 PR 流程 autopilot-full](./skills/poteto-mode/playbooks/autopilot-full.md) | 每个独立 PR 由唯一负责人推进；主控复验代码就绪或补丁变化的每轮结果，合并需另有授权。 |
| [线性提交栈 autopilot-stack](./skills/poteto-mode/playbooks/autopilot-stack.md) | 构建并验证一条线性 PR 栈，供用户审阅和合并。 |
| [接续任务 session pickup](./skills/poteto-mode/playbooks/session-pickup.md) | 接手或恢复另一个 Agent 尚未完成的工作。 |
| [安全暂停 pause safely](./skills/poteto-mode/playbooks/pause-safely.md) | 妥善暂停执行，留下可以接续的状态和证据。 |
| [分阶段计划 multi-phase plan](./skills/poteto-mode/playbooks/multi-phase-plan.md) | 规划跨阶段或跨多个 PR 的任务。 |
| [工作区清理 worktree cleanup](./skills/poteto-mode/playbooks/worktree-cleanup.md) | 核验安全条件后，清理已合并或废弃的 worktree 和过期 iOS 模拟器。 |
| [创建 PR opening a pr](./skills/poteto-mode/playbooks/opening-a-pr.md) | 获得创建 PR 的授权后，整理小而有序的提交、规范标题和便于评审的说明。 |

</details>

### 常用请求示例

```text
$poteto-mode 列表做了虚拟化，但加载大量数据仍然很慢。先采集 CPU trace，找出瓶颈。

$poteto-mode 为 Markdown 渲染器做两个原型，分别运行并比较结果，再确定实现。

$poteto-mode 我暂时离开。请在独立 worktree 中准备并验证这组改动；
遇到无法解决的检查就停下来，保留可审计的决策记录。远程合并由我另行授权。

$how 取消任务的调用链是什么？批量取消时是否会产生 N+1 查询？

$why 为什么这个功能开关还没有打开？

$swarm 检查 packages/ 下各个包的 check.sh，每个包分配一个 worker，最后汇总结果。

$interrogate review 这个 PR，重点检查行为回归和维护成本。
```

### 长任务与定时任务

对于有明确终点的长任务，可以明确请求主控原生的 `/goal` 能力。目标的继续执行与完成行为取决于实际主控和[对应适配器](#主控适配与执行边界)。需要重复运行、定时检查或稍后唤醒时，使用主控实际提供的自动化或调度接口。

pstack 本身不安装定时器；长任务流程也不保证会话退出或主控重启后自动恢复。安装插件不会自动创建目标、计划任务、机器人或 webhook。

## 技能一览

`poteto-mode` 会在合适的步骤调用这些技能，也可以直接使用。48 个技能中，25 个是下面的工作流技能，另有 23 个工程原则技能。

<details>
<summary>查看全部工作流技能</summary>

| 技能 | 适用场景 |
|---|---|
| [`poteto-mode`](./skills/poteto-mode/SKILL.md) | 非简单任务的默认入口，选择流程并协调执行。 |
| [`how`](./skills/how/SKILL.md) | 梳理子系统的结构、行为和调用关系。 |
| [`why`](./skills/why/SKILL.md) | 通过实际可用的源码、Issue、文档、讨论和观测工具追溯设计原因。 |
| [`recall`](./skills/recall/SKILL.md) | 从相关历史会话和共享记录中恢复某个主题的当前上下文。 |
| [`blast-radius`](./skills/blast-radius/SKILL.md) | 检查小改动可能影响的其他部分，用运行证据验证关键安全假设。 |
| [`architect`](./skills/architect/SKILL.md) | 在跨函数边界的实现前，明确调用示例、类型和模块形状。 |
| [`arena`](./skills/arena/SKILL.md) | 对同一任务并行尝试多个方案，再选取各自优点。 |
| [`swarm`](./skills/swarm/SKILL.md) | 把不同工作切片或竞争性尝试分给多个 worker，再统一验收。 |
| [`interrogate`](./skills/interrogate/SKILL.md) | 对 diff 进行多角度评审，包含严格代码质量检查；模型由策略和主控能力决定。 |
| [`xagent`](./skills/xagent/SKILL.md) | 通过统一 CLI 向本机不同厂商的 Agent 派发任务并收集结果。 |
| [`automate-me`](./skills/automate-me/SKILL.md) | 根据已授权的工作记录，起草符合个人习惯的 `<你的名字>-mode` 技能。 |
| [`make-bot-ui`](./skills/make-bot-ui/SKILL.md) | 按需配置 webhook UI 工作流；凭据、发送方校验和网络暴露取决于主控，默认不开启。 |
| [`setup-pstack`](./skills/setup-pstack/SKILL.md) | 查看和修改角色、模型、评审组及推理偏好。 |
| [`reflect`](./skills/reflect/SKILL.md) | 在任务结束后，把可复用经验整理为技能改进。 |
| [`teach`](./skills/teach/SKILL.md) | 结合 how 与 why，用解释和图示帮助理解改动或子系统。 |
| [`tdd`](./skills/tdd/SKILL.md) | 有合适的本地测试路径时，先写失败测试，再修复问题。 |
| [`no-comments`](./skills/no-comments/SKILL.md) | 通过 Comment Sicko 评审注释，把可接受的约束尽量落实到结构中。 |
| [`typescript-best-practices`](./skills/typescript-best-practices/SKILL.md) | 阅读或修改 TypeScript 时，应用具体的类型系统约束。 |
| [`figure-it-out`](./skills/figure-it-out/SKILL.md) | 没有现成模板适用时，为当前任务设计可审计的执行流程。 |
| [`show-me-your-work`](./skills/show-me-your-work/SKILL.md) | 把决策过程记录为可以审阅和提交的 TSV 文件。 |
| [`create-verification-skill`](./skills/create-verification-skill/SKILL.md) | 为缺少行为验证手段的项目创建验证技能和功能清单。 |
| [`maintain-verification-skill`](./skills/maintain-verification-skill/SKILL.md) | 结合源码与实际运行，修正已经偏离产品的验证技能。 |
| [`unslop`](./skills/unslop/SKILL.md) | 去掉空泛、机械或带明显 AI 痕迹的表达。 |
| [`bro`](./skills/bro/SKILL.md) | 用简单、自然的语言重新解释上一条回复。 |
| [`technical-writing`](./skills/technical-writing/SKILL.md) | 编写文档、RFC、README、PR 说明和提交信息。 |

</details>

## 跨厂商协作：xagent

共享策略中的 `xagent:<agent>` 表示外部 Agent CLI，例如 `xagent:pi` 或 `xagent:codex`。它可以用于 worker 角色或评审组；它不是主控模型 ID，也不应作为原生子 Agent 的 `model` 参数传入。

| 配置值 | 本机执行入口 |
|---|---|
| `xagent:claude` | `claude` |
| `xagent:codex` | `codex` |
| `xagent:grok` | `grok` |
| `xagent:gemini` | `agy` |
| `xagent:pi` | `pi` |

统一调用形式：

```text
<plugin-root>/bin/xagent <claude|codex|grok|gemini|pi> <ro|rw> <workdir> <prompt-file> <out-dir> [timeout-sec]
```

主控为每个外部 worker 准备独占 Git worktree 和独立 brief，评审者也遵循这一规则；每次尝试使用新的空输出目录。`xagent` 不会自行创建 worktree。审查、裁决和探索使用 `ro`，写入任务使用 `rw`。

输出包括 `prompt.md`、`result.md`、`agent.log` 和 `meta.json`，pi 另有 `guard.log`。主控需要同时检查进程终态、`completed`、状态、diff 和验证证据：

- `PASS`：worker 声称完成，仍需主控独立验收。
- `ISSUES`：存在问题或缺失检查，主控必须处理后才能接受结果。
- `BLOCKED`：前置条件或执行边界阻止任务继续。
- `DROPOUT`：没有可用的最终结论；检查部分产出和进程终止状态后，最多重试一次，再记录缺口。取消的任务不自动重试。

`ro` 模式会比较 HEAD、index、文件内容和非忽略的未跟踪文件；只读快照是事后检测，pi 路径与命令检查用于减少误操作。它们都不能代替操作系统沙箱。派发会向所选厂商发送 brief 和代码，必须在相应的数据授权范围内使用。

完整参数、权限差异、隔离规则和测试命令见 [xagent 技能](./skills/xagent/SKILL.md)。[第二轮验收记录](./docs/verification/xagent-2026-10-01-round2.md)记录了六项审查修复、五家执行器实测，以及 Codex 通过、Claude 首次超时后独立重跑通过的证据；变更见 [PR #1](https://github.com/mtmtian/pstack-remix/pull/1)。主会话退出或重启后的持久运行，以及长期无人值守编排仍未验收。

## 共享 Agent 提示词

[`poteto-agent`](./agents/poteto-agent.md) 和 [`comment-sicko`](./agents/comment-sicko.md) 是两种主控共用的 Agent 提示词。Claude Code 将它们作为原生 Agent 定义；Codex 把正文交给实际支持的协作角色，不虚构自定义 Agent 类型。

Comment Sicko 在 Claude Code 中仅有只读工具，在 Codex 中也需要匹配的只读角色与范围。两者读取同一套运行时约定和技能。

## 工程原则

23 个原则各有一个短技能。`poteto-mode` 在任务开始时读取原则索引，并在需要时引用具体规则。

<details>
<summary>查看全部 23 个工程原则</summary>

| 原则 | 类别 | 要点 |
|---|---|---|
| [laziness-protocol](./skills/principle-laziness-protocol/SKILL.md) | 核心 | 优先删除冗余，以能解决问题的最小完整改动收敛。 |
| [foundational-thinking](./skills/principle-foundational-thinking/SKILL.md) | 核心 | 先明确核心类型、数据结构和并发参与者的共享状态，再写逻辑。 |
| [redesign-from-first-principles](./skills/principle-redesign-from-first-principles/SKILL.md) | 核心 | 把新需求视为设计起点重新推导，避免不断外挂补丁。 |
| [attack-the-premise](./skills/principle-attack-the-premise/SKILL.md) | 核心 | 同一前提下连续修复仍失败时，重新检查前提和问题分布。 |
| [subtract-before-you-add](./skills/principle-subtract-before-you-add/SKILL.md) | 核心 | 先去掉死代码、重复验证和空壳引用，再增加内容。 |
| [minimize-reader-load](./skills/principle-minimize-reader-load/SKILL.md) | 核心 | 减少理解代码所需的跳转和隐含状态，收窄可变范围。 |
| [outcome-oriented-execution](./skills/principle-outcome-oriented-execution/SKILL.md) | 核心 | 按明确阶段收敛到目标结构，避免只为中间态添加临时兼容层。 |
| [experience-first](./skills/principle-experience-first/SKILL.md) | 核心 | 优先打磨用户体验，宁可减少功能，也要完成关键体验。 |
| [exhaust-the-design-space](./skills/principle-exhaust-the-design-space/SKILL.md) | 核心 | 在关键取舍前实现 2–3 个候选原型，实际比较。 |
| [build-the-lever](./skills/principle-build-the-lever/SKILL.md) | 核心 | 为重复或复杂工作建立可重跑的工具、脚本或技能，并交付验证手段。 |
| [model-the-domain](./skills/principle-model-the-domain/SKILL.md) | 架构 | 用恰当的数据结构表达领域，减少分散的条件判断。 |
| [boundary-discipline](./skills/principle-boundary-discipline/SKILL.md) | 架构 | 在 CLI、配置、网络等边界集中校验，内部保持类型可信和业务逻辑清晰。 |
| [type-system-discipline](./skills/principle-type-system-discipline/SKILL.md) | 架构 | 让非法状态难以表达，在边界解析数据，穷尽处理类型分支。 |
| [make-operations-idempotent](./skills/principle-make-operations-idempotent/SKILL.md) | 架构 | 不论之前执行到哪里，重复操作都能收敛到同一个目标状态。 |
| [migrate-callers-then-delete-legacy-apis](./skills/principle-migrate-callers-then-delete-legacy-apis/SKILL.md) | 架构 | 同一轮迁移调用方并清理旧 API，避免长期保留兼容路径。 |
| [separate-before-serializing-shared-state](./skills/principle-separate-before-serializing-shared-state/SKILL.md) | 架构 | 先消除不必要的共享；确需单一写入者时再串行化。 |
| [prove-it-works](./skills/principle-prove-it-works/SKILL.md) | 验证 | 检查真实产物和行为；自述、编译通过或代理指标不能单独证明完成。 |
| [fix-root-causes](./skills/principle-fix-root-causes/SKILL.md) | 验证 | 先复现并追踪根因，避免仅添加保护条件掩盖问题。 |
| [sequence-verifiable-units](./skills/principle-sequence-verifiable-units/SKILL.md) | 验证 | 把工作拆成有顺序、可独立验证的单元，每步都留下可核验状态。 |
| [test-behavior-not-implementation](./skills/principle-test-behavior-not-implementation/SKILL.md) | 验证 | 按用户使用方式测试真实行为，不用镜像实现的断言自证正确。 |
| [guard-the-context-window](./skills/principle-guard-the-context-window/SKILL.md) | 委派 | 适合独立处理的大量内容交给子 Agent，主会话保留结论和必要依据。 |
| [never-block-on-the-human](./skills/principle-never-block-on-the-human/SKILL.md) | 委派 | 在已有授权内推进可逆工作，同时保留不可逆动作和明确要求的批准门槛。 |
| [encode-lessons-in-structure](./skills/principle-encode-lessons-in-structure/SKILL.md) | 维护 | 尽量把经验落实为 lint、元数据、检查或脚本，减少反复增加文字规则。 |

</details>

## 主控适配与执行边界

[共享运行时](./references/runtime.md) 负责配置、范围、证据和技能发现。[Codex 适配器](./references/codex-runtime.md) 与 [Claude Code 适配器](./references/claude-runtime.md) 分别说明各自的委派、目标和调度接口，不应把一方的工具名直接套给另一方。

主控必须亲自读取最终产物和进程终态，按原任务约定处理评审反例。空邮箱、闲置状态、超时或子 Agent 的 `PASS` 都不能单独证明任务完成。仍有范围内缺陷或必要检查缺口时，必须继续修复或明确报告未完成。

安装和调用 pstack 不会扩大权限。远程消息、推送、PR 写入、合并、发布、资源创建和破坏性清理，都需要覆盖相应动作与范围的授权。上游依赖的控制工具由实际可用的项目验证工具和主控能力替代，缺失能力要如实报告。

## 按自己的习惯调整

`poteto-mode` 提供了一套有明确取舍的工程习惯。需要自己的入口时，可以使用 [`automate-me`](./skills/automate-me/SKILL.md)，从已授权的近期工作记录中提炼 `<你的名字>-mode`；底层继续复用 pstack，个人路由技能与 `poteto-mode` 并存。

模型和角色偏好通过 [`setup-pstack`](./skills/setup-pstack/SKILL.md) 调整，不必修改插件源码。项目新增共享技能遵循[运行时约定](./references/runtime.md)，保留一份权威目录，再接入各主控的发现机制。

## 跟进上游与验证

从插件源码目录执行只读上游检查：

```sh
node scripts/check-upstream.mjs
```

它会比较 `UPSTREAM.json` 固定提交与上游最近的 pstack 改动。先审阅差异，再应用到共享源码树，保留两个主控适配器；不要直接用上游 Cursor 目录覆盖本适配版本。

本地基础检查：

```sh
bash scripts/check.sh runtime
```

完整 CI 还包含 `orch` 与 `watch-pr` 的类型检查、Bun 测试和分发产物一致性检查。按 [CI 指南](./docs/ci.md)安装锁定的构建依赖后，运行 `bash scripts/check.sh`。GitHub Actions 对每个 PR 检查 Linux 最低支持版本、macOS 当前运行版本和构建产物，不需要厂商登录态。

真实跨厂商 E2E 会使用相应 CLI 登录态、发送合成任务并消耗厂商额度，还需要支持 `-k` 的 `timeout` 命令。具备对应授权和前置条件后，使用新的结果目录运行：

```sh
bash scripts/xagent-e2e.sh <new-vendor-run-dir>
python3 scripts/pstack-host-e2e.py <new-host-run-dir>
```

修改运行时或技能并发布时，同步更新两份插件 manifest 的版本；验证后按[安装指南](./docs/guide/01-setup.md) 刷新所需主控。源码、已安装缓存和当前会话是不同状态，要分别核对。

## 可选自动化

仓库还提供未启用的 [Benny 自动化包](./automations/benny/)，用于 Issue 分流和 UI 证据工作流。它没有默认开启 Slack 远程访问或定时执行，也没有注册成斜杠技能。需要使用时，先核对主控连接器、执行范围和授权，再按包内文档配置。

## 进一步阅读

- [完整使用指南](./docs/guide/README.md)：安装、理解代码、设计、实现、验证、长任务和常见问题。
- [适配说明](./ADAPTATION.md)：本版本与上游的差异及维护要求。
- [共享运行时约定](./references/runtime.md)：配置、委派、权限和证据标准。

## 许可证

[MIT](./LICENSE)。
