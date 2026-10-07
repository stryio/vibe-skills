# vibe-skills

我在做视频时实际在用的 AI 编程助手 skill，拿去就能用。

| skill | 做什么 |
|---|---|
| [voiceover](voiceover/) | 视频配音：文案 → 逐句配音（改哪句只重配哪句）→ 整条配音 + 对齐的字幕，可直接拖进剪映 |

## 安装

把 skill 文件夹放进你的 AI 编程助手的 skills 目录，例如 Claude Code：

```bash
git clone https://github.com/stryio/vibe-skills.git
cp -r vibe-skills/voiceover ~/.claude/skills/
```

其他支持 skill 的助手（如 Codex）放到它对应的 skills 目录即可。

## voiceover 的配置

1. 去 [Fish Audio](https://fish.audio) 注册。
2. **挑声音**：发现页 → 语言选中文 → 试听 → 看中的声音点「⋯」→ 复制模型 ID。
3. **拿密钥**：开发者 → API 密钥 → 创建 API 密钥 → 复制。
4. 写进 `~/.config/voiceover.json`（不要写进代码，也不要提交到仓库）：

```json
{
  "FISH_API_KEY": "你的密钥",
  "FISH_REFERENCE_ID": "你复制的模型 ID"
}
```

然后对 AI 说一句：**「把这期文案配上音」**。

需要 Python 3 和 ffmpeg。

## 输出

```
voiceover/
├── narration.json   每句的字幕（text）和读法（say），改稿就改这里
├── l01.mp3 …        一句一个文件
├── voiceover.mp3    整条配音
├── voiceover.srt    字幕，时间和声音对齐
└── vo.json          每句的开始时间和时长
```
