#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 core/ 的单一源，构建成各 harness 的适配产物。

设计原则：**只有一个源**。四份适配不允许各自维护正文，否则必然漂移。
各 harness 的差异只体现在两处：frontmatter 的字段、以及"有没有文件访问能力"。

用法：
    python build.py            # 生成 dist/
    python build.py --check    # 只校验，不写盘（CI 用）
"""

import argparse
import io
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(HERE, "core")
DIST = os.path.join(HERE, "dist")
ADAPTERS = os.path.join(HERE, "adapters")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def read(p):
    with io.open(p, encoding="utf-8") as fh:
        return fh.read()


def write(p, s):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)


def split_frontmatter(text):
    """返回 (frontmatter dict, body)。只支持本项目用到的简单 key: value。"""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm, text[m.end():]


def dump_frontmatter(d):
    return "---\n" + "\n".join("%s: %s" % (k, v) for k, v in d.items()) + "\n---\n"


def copy_tree(src, dst):
    for root, _, files in os.walk(src):
        rel = os.path.relpath(root, src)
        for f in files:
            s = os.path.join(root, f)
            d = os.path.join(dst, rel, f) if rel != "." else os.path.join(dst, f)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copyfile(s, d)


# ---------------------------------------------------------------- 各 harness

def build_workbuddy(fm, body):
    """WorkBuddy：原样。技能目录 ~/.workbuddy-ai/skills/prompt-forge/"""
    out = os.path.join(DIST, "workbuddy", "prompt-forge")
    write(os.path.join(out, "SKILL.md"), dump_frontmatter(fm) + body)
    copy_tree(os.path.join(CORE, "references"), os.path.join(out, "references"))
    copy_tree(os.path.join(CORE, "scripts"), os.path.join(out, "scripts"))


def build_claude_code(fm, body):
    """Claude Code：.claude/skills/<name>/SKILL.md，frontmatter 只认 name/description。"""
    keep = {"name": fm.get("name", "prompt-forge"),
            "description": fm.get("description", "")}
    out = os.path.join(DIST, "claude-code", ".claude", "skills", "prompt-forge")
    write(os.path.join(out, "SKILL.md"), dump_frontmatter(keep) + body)
    copy_tree(os.path.join(CORE, "references"), os.path.join(out, "references"))
    copy_tree(os.path.join(CORE, "scripts"), os.path.join(out, "scripts"))


def build_codex(fm, body):
    """Codex：仓库根或 ~/.codex/AGENTS.md。Codex 没有技能目录，靠一份指引文件。"""
    header = read(os.path.join(ADAPTERS, "codex", "HEADER.md"))
    out = os.path.join(DIST, "codex")
    write(os.path.join(out, "AGENTS.md"), header + body)
    copy_tree(os.path.join(CORE, "references"), os.path.join(out, "prompt-forge", "references"))
    copy_tree(os.path.join(CORE, "scripts"), os.path.join(out, "prompt-forge", "scripts"))


def build_deepseek(fm, body):
    """DeepSeek：多数入口没有文件系统，只能粘贴。用自包含的浓缩版。

    浓缩版手写在 adapters/deepseek/SYSTEM_PROMPT.md；tests/test_build.py 会断言
    I1–I13 一条不少，防止它与 core 漂移。
    """
    src = os.path.join(ADAPTERS, "deepseek", "SYSTEM_PROMPT.md")
    write(os.path.join(DIST, "deepseek", "SYSTEM_PROMPT.md"), read(src))


BUILDERS = {
    "workbuddy": build_workbuddy,
    "claude-code": build_claude_code,
    "codex": build_codex,
    "deepseek": build_deepseek,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验，不写盘")
    args = ap.parse_args()

    fm, body = split_frontmatter(read(os.path.join(CORE, "SKILL.md")))
    if not fm.get("name") or not fm.get("description"):
        print("core/SKILL.md 缺少 name 或 description", file=sys.stderr)
        return 2

    if args.check:
        missing = [p for p in BUILDERS if not os.path.isdir(os.path.join(DIST, p))]
        if missing:
            print("dist 尚未构建：%s" % ", ".join(missing), file=sys.stderr)
            return 3
        print("dist 已存在，共 %d 个目标。" % len(BUILDERS))
        return 0

    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    for name, fn in BUILDERS.items():
        fn(fm, body)
        print("built %s" % name)
    print("\n输出目录：%s" % DIST)
    return 0


if __name__ == "__main__":
    sys.exit(main())
