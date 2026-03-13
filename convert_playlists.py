# -*- coding: utf-8 -*-
"""
将 GoMusic 纯文本歌单（每行：<曲名 - 作曲家>）匹配到本地曲库文件，
输出为 椒盐音乐 歌单格式（每行：/storage/emulated/0/Music/曲库/<文件名含扩展名>）

使用方式（在 D:\Workshop\音乐工作目录 下运行）：
  pip install rapidfuzz
  python convert_playlists.py

目录约定（可在 CONFIG 修改）：
  工作目录：D:\Workshop\音乐工作目录
  曲库：    曲库
  歌单：    歌单
  输出：    椒盐歌单_output
"""

from __future__ import annotations

import os
import re
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Dict, Optional

from rapidfuzz import process, fuzz


# ------------------------- CONFIG -------------------------

CONFIG = {
    "workdir": r"D:\Workshop\音乐工作目录",
    "library_dirname": "曲库",
    "playlist_dirname": "歌单",
    "output_dirname": "椒盐歌单_output",
    "report_dirname": "_report",

    # 手机端曲库目录（椒盐歌单每行的前缀）
    "phone_music_dir": "/storage/emulated/0/Music/曲库/",

    # 你曲库里常见音频扩展名（按需增减）
    "audio_exts": {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".ape", ".wma"},

    # 匹配阈值：越高越严格
    "min_score_accept": 90,         # 第一名至少达到这个分才算“可能命中”
    "min_score_margin": 4,          # 第一名与第二名至少拉开这个差距才算“唯一”
    "topk": 5,                      # 取前 K 个候选用于诊断

    # 预处理：删除这些括号内容（可按需调整）
    "strip_bracket_content": False, # True 会更激进：把 (xxx)、（xxx）、[xxx] 等内容整体移除
}

# ---------------------------------------------------------


@dataclass(frozen=True)
class TrackEntry:
    path: Path               # 本地实际路径
    filename: str            # 含扩展名
    stem: str                # 不含扩展名
    norm: str                # 规范化后（用于匹配）
    title_norm: str          # 假设“曲名”部分的规范化（尝试从 "title - artist" 拆）
    artist_norm: str         # 假设“作曲家/作者”部分的规范化


def set_workdir(workdir: str) -> Path:
    wd = Path(workdir).resolve()
    os.chdir(wd)
    return wd


def normalize_text(s: str, strip_bracket_content: bool = False) -> str:
    s = s.strip()

    # 统一一些分隔符
    s = s.replace("—", "-").replace("–", "-").replace("－", "-").replace("—", "-")
    s = s.replace("／", "/").replace("｜", "|").replace("：", ":")

    # 可选：删除括号内容（对“版本信息很多”时有用，但也可能误删关键信息）
    if strip_bracket_content:
        s = re.sub(r"\([^)]*\)", " ", s)
        s = re.sub(r"（[^）]*）", " ", s)
        s = re.sub(r"\[[^\]]*\]", " ", s)
        s = re.sub(r"【[^】]*】", " ", s)

    # 去掉文件系统里常见的替代符号
    s = s.replace("_", " ")

    # 标点弱化：把多种符号都当空格（保留中日韩文字、字母数字）
    # 注意：不做过度清洗，否则不同曲子容易被“洗成一样”
    s = re.sub(r"[“”\"'`]", " ", s)
    s = re.sub(r"[·•]", " ", s)
    s = re.sub(r"[，,;；。.!！?？]", " ", s)
    s = re.sub(r"[\t\r\n]+", " ", s)

    # 统一斜杠两边空格
    s = re.sub(r"\s*/\s*", " / ", s)

    # 连续空格压缩
    s = re.sub(r"\s+", " ", s).strip()

    # 统一大小写（对英文有用；中日文不受影响）
    s = s.lower()

    return s


def split_title_artist(raw: str) -> Tuple[str, str]:
    """
    尝试把 'title - artist' 拆成两段。
    如果没找到分隔符，就返回 (raw, "")。
    """
    # 常见形式：Title - Artist
    parts = [p.strip() for p in raw.split(" - ", 1)]
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0], parts[1]

    # 有些文件名可能是 "Title-Artist" 或 "Title -Artist" 等
    m = re.split(r"\s*-\s*", raw, maxsplit=1)
    if len(m) == 2 and m[0].strip() and m[1].strip():
        return m[0].strip(), m[1].strip()

    return raw.strip(), ""


