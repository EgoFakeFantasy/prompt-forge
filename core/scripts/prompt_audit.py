#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prompt_audit.py — 提示词规格诊断器（确定性启发式）

定位：只做"缺什么"的客观清点，不做"好不好"的主观评判。
所有输出都是可复核的规则命中，不含模型判断，因此可以被信任为
改写前后的对比基线（同一脚本跑两次，结果必然一致）。

用法：
    python prompt_audit.py audit --file req.txt
    cat req.txt | python prompt_audit.py audit
    python prompt_audit.py audit --file req.txt --json
    python prompt_audit.py ledger add --tier T2 --score 41 --patterns spec,contract --outcome ok --note "..."
    python prompt_audit.py ledger stats
"""

import argparse
import datetime
import json
import os
import re
import sys
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

LEDGER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ledger.jsonl")

# ---------------------------------------------------------------- 规格槽位
# (key, 中文名, 权重, 命中即视为该槽位已存在, 缺失时的改写动作)
SLOTS = [
    ("goal", "目标动作", 12,
     r"实现|完成|生成|写一?[个份篇]|做一?[个份]|分析|对比|评估|排查|修复|重构|翻译|转换|导出|总结|调研|设计|制定|给出|列出|解释|证明|核对|审查|清理|整理|删掉|移除|替换|补全|跑一遍|只改|改正|改掉|改成",
     "补一个动词开头的目标句：产出什么 + 用来干什么"),

    ("deliverable", "交付物载体", 15,
     r"报告|文档|表格|清单|代码|脚本|函数|网页|页面|PPT|幻灯片|图片|图表|思维导图|JSON|CSV|Markdown|\.md\b|\.py\b|\.xlsx\b|\.docx\b|\.pptx\b|文件|链接|回复里直接",
     "指定载体与落盘位置：文件（含路径与扩展名）/ 聊天内直接回答 / 网页链接"),

    ("audience", "受众与用途", 6,
     r"给.{0,8}(看|用|读)|面向|受众|读者|客户|老板|领导|同事|新人|非技术|专家|内部|对外|用于",
     "补受众与用途（决定术语密度与详略）"),

    ("constraints", "硬约束", 12,
     r"必须|不得|不要|禁止|只能|仅限|不超过|至少|最多|控制在|字数|篇幅|风格|语气|技术栈|版本|兼容|离线|免费|开源|预算|时限",
     "补硬约束：长度 / 风格 / 技术栈 / 版本 / 禁项"),

    ("acceptance", "验收标准", 18,
     r"验收|通过标准|成功判据|判据|满足以下|检查项|自检|测试通过|能运行|跑通|可复现|准确率|覆盖率|对照|逐条|符合",
     "补 3-6 条可机械检查的验收标准（判据要能被第三方复算）"),

    ("inputs", "输入材料指向", 12,
     r"[A-Za-z]:[\\/]|https?://|附件|上传|\.pdf\b|\.xlsx\b|\.csv\b|\.txt\b|@\w|本地文件|下面的|以下内容|数据源|表[一二三四五]|第\s*\d+\s*(行|列|页|章)",
     "把「那个文件/上面的数据」换成具体路径、URL 或粘贴的原文"),

    ("scope", "范围与边界", 10,
     r"只|仅|不要涉及|不包含|排除|范围|限定|先不|暂时不|除此之外|边界|不做",
     "划边界：明确「这次不做什么」，防止范围蔓延"),

    ("format", "输出格式契约", 15,
     r"格式|结构|分[点条]|小节|标题|表格[^\n]{0,6}列|字段|模板|schema|大纲|先给结论|TL;?DR|列表|编号|代码块|JSON|YAML"
     r"|只输出|只允许|只能有|仅输出|原样输出|不要解释|不要任何其它",
     "给出输出骨架（小节标题 / 表格列名 / 字段名），而不是只说「整理一下」"),
]

# ---------------------------------------------------------------- 歧义信号
AMBIG = [
    ("模糊量词", r"一些|一点|稍微|适当|适量|尽量|大概|大约|差不多|左右|若干|等等|之类|什么的|合理地|酌情"),
    ("模糊动词", r"优化一?下|改进一?下|完善一?下|处理一?下|搞一?下|看一?下|弄一?下|调整一?下|润色一?下|提升|加强|丰富"),
    ("无着落指代", r"这个|那个|上面|刚才|之前(说|提)?的|前面|上次|原来的|现有的"),
    ("开放枚举", r"等[。，,\s]|之类|包括但不限于|such as|etc\.|and so on"),
    ("未定实体", r"某个|某家|XX|xxx|某某|待定|TBD|\?\?\?"),
]

# ---------------------------------------------------------------- 风险信号
RISK = [
    ("不可逆写入", r"删除|删掉|清空|覆盖|格式化|\brm\s+-rf\b|DROP\s+TABLE|\btruncate\b|批量重命名|移动文件"),
    ("对外发布", r"发布|上线|部署|\bdeploy\b|\bgit push\b|发邮件|发送给|群发|公告|提交到|\bPR\b|合并到\s*main"),
    ("资金交易", r"支付|付款|下单|转账|退款|订阅|购买"),
    ("权限与凭证", r"\btoken\b|密钥|密码|凭证|\bAPI\s*key\b|私钥|授权|\bsudo\b|管理员"),
]

# ---------------------------------------------------------------- 任务类型
TASK_TYPES = [
    ("code", r"代码|脚本|函数|类|bug|报错|异常|实现|重构|接口|API|python|javascript|typescript|java|go\b|rust|sql|react|vue|编译|部署|依赖"),
    ("writing", r"写|撰写|起草|文案|文章|稿件|报告|文档|总结|润色|改写|扩写|缩写|标题|邮件|周报"),
    ("analysis", r"分析|对比|评估|诊断|归因|统计|指标|趋势|数据|报表|透视|相关性|回归|漏斗|留存"),
    ("research", r"查|搜|调研|资料|来源|引用|核实|事实|最新|新闻|论文|文献|竞品"),
    ("decision", r"选|建议|方案|取舍|推荐|决策|值不值|该不该|哪个好|优先级|排期"),
    ("transform", r"转换|转成|导出|翻译|格式化|清洗|提取|解析|OCR|截图"),
    ("meta", r"提示词|prompt|技能|skill|工作流|自动化|规则|流程"),
]

# ---------------------------------------------------------------- 计分阈值
AMBIG_PENALTY_PER_HIT = 3   # 每处歧义信号扣的分
AMBIG_PENALTY_CAP = 24      # 歧义扣分上限
SKIP_SCORE = 78             # 达到此分且无缺失槽位时不必改写
CONFIRM_SCORE = 55          # 有风险信号且低于此分时先确认
T1_MAX_MISSING = 3          # 缺失槽位不超过此数时只需微改写（T1）
ONE_LINER_CHARS = 30        # 短于此长度视为一行需求

VAGUE_QUANT = re.compile(r"一些|一点|稍微|适当|尽量|大概|大约|差不多|左右|若干|等等|之类|什么的")

# 回复形态的绝对约束：命中即禁止任何扩写（追加内容本身就在违反它）
FORM_CONTRACT = (
    r"只输出|只允许|只能有|只准|仅输出|仅返回|整个回复|原样输出|不要输出|不许输出"
    r"|不要任何其它|不要解释|不要代码块围栏"
)

# 终止/异常出口：命中即禁止稀释（改写不得把它降级成"交付分支之一"）
TERMINATION = r"若.{0,14}无法|如果.{0,14}不能|无法同时满足|不能满足|若以上|否则.{0,8}只|无解"

# 审美类约束：不可转成指标，只能用锚定传递（I12）
SUBJECTIVE = (
    r"精美|好看|美观|有吸引力|吸引人|高级感|质感|氛围|惊艳|优雅|有设计感"
    r"|酷炫|炫酷|精致|大气|高级|有品味|有味道|视觉冲击"
)


def _hits(text, pattern):
    # 用 finditer 取整段匹配：避免模式里的捕获组把结果替换成组内容
    return [m.group(0) for m in re.finditer(pattern, text, flags=re.IGNORECASE)]


def _w(s):
    """终端显示宽度：CJK 记 2 列。"""
    return sum(2 if ord(c) > 0x2E80 else 1 for c in s)


def _pad(s, width):
    return s + " " * max(0, width - _w(s))


def ambiguity_penalty(hits):
    """歧义扣分：每处固定扣分，总额封顶。"""
    return min(hits * AMBIG_PENALTY_PER_HIT, AMBIG_PENALTY_CAP)


def detect_task_type(text):
    """取命中次数最多的任务类型；并列时取 TASK_TYPES 中靠前者，全不命中为 general。"""
    ttype, best = "general", 0
    for name, pattern in TASK_TYPES:
        c = len(_hits(text, pattern))
        if c > best:
            ttype, best = name, c
    return ttype


def decide_verdict(score, missing, present_keys, risk, form_contract, terminate):
    """裁决：脚本只给建议，最终由 P1.5 的"猜测面"三问决定。返回 (verdict, reason)。"""
    if form_contract and {"goal", "deliverable", "format"} <= present_keys:
        return "skip", "输出形态已被「只输出/只能有」唯一确定，任何扩写都会自相矛盾"
    if terminate:
        return "skip", "用户给了明确的终止/异常出口，改写会稀释它"
    if score >= SKIP_SCORE and not missing:
        return "skip", "适用槽位齐全，执行者没有猜测空间"
    if risk and score < CONFIRM_SCORE:
        return "confirm", "高风险且欠定义，先确认再动手"
    return "rewrite", "存在适用槽位缺失：%s" % "、".join(m["label"] for m in missing)


def tier_for(verdict, missing):
    """把裁决映射到 T0–T3 档位。"""
    if verdict == "confirm":
        return "T3"
    if verdict == "skip":
        return "T0"
    return "T1" if len(missing) <= T1_MAX_MISSING else "T2"


def audit(text):
    text = text.strip()
    n_chars = len(text)
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))

    ttype = detect_task_type(text)

    # 槽位适用性：自包含脚本任务没有"受众"，也没有"输入材料"可指
    external = bool(re.search(r"[A-Za-z]:[\\/]|https?://|附件|上传|\.(?:csv|xlsx|log|json|txt|pdf|md)\b", text))
    na = set()
    if ttype in ("code", "meta", "transform") and not re.search(r"给.{0,6}(看|读|用)|面向|受众", text):
        na.add("audience")
    if ttype in ("code", "transform") and not external:
        na.add("inputs")

    slots = []
    got, avail = 0, 0
    for key, label, weight, pattern, fix in SLOTS:
        found = _hits(text, pattern)
        present = bool(found)
        applies = key not in na
        if applies:
            avail += weight
            if present:
                got += weight
        slots.append({
            "key": key,
            "label": label,
            "weight": weight,
            "present": present,
            "applies": applies,
            "evidence": sorted(set(found))[:4],
            "fix": fix,
        })

    ambig = []
    ambig_total = 0
    for label, pattern in AMBIG:
        found = _hits(text, pattern)
        if found:
            ambig_total += len(found)
            ambig.append({"label": label, "count": len(found), "samples": sorted(set(found))[:5]})

    risk = []
    for label, pattern in RISK:
        found = _hits(text, pattern)
        if found:
            risk.append({"label": label, "samples": sorted(set(found))[:5]})

    raw_score = 100.0 * got / avail if avail else 0.0
    penalty = ambiguity_penalty(ambig_total)
    score = max(0, min(100, int(round(raw_score)) - penalty))

    missing = [s for s in slots if s["applies"] and not s["present"]]
    present_keys = {s["key"] for s in slots if s["present"]}

    form_contract = bool(_hits(text, FORM_CONTRACT))
    terminate = bool(_hits(text, TERMINATION))
    subjective = bool(_hits(text, SUBJECTIVE))

    verdict, reason = decide_verdict(score, missing, present_keys, risk, form_contract, terminate)
    tier = tier_for(verdict, missing)

    return {
        "chars": n_chars,
        "cjk_chars": cjk,
        "spec_score": score,
        "tier": tier,
        "verdict": verdict,
        "verdict_reason": reason,
        "form_contract": form_contract,
        "has_termination_clause": terminate,
        "subjective_quality": subjective,
        "task_type": ttype,
        "slots": slots,
        "not_applicable": sorted(na),
        "missing": [{"label": s["label"], "weight": s["weight"], "fix": s["fix"]} for s in missing],
        "ambiguity": ambig,
        "ambiguity_hits": ambig_total,
        "risk": risk,
        "one_liner": "一行说清目标" if n_chars < ONE_LINER_CHARS else "",
    }


def render_human(r):
    L = []
    L.append("提示词规格诊断  (确定性启发式，非模型判断)")
    L.append("=" * 52)
    L.append("长度 %d 字（中文 %d） | 任务类型 %s | 规格分 %d/100 | 建议档位 %s"
             % (r["chars"], r["cjk_chars"], r["task_type"], r["spec_score"], r["tier"]))
    L.append("裁决：%s  —— %s" % ({"skip": "不必改写", "rewrite": "建议改写", "confirm": "先确认"}.get(r["verdict"], r["verdict"]),
                                 r["verdict_reason"]))
    if r["form_contract"]:
        L.append("⚠ 检测到「只输出/只能有」类形态约束：追加任何内容都会破坏它（见 I9）")
    if r["has_termination_clause"]:
        L.append("⚠ 检测到终止/异常出口：改写不得稀释（见 I10）")
    if r["subjective_quality"]:
        L.append("⚠ 检测到审美类要求：不要转成指标，只能用参考锚 + 反例 + 场景传递（见 I12）")
    if r["not_applicable"]:
        L.append("（本任务不适用槽位：%s，不计分）" % "、".join(r["not_applicable"]))
    L.append("")
    L.append("[规格槽位]  ✔ 已有 / ✘ 缺失 / – 不适用（括号内为权重）")
    for s in r["slots"]:
        mark = "–" if not s["applies"] else ("✔" if s["present"] else "✘")
        ev = ("  ← " + ", ".join(s["evidence"])) if s["evidence"] else ""
        L.append("  %s %s(%2d)%s" % (mark, _pad(s["label"], 13), s["weight"], ev))
    if r["missing"]:
        L.append("")
        L.append("[缺失项 → 改写动作]")
        for m in r["missing"]:
            L.append("  · %s：%s" % (m["label"], m["fix"]))
    if r["ambiguity"]:
        L.append("")
        L.append("[歧义信号] 共 %d 处，扣 %d 分" % (r["ambiguity_hits"], ambiguity_penalty(r["ambiguity_hits"])))
        for a in r["ambiguity"]:
            L.append("  · %s ×%d：%s" % (a["label"], a["count"], ", ".join(a["samples"])))
    if r["risk"]:
        L.append("")
        L.append("[风险信号] —— 命中即需在改写后加确认闸门")
        for x in r["risk"]:
            L.append("  · %s：%s" % (x["label"], ", ".join(x["samples"])))
    L.append("")
    L.append("[档位含义]")
    L.append("  T0 规格已足 → 不改写，直接执行")
    L.append("  T1 缺 1-3 项 → 微改写（补输出契约 + 验收标准）")
    L.append("  T2 歧义多/缺项多 → 完整改写 + 假设台账")
    L.append("  T3 高风险且欠定义 → 先确认再动手，不得静默执行")
    return "\n".join(L)


def cmd_audit(args):
    if args.file:
        with open(args.file, "r", encoding="utf-8-sig") as f:
            text = f.read()
    else:
        text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    if not text.strip():
        print("输入为空。", file=sys.stderr)
        return 2
    r = audit(text)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(render_human(r))
    return 0


def cmd_ledger(args):
    path = os.path.normpath(LEDGER)
    if args.action == "add":
        rec = {
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "tier": args.tier,
            "score": args.score,
            "patterns": [p.strip() for p in (args.patterns or "").split(",") if p.strip()],
            "outcome": args.outcome,
            "note": args.note or "",
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print("已记录 → %s" % path)
        return 0

    if not os.path.exists(path):
        print("台账为空（尚无记录）。")
        return 0
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    if args.action == "list":
        for r in rows[-args.last:]:
            print("%s  %s  %s  [%s]  %s" % (r.get("ts", ""), r.get("tier", ""),
                                            r.get("score", ""), ",".join(r.get("patterns", [])),
                                            r.get("outcome", "")))
        return 0

    # stats
    c = Counter()
    tot = Counter()
    for r in rows:
        for p in r.get("patterns", []):
            tot[p] += 1
            if r.get("outcome") == "ok":
                c[p] += 1
    print("台账 %d 条记录" % len(rows))
    if not tot:
        return 0
    print("模式       使用  成功  成功率")
    for p, n in tot.most_common():
        print("%-10s %4d  %4d   %5.0f%%" % (p, n, c[p], 100.0 * c[p] / n))
    return 0


def main():
    ap = argparse.ArgumentParser(description="提示词规格诊断 / 改写台账")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("audit", help="诊断一段提示词")
    a.add_argument("--file", "-f", help="提示词文件路径；省略则读 stdin")
    a.add_argument("--json", action="store_true", help="输出 JSON")
    a.set_defaults(func=cmd_audit)

    ledger = sub.add_parser("ledger", help="改写台账")
    ledger.add_argument("action", choices=["add", "list", "stats"])
    ledger.add_argument("--tier")
    ledger.add_argument("--score", type=int)
    ledger.add_argument("--patterns", help="逗号分隔的改写模式 key，如 spec,contract,decompose")
    ledger.add_argument("--outcome", default="unknown", choices=["ok", "partial", "fail", "unknown"])
    ledger.add_argument("--note")
    ledger.add_argument("--last", type=int, default=10)
    ledger.set_defaults(func=cmd_ledger)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
