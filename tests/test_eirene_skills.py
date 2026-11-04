"""The Eirene Skills bundle: catalog entry, install/refresh, content and scripts."""
from __future__ import annotations

import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from eirene.core import plugins, skills
from eirene.core.plugin_catalog import BUNDLES, source_for
from eirene.core.plugin_install import bundled_skills, install

ROOT = Path(__file__).resolve().parents[1]
# Importing bundle scripts in-process must not leave __pycache__ inside the shipped bundle.
sys.dont_write_bytecode = True
BUNDLE = ROOT / "eirene" / "plugins" / "eirene-skills"
SKILLS = BUNDLE / "skills"
EXPECTED = {
    "algorithmic-art", "canvas-design", "discernment-nudge", "doc-coauthoring", "docx", "frontend-design",
    "internal-comms", "mcp-builder", "pdf", "pptx", "skill-creator", "slack-gif-creator", "theme-factory",
    "web-artifacts-builder", "webapp-testing", "xlsx",
}


def run(*args, cwd=None, check=True):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, cwd=cwd, env=env)
    if check and result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result


def frontmatter(path: Path) -> dict[str, str]:
    sys.path.insert(0, str(SKILLS / "skill-creator" / "scripts"))
    try:
        from utils import parse_frontmatter
    finally:
        sys.path.pop(0)
    return parse_frontmatter(path.read_text(encoding="utf-8"))[0]


# catalog and installation ------------------------------------------------------

def test_catalog_offers_eirene_skills_instead_of_the_anthropic_bundle():
    names = {name for name, _, _ in BUNDLES}
    assert "eirene-skills" in names and "anthropic-skills" not in names
    assert source_for("eirene-skills") == "builtin:eirene-skills"
    assert bundled_skills() == BUNDLE


def test_install_copies_the_bundle_without_network(config, monkeypatch):
    monkeypatch.setattr("eirene.core.plugin_install.subprocess.run",
                        lambda *a, **k: pytest.fail("the bundled install must not run git"))
    name, count = install("eirene-skills")
    assert (name, count) == ("eirene-skills", len(EXPECTED))
    plugin = plugins.discover()[0]
    assert plugin.name == "eirene-skills" and plugin.catalog_shortcut == "eirene-skills"
    found = {skill.name for skill in skills.discover()}
    assert found == {f"eirene-skills:{name}" for name in EXPECTED}
    # supporting files travel with each skill
    exported = plugins.paths.skills_dir() / "eirene-skills"
    assert (exported / "docx" / "scripts" / "office" / "validate.py").is_file()
    assert (exported / "theme-factory" / "themes" / "ocean-depths.md").is_file()


def test_bundle_is_packaged():
    assert '"eirene" = ["plugins/**/*"]' in (ROOT / "pyproject.toml").read_text()
    assert 'ROOT / "eirene" / "plugins"' in (ROOT / "build" / "eirene.spec").read_text()
    assert '"**/__pycache__/*"' in (ROOT / "pyproject.toml").read_text()


# content -------------------------------------------------------------------------

def test_every_skill_has_valid_front_matter_and_existing_references():
    assert {p.name for p in SKILLS.iterdir() if p.is_dir()} == EXPECTED
    for folder in sorted(SKILLS.iterdir()):
        result = run(SKILLS / "skill-creator" / "scripts" / "quick_validate.py", folder, check=False)
        assert result.returncode == 0, f"{folder.name}: {result.stdout}"
        meta = frontmatter(folder / "SKILL.md")
        assert meta["name"] == folder.name
        assert 40 <= len(meta["description"]) <= 1024


def test_no_vendor_specific_skills_or_branding():
    for name in ("claude-api", "academy-guide", "brand-guidelines"):
        assert not (SKILLS / name).exists()
    for path in BUNDLE.rglob("*"):
        if (not path.is_file() or path.name == "LICENSE" or "__pycache__" in path.parts
                or path.suffix in (".png", ".gif", ".pdf", ".pyc")):
            continue
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"anthropic|claude\.ai|cowork", text, re.I), path
        assert not re.search(r"\bClaude\b(?! Code)", text), path


