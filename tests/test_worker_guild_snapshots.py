import ast
from pathlib import Path


def _snapshot_function():
    tree = ast.parse(Path("app/tasks/worker.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "guild_member_snapshots":
            return node
    raise AssertionError("guild_member_snapshots worker was not found")


def test_snapshot_worker_persists_guild_before_recording_foreign_key_child():
    function = _snapshot_function()
    loops = [
        node for node in ast.walk(function)
        if isinstance(node, ast.For)
        and isinstance(node.target, ast.Name)
        and node.target.id == "guild"
    ]
    assert loops
    guild_loop = loops[0]
    try_blocks = [node for node in ast.walk(guild_loop) if isinstance(node, ast.Try)]
    assert try_blocks
    calls = sorted(
        (node.lineno, node.func.id)
        for node in ast.walk(try_blocks[0])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in {"ensure_guild", "record_guild_snapshot"}
    )
    ensure_positions = [line for line, name in calls if name == "ensure_guild"]
    snapshot_positions = [line for line, name in calls if name == "record_guild_snapshot"]
    assert ensure_positions and snapshot_positions
    assert ensure_positions[0] < snapshot_positions[0]
    source = Path("app/tasks/worker.py").read_text(encoding="utf-8")
    assert "stored_guild is None or settings is None" in source



def test_snapshot_worker_isolates_failure_per_guild_and_logs_guild_id():
    function = _snapshot_function()
    guild_loop = next(
        node for node in ast.walk(function)
        if isinstance(node, ast.For)
        and isinstance(node.target, ast.Name)
        and node.target.id == "guild"
    )
    assert any(isinstance(node, ast.Try) for node in guild_loop.body)
    source = Path("app/tasks/worker.py").read_text(encoding="utf-8")
    assert 'logger.exception("guild member snapshot failed guild=%s", guild.id)' in source
    assert "async with session_factory() as session:" in source[source.index("async def guild_member_snapshots"):source.index("@guild_member_snapshots.before_loop")]
