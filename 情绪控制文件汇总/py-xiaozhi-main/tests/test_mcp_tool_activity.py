import json

from src.avatar.emotion_classifier import classify_tool_name
from src.avatar.emotion_engine import EmotionEngine
from src.mcp.mcp_server import McpServer


class FakeTool:
    def __init__(self, name: str, result: dict | None = None, error: Exception | None = None):
        self.name = name
        self._result = result or {"content": [{"type": "text", "text": "ok"}]}
        self._error = error

    async def call(self, arguments: dict) -> str:
        if self._error:
            raise self._error
        return json.dumps(self._result)

    def to_json(self) -> dict:
        return {"name": self.name}


def test_qualified_tool_name_avatar_mapping() -> None:
    expected = {
        "self.codex.execute": "编写代码",
        "research.paper_search": "论文搜索",
        "search.arxiv": "论文搜索",
        "paper.read": "阅读论文",
        "paper.analyze": "阅读论文",
        "paper.summary": "阅读论文",
        "self.unknown_tool.execute": "协作",
    }
    for tool_name, avatar_state in expected.items():
        assert classify_tool_name(tool_name).avatar_state == avatar_state


def test_tool_result_avatar_is_temporary_and_restores() -> None:
    clock = [0.0]
    engine = EmotionEngine(now_fn=lambda: clock[0])
    engine.decide(tool_name="self.codex.execute")
    success = engine.decide(result_status="success")
    assert success.avatar_state == "灵光一现"
    assert success.is_temporary is True
    clock[0] = 10.0
    assert engine.current_decision().avatar_state == "细心讲解"

    engine.decide(tool_name="self.unknown.execute")
    failed = engine.decide(result_status="failed")
    assert failed.avatar_state == "温柔安抚"
    assert failed.is_temporary is True
    clock[0] = 20.0
    assert engine.current_decision().avatar_state == "细心讲解"


async def test_only_tools_call_emits_lifecycle() -> None:
    server = McpServer()
    activities = []
    replies = []
    server.tools = [FakeTool("self.codex.execute")]

    async def collect(activity) -> None:
        activities.append(activity)

    server.set_tool_lifecycle_callback(collect)

    async def send(payload: str) -> None:
        replies.append(json.loads(payload))

    server.set_send_callback(send)
    await server.parse_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    await server.parse_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert activities == []

    await server.parse_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "self.codex.execute", "arguments": {}},
        }
    )
    assert [activity.status for activity in activities] == ["running", "succeeded"]
    assert replies[-1]["id"] == 3
    assert "result" in replies[-1]


async def test_is_error_result_and_exception_emit_failed() -> None:
    server = McpServer()
    activities = []
    replies = []
    server.tools = [
        FakeTool(
            "paper.summary",
            {"isError": True, "content": [{"type": "text", "text": "bad paper"}]},
        ),
        FakeTool("broken.tool", error=RuntimeError("boom")),
    ]

    async def collect(activity) -> None:
        activities.append(activity)

    server.set_tool_lifecycle_callback(collect)

    async def send(payload: str) -> None:
        replies.append(json.loads(payload))

    server.set_send_callback(send)
    for request_id, tool_name in ((1, "paper.summary"), (2, "broken.tool")):
        await server.parse_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": {}},
            }
        )

    assert [activity.status for activity in activities] == [
        "running",
        "failed",
        "running",
        "failed",
    ]
    assert replies[0]["result"]["isError"] is True
    assert replies[1]["error"]["message"] == "boom"


async def test_lifecycle_callback_failure_does_not_block_rpc_reply() -> None:
    server = McpServer()
    replies = []
    server.tools = [FakeTool("self.codex.execute")]

    async def broken_lifecycle(_activity) -> None:
        raise RuntimeError("ui unavailable")

    async def send(payload: str) -> None:
        replies.append(json.loads(payload))

    server.set_tool_lifecycle_callback(broken_lifecycle)
    server.set_send_callback(send)
    await server.parse_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "self.codex.execute", "arguments": {}},
        }
    )

    assert replies[-1]["result"]["content"][0]["text"] == "ok"