def test_shared_office_helpers_are_identical_in_each_document_skill():
    reference = SKILLS / "docx" / "scripts" / "office"
    names = sorted(p.name for p in reference.glob("*.py"))
    for skill in ("pptx", "xlsx"):
        other = SKILLS / skill / "scripts" / "office"
        assert sorted(p.name for p in other.glob("*.py")) == names
        match, mismatch, errors = filecmp.cmpfiles(reference, other, names, shallow=False)
        assert not mismatch and not errors, (skill, mismatch, errors)


def test_python_scripts_compile_and_answer_help():
    for path in sorted(BUNDLE.rglob("*.py")):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    for script in ("docx/scripts/office/validate.py", "xlsx/scripts/recalc.py", "pdf/scripts/check_boxes.py",
                   "webapp-testing/scripts/with_server.py", "mcp-builder/scripts/evaluation.py",
                   "canvas-design/scripts/fonts.py"):
        run(SKILLS / script, "--help")


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_javascript_files_parse():
    for path in sorted(BUNDLE.rglob("*.mjs")) + sorted(BUNDLE.rglob("*.js")):
        result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, f"{path}: {result.stderr}"


# document scripts -----------------------------------------------------------------

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
                 'content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
                 'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName='
                 '"/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.'
                 'document.main+xml"/></Types>')
ROOT_RELS = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/'
             '2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
             '2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')


def make_docx(path: Path, body: str) -> Path:
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W}" '
                f'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
                f'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" mc:Ignorable="w14">'
                f'<w:body>{body}</w:body></w:document>')
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", ROOT_RELS)
        archive.writestr("word/document.xml", document)
    return path


def body_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read("word/document.xml").decode()


def test_docx_merge_comment_and_validate(tmp_path):
    scripts = SKILLS / "docx" / "scripts"
    source = make_docx(tmp_path / "in.docx", '<w:p><w:r w:rsidR="1"><w:t xml:space="preserve">The fee is </w:t></w:r>'
                                             '<w:proofErr w:type="spellStart"/><w:r w:rsidR="2"><w:t>capped</w:t></w:r>'
                                             '<w:r><w:t xml:space="preserve"> at 10.</w:t></w:r></w:p>')
    run(scripts / "merge_runs.py", source, "-o", tmp_path / "merged.docx")
    merged = body_text(tmp_path / "merged.docx")
    assert "The fee is capped at 10." in merged and "proofErr" not in merged
    assert 'mc:Ignorable="w14"' in merged  # namespace declarations survive the edit
    run(scripts / "comment.py", tmp_path / "merged.docx", "Too low", "--anchor", "capped", "--author", "Ada",
        "-o", tmp_path / "commented.docx")
    run(scripts / "comment.py", tmp_path / "commented.docx", "Agreed", "--parent", "0")
    with zipfile.ZipFile(tmp_path / "commented.docx") as archive:
        names = set(archive.namelist())
        document = archive.read("word/document.xml").decode()
    assert {"word/comments.xml", "word/commentsExtended.xml", "word/commentsIds.xml"} <= names
    assert document.count("commentReference") == 2
    result = run(scripts / "office" / "validate.py", tmp_path / "commented.docx", "--json")
    assert json.loads(result.stdout)["ok"]


