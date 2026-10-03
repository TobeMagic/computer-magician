# Reaction Library

这里是正文内小型 reaction assets 的 canonical 库，不是随手堆图的文件夹。

当前目录只允许使用 vendored 第三方素材，旧的自生成 reaction 资产已经废弃。当前来源包括：

- `https://github.com/getActivity/EmojiPackage`
- `https://github.com/zhaoolee/ChineseBQB/tree/master/024Programmer_%E7%A8%8B%E5%BA%8F%E5%91%98BQB`
- `https://github.com/scdd/github-emoji/tree/master/images`

## 目录约定

- `manifest.json`
  - starter pack 的 machine-readable 索引。
- `manifest.schema.json`
  - manifest 合约说明，供 validator 和后续 CI 对齐。
- `by-id/<reaction-id>/`
  - 每个 reaction 的稳定目录，当前只保留：
    - `transparent.png`
- `sources/<repo>/<category>/`
  - 对应 reaction 的原始来源文件，供 validator 审计来源。
- `preview/index.html`
  - 可选的本地预览页，不属于发布链路必需品。

## 引用方式

正文里不要写文件路径，只写稳定 placeholder：

```text
[[reaction:no-bug-blessing]]
[[reaction:take-this-blame|alt=这口锅先背上再说]]
[[reaction:dalao-carry-me|alt=卡住时看到大佬出现的表情]]
```

解析时：

- `id` 是稳定主键，不随文案变动
- `default_alt` 是默认可读替代文本
- `tags / tone / trigger_scenes` 负责筛选和推荐
- `variants` 当前只保留发布主路径 `transparent_png`

## 新增素材流程

1. 只从当前允许的 vendored 图库挑选候选图，不允许再自绘或接入其他图库。
2. 先把原始文件 vendored 到 `sources/<repo>/<分类>/`。
3. 为新素材分配稳定 `id`，创建 `by-id/<id>/`。
4. 从 vendored source 生成 `transparent.png`。
5. 在 `manifest.json` 里补：
   - `id`
   - `display_name`
   - `default_alt`
   - `tone`
   - `tags`
   - `trigger_scenes`
   - `source_path`
   - `variants`
6. 做基础校验：

```bash
python3 -m json.tool aimagician/assets/reaction-library/manifest.json >/tmp/reaction-manifest.json
cd backend && .venv/bin/python -m pytest -q \
  tests/test_publish_normalization.py::test_reaction_library_default_is_backend_owned \
  tests/test_publish_normalization.py::test_native_publish_markdown_renders_infographic_and_reactions_with_postgres_audit
```

7. 如需人工扫库，直接打开 `preview/index.html` 或通过后续 AImagician asset-library 后台查看；不要再走 OpenClaw 脚本。

## 设计边界

- 这套库优先服务“段落之间的小反应图”，不是整屏漫画。
- 风格应稳定在：轻吐槽、轻反讽、程序员自嘲、职场无奈、冷幽默。
- 第三方图库不能直接绕过 manifest 接进发布链路。
- 所有来源都必须先 vendored 到 `reaction-library/sources/` 再进入 manifest。
