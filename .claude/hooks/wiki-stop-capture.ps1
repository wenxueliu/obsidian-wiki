# Fires on Claude Code Stop event (Windows PowerShell).
#
# Reads the session transcript; if significant work happened, asks Claude
# to run /wiki-capture --quick so findings aren't silently lost.
#
# Exit 0 = no-op (nothing worth capturing).
# Exit 2 = stderr fed to Claude as a user message, triggering capture.
#
# Register in settings.json:
#   "Stop": [
#     {"command": "powershell", "args": ["-NoProfile", "-File", ".claude/hooks/wiki-stop-capture.ps1"]}
#   ]

param()

$ErrorActionPreference = "Stop"

$input = [Console]::In.ReadToEnd()
if (-not $input) { exit 0 }

try { $data = $input | ConvertFrom-Json }
catch { exit 0 }

# Suppress if already in a stop-hook-triggered turn
if ($data.stop_hook_active) { exit 0 }

# Fire at most once per session
$rearm_seconds = if ($env:WIKI_STOP_REARM_SECONDS) { [int]$env:WIKI_STOP_REARM_SECONDS } else { 21600 }
$rearm_edits = if ($env:WIKI_STOP_REARM_EDITS) { [int]$env:WIKI_STOP_REARM_EDITS } else { 10 }
$session_id = $data.session_id
$sentinel = $null
$rearm_candidate = $false

if ($session_id) {
    $tmp_dir = if ($env:TMPDIR) { $env:TMPDIR } elseif ($env:TMP) { $env:TMP } else { $env:TEMP }
    $sentinel = Join-Path $tmp_dir "wiki-stop-capture-$session_id.done"
    if (Test-Path $sentinel) {
        $now = [int](Get-Date -UFormat %s)
        $claimed_at = [int]((Get-Item $sentinel).LastWriteTimeUtc | New-TimeSpan -Start (Get-Date "1970-01-01") | Select-Object -ExpandProperty TotalSeconds)
        if ($now - $claimed_at -lt $rearm_seconds) {
            exit 0
        }
        $rearm_candidate = $true
    }
}

$transcript_path = $data.transcript_path
if (-not $transcript_path -or -not (Test-Path $transcript_path)) { exit 0 }

# Count meaningful tool uses
$write_edit = 0
$bash_count = 0
$mutating_bash = 0
$suspicious = 0

$readonly_cmds = @("cat", "ls", "head", "tail", "grep", "rg", "echo", "pwd", "which", "whereis", "type", "file", "wc", "diff", "findstr")
$git_readonly = @("status", "log", "diff", "show", "blame", "rev-parse", "ls-files", "ls-tree")
$gh_readonly = @("view", "list", "status", "diff")

Get-Content $transcript_path | ForEach-Object {
    $line = $_.Trim()
    if (-not $line) { return }
    try { $entry = $line | ConvertFrom-Json } catch { return }
    $msg = $entry.message
    if (-not $msg -or $msg.role -ne "assistant") { return }
    foreach ($block in $msg.content) {
        if ($block.type -ne "tool_use") { continue }
        $name = $block.name
        if ($name -in @("Write", "Edit", "NotebookEdit")) {
            $script:write_edit++
        }
        elseif ($name -eq "Bash") {
            $script:bash_count++
            $cmd = $block.input.command
            $base = (($cmd -split '\s+')[0] -split '/')[-1]
            if ($base -notin $script:readonly_cmds) {
                $args0 = ($cmd -split '\s+')[1]
                if ($base -eq "git" -and $args0 -notin $script:git_readonly) { $script:mutating_bash++ }
                elseif ($base -eq "gh" -and $args0 -notin $script:gh_readonly) { $script:mutating_bash++ }
                else { $script:mutating_bash++ }
            }
        }
        elseif ($name -in @("Task", "Agent")) {
            $agent_type = $block.input.subagent_type
            if ($agent_type -notin @("Explore", "Plan")) { $script:suspicious++ }
        }
        elseif ($name -notmatch "^Read$|^Glob$|^Grep$|^LS$|^WebFetch$|^WebSearch$|^Todo|^Skill$|^Ask") {
            $script:suspicious++
        }
    }
}

$trigger = ($write_edit -ge 1) -or ($bash_count -ge 4 -and ($mutating_bash -ge 1 -or $suspicious -ge 1))
if (-not $trigger) { exit 0 }

# Re-arm gate
if ($rearm_candidate -and $sentinel) {
    $prev_edits = try { [int](Get-Content "$sentinel\edits" -ErrorAction SilentlyContinue) } catch { 0 }
    if ($write_edit - $prev_edits -lt $rearm_edits) { exit 0 }
    $retired = "$sentinel.retired.$pid"
    try { Move-Item $sentinel $retired -ErrorAction Stop } catch { exit 0 }
    Remove-Item -Recurse $retired -ErrorAction SilentlyContinue
}

# Atomically claim the right to nudge
if ($sentinel) {
    try { New-Item -ItemType Directory $sentinel -ErrorAction Stop | Out-Null }
    catch { exit 0 }
    "$write_edit" | Out-File "$sentinel\edits" -Encoding utf8
}

"Session ended with $write_edit file edit(s) and $bash_count shell call(s). Please run /wiki-capture --quick now to preserve any reusable findings before this context closes." | Write-Error
exit 2