def test_docx_untracked_edits_are_caught_and_changes_accepted(tmp_path):
    scripts = SKILLS / "docx" / "scripts"
    original = make_docx(tmp_path / "orig.docx", "<w:p><w:r><w:t>Keep this.</w:t></w:r></w:p>"
                                                 "<w:p><w:r><w:t>Drop this.</w:t></w:r></w:p>"
                                                 "<w:p><w:r><w:t>Fee 10.</w:t></w:r></w:p>")
    stamp = 'w:author="Ada" w:date="2025-01-01T00:00:00Z"'
    tracked = ("<w:p><w:r><w:t>Keep this.</w:t></w:r></w:p>"
               f'<w:p><w:pPr><w:rPr><w:del w:id="1" {stamp}/></w:rPr></w:pPr>'
               f'<w:del w:id="2" {stamp}><w:r><w:delText>Drop this.</w:delText></w:r></w:del></w:p>'
               f'<w:p><w:r><w:t xml:space="preserve">Fee </w:t></w:r><w:del w:id="3" {stamp}><w:r><w:delText>10'
               f'</w:delText></w:r></w:del><w:ins w:id="4" {stamp}><w:r><w:t>20</w:t></w:r></w:ins>'
               '<w:r><w:t>.</w:t></w:r></w:p>')
    edited = make_docx(tmp_path / "edited.docx", tracked)
    validate = scripts / "office" / "validate.py"
    run(validate, edited, "--original", original, "--author", "Ada")
    sneaky = make_docx(tmp_path / "sneaky.docx", tracked.replace("Keep this.", "Keep that."))
    result = run(validate, sneaky, "--original", original, "--author", "Ada", check=False)
    assert result.returncode == 1 and "untracked edits" in result.stdout
    run(scripts / "accept_changes.py", edited, tmp_path / "clean.docx")
    clean = body_text(tmp_path / "clean.docx")
    assert "Drop this" not in clean and ">20<" in clean and "w:ins" not in clean
    assert clean.count("<w:p>") == 2  # the fully deleted paragraph is gone, not left empty


def test_validate_flags_broken_relationships(tmp_path):
    path = make_docx(tmp_path / "broken.docx", '<w:p><w:r><w:t>x</w:t></w:r></w:p>')
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("word/_rels/document.xml.rels",
                         '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                         'relationships"><Relationship Id="rId9" Type="x/image" Target="media/missing.png"/>'
                         '</Relationships>')
    result = run(SKILLS / "docx" / "scripts" / "office" / "validate.py", path, check=False)
    assert result.returncode == 1 and "media/missing.png" in result.stdout


def test_package_refuses_unsafe_archives(tmp_path):
    bad = tmp_path / "evil.docx"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("../escape.txt", "x")
    result = run(SKILLS / "docx" / "scripts" / "office" / "package.py", "unpack", bad, tmp_path / "out", check=False)
    assert result.returncode and "unsafe" in (result.stdout + result.stderr)
    assert not (tmp_path / "escape.txt").exists()


def test_show_cells_reads_formulas_and_values(tmp_path):
    book = tmp_path / "book.xlsx"
    x = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(book, "w") as archive:
        archive.writestr("xl/workbook.xml", f'<workbook xmlns="{x}" xmlns:r="{r}"><sheets>'
                                            f'<sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels",
                         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         '<Relationship Id="rId1" Type="t" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{x}"><sheetData><row r="1">'
                                                     '<c r="A1"><v>2</v></c><c r="B1"><f>A1*2</f></c>'
                                                     '<c r="C1" t="e"><f>A1/0</f><v>#DIV/0!</v></c></row>'
                                                     '</sheetData></worksheet>')
    out = run(SKILLS / "xlsx" / "scripts" / "show_cells.py", book).stdout
    assert "=A1*2  →  (not calculated)" in out and "#DIV/0!" in out and "## Data" in out
    sys.path.insert(0, str(SKILLS / "xlsx" / "scripts"))
    try:
        import recalc
        report = recalc.scan(book)
    finally:
        sys.path.pop(0)
    assert report["total_formulas"] == 2 and report["error_summary"]["#DIV/0!"]["locations"] == ["Data!C1"]


