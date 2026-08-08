#!/usr/bin/env python3
"""
Fires on Claude Code Stop event.

Reads the session transcript; if significant work happened (file edits or
substantial shell activity), asks Claude to run /wiki-capture --quick so
findings aren't silently lost at session end.

Exit 0 → no-op (nothing worth capturing, or hook suppressed).
Exit 2 → stderr content is fed back to Claude as a user message, triggering capture.

The stop_hook_active flag in the payload prevents re-entry (this hook won't
fire again for the follow-up capture turn).

Sessions with zero file edits whose shell commands are all read-only are exempt.
"""

import json
import os
import re
import shlex
import sys
import time
from pathlib import Path


# ── Classifier (same logic as the original embedded Python) ──────

READONLY_CMDS = {
    "cat", "ls", "head", "tail", "grep", "egrep", "fgrep", "rg", "fd",
    "wc", "echo", "printf", "pwd", "which", "whereis", "type", "file", "stat",
    "du", "df", "ps", "printenv", "id", "whoami", "uname",
    "true", "false", "test", "[", "diff", "cmp", "tree", "basename", "dirname",
    "readlink", "realpath", "cut", "tr", "column", "jq",
    "md5", "md5sum", "shasum", "sha256sum", "hexdump", "xxd", "strings",
    "less", "more", "nl", "od", "seq", "sleep", "uptime", "dig", "host",
    "nslookup", "sw_vers",
    "cd", "pushd", "popd", "export", "unset", "umask", "ulimit", "shopt",
    "set", "local", "declare", "typeset", "read", "wait", ":",
    "man", "whatis", "apropos", "hostname", "arch", "nproc", "getconf",
    "locale", "groups", "tty", "clear",
}

GIT_READONLY = {
    "status", "log", "diff", "show", "rev-parse", "describe", "blame",
    "shortlog", "ls-files", "ls-tree", "ls-remote", "grep", "reflog",
    "cat-file", "count-objects",
}

GH_READONLY = {"view", "list", "status", "diff", "checks"}

CORE_READONLY_TOOLS = {
    "Read", "Glob", "Grep", "LS", "WebFetch", "WebSearch", "TodoWrite",
    "TodoRead", "NotebookRead", "AskUserQuestion",
    "ToolSearch", "Skill", "SkillSearch", "SlashCommand", "EnterPlanMode",
    "ExitPlanMode", "Explore", "Plan",
    "TaskCreate", "TaskUpdate", "TaskGet", "TaskList", "TaskOutput",
    "TaskStop", "BashOutput", "KillShell", "SendUserFile", "Monitor",
    "ScheduleWakeup", "ListMcpResourcesTool", "ReadMcpResourceTool",
    "ReadMcpResourceDirTool",
}

READONLY_AGENT_TYPES = {"Explore", "Plan"}

MCP_READ_VERBS = {
    "get", "list", "search", "read", "query", "fetch", "find", "describe",
    "inspect", "explain", "compare", "view", "check", "status", "whoami",
    "analyze", "show", "health", "info", "download", "lookup",
    "browse", "watch", "screenshot",
}

MCP_WRITE_VERBS = {
    "create", "update", "delete", "remove", "write", "insert", "upsert",
    "execute", "run", "send", "post", "put", "patch", "move", "add", "set",
    "complete", "archive", "clone", "push", "upload", "provision", "reset",
    "apply", "schedule", "cancel", "start", "stop", "restart", "deploy",
    "publish", "merge", "commit", "approve", "assign", "register", "enable",
    "disable", "duplicate", "prepare",
}

SQL_TOOL_HINT = {"sql", "statement", "query", "database", "db"}

SQL_WRITE_RX = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|grant|revoke|vacuum)\b"
    r'|"analyze"\s*:\s*true',
    re.IGNORECASE,
)