def build_library_index(library_dir: Path) -> Tuple[List[TrackEntry], Dict[str, List[int]]]:
    tracks: List[TrackEntry] = []
    exact_map: Dict[str, List[int]] = {}

    for p in library_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in CONFIG["audio_exts"]:
            continue

        filename = p.name
        stem = p.stem

        # 文件名 stem 的拆分（假设也是 title - artist）
        title, artist = split_title_artist(stem)

        norm = normalize_text(stem, strip_bracket_content=CONFIG["strip_bracket_content"])
        title_norm = normalize_text(title, strip_bracket_content=CONFIG["strip_bracket_content"])
        artist_norm = normalize_text(artist, strip_bracket_content=CONFIG["strip_bracket_content"]) if artist else ""

        idx = len(tracks)
        tracks.append(TrackEntry(
            path=p,
            filename=filename,
            stem=stem,
            norm=norm,
            title_norm=title_norm,
            artist_norm=artist_norm,
        ))
        exact_map.setdefault(norm, []).append(idx)

    return tracks, exact_map


def score_candidate(query_norm: str, query_title: str, query_artist: str, track: TrackEntry) -> float:
    """
    综合评分：兼顾整体相似度 + title/artist 相似度
    """
    # 整体相似度（更重要）
    s_full = fuzz.token_set_ratio(query_norm, track.norm)

    # title/artist 子评分（在“语序变化/措辞差异”时能拉回来）
    s_title = fuzz.token_set_ratio(query_title, track.title_norm) if query_title else 0
    s_artist = fuzz.token_set_ratio(query_artist, track.artist_norm) if query_artist and track.artist_norm else 0

    # 加权（可按经验调）
    # full 0.70, title 0.20, artist 0.10
    return 0.70 * s_full + 0.20 * s_title + 0.10 * s_artist


def find_best_match(line: str, tracks: List[TrackEntry], exact_map: Dict[str, List[int]]) -> Dict:
    raw = line.strip()
    q_title_raw, q_artist_raw = split_title_artist(raw)

    q_norm = normalize_text(raw, strip_bracket_content=CONFIG["strip_bracket_content"])
    q_title = normalize_text(q_title_raw, strip_bracket_content=CONFIG["strip_bracket_content"])
    q_artist = normalize_text(q_artist_raw, strip_bracket_content=CONFIG["strip_bracket_content"]) if q_artist_raw else ""

    # 1) 规范化后精确匹配（可能多条 → 视为歧义）
    if q_norm in exact_map:
        idxs = exact_map[q_norm]
        if len(idxs) == 1:
            t = tracks[idxs[0]]
            return {
                "status": "matched_exact",
                "score": 100.0,
                "track": t,
                "candidates": [{"score": 100.0, "filename": t.filename, "path": str(t.path)}],
                "query_norm": q_norm,
            }
        else:
            # 多个文件同名（不同扩展名/重复文件）→ 仍输出候选供人工
            cands = []
            for i in idxs[:CONFIG["topk"]]:
                t = tracks[i]
                cands.append({"score": 100.0, "filename": t.filename, "path": str(t.path)})
            return {
                "status": "ambiguous_exact",
                "score": 100.0,
                "track": None,
                "candidates": cands,
                "query_norm": q_norm,
            }

    # 2) 模糊匹配：先用 rapidfuzz 的 process 取候选（按 track.norm）
    norms = [t.norm for t in tracks]
    rough = process.extract(
        q_norm,
        norms,
        scorer=fuzz.token_set_ratio,
        limit=CONFIG["topk"],
    )

    # 3) 对候选做二次综合评分
    scored = []
    for match_norm, rough_score, idx in rough:
        t = tracks[idx]
        final_score = score_candidate(q_norm, q_title, q_artist, t)
        scored.append((final_score, t))

    scored.sort(key=lambda x: x[0], reverse=True)

    if not scored:
        return {"status": "not_found", "score": 0.0, "track": None, "candidates": [], "query_norm": q_norm}

    best_score, best_track = scored[0]
    second_score = scored[1][0] if len(scored) >= 2 else -1.0

    candidates_dump = [
        {"score": round(s, 2), "filename": t.filename, "path": str(t.path)}
        for s, t in scored
    ]

    if best_score >= CONFIG["min_score_accept"] and (best_score - second_score) >= CONFIG["min_score_margin"]:
        return {
            "status": "matched_fuzzy",
            "score": round(best_score, 2),
            "track": best_track,
            "candidates": candidates_dump,
            "query_norm": q_norm,
        }

    # 分数不够或领先不明显：歧义
    return {
        "status": "ambiguous_fuzzy",
        "score": round(best_score, 2),
        "track": None,
        "candidates": candidates_dump,
        "query_norm": q_norm,
    }