@pytest.mark.skipif(not (shutil.which("soffice") or shutil.which("libreoffice")), reason="needs LibreOffice")
def test_recalc_fills_in_formula_results(tmp_path):
    csv = tmp_path / "data.csv"
    csv.write_text("a,b\n1,2\n", encoding="utf-8")
    run(SKILLS / "xlsx" / "scripts" / "office" / "soffice.py", "--convert-to", "xlsx", "--outdir", tmp_path, csv)
    book = tmp_path / "data.xlsx"
    folder = tmp_path / "u"
    sys.path.insert(0, str(SKILLS / "xlsx" / "scripts" / "office"))
    try:
        from package import pack, unpack
        unpack(book, folder)
        sheet = folder / "xl" / "worksheets" / "sheet1.xml"
        sheet.write_text(sheet.read_text().replace(
            "</sheetData>", '<row r="3"><c r="A3"><f>SUM(A2:B2)</f></c><c r="B3"><f>A2/0</f></c></row></sheetData>'))
        pack(folder, book)
    finally:
        sys.path.pop(0)
    report = json.loads(run(SKILLS / "xlsx" / "scripts" / "recalc.py", book, "60").stdout)
    assert report["status"] == "errors_found" and report["total_formulas"] == 2
    assert list(report["error_summary"]) == ["#DIV/0!"]


def test_pdf_box_checker(tmp_path):
    spec = {"pages": [{"page_number": 1, "pdf_width": 612, "pdf_height": 792}], "form_fields": [
        {"page_number": 1, "description": "a", "entry_bounding_box": [10, 10, 100, 24], "entry_text": {"text": "x"}},
        {"page_number": 1, "description": "b", "entry_bounding_box": [50, 12, 120, 22], "entry_text": {"text": "y"}},
        {"page_number": 1, "description": "c", "entry_bounding_box": [10, 40, 100, 44],
         "entry_text": {"text": "z", "font_size": 10}}]}
    (tmp_path / "fields.json").write_text(json.dumps(spec))
    result = run(SKILLS / "pdf" / "scripts" / "check_boxes.py", tmp_path / "fields.json", check=False)
    assert result.returncode == 1
    assert "overlaps" in result.stdout and "too short" in result.stdout


# other skills' helpers -----------------------------------------------------------

def test_gif_helpers_build_a_valid_emoji(tmp_path):
    pytest.importorskip("PIL")
    sys.path.insert(0, str(SKILLS / "slack-gif-creator"))
    try:
        from core.easing import interpolate, progress
        from core.frame_composer import create_gradient_background, draw_star
        from core.gif_builder import GIFBuilder
        from core.validators import validate_gif
        builder = GIFBuilder(128, 128, fps=10)
        for i in range(8):
            frame = create_gradient_background(128, 128, (250, 240, 220), (240, 180, 150))
            draw_star(frame, (interpolate(20, 108, progress(i, 8), "ease_in_out"), 64), 14)
            builder.add_frame(frame)
        info = builder.save(tmp_path / "e.gif", num_colors=48, optimize_for_emoji=True)
        passes, details = validate_gif(tmp_path / "e.gif", is_emoji=True, verbose=False)
    finally:
        sys.path.pop(0)
        for name in [m for m in sys.modules if m == "core" or m.startswith("core.")]:
            del sys.modules[name]
    assert passes and info["frames"] == 8 and details["width"] == 128


def test_with_server_runs_a_command_while_a_server_listens(tmp_path):
    port = 8000 + (abs(hash(str(tmp_path))) % 1000)
    command = (f"import urllib.request; print(urllib.request.urlopen('http://localhost:{port}').status)")
    result = run(SKILLS / "webapp-testing" / "scripts" / "with_server.py", "--server",
                 f"{sys.executable} -m http.server {port}", "--port", port, "--", sys.executable, "-c", command,
                 cwd=tmp_path)
    assert "200" in result.stdout and "stopped 1 server" in result.stdout