WRAPPERS = {"sudo", "command", "nohup", "time", "xargs", "env", "nice", "stdbuf"}
FIND_MUTATING_FLAGS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fls"}
HARMLESS_REDIRECTS = re.compile(r"\s*(2>&1|&?>{1,2}\s*/dev/null|2>{1,2}\s*/dev/null)")
ENV_TOKEN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

PY_RISKY = re.compile(
    r"subprocess|shutil\.|socket|http\.client|HTTPConnection"
    r"|\bexec\s*\(|\beval\s*\(|__import__"
    r"|import\s+os\s+as|from\s+os\s+import"
    r"|os\.(system|popen|remove|unlink|rename|replace|rmdir|mkdir|makedirs"
    r"|chmod|chown|symlink|link|truncate|environ\[)"
    r"|\.write\w*\(|\.unlink\(|\.touch\(|\.mkdir\(|\.rename\(|\.rmdir\("
    r"|\.save\(|\.to_csv\(|\.to_excel\(|\.commit\("
    r"|\.execute(many|script)?\s*\("
    r'|\.open\(\s*[\"\'][wax]'
    r"|open\([^()]*,\s*[\"']?[wax]|open\([^()]*mode\s*=\s*[\"'][wax]"
    r"|urlopen\([^()]*data|Request\([^()]*data|requests\.(post|put|patch|delete)"
    r"|INSERT INTO|DELETE FROM|DROP TABLE|CREATE TABLE|ALTER TABLE"
    r"|smtplib|ftplib|paramiko|os\.kill",
    re.IGNORECASE,
)

AWK_RISKY = re.compile(
    r">>?\s*[\"'A-Za-z_]|\|\s*[\"'A-Za-z_]|[\"']\s*\|"
    r"|system\s*\(|close\s*\(|getline"
)


def split_segments(cmd):
    """Split on |, ||, &&, ;, newline — but never inside quotes."""
    segs = []
    buf, ubuf, ebuf = [], [], []
    quote = None
    i, n = 0, len(cmd)

    def close():
        segs.append(("".join(buf), "".join(ubuf), "".join(ebuf)))
        buf.clear()
        ubuf.clear()
        ebuf.clear()

    while i < n:
        c = cmd[i]
        if quote:
            buf.append(c)
            if quote == '"':
                ebuf.append(c)
            if c == quote:
                bs = 0
                j = i - 1
                while j >= 0 and cmd[j] == "\\":
                    bs += 1
                    j -= 1
                if quote == "'" or bs % 2 == 0:
                    quote = None
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
            buf.append(c)
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            buf.append(cmd[i : i + 2])
            ubuf.append(cmd[i + 1])
            i += 2
            continue
        if cmd[i : i + 2] in ("||", "&&"):
            close()
            i += 2
            continue
        if c in (";", "|", "\n"):
            close()
            i += 1
            continue
        buf.append(c)
        ubuf.append(c)
        ebuf.append(c)
        i += 1
    close()
    return segs


