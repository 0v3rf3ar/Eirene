"""Read-only native command templates; no Python tree walking or text searching.

Arguments are data. Only these fixed templates qualify as trusted Windows reads.
Every child uses the command supervisor and the caller's execution policy.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shlex
import shutil
import sys
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import ToolError
from ..core.text import safe_text
from . import shell

POLICY = ContextVar("native_read_policy", default={})
SKIP = (
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".tox",
    "target",
    ".idea",
    ".next",
)
MAX_BYTES = 200_000


def sync(coro):
    """Compatibility for direct, synchronous callers; app tools use async APIs."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    coro.close()
    raise ToolError("native reads must be awaited inside an event loop")


async def command(box, argv, *, script=None, env=None, allowed=(0,), cap=MAX_BYTES):
    input_text = None
    if isinstance(script, PowerShellScript):
        input_text = script.data
        script = "$d=([Console]::In.ReadToEnd() | ConvertFrom-Json); " + script.body
    policy = dict(POLICY.get())
    if policy.get("isolation", "none") != "none":
        policy["read_paths"] = [str(p) for p in box._grants.get()]
    # Fixed argv/templates on Windows are trusted reads, not arbitrary shell text.
    if os.name == "nt":
        policy = {}
    result = await shell.run(
        script or shlex.join(argv),
        box.root,
        argv=argv if not script else None,
        shell_name="powershell" if os.name == "nt" and script else "auto",
        allow_blocked=True,
        timeout=30,
        max_bytes=cap,
        env=env,
        input_text=input_text,
        **policy,
    )
    if result.timed_out:
        raise ToolError("native read timed out; narrow the path or range")
    if result.exit_code not in allowed:
        raise ToolError("native command failed: " + result.summary())
    return result


@dataclass(frozen=True)
class PowerShellScript:
    data: str
    body: str

    def __add__(self, body):
        return PowerShellScript(self.data, self.body + body)


def ps_data(data):
    # Keep arbitrary paths/patterns out of executable script and Windows argv limits.
    return PowerShellScript(json.dumps(data), "")


