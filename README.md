# Prompt Forge

> 不改参数，只补规格。
> **A prompt-specification skill for Codex, Claude Code, DeepSeek and WorkBuddy.**
> It does not make the model stronger. It stops the model from guessing.

Prompt Forge 是一个**提示词规格补全**技能：在动手之前，把一段欠定义的请求补成执行者无需猜测的任务书，然后按它执行。

它补的是**规格**，不是**能力**。任务瓶颈在能力侧（算术、长链逻辑、精确复现）时，这套流程收益趋近于零——此时应该换工具或换执行者，而不是继续堆提示词。

---

## 它做什么

```
P0 抓取原文 → P1 诊断（八个槽位）→ P2 定档（T0–T3）
   → P3 改写（十三条不变量）→ P4 三重审核 → P5 确认闸门
   → P6 执行 → P7 交付（台账 + 证据缺口）
```

三条核心机制：

1. **三问定生死**——改写前必须过三问（会不会猜错目标 / 有没有没说但猜错就返工的硬约束 / 能不能验收）。**三问全否就是 T0，不改写**，无论诊断脚本给多少分。这条优先级高于脚本。
2. **十三条不变量**——每条都来自一次真实翻车，不是设计出来的原则（见下）。
3. **能力外置**——算术和长链逻辑不许指望"算得更仔细"，要用工具算完当材料喂进去。

## 它不做什么

- 不加人设、不加鼓励、不加恐吓来"提升表现"（实测 placebo 臂只比原话高 0.03）
- 不承诺提升模型能力
- 不把模糊需求改写成"我习惯的做法"再当需求执行
- 不在规格已精确的提示词上动手——**这是本流程最常见、也最昂贵的错误**

---

## 安装

四份适配由同一份 `core/SKILL.md` 构建，不会各自漂移（`tests/test_build.py` 会拦）。

```bash
git clone https://github.com/EgoFakeFantasy/prompt-forge.git
cd prompt-forge
python build.py          # 生成 dist/
```

### Claude Code

```bash
cp -r dist/claude-code/.claude ~/.claude          # 全局
# 或 cp -r dist/claude-code/.claude .claude       # 仅当前项目
```

技能位于 `.claude/skills/prompt-forge/`，含 `SKILL.md` + `references/` + `scripts/`。

### Codex

```bash
cp dist/codex/AGENTS.md ./AGENTS.md               # 项目级
# 或 cp dist/codex/AGENTS.md ~/.codex/AGENTS.md   # 全局
cp -r dist/codex/prompt-forge ./prompt-forge      # 脚本与参考
```

### DeepSeek（网页 / App / 纯 API）

没有文件系统访问的入口用自包含版：把 `dist/deepseek/SYSTEM_PROMPT.md` 整段粘进系统提示词即可。
它不依赖脚本，也不引用任何本地路径。

### WorkBuddy

```bash
cp -r dist/workbuddy/prompt-forge ~/.workbuddy-ai/skills/prompt-forge
```

---

## 快速试用

```bash
# 诊断一段提示词
python prompt-forge/scripts/prompt_audit.py audit --file request.txt

# 机器可读
python prompt-forge/scripts/prompt_audit.py audit --file request.txt --json
```

输出示例（一段**已经精确**的提示词，脚本正确判定不该改写）：

```
长度 92 字 | 任务类型 code | 规格分 78/100 | 建议档位 T0
裁决：不必改写 —— 输出形态已被「只输出/只能有」唯一确定，任何扩写都会自相矛盾
⚠ 检测到「只输出/只能有」类形态约束：追加任何内容都会破坏它（见 I9）
```

---

## 为什么值得信：十三条不变量都来自翻车

| # | 不变量 | 它来自哪次失败 |
|---|---|---|
| I1–I6 | 保意图 / 只加可验证项 / 显式假设 / 约束只增不减 / 长度预算 / 输出契约优先 | 初版设计 |
| I7 | 素材对齐 | 要求模型写"发生时间"，材料里没有，模型编了"今日下午" |
| I8 | 能力外置 | 加"先列中间量再汇总"，4B 模型成绩 0.70 → 0.48；改成"写代码算" → 0.00 |
| I9 | 形态契约不可扩写 | 给"只准一行"的任务追加 5 条验收，回复从 1 行变 31 行 |
| I10 | 终止条件不可稀释 | 给"无解则回 CONFLICT"补交付说明，模型改为硬写代码 |
| I11 | 置信度不衰减 | 正文标"推断（强）"，结尾写成陈述句 |
| I12 | 审美用锚定不用指标 | 把"精美"翻译成对比度/留白率，产出符合指标但没有味道 |
| I13 | 指标要交代盲区 | 用"字节相同率 0%"描述两个分支，掩盖了"内容重复 91%" |

## 实测数据

被测对象 `qwen3.5:4b`，temperature 0.7，每臂 3 次重复，判分全为确定性脚本：

| 任务 | 原话 | 只加"请仔细思考" | 改写后 |
|---|---|---|---|
| 数据汇总（JSON 契约） | 0.00 | 0.00 | 0.70 |
| 日志统计脚本 | 0.47 | 0.40 | 0.87 |
| 清理文件（不可逆） | 0.67 | 0.92 | 1.00 |
| 客户故障说明 | 0.61 | 0.56 | 0.83 |
| **平均** | **0.44** | **0.47** | **0.85** |

代价：提示词 136 → 381 字（+180%），输出 1363 → 561 字（−59%），总字符数反而下降。

**红队测试**：四个"本来就精确"的编程任务上，v2 净收益约等于零且局部受损；v3 修正后四个全部判 T0 不改写。

完整报告见 [`docs/`](docs/)。

---

## 仓库结构

```
core/                     ← 单一源。改规则只改这里
  SKILL.md
  references/*.md
  scripts/prompt_audit.py
adapters/                 ← 各 harness 的差异层（只放 header / 浓缩版）
  claude-code/  codex/  deepseek/
build.py                  ← 从 core 生成 dist/
dist/                     ← 构建产物（不入库，CI 生成）
tests/test_build.py       ← 护栏：每个适配必须覆盖全部不变量
```

**为什么只有一个源**：四份手写文档必然漂移。这里的做法是 core 出正文，adapter 只出差异，测试断言"每个产物都含 I1–I13"。

---

## 局限（写在最前面，免得误用）

- 实测只在 **4B 级小模型**上做过，强模型上差异大概率缩小
- **能力瓶颈无效**：算术、长链逻辑、精确复现，改写帮不上忙，硬加要求还会反伤
- 诊断脚本是**词表启发式**，换个说法就可能绕过；它只做清点，不做裁决
- 三问依赖判断力；使用者本身是弱模型时，可能草率答"否"而漏改写
- 判分是代理指标：0.85 不代表"好 0.85"，只代表"该做到的都做到了"

---

## License

MIT。见 [LICENSE](LICENSE)。