def tokenize(text):
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def segment_readonly(seg, unquoted, expandable):
    seg = seg.strip().lstrip("(!").strip()
    if not seg:
        return True
    if ">" in HARMLESS_REDIRECTS.sub(" ", unquoted):
        return False
    if "$(" in expandable or "`" in expandable or "<(" in expandable or ">(" in expandable:
        return False
    tokens = tokenize(seg)
    while tokens:
        head = tokens[0].rsplit("/", 1)[-1]
        if head in WRAPPERS or ENV_TOKEN.match(tokens[0]):
            tokens = tokens[1:]
            continue
        if head == "timeout":
            tokens = tokens[2:]
            continue
        break
    if not tokens:
        return True
    cmd = tokens[0].rsplit("/", 1)[-1]
    args = tokens[1:]

    if cmd == "find":
        return not any(t in FIND_MUTATING_FLAGS or t.startswith("-fprint") for t in args)
    if cmd == "fd":
        return not any(t in ("-x", "--exec", "-X", "--exec-batch") for t in args)
    if cmd == "rg":
        return not any(t == "--pre" or t.startswith("--pre=") for t in args)
    if cmd == "tree":
        return not any(t == "-o" for t in args)
    if cmd == "hostname":
        return not [t for t in args if not t.startswith("-")]
    if cmd == "xxd":
        return len([t for t in args if t == "-" or not t.startswith("-")]) < 2
    if cmd in ("less", "more"):
        return not any(
            t in ("-o", "-O") or t.startswith("--log-file") or t.startswith("--LOG-FILE")
            for t in args
        )
    if cmd == "sort":
        return not any(
            t == "-o" or t.startswith("--output") or (t.startswith("-o") and len(t) > 2)
            for t in args
        )
    if cmd == "uniq":
        return len([t for t in args if t == "-" or not t.startswith("-")]) < 2
    if cmd == "date":
        if any(t == "-s" or t.startswith("--set") for t in args):
            return False
        if "-j" in args:
            return True
        return not [t for t in args if not t.startswith("-") and not t.startswith("+")]
    if cmd == "sysctl":
        return not any(t == "-w" or "=" in t for t in args)
    if cmd == "awk":
        if any(t == "-i" or t.startswith("inplace") for t in args):
            return False
        return not AWK_RISKY.search(seg)
    if cmd in READONLY_CMDS:
        return True
    if cmd == "sed":
        if any(t.startswith("-i") or t == "--in-place" for t in args):
            return False
        return not any(
            re.search(r"(^|;)\s*w\s|[^\w\s]w(\s|$)", t) for t in args
        )
    if cmd == "history":
        return not any(t.startswith("-") and t != "--" for t in args)
    if cmd == "git":
        if any(
            t.startswith("--output")
            or t.startswith("--upload-pack")
            or t.startswith("--receive-pack")
            or t.startswith("--exec")
            for t in args
        ):
            return False
        positional = [t for t in args if not t.startswith("-")]
        sub = positional[0] if positional else ""
        if sub == "reflog":
            return len(positional) < 2 or positional[1] == "show"
        return sub in GIT_READONLY
    if cmd == "gh":
        rest = [t for t in args if not t.startswith("-")]
        return bool(rest) and (rest[0] in GH_READONLY or (len(rest) > 1 and rest[1] in GH_READONLY))
    if cmd in ("python", "python3"):
        if "-V" in args or "--version" in args:
            return True
        return "-c" in args and not PY_RISKY.search(seg)
    if cmd == "curl":
        long_writes = {
            "--output", "--output-dir", "--remote-name", "--upload-file",
            "--form", "--form-string", "--json", "--cookie-jar",
            "--dump-header", "--etag-save", "--quote", "--config",
        }
        for idx, t in enumerate(args):
            if t in long_writes or t.startswith("--data") or t.startswith("--trace"):
                return False
            if t == "--request":
                method = args[idx + 1] if idx + 1 < len(args) else ""
                if method.upper() not in ("GET", "HEAD"):
                    return False
            elif t.startswith("--"):
                continue
            elif t.startswith("-X"):
                method = t[2:] or (args[idx + 1] if idx + 1 < len(args) else "")
                if method.upper() not in ("GET", "HEAD"):
                    return False
            elif re.match(r"^-[A-Za-z]*[dDoOTFXcQK]", t):
                return False
        return True
    return False


def command_readonly(cmd):
    return all(segment_readonly(*parts) for parts in split_segments(cmd))


