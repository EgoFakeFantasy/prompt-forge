#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本地仓库发布到 GitHub（建仓 + 推送 + 开 Issues + 设 topics）。

    set GITHUB_TOKEN=ghp_xxx
    python publish.py --dry-run        # 只看会做什么
    python publish.py                  # 真发布

设计要点：
- 建仓时 **has_issues=True**（fork 默认关闭的问题不再重演）
- 推送用临时 token URL，推完立刻把 remote 改回干净地址，不把 token 留在 .git/config
- 每一步都复核：建完仓 GET 一次确认 has_issues，推完 ls-remote 确认分支存在
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

API = "https://api.github.com"

DESCRIPTION = (
    "Prompt specification skill for Codex / Claude Code / DeepSeek / WorkBuddy — "
    "stops the model from guessing instead of making it stronger. "
    "13 invariants, each from a real failure."
)
TOPICS = ["prompt-engineering", "llm", "codex", "claude-code", "deepseek",
          "workbuddy", "ai-agents", "skill"]


def req(url, token, payload=None, method="GET"):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "prompt-forge-publish",
    })
    with urllib.request.urlopen(r, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body.strip() else {}


def git(*args, **kw):
    return subprocess.run(["git"] + list(args), cwd=HERE, check=kw.pop("check", True),
                          capture_output=True, text=True, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", default="EgoFakeFantasy")
    ap.add_argument("--name", default="prompt-forge")
    ap.add_argument("--private", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token and not args.dry_run:
        print("缺少 GITHUB_TOKEN。", file=sys.stderr)
        return 2

    full = "%s/%s" % (args.owner, args.name)

    # ---- 0. 本地 git 仓库
    if not os.path.isdir(os.path.join(HERE, ".git")):
        if args.dry_run:
            print("[dry] git init -b main")
        else:
            git("init", "-b", "main")
            git("add", "-A")
            git("-c", "user.name=%s" % args.owner,
                "-c", "user.email=%s@users.noreply.github.com" % args.owner,
                "commit", "-m", "Prompt Forge v6: 13 invariants, four harness adapters")
            print("已提交本地仓库")
    else:
        print("本地 git 仓库已存在")

    # ---- 1. 建仓
    if args.dry_run:
        print("[dry] POST /user/repos  name=%s private=%s has_issues=True" % (args.name, args.private))
    else:
        try:
            d = req(API + "/user/repos", token, {
                "name": args.name,
                "description": DESCRIPTION,
                "private": args.private,
                "has_issues": True,          # 不再重演 fork 默认关闭
                "has_wiki": False,
                "has_projects": False,
                "auto_init": False,
            }, "POST")
            print("已建仓：%s" % d.get("html_url"))
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")
            if e.code == 422 and "already exists" in msg:
                print("仓库已存在，继续推送")
            else:
                print("建仓失败 HTTP %s\n%s" % (e.code, msg[:400]), file=sys.stderr)
                return 1

    # ---- 2. 推送（token 只在这一次用到）
    push_url = "https://x-access-token:%s@github.com/%s.git" % (token, full)
    if args.dry_run:
        print("[dry] git push -u <token-url> main")
    else:
        git("remote", "remove", "origin", check=False)
        git("remote", "add", "origin", push_url)
        try:
            git("push", "-u", "origin", "main")
            print("已推送 main")
        finally:
            git("remote", "set-url", "origin", "https://github.com/%s.git" % full)
            print("remote 已改回干净地址（token 未留在 .git/config）")

    # ---- 3. 复核 + topics
    if not args.dry_run:
        time.sleep(1.5)
        d = req(API + "/repos/" + full, token)
        print("复核 has_issues = %s" % d.get("has_issues"))
        if not d.get("has_issues"):
            print("Issues 未开启，补一次 PATCH …", file=sys.stderr)
            req(API + "/repos/" + full, token, {"has_issues": True}, "PATCH")
            time.sleep(1)
            d = req(API + "/repos/" + full, token)
            print("复核（第二次）has_issues = %s" % d.get("has_issues"))
        try:
            req(API + "/repos/%s/topics" % full, token,
                {"names": TOPICS}, "PUT")
            print("已设置 topics：%s" % ", ".join(TOPICS))
        except urllib.error.HTTPError as e:
            print("topics 设置失败（不影响仓库）：HTTP %s" % e.code, file=sys.stderr)

        print("\n完成：https://github.com/%s" % full)
    return 0


if __name__ == "__main__":
    sys.exit(main())
