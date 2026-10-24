# pstack：Codex 与 Claude Code 共用的工程工作流

[English](./README.md) | 简体中文

一份源码、一份配置，分别接入 Codex 和 Claude Code 的原生能力。你描述任务和验收条件，pstack 选择相应流程，组织调查、设计、实现、评审与验证。

这是一个独立维护的本地适配版本，基于 Lauren Tan 以 MIT 协议发布的上游 pstack 0.15.32，跟踪提交 [`e73df471`](https://github.com/cursor/plugins/tree/e73df471cd4bd918367e99f3dd9c51bd53ddf5f0/pstack)。本项目不由 Lauren Tan、Cursor、OpenAI 或 Anthropic 维护。

各主控共用 **58 个技能、23 个流程模板**、Agent 提示词和 Node 工具，主控差异只在插件清单和运行时适配里。为兼容已有安装，Codex 插件名仍为 `pstack-codex`，Claude Code 插件名为 `pstack`。本页只讲安装和入门；技能清单、示例和设计取舍见[英文 README](./README.md) 与[使用指南](./docs/guide/README.md)。

## 安装

需要 Git、Node.js 22.18 或更新版本，以及要使用的主控 CLI。跨厂商派发（xagent）还需要 POSIX 环境、Python 3.9+ 和对应 Agent CLI 的登录态。普通使用不需要 Bun。

每台机器只克隆一份源码，再让所需主控注册同一个目录，只装实际使用的主控：

```sh
git clone https://github.com/mtmtian/pstack-remix.git "$HOME/plugins/pstack-remix"
cd "$HOME/plugins/pstack-remix"

# Codex
codex plugin marketplace add "$PWD"
codex plugin add pstack-codex@pstack-local

# Claude Code
claude plugin marketplace add "$PWD"
claude plugin install pstack@pstack-local --scope user

# Antigravity
agy plugin install "$PWD"
```

插件缓存是安装生成物，维护时只改 checkout。源码更新后要刷新插件并开新会话，源码、缓存和当前会话是三种不同状态。已有 `pstack-codex@personal` 安装且指向同一份源码的，继续用原注册即可。完整的安装、更新和迁移说明见[安装指南](./docs/guide/01-setup.md)。

| 用途 | Codex | Claude Code |
|---|---|---|
| 开始任务 | `$pstack-codex:poteto-mode` | `/pstack:poteto-mode` |
| 不知道用哪个技能 | `$pstack-codex:poteto-help` | `/pstack:poteto-help` |
| 配置角色与模型 | `$pstack-codex:setup-pstack` | `/pstack:setup-pstack` |
| 直接发起评审 | `$pstack-codex:interrogate` | `/pstack:interrogate` |

T3 Code 会话沿用底层 Codex 或 Claude Code 的入口；只有会话里有 T3 的编排工具时，才会改用 [T3 叠加层](./references/t3-runtime.md)派发子任务。

## 日常使用

[`poteto-mode`](./skills/poteto-mode/SKILL.md) 是主要入口。说明目标、约束和完成条件即可，它会选择[流程模板](./skills/poteto-mode/playbooks/)，在需要时调用调查、设计、实现、评审和验证技能，最后汇总实际结果、证据和未解决的问题。它是会话内指令，会持续生效到你明确退出，不会改全局模式，也不会自动创建目标任务。

下面的 `$技能名` 是简写，实际调用时加上主控前缀：

```text
$poteto-mode 这个 PR 中的列表在静止时每隔 750ms 就会发生滚动偏移。先复现，再定位根因、修复并验证。

$poteto-mode 我暂时离开。请在独立 worktree 中准备并验证这组改动；遇到无法解决的检查就停下来，保留可审计的决策记录。

$how 取消任务的调用链是什么？批量取消时是否会产生 N+1 查询？

$interrogate review 这个 PR，重点检查行为回归和维护成本。
```

流程会像上游一样推送自己的分支、开出并更新自己的 PR，不再逐次询问，但不会直接推送主干。合并、`--auto`、对他人分支的 force-push、部署、发布、PR 以外的远程消息、资源创建和破坏性清理，都需要覆盖相应动作和范围的授权。pstack 不安装定时器，也不会自动创建目标、计划任务或 webhook。

## 共享配置

配置保存在 `~/.config/pstack/config.json`，独立于各主控的插件缓存。未配置的角色默认继承当前主会话，worker 接收主控解析后的策略，不需要各自执行 setup。查看某个主控最终采用的配置：

```sh
node bin/config.mjs show --host codex   # 或 claude、antigravity、t3
```

共享部分写角色、评审组和推理强度；具体模型 ID 写在 `hosts.codex`、`hosts.claude` 或 `hosts.t3` 里，优先于共享设置，这样一家厂商的模型 ID 不会传给另一家。外部 Agent 自己的模型是例外，例如 `xagent:claude/claude-opus-5-5` 可以写在共享配置里，规则见 [xagent 技能](./skills/xagent/SKILL.md)。修改偏好时调用 `setup-pstack`，它只改你要求的部分。

## 进一步阅读

- [使用指南](./docs/guide/README.md)：安装、理解代码、设计、实现、验证、长任务和常见问题。
- [英文 README](./README.md)：完整技能清单、示例和工程原则。
- [适配说明](./ADAPTATION.md)：本版本与上游的差异、跟进上游的规则和验证方法。
- [CI 指南](./docs/ci.md)：本地检查与 fork 守卫。
- [共享运行时约定](./references/runtime.md)：配置、委派、授权和证据标准。

## 许可证

[MIT](./LICENSE)。
