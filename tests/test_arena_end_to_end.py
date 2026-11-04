"""Run a whole arena through Eirene: real Agent, delegate_tasks, sandbox and bracket.py.

Only the model is scripted. It follows the skill's instructions literally, so these
tests show what Eirene and the bracket do, not whether a given model follows them.
"""
import collections
import json
import pathlib
import re

import pytest

from eirene.core import paths, plugin_install, skills
from eirene.core.agent import Agent, Failed, ToolFinished
from eirene.core.config import Config
from eirene.core.modes import Mode
from eirene.core.session import Session
from eirene.providers.base import Done, TextDelta, ToolCall
from eirene.tools.sandbox import Sandbox

log = collections.Counter()
seq = {"n": 0}
AGENTS = 4


def call(_tool, **arguments):
    seq["n"] += 1
    return ToolCall(f"c{seq['n']}", _tool, arguments)


def text_of(m):
    c=m.get("content"); return c if isinstance(c,str) else json.dumps(c)
class Child:
    supports_tools=True; protocol="test"
    def __init__(self): self.step=0; self.brief=""
    async def stream(self,messages,model,*,system="",tools=None,max_tokens=8192):
        self.step+=1
        first=text_of(messages[0]); m=re.search(r"Read (\S+) and follow it exactly",first)
        if self.step==1:
            log["child_started"]+=1
            yield call("read_file",path=m.group(1),limit=500); yield Done("tool_use"); return
        if self.step==2:
            brief=pathlib.Path(m.group(1)).read_text(); kind=None; writes=[]
            if (x:=re.search(r"Write your solution to (\S+?):",brief)): kind="competitor"; ag=re.search(r"You are competitor (\S+)",brief).group(1); writes=[(x.group(1),f"Solution by {ag}.")]
            elif (x:=re.search(r"Write the attacks to (\S+) in this format",brief)): kind="attacker"; writes=[(x.group(1),"ATTACK 1 [MINOR] t\nWhere: x\nProblem: y\n")]
            elif (x:=re.search(r"Write your point-by-point defense to (\S+) in this format",brief)):
                kind="defender"; y=re.search(r"Write your revised solution to (\S+?)\.\n",brief); ag=re.search(r"You are competitor (\S+)",brief).group(1)
                writes=[(x.group(1),"ATTACK 1: CONCEDE. fixed\n"),(y.group(1),f"Revised by {ag}.")]
            elif (x:=re.search(r"Write this JSON, and nothing else, to (\S+?):",brief)):
                ids=re.findall(r"^Solution (\S+)$",brief,re.M)
                if ids:
                    kind="judge"; a,b=ids; mid=re.search(r"judge of match (\S+),",brief).group(1)
                    # The lower number scores higher, but the judge names the other one.
                    hi,lo=(a,b) if int(re.sub(r"\D","",a))<int(re.sub(r"\D","",b)) else (b,a)
                    log["judge_lied"]+= 1
                    v={"match":mid,"scores":{hi:dict(correctness=9,completeness=9,specificity=9,robustness=9,clarity=9,fatal=False),lo:dict(correctness=3,completeness=3,specificity=3,robustness=3,clarity=3,fatal=False)},"winner":lo,"reason":"r","survived":[],"standing":{a:[],b:[]}}
                    writes=[(x.group(1),json.dumps(v))]
            assert writes,brief[:300]
            log["kind_"+kind]+=1; self.pending=writes
        if getattr(self,"pending",None):
            p,c=self.pending.pop(0); yield call("write_file",path=p,content=c); yield Done("tool_use"); return
        yield TextDelta("DONE"); yield Done("stop")
    async def close(self): pass
    async def models(self): return ["m"]