def test_skill_creator_scripts_with_a_stand_in_eirene(tmp_path):
    fake = tmp_path / "fake-eirene"
    fake.write_text(f"""#!{sys.executable}
import json, os, pathlib, sys
a = sys.argv[1:]
cwd = a[a.index("-C") + 1]
prompt = a[a.index("-p") + 1]
def out(**e): print(json.dumps(e), flush=True)
if "--max-steps" in a:
    if "widget" in prompt:
        home = os.environ["EIRENE_HOME"]
        out(type="tool_end", id="1", name="load_skill", label="load_skill", is_error=False, seconds=0,
            result=f"# Skill: demo\\nSkill directory: {{home}}/skills/demo")
    out(type="result", result={{"status": "completed"}}); sys.exit(0)
mine = (pathlib.Path(cwd) / "skill" / "SKILL.md").exists()
(pathlib.Path(cwd) / "outputs" / "r.txt").write_text("skill" if mine else "plain")
out(type="tool_start", id="1", name="write_file", label="outputs/r.txt", kind="write")
out(type="tool_end", id="1", name="write_file", label="outputs/r.txt", is_error=False, seconds=0, result="ok")
out(type="text", text="done")
out(type="result", result={{"status": "completed", "input_tokens": 5, "output_tokens": 5, "duration_seconds": 1,
    "tool_calls": [{{"name": "write_file"}}], "tool_call_count": 1, "exit_code": 0}})
""")
    fake.chmod(0o755)
    skill = tmp_path / "demo"
    (skill / "evals").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: demo\ndescription: A demo skill used to test the skill creator "
                                    "scripts.\n---\n\n# Demo\n")
    (skill / "evals" / "evals.json").write_text(json.dumps({"skill_name": "demo", "evals": [
        {"id": 1, "name": "first", "prompt": "write r.txt"}]}))
    creator = SKILLS / "skill-creator"
    run("-m", "scripts.run_tests", "--skill", skill, "--eirene", fake, cwd=creator)
    iteration = tmp_path / "demo-workspace" / "iteration-1"
    assert (iteration / "first" / "with_skill" / "run-1" / "outputs" / "r.txt").read_text() == "skill"
    assert (iteration / "first" / "without_skill" / "run-1" / "outputs" / "r.txt").read_text() == "plain"
    for config, passed in (("with_skill", True), ("without_skill", False)):
        (iteration / "first" / config / "run-1" / "grading.json").write_text(json.dumps(
            {"expectations": [{"text": "says skill", "passed": passed, "evidence": "r.txt"}]}))
    run("-m", "scripts.aggregate_benchmark", iteration, "--skill-name", "demo", cwd=creator)
    benchmark = json.loads((iteration / "benchmark.json").read_text())
    assert benchmark["run_summary"]["delta"]["pass_rate"] == "+1.00"
    run(creator / "eval-viewer" / "generate_review.py", iteration, "--skill-name", "demo",
        "--static", tmp_path / "review.html", "--no-open")
    assert "first-with_skill" in (tmp_path / "review.html").read_text()
    evals = tmp_path / "trigger.json"
    evals.write_text(json.dumps([{"query": "widget report please", "should_trigger": True},
                                 {"query": "bake bread", "should_trigger": False}]))
    home = tmp_path / "home"
    (home / "skills").mkdir(parents=True)
    env_run = subprocess.run([sys.executable, "-m", "scripts.trigger_eval", "--eval-set", evals, "--skill-path", skill,
                              "--eirene", fake, "--runs", "1"], capture_output=True, text=True, cwd=creator,
                             env={**os.environ, "EIRENE_HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"})
    assert env_run.returncode == 0, env_run.stderr
    assert json.loads(env_run.stdout)["summary"]["accuracy"] == 1.0
    run("-m", "scripts.package_skill", skill, tmp_path, cwd=creator)
    assert zipfile.ZipFile(tmp_path / "demo.skill").namelist() == ["demo/SKILL.md"]


def test_docx_reader_shows_structure_changes_and_comments(tmp_path):
    scripts = SKILLS / "docx" / "scripts"
    stamp = 'w:author="Ada" w:date="2025-01-01T00:00:00Z"'
    doc = make_docx(tmp_path / "d.docx",
                    '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Status</w:t></w:r></w:p>'
                    f'<w:p><w:r><w:t xml:space="preserve">Fee </w:t></w:r><w:del w:id="1" {stamp}><w:r>'
                    f'<w:delText>10</w:delText></w:r></w:del><w:ins w:id="2" {stamp}><w:r><w:t>20</w:t></w:r></w:ins></w:p>'
                    '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>'
                    '<w:r><w:t>item</w:t></w:r></w:p>'
                    '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>B</w:t></w:r></w:p>'
                    '</w:tc></w:tr><w:tr><w:tc><w:p><w:r><w:t>1</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>2</w:t>'
                    '</w:r></w:p></w:tc></w:tr></w:tbl>')
    out = run(scripts / "docx_text.py", doc).stdout
    assert "# Status" in out and "Fee 20" in out and "10" not in out.replace("Fee 20", "")
    assert "- item" in out and "| A | B |" in out and "| 1 | 2 |" in out
    marked = run(scripts / "docx_text.py", doc, "--changes").stdout
    assert "[-10-](Ada)[+20+]" in marked