def classify_transcript(transcript_path):
    """Count Write/Edit, Bash, mutating Bash, and suspicious tools."""
    write_edit = 0
    bash_count = 0
    mutating_bash = 0
    suspicious_tools = 0

    with open(transcript_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = entry.get("message") or {}
            if msg.get("role") != "assistant":
                continue
            for block in msg.get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = block.get("name", "")
                if name in ("Write", "Edit", "NotebookEdit"):
                    write_edit += 1
                elif name == "Bash":
                    bash_count += 1
                    command = (block.get("input") or {}).get("command", "")
                    if not command_readonly(command):
                        mutating_bash += 1
                elif name in CORE_READONLY_TOOLS:
                    continue
                elif name in ("Task", "Agent"):
                    agent_type = (block.get("input") or {}).get("subagent_type", "")
                    if agent_type not in READONLY_AGENT_TYPES:
                        suspicious_tools += 1
                elif name.startswith("mcp__"):
                    words = set(re.split(r"[-_]", name.rsplit("__", 1)[-1].lower()))
                    if any(w in MCP_WRITE_VERBS for w in words) or not any(
                        w in MCP_READ_VERBS for w in words
                    ):
                        suspicious_tools += 1
                    elif words & SQL_TOOL_HINT and SQL_WRITE_RX.search(
                        json.dumps(block.get("input") or {})
                    ):
                        suspicious_tools += 1
                else:
                    suspicious_tools += 1

    return write_edit, bash_count, mutating_bash, suspicious_tools


# ── Main hook logic ──────────────────────────────────────────────

def main():
    input_data = json.loads(sys.stdin.read())

    # Suppress if already in a stop-hook-triggered turn
    if input_data.get("stop_hook_active"):
        sys.exit(0)

    rearm_seconds = int(os.environ.get("WIKI_STOP_REARM_SECONDS", "21600"))
    rearm_edits = int(os.environ.get("WIKI_STOP_REARM_EDITS", "10"))
    session_id = input_data.get("session_id", "")
    tmpdir = os.environ.get("TMPDIR", "/tmp")
    sentinel = ""
    rearm_candidate = False

    if session_id:
        sentinel = Path(tmpdir) / f"wiki-stop-capture-{session_id}.done"
        if sentinel.exists():
            now = int(time.time())
            claimed_at = int(sentinel.stat().st_mtime)
            if now - claimed_at < rearm_seconds:
                sys.exit(0)
            rearm_candidate = True

    transcript_path = input_data.get("transcript_path", "")
    if not transcript_path or not Path(transcript_path).is_file():
        sys.exit(0)

    write_edit, bash_count, mutating_bash, suspicious_tools = classify_transcript(transcript_path)

    # Trigger if file edits >= 1, or bash >= 4 with mutating or suspicious activity
    trigger = (write_edit >= 1) or (
        bash_count >= 4 and (mutating_bash >= 1 or suspicious_tools >= 1)
    )

    if not trigger:
        sys.exit(0)

    # Re-arm gate: only re-fire when enough NEW edits since last nudge
    if rearm_candidate and sentinel:
        prev_edits = 0
        edits_file = sentinel / "edits"
        if edits_file.is_file():
            try:
                prev_edits = int(edits_file.read_text().strip())
            except (ValueError, OSError):
                prev_edits = 0
        if write_edit - prev_edits < rearm_edits:
            sys.exit(0)

        # Atomically retire the expired sentinel
        retired = sentinel.parent / f"{sentinel.name}.retired.{os.getpid()}"
        try:
            sentinel.rename(retired)
        except OSError:
            sys.exit(0)

        # Guard: if what we grabbed is young, put it back
        ret_at = int(retired.stat().st_mtime)
        if int(time.time()) - ret_at < rearm_seconds:
            try:
                retired.rename(sentinel)
                if not (sentinel / "edits").exists():
                    (sentinel / "edits").write_text(str(write_edit))
            except OSError:
                import shutil
                shutil.rmtree(retired, ignore_errors=True)
            sys.exit(0)

        import shutil
        shutil.rmtree(retired, ignore_errors=True)

    # Atomically claim the right to nudge
    if sentinel:
        try:
            sentinel.mkdir()
        except FileExistsError:
            sys.exit(0)
        (sentinel / "edits").write_text(str(write_edit))

    print(
        f"Session ended with {write_edit} file edit(s) and {bash_count} shell call(s). "
        "Please run /wiki-capture --quick now to preserve any reusable findings "
        "before this context closes.",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