class Orchestrator:
    supports_tools=True; protocol="test"
    def __init__(self): self.dir=None; self.queue=[]; self.done=False; self.waves=0; self.last=None
    def arena(self,c): return f'python3 "{self.dir}/bracket.py" {c}'
    async def stream(self,messages,model,*,system="",tools=None,max_tokens=8192):
        out=text_of(messages[-1]) if messages else ""
        out=out.replace('\\n','\n') if messages[-1].get("role")!="user" else out
        assert "Already attempted" not in out, out[:200]
        assert "Still running" not in out, out[:200]  # Quick scripts return their result directly.
        if self.dir is None and "Skill directory:" not in out:
            yield call("load_skill",name="arena:arena"); yield Done("tool_use"); return
        if self.dir is None:
            self.dir=pathlib.Path(re.search(r'python3 \\?"(\S+?)/bracket\.py',out).group(1)); self.state="task"
            yield call("write_file",path=".arena/task.md",content="Name a cat."); yield Done("tool_use"); return
        def run(c):
            self.last=c; log["arena_commands"]+=1
            return call("run_command",command=self.arena(c))
        if self.state=="task":
            self.state="init"; yield run(f"init --agents {AGENTS} --seed 3 --task-file .arena/task.md"); yield Done("tool_use"); return
        if self.state=="init":
            self.state="next"; yield run("next"); yield Done("tool_use"); return
        if self.state=="next":
            if "DONE." in out: self.state="winner"; yield run("winner"); yield Done("tool_use"); return
            if (m:=re.search(r"NEXT: (\w+)\. \d+ of",out)):
                self.state="prompts"; yield run(f"prompts {m.group(1)}"); yield Done("tool_use"); return
            if "NEXT: collect" in out: self.state="after"; yield run("collect"); yield Done("tool_use"); return
            if "NEXT: advance" in out: self.state="after"; yield run("advance"); yield Done("tool_use"); return
            raise AssertionError("next said: "+out[:500])
        if self.state=="after":
            self.state="next"; yield run("next"); yield Done("tool_use"); return
        if self.state=="prompts":
            self.waves_left=[]; cur=None
            for line in out.splitlines():
                if re.match(r"wave \d+",line.strip()): cur=[]; self.waves_left.append(cur)
                elif cur is not None and (x:=re.match(r"\s+(\S+)\s+(\S+\.(?:md|txt))\s*$",line)): cur.append((x.group(1),x.group(2)))
            assert self.waves_left, out[:600]
            self.state="wave"
        if self.state=="wave":
            if self.waves_left:
                w=self.waves_left.pop(0); self.waves+=1; log["delegate_calls"]+=1; log["delegated_tasks"]+=len(w)
                yield call("delegate_tasks",tasks=[dict(name=f"arena {j}",read_only=False,prompt=f"Read {p} and follow it exactly. It is your whole brief.") for j,p in w]); yield Done("tool_use"); return
            self.state="next"; yield run("next"); yield Done("tool_use"); return
        if self.state=="winner":
            self.result=out; self.state="end"
            yield TextDelta("finished"); yield Done("stop"); return
        yield TextDelta("end"); yield Done("stop")
    async def close(self): pass
    async def models(self): return ["m"]


async def run_arena(workdir, monkeypatch, agents):
    global AGENTS
    AGENTS = agents
    log.clear()
    monkeypatch.setattr("eirene.providers.registry.build", lambda key, config: Child())
    plugin_install.install("arena")
    config = Config.load()
    config.set("mode", "auto")
    agent = Agent(Session.create(workdir), config, Sandbox(workdir))
    agent.mode = Mode.AUTO
    orchestrator = Orchestrator()
    agent.use(orchestrator, "test", "m")
    agent.reload_skills()

    async def approve(name, *args):
        return "always"

    agent.approve = approve
    errors = []
    async for event in agent.run("/arena"):
        if isinstance(event, Failed):
            errors.append(event.text)
        if isinstance(event, ToolFinished) and event.is_error:
            errors.append(f"{event.name}: {event.result}")
    await agent.close()
    assert not errors
    state = json.loads(next((workdir / ".arena").glob("*/arena.json")).read_text())
    return orchestrator, state


@pytest.mark.usefixtures("trusted_plugins")
@pytest.mark.parametrize("agents, calls", [(2, 7), (4, 19), (8, 43)])
async def test_runs_every_sub_agent_the_plan_promises(workdir, monkeypatch, agents, calls):
    orchestrator, state = await run_arena(workdir, monkeypatch, agents)
    assert log["delegated_tasks"] == log["child_started"] == calls
    assert log["kind_competitor"] == agents
    assert log["kind_judge"] == agents - 1  # One match per competitor knocked out.
    assert log["kind_attacker"] == log["kind_defender"] == 2 * (agents - 1)
    assert len(state["rounds"][0]["alive"]) == agents
    assert state["champion"]
    assert "CHAMPION" in orchestrator.result


@pytest.mark.usefixtures("trusted_plugins")
async def test_scores_decide_when_a_judge_names_the_wrong_winner(workdir, monkeypatch):
    # Every scripted judge scores the lower number higher, then names the other as winner.
    orchestrator, state = await run_arena(workdir, monkeypatch, 8)
    assert log["judge_lied"] == 7
    assert state["champion"] == "a001"
    assert "beat a003, 90 to 30" in orchestrator.result


async def test_cannot_advance_past_a_sub_agent_that_wrote_nothing(workdir):
    import subprocess
    import sys
    plugin_install.install("arena")
    script = str(paths.skills_dir() / "arena/arena/bracket.py")

    def bracket(*args):
        return subprocess.run([sys.executable, script, *args], capture_output=True, text=True, cwd=workdir)

    (workdir / "task.md").write_text("Name a cat.")
    assert bracket("init", "--agents", "2", "--task-file", "task.md").returncode == 0
    bracket("prompts", "spawn")
    assert "NEXT: spawn. 2 of 2" in bracket("next").stdout
    assert bracket("advance").returncode != 0
    assert not json.loads(next((workdir / ".arena").glob("*/arena.json")).read_text())["champion"]


async def test_instructions_give_the_model_the_exact_script_path(config):
    # A real run failed on skills/arena/bracket.py, dropping one "arena" from the path.
    plugin_install.install("arena")
    body = skills.load(skills.discover()[0])
    real = paths.skills_dir() / "arena/arena/bracket.py"
    assert f'python3 "{real}" <command>' in body and "${" not in body
    assert real.is_file()