async def inventory(
    box, path=".", pattern="", *, hidden=False, ignored=False, limit=10000, exclude=None
):
    root = box.resolve(path)
    if not root.is_dir():
        raise ToolError(f"{path} is not a directory")
    if pattern.startswith("/") or ".." in Path(pattern).parts:
        raise ToolError("pattern must be relative to the search directory")
    rg = shutil.which("rg")
    note = ""
    if rg:
        argv = [rg, "--files", "--null", "--color", "never"]
        if hidden:
            argv += ["--hidden"]
        if ignored:
            argv += ["--no-ignore"]
        if pattern:
            argv += ["-g", pattern]
        for name in SKIP:
            if not ignored or name == ".git":
                argv += ["-g", f"!**/{name}/**"]
        for value in exclude or []:
            argv += ["-g", "!" + value]
        argv += ["--", str(root)]
        result = await command(box, argv, allowed=(0, 1))
        raw = result.output.split("\0")
    elif os.name == "nt":
        script = (
            ps_data(
                {
                    "root": str(root),
                    "pattern": pattern,
                    "hidden": hidden,
                    "skip": [".git"] if ignored else list(SKIP),
                    "exclude": exclude or [],
                }
            )
            + r"""
function Walk($p) {
  Get-ChildItem -LiteralPath $p -Force -ErrorAction Stop | ForEach-Object {
    if (($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { return }
    if (-not $d.hidden -and ($_.Name.StartsWith('.') -or (($_.Attributes -band [IO.FileAttributes]::Hidden) -ne 0))) { return }
    if ($_.PSIsContainer) { if ($d.skip -notcontains $_.Name) { Walk $_.FullName } }
    else {
      $file=$_; $relative=$file.FullName.Substring($d.root.Length+1).Replace('\','/');
      $skip=$false; foreach($excluded in $d.exclude){if($relative -like $excluded -or $relative -like $excluded.Replace('**/','')){$skip=$true}};
      if(-not $skip -and (-not $d.pattern -or $relative -like $d.pattern -or $relative -like $d.pattern.Replace('**/',''))){[Console]::Write($file.FullName+[char]0)}
    }
  }
}; Walk $d.root
"""
        )
        result = await command(box, [], script=script)
        raw = result.output.split("\0")
        note = "OS fallback: ignore-file rules unavailable without ripgrep."
    else:
        find = shutil.which("find")
        if not find:
            raise ToolError("native discovery needs ripgrep or find")
        argv = [find, str(root), "-type", "d", "("]
        excluded = [".git"] if ignored else list(SKIP)
        if not hidden:
            excluded.append(".*")
        for index, name in enumerate(excluded):
            if index:
                argv += ["-o"]
            argv += ["-name", name]
        # Root itself may be hidden (e.g. a temporary checkout).
        argv += [")", "!", "-path", str(root), "-prune", "-o", "-type", "f"]
        if pattern:
            argv += ["(", "-path", str(root / pattern)]
            if pattern.startswith("**/"):
                argv += ["-o", "-path", str(root / pattern[3:])]
            argv += [")"]
        for value in exclude or []:
            argv += ["!", "-path", str(root / value)]
            if value.startswith("**/"):
                argv += ["!", "-path", str(root / value[3:])]
        argv += ["-print0"]
        result = await command(box, argv)
        raw = result.output.split("\0")
        note = "OS fallback: ignore-file rules unavailable without ripgrep or Git."
    paths = []
    for value in raw:
        if not value or not box.contains(value):
            continue
        target = Path(value)
        if target.is_symlink() or not target.is_file():
            continue
        paths.append(target)
    # Native Git applies nested ignore rules on fallback candidate lists, in one call.
    if not rg and not ignored and shutil.which("git"):
        probe = await command(
            box,
            [shutil.which("git"), "-C", str(root), "rev-parse", "--show-toplevel"],
            allowed=(0, 128),
        )
        if probe.exit_code == 0:
            listing = await command(
                box,
                [
                    shutil.which("git"),
                    "-C",
                    str(root),
                    "ls-files",
                    "-z",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                ],
            )
            approved = {str(root / p) for p in listing.output.split("\0") if p}
            paths = [p for p in paths if str(p) in approved]
            note = ""
            if listing.truncated:
                note = "Partial Git inventory; narrow the path."
    paths = sorted(set(paths), key=lambda p: p.as_posix())
    partial = result.truncated or len(paths) > limit
    return paths[:limit], partial, note


async def glob_files(
    box, pattern, path=".", *, hidden=False, ignored=False, query="", limit=500
):
    paths, partial, note = await inventory(
        box, path, pattern, hidden=hidden, ignored=ignored, limit=10000
    )

    def rank(p):
        relative = p.relative_to(box.resolve(path)).as_posix()
        return (
            0
            if relative == query
            else 1
            if p.name == query
            else 2
            if query in p.parts
            else 3
            if query.casefold() in relative.casefold()
            else 4,
            relative,
        )

    if query:
        paths.sort(key=rank)
    partial |= len(paths) > limit
    body = (
        "\n".join(display_path(box, p) for p in paths[:limit])
        or f"no matches for '{pattern}'"
    )
    return (
        body
        + (
            f"\n… {max(0, len(paths) - limit)} more; results incomplete; narrow the pattern or path"
            if partial
            else ""
        )
        + ("\n" + note if note else "")
    )


async def list_dir(box, path=".", *, limit=500):
    root = box.resolve(path)
    if not root.is_dir():
        raise ToolError(f"{path} is not a directory")
    if os.name == "nt":
        script = (
            ps_data({"path": str(root)})
            + "Get-ChildItem -LiteralPath $d.path -Force | ForEach-Object { [Console]::Write($_.FullName + [char]0) }"
        )
        result = await command(box, [], script=script)
    else:
        result = await command(
            box,
            [
                shutil.which("find") or "find",
                str(root),
                "-mindepth",
                "1",
                "-maxdepth",
                "1",
                "-print0",
            ],
        )
    rows = []
    for value in sorted(result.output.split("\0")):
        if value and box.contains(value):
            target = Path(value)
            rows.append(target.name + ("/" if target.is_dir() else ""))
    return (
        "\n".join(rows[:limit])
        + (
            f"\n… {max(0, len(rows) - limit)} more; results incomplete"
            if result.truncated or len(rows) > limit
            else ""
        )
        or "(empty directory)"
    )


