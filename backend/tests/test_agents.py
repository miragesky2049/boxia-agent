"""智能体 CRUD、配置默认值与工具/技能关联测试。"""

from fastapi.testclient import TestClient


def _create_tool(client: TestClient, headers: dict[str, str], name: str = "工具A") -> int:
    response = client.post(
        "/api/v1/admin/tools",
        json={"name": name, "description": "", "type": "http", "config": {}},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_skill(client: TestClient, headers: dict[str, str], name: str = "技能A") -> int:
    response = client.post(
        "/api/v1/admin/skills",
        json={"name": name, "description": "", "content": "", "config": {}},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_agent(
    client: TestClient, headers: dict[str, str], name: str = "智能体A", **extra
) -> dict:
    response = client.post(
        "/api/v1/admin/agents",
        json={"name": name, "description": "描述", **extra},
        headers=headers,
    )
    return response


def test_create_with_default_config(client: TestClient, auth_headers) -> None:
    response = _create_agent(client, auth_headers)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "智能体A"
    assert body["is_enabled"] is True
    assert body["tool_ids"] == []
    assert body["skill_ids"] == []
    assert body["config"]["model"]["model"] == "glm-5"
    assert body["config"]["model"]["temperature"] == 0.2
    assert body["config"]["other"]["max_turns"] == 30
    assert body["config"]["conversation"]["faqs"] == []
    assert body["config"]["extensions"] == {}


def test_create_with_full_config(client: TestClient, auth_headers) -> None:
    payload = {
        "name": "完整智能体",
        "avatar_url": "https://example.com/a.png",
        "description": "带完整配置",
        "is_enabled": False,
        "config": {
            "model": {"model": "gpt-4o", "temperature": 0.7, "max_output_tokens": 1024},
            "prompt": {"role_setting": "你是陪练教练", "persona": "专业"},
            "memory": {"enabled": True, "long_term_enabled": True},
            "conversation": {
                "welcome": "你好",
                "faqs": [{"question": "怎么用", "answer": "直接提问"}],
            },
            "channel": {"type": "web", "enabled": True},
            "knowledge": {"enabled": True, "dataset_ids": ["ds-1"]},
            "other": {"max_turns": 50, "web_search": True},
            "extensions": {"chat.position": 1},
        },
        "tool_ids": [],
        "skill_ids": [],
    }

    response = client.post("/api/v1/admin/agents", json=payload, headers=auth_headers)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["config"]["model"]["model"] == "gpt-4o"
    # 未显式提供的字段仍补默认值
    assert body["config"]["model"]["context_window"] == 65536
    assert body["config"]["prompt"]["memory_count"] == 20
    assert body["config"]["other"]["create_task"] is True
    assert body["config"]["knowledge"]["dataset_ids"] == ["ds-1"]
    assert body["config"]["extensions"] == {"chat.position": 1}
    assert body["is_enabled"] is False


def test_relations_saved_and_deduplicated(client: TestClient, auth_headers) -> None:
    tool_a = _create_tool(client, auth_headers, "工具A")
    tool_b = _create_tool(client, auth_headers, "工具B")
    skill_a = _create_skill(client, auth_headers, "技能A")

    response = _create_agent(
        client,
        auth_headers,
        tool_ids=[tool_b, tool_a, tool_b],
        skill_ids=[skill_a, skill_a],
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["tool_ids"] == sorted([tool_a, tool_b])
    assert body["skill_ids"] == [skill_a]

    detail = client.get(f"/api/v1/admin/agents/{body['id']}", headers=auth_headers).json()
    assert detail["tool_ids"] == sorted([tool_a, tool_b])


def test_relations_replaced_on_update(client: TestClient, auth_headers) -> None:
    tool_a = _create_tool(client, auth_headers, "工具A")
    tool_b = _create_tool(client, auth_headers, "工具B")
    skill_a = _create_skill(client, auth_headers, "技能A")
    agent = _create_agent(
        client,
        auth_headers,
        tool_ids=[tool_a],
        skill_ids=[skill_a],
    ).json()

    updated = client.put(
        f"/api/v1/admin/agents/{agent['id']}",
        json={"name": "智能体A", "description": "", "tool_ids": [tool_b], "skill_ids": []},
        headers=auth_headers,
    )

    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["tool_ids"] == [tool_b]
    assert body["skill_ids"] == []


def test_relations_missing_tool(client: TestClient, auth_headers) -> None:
    response = _create_agent(client, auth_headers, tool_ids=[999999])

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert "工具不存在" in response.json()["detail"]


def test_relations_missing_skill(client: TestClient, auth_headers) -> None:
    response = _create_agent(client, auth_headers, skill_ids=[888888])

    assert response.status_code == 422
    assert "技能不存在" in response.json()["detail"]


def test_tool_delete_cascades_relation(client: TestClient, auth_headers) -> None:
    tool_id = _create_tool(client, auth_headers)
    agent = _create_agent(client, auth_headers, tool_ids=[tool_id]).json()

    assert client.delete(f"/api/v1/admin/tools/{tool_id}", headers=auth_headers).status_code == 204

    detail = client.get(f"/api/v1/admin/agents/{agent['id']}", headers=auth_headers).json()
    assert detail["tool_ids"] == []


def test_agent_delete_cascades_relations(client: TestClient, auth_headers) -> None:
    tool_id = _create_tool(client, auth_headers)
    skill_id = _create_skill(client, auth_headers)
    agent = _create_agent(client, auth_headers, tool_ids=[tool_id], skill_ids=[skill_id]).json()

    assert (
        client.delete(f"/api/v1/admin/agents/{agent['id']}", headers=auth_headers).status_code
        == 204
    )

    # 关联删除后资源本身仍存在
    assert client.get(f"/api/v1/admin/tools/{tool_id}", headers=auth_headers).status_code == 200
    assert client.get(f"/api/v1/admin/skills/{skill_id}", headers=auth_headers).status_code == 200
    assert (
        client.get(f"/api/v1/admin/agents/{agent['id']}", headers=auth_headers).status_code == 404
    )


def test_duplicate_name_conflict(client: TestClient, auth_headers) -> None:
    _create_agent(client, auth_headers, "Agent One")

    response = _create_agent(client, auth_headers, "agent one")

    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


def test_list_summary_without_config(client: TestClient, auth_headers) -> None:
    _create_agent(client, auth_headers, "甲")
    _create_agent(client, auth_headers, "乙")

    page = client.get("/api/v1/admin/agents?page=1&page_size=10", headers=auth_headers).json()

    assert page["total"] == 2
    assert [item["name"] for item in page["items"]] == ["乙", "甲"]
    assert "config" not in page["items"][0]
    assert "tool_ids" not in page["items"][0]


def test_list_keyword_and_enabled_filter(client: TestClient, auth_headers) -> None:
    _create_agent(client, auth_headers, "陪练剧本", description="生成剧本")
    _create_agent(client, auth_headers, "客服助手", description="答疑", is_enabled=False)

    searched = client.get("/api/v1/admin/agents?keyword=剧本", headers=auth_headers).json()
    assert searched["total"] == 1
    assert searched["items"][0]["name"] == "陪练剧本"

    disabled = client.get("/api/v1/admin/agents?is_enabled=false", headers=auth_headers).json()
    assert disabled["total"] == 1
    assert disabled["items"][0]["name"] == "客服助手"


def test_update_agent(client: TestClient, auth_headers) -> None:
    agent = _create_agent(client, auth_headers).json()

    response = client.put(
        f"/api/v1/admin/agents/{agent['id']}",
        json={
            "name": "新名字",
            "avatar_url": "",
            "description": "更新后的描述",
            "is_enabled": False,
            "config": {"model": {"model": "glm-4.5", "temperature": 1.2}},
        },
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "新名字"
    assert body["description"] == "更新后的描述"
    assert body["is_enabled"] is False
    assert body["config"]["model"]["model"] == "glm-4.5"
    assert body["config"]["model"]["temperature"] == 1.2


def test_agent_not_found(client: TestClient, auth_headers) -> None:
    assert client.get("/api/v1/admin/agents/999999", headers=auth_headers).status_code == 404
    assert (
        client.put(
            "/api/v1/admin/agents/999999",
            json={"name": "不存在"},
            headers=auth_headers,
        ).status_code
        == 404
    )
    assert client.delete("/api/v1/admin/agents/999999", headers=auth_headers).status_code == 404


def test_agent_validation_error(client: TestClient, auth_headers) -> None:
    too_hot = _create_agent(client, auth_headers, config={"model": {"temperature": 5}})
    assert too_hot.status_code == 422

    no_name = client.post("/api/v1/admin/agents", json={"description": ""}, headers=auth_headers)
    assert no_name.status_code == 422


def test_agent_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/admin/agents").status_code == 401
    assert client.post("/api/v1/admin/agents", json={"name": "x"}).status_code == 401
