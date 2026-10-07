#!/usr/bin/env python3
"""voiceover：把视频文案变成可直接剪辑的配音（Fish Audio TTS）。

  init  文案.txt -o narration.json   拆句，自动生成读法（say），写成可编辑的稿子
  synth narration.json --out DIR     一句一个文件；只合成新增 / 改过的句子
  build narration.json --out DIR     测每句时长 → vo.json、整条 voiceover.mp3、字幕 voiceover.srt
  run   文案.txt|narration.json --out DIR    以上全部

配置（按优先级取第一个非空值）：环境变量 → ~/.config/voiceover.json 同名字段
  FISH_API_KEY        必填
  FISH_REFERENCE_ID   必填，Fish Audio 声音模型 ID（发现页 → ⋯ → 复制模型 ID）
  FISH_TTS_MODEL      可选，默认 s2.1-pro-free
  FISH_API_BASE_URL   可选，默认 https://api.fish.audio
只依赖 Python 3 标准库和 ffmpeg。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "voiceover.json"
DEFAULTS = {"FISH_TTS_MODEL": "s2.1-pro-free", "FISH_API_BASE_URL": "https://api.fish.audio"}
MANIFEST = ".voiceover-manifest.json"


class VoError(Exception):
    pass


# ---------------------------------------------------------------- 配置

def config():
    data = {}
    if CONFIG_PATH.is_file():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise VoError(f"无法解析 {CONFIG_PATH}: {type(e).__name__}")
    def get(name):
        v = os.environ.get(name) or data.get(name) or DEFAULTS.get(name)
        return v.strip() if isinstance(v, str) else v
    cfg = {k: get(k) for k in ("FISH_API_KEY", "FISH_REFERENCE_ID", "FISH_TTS_MODEL", "FISH_API_BASE_URL")}
    for k in ("FISH_API_KEY", "FISH_REFERENCE_ID"):
        if not cfg[k] or cfg[k].startswith("<"):
            raise VoError(f"缺少 {k}：设置环境变量，或写进 {CONFIG_PATH}")
    return cfg


# ---------------------------------------------------------------- 读法：数字、缩写转成配音读得准的写法

DIGITS = "零一二三四五六七八九"
WORDS = {"JSON": "Jason", "json": "Jason", "GitHub": "Git Hub", "APP": "A P P", "App": "app"}


def cn_int(n):
    """整数 → 中文读法（到亿以内）：64 → 六十四，1005 → 一千零五。"""
    if n == 0:
        return "零"
    if n >= 10 ** 8:
        return "".join(DIGITS[int(d)] for d in str(n))
    def under_10k(x):
        out, zero = "", False
        for unit, base in (("千", 1000), ("百", 100), ("十", 10), ("", 1)):
            d = x // base % 10
            if d:
                if zero:
                    out += "零"
                out += DIGITS[d] + unit
                zero = False
            elif out:
                zero = True
        return out
    hi, lo = divmod(n, 10000)
    s = (under_10k(hi) + "万" + ("零" if 0 < lo < 1000 else "") + under_10k(lo)) if hi else under_10k(lo)
    return s[1:] if s.startswith("一十") else s


def read_number(s):
    if "." in s:
        a, b = s.split(".", 1)
        return cn_int(int(a)) + "点" + "".join(DIGITS[int(d)] for d in b)
    if len(s) > 1 and s.startswith("0"):
        return "".join(DIGITS[int(d)] for d in s)
    return cn_int(int(s))


def auto_say(text):
    """文案 → 配音读法。只处理规则明确的情况；连着英文字母的数字（如 s2.1、mp3）保持原样，交给人工 / AI 复核。"""
    s = text
    for w, r in WORDS.items():
        s = re.sub(rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])", r, s)
    s = re.sub(r"(?<![\w.])(\d{4})(?=年)", lambda m: "".join(DIGITS[int(d)] for d in m[1]), s)
    s = re.sub(r"(?<![\w.])(\d+(?:\.\d+)?)%", lambda m: "百分之" + read_number(m[1]), s)
    s = re.sub(r"(?<![A-Za-z\d.])(\d+(?:\.\d+)?)(?![A-Za-z\d])", lambda m: read_number(m[1]), s)
    s = re.sub(r"(?<![A-Za-z])([A-Z]{2,5})(?![A-Za-z])", lambda m: " ".join(m[1]), s)
    return s


# ---------------------------------------------------------------- 拆句

def split_script(text, max_len=40):
    """按段落和句末标点拆成一句一条；太短的并到前一句，太长的在逗号处再拆。"""
    out = []
    for para in re.split(r"\n\s*\n|\n", text):
        para = para.strip()
        if not para:
            continue
        sents = [s.strip() for s in re.split(r"(?<=[。！？!?；;])", para) if s.strip()]
        for s in sents:
            while len(s) > max_len:
                cut = max((s.rfind(p, 0, max_len) for p in "，,、："), default=-1)
                if cut <= 0:
                    break
                out.append(s[:cut + 1]); s = s[cut + 1:].strip()
            if out and len(s) < 8 and not re.search(r"[。！？!?]$", out[-1]):
                out[-1] += s
            elif s:
                out.append(s)
    return out


def load_lines(path):
    lines = json.loads(Path(path).read_text(encoding="utf-8"))
    ids = [x["id"] for x in lines]
    if len(ids) != len(set(ids)):
        raise VoError("narration.json 里有重复的 id")
    return lines


def cmd_init(src, out):
    text = Path(src).read_text(encoding="utf-8")
    lines = []
    for i, s in enumerate(split_script(text), 1):
        item = {"id": f"l{i:02d}", "text": s}
        say = auto_say(s)
        if say != s:
            item["say"] = say
        lines.append(item)
    Path(out).write_text(json.dumps(lines, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    flagged = [x["id"] for x in lines if re.search(r"[A-Za-z]\d|\d[A-Za-z]", x.get("say", x["text"]))]
    print(json.dumps({"narration": out, "lines": len(lines), "with_say": sum("say" in x for x in lines),
                      "check_reading": flagged}, ensure_ascii=False))


# ---------------------------------------------------------------- 合成：一句一个文件，只重配改过的

def tts(cfg, text, out, speed=1.0):
    payload = {"text": text, "reference_id": cfg["FISH_REFERENCE_ID"], "format": "mp3"}
    if speed != 1.0:
        payload["prosody"] = {"speed": speed}  # 语速 0.5–2.0
    req = urllib.request.Request(
        cfg["FISH_API_BASE_URL"].rstrip("/") + "/v1/tts",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {cfg['FISH_API_KEY']}", "Content-Type": "application/json", "model": cfg["FISH_TTS_MODEL"]},
    )
    key = cfg["FISH_API_KEY"]
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            audio, ctype = r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        raise VoError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}".replace(key, "***"))
    except urllib.error.URLError as e:
        raise VoError(f"网络错误: {e.reason}")
    if "json" in ctype or len(audio) < 512:
        raise VoError(f"接口没有返回音频: {audio[:300].decode('utf-8', 'replace')}".replace(key, "***"))
    out.write_bytes(audio)


def cmd_synth(narration, outdir, force=False, speed=1.0):
    cfg = config()
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    mpath = outdir / MANIFEST
    manifest = json.loads(mpath.read_text()) if mpath.is_file() else {}
    done, skipped = [], []
    for x in load_lines(narration):
        say = x.get("say") or auto_say(x["text"])
        sp = float(x.get("speed", speed))
        h = hashlib.sha1(f"{say}|{cfg['FISH_REFERENCE_ID']}|{cfg['FISH_TTS_MODEL']}{'' if sp == 1.0 else f'|{sp}'}".encode()).hexdigest()[:16]
        f = outdir / f"{x['id']}.mp3"
        if f.is_file() and not force and manifest.get(x["id"], h) == h:
            manifest[x["id"]] = h
            skipped.append(x["id"])
            continue
        tts(cfg, say, f, sp)
        manifest[x["id"]] = h
        mpath.write_text(json.dumps(manifest, indent=1))
        done.append(x["id"])
        print(f"🎙 {x['id']}  {say}", file=sys.stderr)
    mpath.write_text(json.dumps(manifest, indent=1))
    return {"synthesized": done, "skipped": len(skipped)}


# ---------------------------------------------------------------- 测时长、拼整条、出字幕

def ffmpeg():
    p = shutil.which("ffmpeg")
    if not p:
        raise VoError("需要 ffmpeg")
    return p


def measure(f):
    """返回 (文件时长, 说话时长)：说话时长去掉了结尾的静音，排时间轴用它。"""
    r = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(f), "-af", "silencedetect=n=-40dB:d=0.25", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    dur = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    # 最后一段静音要一直持续到文件结尾才算句尾；句中的停顿（后面还有话）不算
    tail = starts and (len(ends) < len(starts) or ends[-1] >= dur - 0.05)
    last = starts[-1] if tail else dur
    return dur, (last if last > dur - 1.2 else dur)


def sub_chunks(text, max_len=16):
    parts = [p for p in re.split(r"(?<=[，。！？；：、,!?;:])", text) if p.strip()]
    out = []
    for p in parts:
        p = p.strip()
        if out and len(out[-1] + p) <= max_len and not re.search(r"[。！？!?]$", out[-1]):
            out[-1] += p
        else:
            out.append(p)
    return [re.sub(r"[，。；：、,;:]$", "", c) for c in out]


def srt_time(t):
    ms = round(t * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def cmd_build(narration, outdir, gap=0.35, lead=0.2):
    outdir = Path(outdir)
    lines = load_lines(narration)
    items, t = [], lead
    for x in lines:
        f = outdir / f"{x['id']}.mp3"
        if not f.is_file():
            raise VoError(f"缺少 {f}，先运行 synth")
        dur, speech = measure(f)
        items.append({"id": x["id"], "text": x["text"], "file": f.name, "start": round(t, 3),
                      "dur": round(speech, 3), "file_dur": round(dur, 3)})
        t += speech + gap
    total = t - gap + 0.6
    (outdir / "vo.json").write_text(json.dumps(items, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # 整条配音：每句按 start 摆好
    args, chains = [], []
    for i, it in enumerate(items):
        args += ["-i", str(outdir / it["file"])]
        ms = round(it["start"] * 1000)
        chains.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=mono,adelay={ms}[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(len(items)))
    filt = ";".join(chains) + f";{mix}amix=inputs={len(items)}:normalize=0:dropout_transition=0,apad,atrim=0:{total:.3f}[out]"
    r = subprocess.run([ffmpeg(), "-y", "-v", "error", *args, "-filter_complex", filt, "-map", "[out]",
                        "-b:a", "192k", str(outdir / "voiceover.mp3")], capture_output=True, text=True)
    if r.returncode:
        raise VoError(f"ffmpeg 拼接失败: {r.stderr.strip()[:500]}")

    # 字幕：一句里再按标点切短，按字数分配时间
    srt, n = [], 0
    for it in items:
        cs = sub_chunks(it["text"])
        total_chars = sum(len(c) for c in cs) or 1
        acc = 0
        for c in cs:
            a = it["start"] + it["dur"] * acc / total_chars
            acc += len(c)
            b = it["start"] + it["dur"] * acc / total_chars
            n += 1
            srt.append(f"{n}\n{srt_time(a)} --> {srt_time(b)}\n{c}\n")
    (outdir / "voiceover.srt").write_text("\n".join(srt), encoding="utf-8")
    return {"vo_json": str(outdir / "vo.json"), "audio": str(outdir / "voiceover.mp3"),
            "srt": str(outdir / "voiceover.srt"), "lines": len(items), "duration": round(total, 2)}


# ---------------------------------------------------------------- 入口

def main():
    p = argparse.ArgumentParser(description="视频配音：文案 → 逐句配音 → 整条音频 + 字幕")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("init", help="文案拆句，生成 narration.json")
    a.add_argument("script"); a.add_argument("-o", "--output", default="narration.json")
    for name in ("synth", "build", "run"):
        b = sub.add_parser(name)
        b.add_argument("narration", help="narration.json（run 也可以直接给 .txt 文案）")
        b.add_argument("--out", default="voiceover", help="输出目录")
        if name != "synth":
            b.add_argument("--gap", type=float, default=0.35, help="句间停顿（秒）")
        if name != "build":
            b.add_argument("--force", action="store_true", help="全部重新合成")
            b.add_argument("--speed", type=float, default=1.0, help="整体语速 0.5–2.0（单句可在 narration.json 里写 speed）")
    args = p.parse_args()
    try:
        if args.cmd == "init":
            cmd_init(args.script, args.output)
            return
        narration = args.narration
        if args.cmd == "run" and not narration.endswith(".json"):
            narration = str(Path(args.out) / "narration.json")
            Path(args.out).mkdir(parents=True, exist_ok=True)
            cmd_init(args.narration, narration)
        result = {}
        if args.cmd in ("synth", "run"):
            result.update(cmd_synth(narration, args.out, args.force, args.speed))
        if args.cmd in ("build", "run"):
            result.update(cmd_build(narration, args.out, args.gap))
        print(json.dumps(result, ensure_ascii=False))
    except VoError as e:
        print(f"voiceover error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