async def search_text(
    box,
    pattern,
    path=".",
    glob="",
    limit=100,
    *,
    literal=False,
    case_sensitive=True,
    whole_word=False,
    patterns=None,
    output="content",
    context=0,
    hidden=False,
    ignored=False,
    exclude=None,
):
    root = box.resolve(path)
    if not root.exists():
        raise ToolError(f"path does not exist: {path}")
    if output not in {"content", "files", "count"}:
        raise ToolError("output must be content, files, or count")
    patterns = [pattern, *(patterns or [])]
    if any(not isinstance(p, str) or "\0" in p for p in patterns):
        raise ToolError("patterns must be text without NUL")
    cap = max(1, min(int(limit), 500))
    context = max(0, min(int(context), 20))
    rg = shutil.which("rg")
    if literal and whole_word:
        boundary = (
            r"[^\p{L}\p{N}_$]" if os.name == "nt" and not rg else "[^[:alnum:]_$]"
        )
        patterns = [f"(^|{boundary}){re.escape(p)}({boundary}|$)" for p in patterns]
        literal = False
        whole_word = False
    rows = []
    counts = {}
    note = ""
    selected_partial = False
    if rg:
        argv = [
            rg,
            "--json",
            "--color",
            "never",
            "--max-columns",
            "2000",
            "--max-count",
            str(cap + 1),
        ]
        if output != "content":
            argv = [
                rg,
                "--color",
                "never",
                "--null",
                "--files-with-matches" if output == "files" else "--count",
            ]
        if literal:
            argv += ["-F"]
        if not case_sensitive:
            argv += ["-i"]
        if whole_word:
            argv += ["-w"]
        if context:
            argv += ["-C", str(context)]
        if hidden:
            argv += ["--hidden"]
        if ignored:
            argv += ["--no-ignore"]
        if glob:
            argv += ["-g", glob]
        for name in SKIP:
            if not ignored or name == ".git":
                argv += ["-g", f"!**/{name}/**"]
        for value in exclude or []:
            argv += ["-g", "!" + value]
        for value in patterns:
            argv += ["-e", value]
        argv += ["--", str(root)]
        try:
            if output == "content" and os.name != "nt" and shutil.which("awk"):
                bound = 3 * (cap + context * 2) + 3
                marker = json.dumps('{"type":"eirene_limit"}')
                limiter = f"NR<={bound}{{print}} NR=={bound + 1}{{print {marker};exit}}"
                pipeline = (
                    shlex.join(argv)
                    + " | "
                    + shlex.join([shutil.which("awk"), limiter])
                )
                result = await command(box, [], script=pipeline, allowed=(0, 1, 141))
                selected_partial = '"type":"eirene_limit"' in result.output
            else:
                result = await command(box, argv, allowed=(0, 1))
        except ToolError as exc:
            raise ToolError(
                f"bad regular expression or search failure (ripgrep): {exc}"
            ) from exc
        if output == "files":
            for location in result.output.split("\0"):
                if location and box.contains(location):
                    counts[location] = 1
                    if len(counts) > cap:
                        selected_partial = True
                        break
        elif output == "count":
            rest = result.output
            while "\0" in rest:
                location, _, rest = rest.partition("\0")
                number, _, rest = rest.partition("\n")
                if number.isdigit() and box.contains(location):
                    counts[location] = int(number)
                    if len(counts) > cap:
                        selected_partial = True
                        break
        else:
            for line in result.output.splitlines():
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record["type"] not in {"match", "context"}:
                    continue
                data = record["data"]
                location = data["path"].get("text")
                if not location or not box.contains(location):
                    continue
                text = data["lines"].get("text", "[non-UTF-8 match]")
                if record["type"] == "match":
                    counts[location] = counts.get(location, 0) + 1
                rows.append((location, data["line_number"], text.rstrip("\r\n")))
                if len(rows) > cap + context * 2:
                    selected_partial = True
                    break
        engine = "ripgrep"
    else:
        paths, partial, note = (
            await inventory(
                box, path, glob, hidden=hidden, ignored=ignored, exclude=exclude
            )
            if root.is_dir()
            else ([root], False, "")
        )
        if os.name == "nt":
            script = (
                ps_data(
                    {
                        "paths": [str(p) for p in paths],
                        "patterns": patterns,
                        "literal": literal,
                        "case": case_sensitive,
                        "whole": whole_word,
                        "context": context,
                    }
                )
                + r"""
$pats=@($d.patterns); if ($d.whole) { $pats=@($pats | ForEach-Object { '\b(?:' + $(if ($d.literal) { [regex]::Escape($_) } else { $_ }) + ')\b' }) }
foreach ($p in $d.paths) {
 Select-String -LiteralPath $p -Pattern $pats -SimpleMatch:($d.literal -and -not $d.whole) -CaseSensitive:$d.case -Context $d.context | ForEach-Object {
  @{ path=$_.Path; number=$_.LineNumber; text=$_.Line; match=$true } | ConvertTo-Json -Compress
  $n=$_.LineNumber-$_.Context.PreContext.Count; foreach ($line in $_.Context.PreContext) { @{path=$_.Path;number=$n;text=$line;match=$false}|ConvertTo-Json -Compress; $n++ }
  $n=$_.LineNumber+1; foreach ($line in $_.Context.PostContext) { @{path=$_.Path;number=$n;text=$line;match=$false}|ConvertTo-Json -Compress; $n++ }
 }
}
"""
            )
            result = await command(box, [], script=script)
            for line in result.output.splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                rows.append((r["path"], r["number"], r["text"]))
                if r["match"]:
                    counts[r["path"]] = counts.get(r["path"], 0) + 1
            engine = "PowerShell/.NET"
        else:
            # One awk process per bounded argv batch. Regex matching happens in awk.
            awk = shutil.which("awk")
            if not awk:
                raise ToolError("native search needs ripgrep or awk")
            if not literal and any(
                "(?" + x in p for p in patterns for x in (":", "=", "!", "<")
            ):
                raise ToolError(
                    "bad regular expression: awk fallback uses POSIX ERE; lookarounds and noncapturing groups require ripgrep"
                )
            if any("\n" in p for p in patterns):
                raise ToolError(
                    "multiline patterns are unsupported; search individual lines"
                )
            expression = "|".join("(" + p + ")" for p in patterns)
            script = r"""BEGIN { pat=ENVIRON["EIRENE_PATTERN"]; lit=ENVIRON["EIRENE_LITERAL"]+0; np=split(ENVIRON["EIRENE_PATTERNS"],pats,"\n"); fold=ENVIRON["EIRENE_FOLD"]+0; word=ENVIRON["EIRENE_WORD"]+0; ctx=ENVIRON["EIRENE_CONTEXT"]+0; if(fold)pat=tolower(pat); if(!lit)valid=(""~pat); nul=sprintf("%c",0) }
FNR==1 { through=0; last=0; for(key in before)delete before[key] }
{ if(nul!=""&&index($0,nul))next; text=$0; value=fold?tolower(text):text; matched=0; if(lit){for(j=1;j<=np;j++){needle=fold?tolower(pats[j]):pats[j];at=index(value,needle);if(at>0&&(!word||((at==1||substr(value,at-1,1)!~/[[:alnum:]_$]/)&&(at+length(needle)>length(value)||substr(value,at+length(needle),1)!~/[[:alnum:]_$]/))))matched=1}}else{matched=value~pat};
 if(word&&!lit) matched=value~("(^|[^[:alnum:]_$])("pat")([^[:alnum:]_$]|$)");
 before[FNR]=text;
 if(matched) { for(i=FNR-ctx;i<FNR;i++)if(i>0&&i>last&&i in before)printf "%s%c%d%c%s%c0%c",FILENAME,0,i,0,substr(before[i],1,2000),0,0; through=FNR+ctx }
 if(matched||FNR<=through){printf "%s%c%d%c%s%c%d%c",FILENAME,0,FNR,0,substr(text,1,2000),0,matched,0; last=FNR}
 delete before[FNR-ctx-1]
}"""
            if not paths:
                try:
                    await command(box, [awk, script, os.devnull], env={"EIRENE_PATTERN": expression, "EIRENE_LITERAL": str(int(literal))})
                except ToolError as exc:
                    raise ToolError(f"bad regular expression: {exc}") from exc
                return "no matches" + ("\n" + note if note else "")
            result = None
            for start in range(0, len(paths), 128):
                result = await command(
                    box,
                    [awk, script, *[str(p) for p in paths[start : start + 128]]],
                    env={
                        "EIRENE_PATTERNS": "\n".join(patterns),
                        "EIRENE_PATTERN": patterns[0] if literal else expression,
                        "EIRENE_LITERAL": str(int(literal)),
                        "EIRENE_FOLD": str(int(not case_sensitive)),
                        "EIRENE_WORD": str(int(whole_word)),
                        "EIRENE_CONTEXT": str(context),
                    },
                )
                parts = result.output.split("\0")
                for i in range(0, len(parts) - 3, 4):
                    location, number, text, matched = parts[i : i + 4]
                    if not number.isdigit() or not box.contains(location):
                        continue
                    selected_partial = selected_partial or len(text) >= 2000
                    rows.append((location, int(number), text))
                    if matched == "1":
                        counts[location] = counts.get(location, 0) + 1
                if result.truncated or len(rows) > cap:
                    break
            engine = "awk/POSIX ERE"
        if partial:
            note += " Partial file inventory."
    if output == "files":
        body = [display_path(box, Path(p)) for p in counts]
    elif output == "count":
        body = [f"{display_path(box, Path(p))}:{n}" for p, n in counts.items()]
    else:
        body = [
            f"{display_path(box, Path(p))}:{n}:{safe_text(t)}"
            for p, n, t in sorted(set(rows))
        ]
    incomplete = (
        result.truncated
        or len(body) >= cap
        or selected_partial
        or (output == "content" and any(n > cap for n in counts.values()))
        or (not rg and partial)
    )
    text = "\n".join(body[:cap]) or (
        "no matches in returned preview (search incomplete)"
        if incomplete
        else "no matches"
    )
    if incomplete:
        text += f"\n… stopped after {cap} matches or output bound; results incomplete; narrow the search"
    return text + f"\n[engine: {engine}]" + ("\n" + note if note else "")


