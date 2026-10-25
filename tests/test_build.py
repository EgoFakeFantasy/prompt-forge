#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建产物的护栏。

存在的理由：四份适配允许有差异，但不允许"漏掉某条不变量"。
没有这个测试，单一源就只是个口号——改了 core，dist 里少一条也没人知道。
"""

import io
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "dist")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def read(p):
    with io.open(p, encoding="utf-8") as fh:
        return fh.read()


def invariant_ids(text):
    """抓 I1..I13 的编号，返回集合。"""
    return set(re.findall(r"\bI(\d{1,2})\b", text))


class BuildArtifacts(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, os.path.join(ROOT, "build.py")],
                       check=True, cwd=ROOT, stdout=subprocess.DEVNULL)

    def core_ids(self):
        return invariant_ids(read(os.path.join(ROOT, "core", "SKILL.md")))

    def test_core_has_all_thirteen(self):
        ids = self.core_ids()
        expected = {str(i) for i in range(1, 14)}
        self.assertTrue(expected.issubset(ids),
                        "core 缺少不变量：%s" % sorted(expected - ids, key=int))

    def test_every_target_covers_all_invariants(self):
        """每个适配都必须覆盖 core 的全部不变量编号。"""
        core = self.core_ids()
        targets = {
            "workbuddy": os.path.join(DIST, "workbuddy", "prompt-forge", "SKILL.md"),
            "claude-code": os.path.join(DIST, "claude-code", ".claude", "skills",
                                        "prompt-forge", "SKILL.md"),
            "codex": os.path.join(DIST, "codex", "AGENTS.md"),
            "deepseek": os.path.join(DIST, "deepseek", "SYSTEM_PROMPT.md"),
        }
        for name, path in targets.items():
            self.assertTrue(os.path.exists(path), "%s 未生成：%s" % (name, path))
            missing = core - invariant_ids(read(path))
            self.assertFalse(missing, "%s 缺少不变量：%s" % (name, sorted(missing, key=int)))

    def test_frontmatter_is_valid(self):
        for name, path in {
            "workbuddy": os.path.join(DIST, "workbuddy", "prompt-forge", "SKILL.md"),
            "claude-code": os.path.join(DIST, "claude-code", ".claude", "skills",
                                        "prompt-forge", "SKILL.md"),
        }.items():
            text = read(path)
            m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
            self.assertIsNotNone(m, "%s frontmatter 缺失" % name)
            fm = m.group(1)
            self.assertIn("name:", fm)
            self.assertIn("description:", fm)

    def test_claude_code_frontmatter_is_minimal(self):
        """Claude Code 只认 name/description，多余字段可能被忽略或告警。"""
        path = os.path.join(DIST, "claude-code", ".claude", "skills",
                            "prompt-forge", "SKILL.md")
        fm = re.match(r"^---\n(.*?)\n---\n", read(path), re.S).group(1)
        keys = {l.split(":")[0].strip() for l in fm.splitlines() if ":" in l}
        self.assertEqual(keys, {"name", "description"})

    def test_deepseek_is_self_contained(self):
        """DeepSeek 版不能引用本地脚本或相对路径文件——那边没有文件系统。"""
        text = read(os.path.join(DIST, "deepseek", "SYSTEM_PROMPT.md"))
        for bad in ("scripts/prompt_audit.py", "references/", "core/"):
            self.assertNotIn(bad, text, "DeepSeek 版不应依赖 %s" % bad)

    def test_codex_points_at_script(self):
        text = read(os.path.join(DIST, "codex", "AGENTS.md"))
        self.assertIn("prompt_audit.py", text)

    def test_scripts_copied(self):
        for name, path in {
            "workbuddy": os.path.join(DIST, "workbuddy", "prompt-forge", "scripts", "prompt_audit.py"),
            "claude-code": os.path.join(DIST, "claude-code", ".claude", "skills",
                                        "prompt-forge", "scripts", "prompt_audit.py"),
            "codex": os.path.join(DIST, "codex", "prompt-forge", "scripts", "prompt_audit.py"),
        }.items():
            self.assertTrue(os.path.exists(path), "%s 未带脚本" % name)


class AuditScript(unittest.TestCase):
    """脚本本身的行为护栏：三条攻击样本必须判 skip，三条真实欠定义必须判 rewrite。"""

    @classmethod
    def setUpClass(cls):
        cls.script = os.path.join(ROOT, "core", "scripts", "prompt_audit.py")

    def audit(self, text):
        import json
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(text)
            path = fh.name
        try:
            out = subprocess.run([sys.executable, self.script, "audit", "--file", path, "--json"],
                                 capture_output=True, check=True)
            return json.loads(out.stdout.decode("utf-8"))
        finally:
            os.unlink(path)

    def test_precise_prompt_is_skipped(self):
        r = self.audit("写一个 Python 脚本 solve.py，从标准输入读一行两个整数 a 和 b（空格分隔），"
                       "把 a+b 打到标准输出。标准输出只允许出现结果本身，不要任何其它字符。非法输入不用管。")
        self.assertEqual(r["verdict"], "skip", r["verdict_reason"])
        self.assertEqual(r["tier"], "T0")

    def test_vague_prompt_is_rewritten(self):
        r = self.audit("把上面的销售数据按区域汇总一下。")
        self.assertEqual(r["verdict"], "rewrite")

    def test_termination_clause_protects(self):
        r = self.audit("用 Python 写 count_paths(n)，必须递归且支持 n=2000，禁止调 sys.setrecursionlimit。"
                       "若以上无法同时满足，不要写任何代码，只回复一行 CONFLICT: <原因>。")
        self.assertTrue(r["has_termination_clause"])
        self.assertEqual(r["verdict"], "skip")


if __name__ == "__main__":
    unittest.main(verbosity=2)
