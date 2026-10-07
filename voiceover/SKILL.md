---
name: voiceover
description: >-
  视频配音：把文案变成可直接剪辑的配音。文案按句拆开、数字和英文缩写自动转成读法，
  一句一个音频文件、改哪句只重配哪句，最后输出整条配音 voiceover.mp3、对齐的字幕 voiceover.srt
  和每句时长 vo.json。用 Fish Audio TTS。用户说“配音 / 配旁白 / 把文案配上音 / 生成字幕”时使用。
---

# 视频配音（voiceover）

脚本：`scripts/voiceover.py`（Python 3 标准库 + ffmpeg）。不要临时拼 curl，不要把密钥写进命令、代码或日志。

## 工作流程

1. **拿到文案**。用户给的是一段文字就先存成 `文案.txt`（UTF-8）。
2. **拆句 + 生成读法**：
   ```bash
   python3 <skill目录>/scripts/voiceover.py init 文案.txt -o narration.json
   ```
   `narration.json` 每句一条：`text` 是字幕，`say` 是配音读法（没有 `say` 就按 `text` 读）。
3. **复核读法**（必须做）：打开 `narration.json`，逐句检查 `say`。规则只会处理清楚的情况（数字、百分比、年份、全大写缩写），
   输出里 `check_reading` 列出的句子含有字母和数字连在一起的写法（如 `s2.1`、`mp3`、`GPT-4o`），要你按常见读法手动补 `say`。
   多音字、专有名词读不准时，也在 `say` 里改写（例如同音字替换）。
4. **合成 + 出成品**：
   ```bash
   python3 <skill目录>/scripts/voiceover.py run narration.json --out voiceover
   ```
   - 一句一个文件 `voiceover/<id>.mp3`。再次运行时只合成**新增或改过**的句子（按读法 + 音色判断），其余跳过
   - `voiceover/voiceover.mp3`：整条配音，句间停顿 `--gap`（默认 0.35 秒）
   - `voiceover/voiceover.srt`：字幕，时间按每句实际时长对齐，可直接拖进剪映等剪辑软件
   - `voiceover/vo.json`：每句的开始时间和说话时长，做动画或排画面时间轴用
5. **调语速**：整体用 `--speed 1.1`（0.5–2.0）；某一句单独调，在 narration.json 里给那句加 `"speed": 0.9`。语速变了的句子会自动重配。
6. **改稿**：直接改 `narration.json` 里某句的 `text` / `say`，重新 `run`，只会重配这一句，整条音频和字幕自动更新。
7. 完成后报告：合成了哪几句、总时长、三个输出文件的路径。

## 配置

按优先级取第一个非空值：环境变量 → `~/.config/voiceover.json` 同名字段。缺少时脚本会报错，此时让用户去填写，不要去别的文件里找密钥。

| 字段 | 说明 |
|---|---|
| `FISH_API_KEY` | 必填。Fish Audio 控制台 → 开发者 → API 密钥 → 创建 |
| `FISH_REFERENCE_ID` | 必填。声音模型 ID：Fish Audio 发现页挑一个声音 → ⋯ → 复制模型 ID |
| `FISH_TTS_MODEL` | 可选，默认 `s2.1-pro-free`（免费模型） |
| `FISH_API_BASE_URL` | 可选，默认 `https://api.fish.audio` |

## 其他命令

- `synth narration.json --out DIR`：只合成，不拼接；`--force` 全部重新合成（换了音色时用不着，音色变了会自动重配）
- `build narration.json --out DIR`：只测时长、拼整条、出字幕
- `run 文案.txt --out DIR`：跳过复核一步到位（会在 DIR 里生成 narration.json）。读法要求高时别用这个