@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX shell script as a fake LibreOffice")
def test_soffice_wrapper_stops_a_runaway_conversion_and_its_children(tmp_path):
    fake = tmp_path / "fake-soffice"
    # A launcher that leaves a child writing forever, like soffice.bin behind oosplash.
    fake.write_text("#!/bin/sh\nfor a in \"$@\"; do last=$a; done\n"
                    f"( while :; do head -c 1048576 /dev/zero >> {tmp_path}/out/data.txt; done ) &\nwait\n")
    fake.chmod(0o755)
    (tmp_path / "out").mkdir()
    env = {**os.environ, "SOFFICE": str(fake), "SOFFICE_MAX_OUTPUT_MB": "5", "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, SKILLS / "docx" / "scripts" / "office" / "soffice.py",
                             "--timeout", "60", "--convert-to", "txt", "--outdir", tmp_path / "out", "x.docx"],
                            capture_output=True, text=True, env=env, timeout=90)
    assert result.returncode and "looping" in result.stdout + result.stderr
    assert not (tmp_path / "out" / "data.txt").exists()  # the partial output is removed
    size = sum(p.stat().st_size for p in (tmp_path / "out").iterdir())
    import time
    time.sleep(1)
    assert sum(p.stat().st_size for p in (tmp_path / "out").iterdir()) == size  # nothing still writing


def test_mcp_evaluation_stops_when_the_server_does_not_start(tmp_path):
    fake = tmp_path / "fake-eirene"
    fake.write_text(f"""#!{sys.executable}
import json
print(json.dumps({{"type": "notice", "text": "MCP: MCP server example exited: no such file"}}))
print(json.dumps({{"type": "text", "text": "<response>NOT_FOUND</response>"}}))
print(json.dumps({{"type": "result", "result": {{"output": "<response>NOT_FOUND</response>", "status": "completed",
    "exit_code": 0, "tool_calls": []}}}}))
""")
    fake.chmod(0o755)
    questions = tmp_path / "q.xml"
    questions.write_text("<evaluation><qa_pair><question>How many?</question><answer>3</answer></qa_pair>"
                         "<qa_pair><question>Who?</question><answer>Ada</answer></qa_pair></evaluation>")
    result = run(SKILLS / "mcp-builder" / "scripts" / "evaluation.py", questions, "--server", "example",
                 "--eirene", fake, check=False)
    assert result.returncode == 2 and "MCP server example exited" in result.stderr


def test_gif_drawing_helpers_take_an_image_or_a_draw(tmp_path):
    pytest.importorskip("PIL")
    from PIL import ImageDraw
    sys.path.insert(0, str(SKILLS / "slack-gif-creator"))
    try:
        from core.frame_composer import draw_circle, draw_text, finish, supersample
        canvas = supersample(64, 64)
        draw_circle(ImageDraw.Draw(canvas), (128, 128), 60, fill=(255, 140, 0, 255))
        draw_text(canvas, "x", (128, 128), size=40, fill=(0, 0, 0, 255))
        assert finish(canvas, 64).size == (64, 64)
    finally:
        sys.path.pop(0)
        for name in [m for m in sys.modules if m == "core" or m.startswith("core.")]:
            del sys.modules[name]


def test_web_artifacts_setup_uses_a_pnpm_other_programs_can_start():
    script = (SKILLS / "web-artifacts-builder" / "scripts" / "init-artifact.sh").read_text()
    assert "npm install -g pnpm@10" in script and "execFileSync" in script