async def read_file(
    box,
    path,
    offset=0,
    limit=0,
    *,
    max_chars=24000,
    tail=False,
    pattern="",
    context=2,
    byte_offset=None,
):
    from .files import _decode_fragment

    target = box.resolve(path)
    if not target.exists():
        raise ToolError(f"{path} does not exist")
    if not target.is_file():
        raise ToolError(f"{path} is not a regular file; use list_dir")
    maximum = max(0, min(int(max_chars), 400_000))
    if maximum < 256:
        return "File read deferred: insufficient context; compact history or request a smaller response."[
            :maximum
        ]
    size = target.stat().st_size
    room = max(4, maximum - 350)
    if byte_offset is not None:
        begin = max(0, int(byte_offset))
        count = max(4, room // 4)
        if os.name == "nt":
            script = (
                ps_data({"path": str(target), "offset": begin, "count": count})
                + r"""
$f=[IO.File]::OpenRead($d.path); try { [void]$f.Seek($d.offset,0); $b=New-Object byte[] $d.count; $n=$f.Read($b,0,$b.Length); [Console]::Write([Convert]::ToBase64String($b,0,$n)) } finally { $f.Dispose() }
"""
            )
            result = await command(box, [], script=script)
            data = base64.b64decode(result.output.strip())
        else:
            # Base64 preserves a UTF-8 sequence split at the byte boundary.
            script = f"tail -c +{begin + 1} {shlex.quote(str(target))} | head -c {count} | base64"
            result = await command(box, [], script=script, allowed=(0, 141))
            data = base64.b64decode(result.output)
        text, consumed = _decode_fragment(data, final=begin + len(data) >= size)
        end = begin + consumed
        note = (
            f"\nContinue with byte_offset={end}; byte ranges may split UTF-8 characters."
            if end < size
            else "\n(end of file)"
        )
        return (
            f"File: {display_path(box, target)} ({size} bytes)\n"
            + safe_text(text)
            + note
        )
    wanted = max(1, int(limit)) if limit > 0 else (20 if tail else 1000000000)
    params = {
        "path": str(target),
        "offset": max(0, int(offset)),
        "wanted": wanted,
        "room": room,
        "tail": bool(tail),
        "pattern": pattern,
        "context": max(0, min(context, 20)),
    }
    if os.name == "nt":
        script = (
            ps_data(params)
            + r"""
$rows=New-Object 'System.Collections.Generic.List[object]'; $before=New-Object 'System.Collections.Generic.List[object]';
$n=0; $pos=0; $used=0; $through=0; $last=0; $binary=$false;
Get-Content -LiteralPath $d.path -Encoding UTF8 -Delimiter "`n" | ForEach-Object {
 $raw=$_; $line=$raw.TrimEnd([char]10).TrimEnd([char]13);
 $n++; $len=[Text.Encoding]::UTF8.GetByteCount($line); if($line.Contains([char]0)){$binary=$true};
 $row=@{n=$n;pos=$pos;length=$len;text=$line.Substring(0,[Math]::Min($line.Length,$d.room))}; $pos+=[Text.Encoding]::UTF8.GetByteCount($raw);
 if($n -le $d.offset){return};
 $match=(-not $d.pattern -or [regex]::IsMatch($line,$d.pattern));
 if($match -and $d.pattern){$through=$n+$d.context; foreach($r in $before){if($r.n -gt $last){$rows.Add($r);$last=$r.n}}};
 if($match -or $n -le $through){if($d.tail -or ($rows.Count -lt $d.wanted+1 -and $used -lt $d.room+1)){ $rows.Add($row);$last=$n;$used+=$row.text.Length+([string]$row.n).Length+2 }};
 $before.Add($row);if($before.Count -gt $d.context){$before.RemoveAt(0)};
 if($d.tail){while($rows.Count -gt 1 -and ($rows.Count -gt $d.wanted -or $used -gt $d.room)){$used-=$rows[0].text.Length+([string]$rows[0].n).Length+2;$rows.RemoveAt(0)}}
}; foreach($r in $rows){$r|ConvertTo-Json -Compress}; @{total=$n;binary=$binary}|ConvertTo-Json -Compress
"""
        )
        result = await command(box, [], script=script)
        rows = []
        total = 0
        binary = False
        for line in result.output.splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if "total" in r:
                total = r["total"]
                binary = r["binary"]
            else:
                rows.append((r["n"], r["pos"], r["length"], r["text"]))
    else:
        if pattern and "(?" in pattern:
            raise ToolError(
                "bad regular expression: bounded reads use POSIX ERE on this host"
            )
        if sys.platform == "darwin":
            # BSD awk cannot retain NUL in strings; compare a native NUL-filtered stream.
            probe = "LC_ALL=C tr -d '\\000' < " + shlex.quote(str(target)) + " | cmp -s " + shlex.quote(str(target)) + " -"
            checked = await command(box, [], script=probe, allowed=(0, 1))
            if checked.exit_code == 1:
                raise ToolError(f"{path} is binary ({size} bytes); use read_image or a bounded hex dump")
        script = r"""BEGIN{start=ENVIRON["EIRENE_OFFSET"]+0;wanted=ENVIRON["EIRENE_WANTED"]+0;room=ENVIRON["EIRENE_ROOM"]+0;tail=ENVIRON["EIRENE_TAIL"]+0;pat=ENVIRON["EIRENE_PATTERN"];ctx=ENVIRON["EIRENE_CONTEXT"]+0;pos=0;first=1;nul=sprintf("%c",0)}
function keep(n,p,l,t) {
 if(!tail && (kept>=wanted+1||used>room))return;
 gsub(sprintf("%c",28),"",t); kept++; a[kept]=sprintf("%d%c%d%c%d%c%s%c",n,28,p,28,l,28,t,28); sizes[kept]=length(t)+length(n)+2;used+=sizes[kept];
 if(tail)while(first<kept&&(kept-first+1>wanted||used>room)){used-=sizes[first];delete a[first];delete sizes[first];first++}
}
{len=length($0);if(nul!=""&&index($0,nul)){binary=1; next};
 if(NR>start){text=substr($0,1,room);matched=(pat==""||$0~pat);
 if(matched&&pat!=""){for(i=NR-ctx;i<NR;i++)if(i>last&&i>start&&i in b){keep(i,bp[i],bl[i],b[i]);last=i};through=NR+ctx}
 if(matched||NR<=through){keep(NR,pos,len,text);last=NR}; b[NR]=text;bp[NR]=pos;bl[NR]=len;delete b[NR-ctx];delete bp[NR-ctx];delete bl[NR-ctx];
 }pos+=len+1
}
END{for(i=first;i<=kept;i++)printf "%s",a[i];printf "TOTAL%c%d%c%d%c",28,NR,28,binary,28}"""
        env = {
            "LC_ALL": "C",
            "EIRENE_OFFSET": str(params["offset"]),
            "EIRENE_WANTED": str(wanted),
            "EIRENE_ROOM": str(room),
            "EIRENE_TAIL": str(int(tail)),
            "EIRENE_PATTERN": pattern,
            "EIRENE_CONTEXT": str(params["context"]),
        }
        result = await command(
            box, [shutil.which("awk") or "awk", script, str(target)], env=env
        )
        parts = result.output.split("\x1c")
        rows = []
        total = 0
        binary = False
        for i in range(0, len(parts) - 3, 4):
            if parts[i] == "TOTAL":
                total = int(parts[i + 1])
                binary = parts[i + 2] == "1"
                break
            if parts[i].isdigit():
                rows.append(
                    (int(parts[i]), int(parts[i + 1]), int(parts[i + 2]), parts[i + 3])
                )
    if binary:
        raise ToolError(
            f"{path} is binary ({size} bytes); use read_image or a bounded hex dump"
        )
    header = f"File: {display_path(box, target)} ({size} bytes, {total} lines)\n"
    room = max(4, maximum - len(header) - 220)
    body = []
    used = 0
    resume = None
    for number, position, length, text in rows:
        clean = safe_text(text.rstrip("\r\n"))
        row = f"{number}\t{clean}"
        if tail:
            if len(row) + 1 > room:
                row = f"{number}\t… " + row[-max(1, room - len(str(number)) - 6) :]
            body.append(row)
            used += len(row) + 1
            while len(body) > 1 and used > room:
                used -= len(body.pop(0)) + 1
        elif (
            len(body) >= wanted
            or used + len(row) + 1 > room
            or len(text.encode()) < length
        ):
            if not body:
                # Fetch the first fragment in native byte mode to preserve UTF-8 boundaries.
                fragment = await read_file(
                    box, path, max_chars=maximum, byte_offset=position
                )
                piece = fragment.split("\n", 1)[1]
                content, _, ending = piece.partition("\nContinue with ")
                if ending:
                    return (
                        header
                        + f"{number}\t"
                        + content
                        + "\n… more lines; continue with "
                        + ending
                    )
                return header + f"{number}\t" + content
            resume = f"offset={number - 1}"
            break
        else:
            body.append(row)
            used += len(row) + 1
    if not resume and not tail and rows and rows[-1][0] < total and not pattern:
        resume = f"offset={rows[-1][0]}"
    if resume:
        note = f"\n… more lines; continue with {resume}. Use pattern/context or tail for focused evidence."
    elif tail:
        note = (
            "\n(end of file; earlier lines omitted)"
            if rows and rows[0][0] > 1
            else "\n(end of file)"
        )
    else:
        note = "\n(end of selected range)" if offset or pattern else "\n(end of file)"
    if result.truncated:
        note = "\n… results incomplete; narrow the range"
    return (
        header + ("\n".join(body) or ("no matches" if pattern else "(empty)")) + note
    )[:maximum]


async def find_symbol(box, name, path=".", limit=100):
    name = name.strip()
    if not name:
        raise ToolError("symbol name is required")
    symbol = re.escape(name)
    space = "[ \t]"
    pattern = (
        rf"(^|{space})(def|class|function|func|fn|struct|enum|interface|type|trait){space}+{symbol}([^A-Za-z0-9_$]|$)"
        rf"|(^|{space}){symbol}{space}*(:=|=){space}*(function|lambda)"
        rf"|(^|{space}){symbol}{space}*\([^;]*\){space}*\{{"
    )
    return await search_text(box, pattern, path, limit=limit)


def display_path(box, path):
    return box.relative(path).replace(os.sep, "/")


async def references(box, symbol, path=".", limit=100):
    if not re.fullmatch(r"[A-Za-z_$][\w$]*", symbol):
        raise ToolError("symbol must be one identifier")
    return await search_text(
        box, symbol, path, limit=limit, literal=True, whole_word=True
    )
