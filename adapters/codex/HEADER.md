# AGENTS.md — Prompt Forge

> 本文件是 [prompt-forge](https://github.com/EgoFakeFantasy/prompt-forge) 的 Codex 适配版。
> Codex 在仓库根目录直接读取本文件；放到 `~/.codex/AGENTS.md` 可全局生效。

## 这是什么

一套**提示词规格补全**的流程：把一段欠定义的请求，补成执行者无需猜测的任务书，然后按它执行。
它补的是规格，不是能力。任务瓶颈在能力侧（算术、长链逻辑、精确复现）时，这套流程收益趋近于零——此时应改用工具或代码，而不是继续堆提示词。

## 何时触发

- 用户明确要求"优化 / 改写 / 自优化提示词"
- 任务约束多、歧义大、做错的代价高，值得先补规格
- 交付物形态不明确（要 JSON 还是表格？要文件还是回复？）

**不触发**：一句话事实查询、名词解释、闲聊、规格已精确的任务。

## 工具

```bash
python prompt-forge/scripts/prompt_audit.py audit --file <把请求原文写进文件>
python prompt-forge/scripts/prompt_audit.py audit --file <file> --json
python prompt-forge/scripts/prompt_audit.py ledger add --tier T2 --score 66 --outcome ok
```

脚本只做**清点**（八个槽位、歧义词、风险词、形态契约、终止出口），**不做裁决**。
裁决走下面的"三问"。

## 硬性要求

1. **脚本的裁决不是最终裁决。** 三问全否 → T0，不改写，无论脚本多少分。
2. **只有一个源。** 本文件与 `core/SKILL.md` 内容同源；改规则请改 core 再重新构建，不要只改这里。
3. **不要为了显得做了工作而改写。** 对已经精确的提示词动手，是本流程最常见、也最昂贵的错误。

---

