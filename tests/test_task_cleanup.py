import asyncio
import ast
import importlib.util
import os
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "bot" / "helper" / "ext_utils" / "task_cleanup.py"
SPEC = importlib.util.spec_from_file_location("task_cleanup", MODULE_PATH)
task_cleanup = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(task_cleanup)


def run(coroutine):
    return asyncio.run(coroutine)


def test_clean_task_paths_removes_only_requested_task(tmp_path):
    root = tmp_path / "downloads"
    task = root / "101"
    sibling = root / "202"
    task.mkdir(parents=True)
    sibling.mkdir()
    (task / "payload.bin").write_bytes(b"task")
    (sibling / "keep.bin").write_bytes(b"keep")

    removed = run(task_cleanup.clean_task_paths([task], root))

    assert removed == [str(task)]
    assert not task.exists()
    assert (sibling / "keep.bin").read_bytes() == b"keep"


def test_clean_task_paths_is_idempotent(tmp_path):
    root = tmp_path / "downloads"
    task = root / "101"
    task.mkdir(parents=True)

    assert run(task_cleanup.clean_task_paths([task, task], root)) == [str(task)]
    assert run(task_cleanup.clean_task_paths([task], root)) == []


def test_clean_task_paths_refuses_root_and_traversal(tmp_path):
    root = tmp_path / "downloads"
    outside = tmp_path / "private"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("keep", encoding="utf-8")

    removed = run(task_cleanup.clean_task_paths([root, outside], root))

    assert removed == []
    assert root.exists()
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "keep"


def test_clean_task_paths_refuses_symlink_escape(tmp_path):
    if os.name == "nt":
        return
    root = tmp_path / "downloads"
    outside = tmp_path / "private"
    root.mkdir()
    outside.mkdir()
    link = root / "101"
    link.symlink_to(outside, target_is_directory=True)

    assert run(task_cleanup.clean_task_paths([link], root)) == []
    assert link.exists()
    assert outside.exists()


def test_release_process_memory_runs_collection(monkeypatch):
    monkeypatch.setattr(task_cleanup, "collect", lambda: 17)
    monkeypatch.setattr(task_cleanup, "platform", "win32")

    assert run(task_cleanup.release_process_memory()) == (17, False)


def test_terminal_cleanup_runs_after_success_and_failure():
    class Listener:
        seed = False

        def __init__(self):
            self.finalized = 0

        async def finalize_terminal_task(self):
            self.finalized += 1

        @task_cleanup.ensure_terminal_cleanup()
        async def success(self):
            return "ok"

        @task_cleanup.ensure_terminal_cleanup()
        async def failure(self):
            raise RuntimeError("הודעת הסיום נכשלה")

    listener = Listener()
    assert run(listener.success()) == "ok"
    assert listener.finalized == 1
    with pytest.raises(RuntimeError, match="הודעת הסיום נכשלה"):
        run(listener.failure())
    assert listener.finalized == 2


def test_terminal_cleanup_preserves_active_seeding_task():
    class Listener:
        seed = True
        finalized = 0

        async def finalize_terminal_task(self):
            self.finalized += 1

        @task_cleanup.ensure_terminal_cleanup(preserve_while_seeding=True)
        async def finish_upload(self):
            return None

    listener = Listener()
    run(listener.finish_upload())
    assert listener.finalized == 0


def test_all_terminal_callbacks_are_guarded_by_cleanup_decorator():
    source_path = (
        Path(__file__).parents[1] / "bot" / "helper" / "listeners" / "task_listener.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    task_listener = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TaskListener"
    )
    callbacks = {
        node.name: node
        for node in task_listener.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    for name in ("on_upload_complete", "on_download_error", "on_upload_error"):
        decorators = callbacks[name].decorator_list
        assert any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Name)
            and decorator.func.id == "ensure_terminal_cleanup"
            for decorator in decorators
        ), f"חסר מנגנון ניקוי סופי עבור {name}"
