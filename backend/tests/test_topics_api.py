def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def test_hotspot_topic_collect_and_adopt(authenticated_client) -> None:
    client, csrf_token = authenticated_client

    collect = client.post(
        "/api/topics/hotspots/collect",
        headers=csrf_headers(csrf_token),
        json={
            "query": "最近 AI 编码工作流热点",
            "source_message": "热点搜集选题",
            "candidates": [
                {
                    "topic_key": "ai-coding-workflow-hotspot",
                    "title": "AI 编码工作流为什么突然火了",
                    "hook": "从 Linear + Symphony 看大厂怎么把 issue 变成 PR",
                    "summary": "介绍 AI coding workflow 的工程化价值。",
                    "source_kind": "hotspot_research",
                    "evidence_urls": ["https://example.com/source"],
                }
            ],
        },
    )
    assert collect.status_code == 201
    candidate = collect.json()["candidates"][0]
    assert candidate["topic_key"] == "ai-coding-workflow-hotspot"

    adopt = client.post(
        f"/api/topics/{candidate['id']}/adopt",
        headers=csrf_headers(csrf_token),
        json={"target_platforms": ["Hexo", "公众号"], "article_style_key": "rational_depth", "target_word_count": 3000},
    )
    assert adopt.status_code == 200
    body = adopt.json()
    assert body["candidate"]["status"] == "adopted"
    assert body["article"]["source_kind"] == "hotspot_topic"
    assert body["article"]["target_platforms"] == ["Hexo", "公众号"]