def iter_playlist_lines(txt_path: Path) -> List[str]:
    """
    读歌单：忽略空行；保留原始文本用于报告。
    编码：优先 utf-8-sig，其次 gbk（适配 Windows 常见情况）
    """
    data = None
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            data = txt_path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    if data is None:
        # 最后兜底：二进制读再忽略错误
        data = txt_path.read_bytes().decode("utf-8", errors="ignore")

    lines = []
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        lines.append(line)
    return lines


def main() -> None:
    wd = set_workdir(CONFIG["workdir"])
    library_dir = wd / CONFIG["library_dirname"]
    playlist_dir = wd / CONFIG["playlist_dirname"]
    output_dir = wd / CONFIG["output_dirname"]
    report_dir = output_dir / CONFIG["report_dirname"]

    output_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    if not library_dir.exists():
        raise SystemExit(f"曲库目录不存在: {library_dir}")
    if not playlist_dir.exists():
        raise SystemExit(f"歌单目录不存在: {playlist_dir}")

    tracks, exact_map = build_library_index(library_dir)
    if not tracks:
        raise SystemExit(f"曲库中未找到音频文件: {library_dir}")

    # 只处理歌单目录下的 .txt
    playlist_files = sorted([p for p in playlist_dir.glob("*.txt") if p.is_file()])
    if not playlist_files:
        raise SystemExit(f"歌单目录中未找到 .txt 文件: {playlist_dir}")

    summary = {
        "workdir": str(wd),
        "library_dir": str(library_dir),
        "playlist_dir": str(playlist_dir),
        "output_dir": str(output_dir),
        "tracks_count": len(tracks),
        "playlists_count": len(playlist_files),
        "playlists": [],
    }

    for pl in playlist_files:
        lines = iter_playlist_lines(pl)
        out_lines: List[str] = []
        not_found: List[Dict] = []
        ambiguous: List[Dict] = []
        matched = 0

        for line in lines:
            res = find_best_match(line, tracks, exact_map)
            if res["track"] is not None:
                matched += 1
                # 输出椒盐歌单行：手机路径前缀 + 本地命中的真实文件名
                out_lines.append(CONFIG["phone_music_dir"] + res["track"].filename)
            else:
                # 记录到报告
                item = {
                    "line": line,
                    "status": res["status"],
                    "best_score": res["score"],
                    "candidates": res.get("candidates", []),
                }
                if res["status"].startswith("not_found"):
                    not_found.append(item)
                else:
                    ambiguous.append(item)

        # 写输出歌单
        # 写输出歌单（强制 LF；并模仿例子：最后一行不额外加换行）
        out_path = output_dir / pl.name
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(out_lines))

        # 写报告
        report = {
            "playlist_file": str(pl),
            "total_lines": len(lines),
            "matched": matched,
            "unmatched": len(not_found),
            "ambiguous": len(ambiguous),
            "config": {
                "min_score_accept": CONFIG["min_score_accept"],
                "min_score_margin": CONFIG["min_score_margin"],
                "strip_bracket_content": CONFIG["strip_bracket_content"],
                "topk": CONFIG["topk"],
            },
            "not_found": not_found,
            "ambiguous": ambiguous,
        }
        report_path = report_dir / f"{pl.stem}.report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        summary["playlists"].append({
            "name": pl.name,
            "input": str(pl),
            "output": str(out_path),
            "report": str(report_path),
            "total_lines": len(lines),
            "matched": matched,
            "unmatched": len(not_found),
            "ambiguous": len(ambiguous),
        })

    (output_dir / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成。输出目录：{output_dir}")
    print(f"汇总：{output_dir / 'SUMMARY.json'}")
    print(f"明细报告目录：{report_dir}")


if __name__ == "__main__":
    main()