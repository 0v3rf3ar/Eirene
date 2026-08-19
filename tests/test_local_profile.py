"""Adaptive local Ollama profiles."""

from eirene.providers import local_profile
from eirene.providers.local_profile import LocalProfile, parameter_billions


def test_parameter_count_is_read_from_common_ollama_names():
    assert parameter_billions("qwen3.5:4b") == 4
    assert parameter_billions("deepseek-r1:8b-q4_K_M") == 8
    assert parameter_billions("model-without-size") is None


def test_four_billion_parameter_models_are_compact():
    profile = LocalProfile.detect("qwen3.5:4b")
    assert profile.tier == "compact"
    assert profile.max_tokens == 1024
    assert profile.max_iterations == 5
    assert profile.context_tokens == 4096


def test_compact_profile_removes_expensive_tools_and_prompt():
    profile = LocalProfile.detect("qwen3.5:4b")
    tools = [{"name": "list_dir"}, {"name": "browser_inspect"},
             {"name": "web_search"}, {"name": "web_fetch"}, {"name": "read_file"}]
    assert [item["name"] for item in profile.tools(tools)] == [
        "list_dir", "web_search", "web_fetch", "read_file"]
    original = "Sandbox: /tmp/project\nMode is manual.\n" + "word " * 2000
    prompt = profile.system(original)
    assert "/tmp/project" in prompt
    assert "Mode: manual" in prompt
    assert len(prompt) < 1000


def test_ram_detection_uses_posix_sysconf_when_proc_is_unavailable(monkeypatch):
    monkeypatch.setattr(local_profile.Path, "read_text",
                        lambda self, **kwargs: (_ for _ in ()).throw(OSError()))
    values = {"SC_PHYS_PAGES": 4 * 1024 * 1024, "SC_PAGE_SIZE": 4096}
    monkeypatch.setattr(local_profile.os, "sysconf", lambda key: values[key])
    assert local_profile._ram_gb() == 16


def test_apple_silicon_unified_memory_counts_as_model_memory(monkeypatch):
    monkeypatch.setattr(local_profile.sys, "platform", "darwin")
    monkeypatch.setattr(local_profile, "platform_machine", lambda: "arm64")
    monkeypatch.setattr(local_profile, "_ram_gb", lambda: 24)
    monkeypatch.setattr(local_profile.Path, "glob", lambda self, pattern: [])
    monkeypatch.setattr(local_profile.Path, "exists", lambda self: False)
    assert local_profile._gpu_vram_gb() == 12
