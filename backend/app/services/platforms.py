from __future__ import annotations


PLATFORM_ALIASES = {
    "hexo": "Hexo",
    "wechat": "公众号",
    "weixin": "公众号",
    "wecom": "公众号",
    "微信公众号": "公众号",
    "微信公众平台": "公众号",
    "公众号草稿": "公众号",
    "公众号": "公众号",
    "csdn": "CSDN",
    "juejin": "掘金",
    "掘金": "掘金",
    "zhihu": "知乎",
    "知乎": "知乎",
    "infoq": "InfoQ",
    "51cto": "51CTO",
    "cnblogs": "博客园",
    "博客园": "博客园",
    "bilibili": "B站专栏",
    "b站": "B站专栏",
    "b站专栏": "B站专栏",
    "腾讯云": "腾讯云开发者社区",
    "腾讯云开发者社区": "腾讯云开发者社区",
    "阿里云": "阿里云开发者社区",
    "阿里云开发者社区": "阿里云开发者社区",
    "华为云": "华为云开发者社区",
    "华为云开发者社区": "华为云开发者社区",
    "火山引擎": "火山引擎开发者社区",
    "火山引擎开发者社区": "火山引擎开发者社区",
}


def canonical_platform(platform: str) -> str:
    raw = str(platform or "").strip()
    if not raw:
        return ""
    compact = raw.replace(" ", "").strip()
    return PLATFORM_ALIASES.get(compact.lower(), PLATFORM_ALIASES.get(compact, raw))


def canonical_platforms(platforms: list[str] | tuple[str, ...]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for platform in platforms:
        normalized = canonical_platform(platform)
        if not normalized or normalized in seen:
            continue
        output.append(normalized)
        seen.add(normalized)
    return output
