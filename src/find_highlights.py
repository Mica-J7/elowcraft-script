"""Detect chat activity spikes in a Twitch VOD to surface candidate clip moments."""
import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from statistics import median

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TOOL_PATH = ROOT / "tools" / "TwitchDownloaderCLI" / "TwitchDownloaderCLI.exe"

BIN_SIZE_S = 15
BASELINE_WINDOW_BINS = 16  # 4 minutes
SPIKE_RATIO = 4
MIN_SPIKE_COUNT = 20
MERGE_GAP_S = 30
LEAD_OFFSET_S = 10
SAMPLE_MESSAGES_PER_MOMENT = 4
CLIP_PRE_ROLL_S = 15
CLIP_POST_ROLL_S = 10


def extract_vod_id(vod: str) -> str:
    if vod.isdigit():
        return vod
    return vod.rstrip("/").split("/")[-1].split("?")[0]


def build_vod_url(vod: str) -> str:
    return f"https://www.twitch.tv/videos/{extract_vod_id(vod)}"


def download_chat(vod: str, output_path: Path, tool_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(tool_path), "chatdownload",
        "-u", vod,
        "-o", str(output_path),
        "--collision", "Overwrite",
    ]
    print(f"Downloading chat: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def load_comments(path: Path) -> list:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["comments"]


def build_bins(comments: list, bin_size: int) -> dict:
    bins = Counter()
    for c in comments:
        offset = c["content_offset_seconds"]
        bins[offset // bin_size] += 1
    return bins


def detect_spike_bins(bins: dict, baseline_window: int, ratio_threshold: float, min_count: int) -> set:
    if not bins:
        return set()
    max_bin = max(bins)
    spikes = set()
    for i in range(max_bin + 1):
        count = bins.get(i, 0)
        if count < min_count:
            continue
        window = [bins.get(j, 0) for j in range(max(0, i - baseline_window), i)]
        baseline = median(window) if window else 0
        if count >= ratio_threshold * max(baseline, 1):
            spikes.add(i)
    return spikes


def merge_into_moments(spike_bins: set, bins: dict, bin_size: int, merge_gap_s: int) -> list:
    if not spike_bins:
        return []
    sorted_bins = sorted(spike_bins)
    merge_gap_bins = max(1, merge_gap_s // bin_size)

    moments = []
    current_group = [sorted_bins[0]]
    for b in sorted_bins[1:]:
        if b - current_group[-1] <= merge_gap_bins:
            current_group.append(b)
        else:
            moments.append(current_group)
            current_group = [b]
    moments.append(current_group)

    result = []
    for group in moments:
        start_s = group[0] * bin_size
        end_s = (group[-1] + 1) * bin_size
        peak_bin = max(group, key=lambda b: bins.get(b, 0))
        peak_s = peak_bin * bin_size
        peak_count = bins.get(peak_bin, 0)
        result.append({
            "start_s": start_s,
            "end_s": end_s,
            "peak_s": peak_s,
            "peak_count": peak_count,
        })
    return result


def enrich_moment(moment: dict, comments: list) -> dict:
    window_comments = [
        c for c in comments
        if moment["start_s"] <= c["content_offset_seconds"] < moment["end_s"]
    ]
    emote_counter = Counter()
    for c in window_comments:
        for emoticon in c["message"].get("emoticons", []):
            emote_counter[emoticon.get("_id", "?")] += 1
        for frag in c["message"].get("fragments", []):
            if frag.get("emoticon"):
                emote_counter[frag["text"]] += 1

    sample_messages = [c["message"]["body"] for c in window_comments[:SAMPLE_MESSAGES_PER_MOMENT]]

    moment["message_count"] = len(window_comments)
    moment["top_emotes"] = emote_counter.most_common(3)
    moment["sample_messages"] = sample_messages
    return moment


def format_timecode(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_twitch_link(vod_id: str, seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"https://www.twitch.tv/videos/{vod_id}?t={h:02d}h{m:02d}m{s:02d}s"


def build_report(moments: list, vod_id: str, lead_offset: int) -> str:
    lines = [f"# Moments candidats - VOD {vod_id}", f"# {len(moments)} moment(s) detecte(s)\n"]
    for i, m in enumerate(moments, 1):
        suggested_s = max(0, m["peak_s"] - lead_offset)
        lines.append(f"## Moment {i} - {format_timecode(suggested_s)}")
        lines.append(f"Lien: {format_twitch_link(vod_id, suggested_s)}")
        lines.append(f"Pic de chat a {format_timecode(m['peak_s'])} ({m['peak_count']} msg sur 15s, {m['message_count']} msg sur la fenetre)")
        if m["top_emotes"]:
            emotes_str = ", ".join(f"{name} x{count}" for name, count in m["top_emotes"])
            lines.append(f"Emotes: {emotes_str}")
        if m["sample_messages"]:
            lines.append("Exemples de messages:")
            for msg in m["sample_messages"]:
                lines.append(f"  - {msg}")
        lines.append("")
    return "\n".join(lines)


def clip_window(moment: dict, lead_offset: int, pre_roll: int, post_roll: int) -> tuple:
    start_s = max(0, moment["peak_s"] - lead_offset - pre_roll)
    end_s = moment["end_s"] + post_roll
    return start_s, end_s


def download_clip(vod: str, start_s: int, end_s: int, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "best",
        "--download-sections", f"*{start_s}-{end_s}",
        "--force-keyframes-at-cuts",
        "--no-part",
        "-o", str(output_path),
        vod,
    ]
    subprocess.run(cmd, check=True)


def download_clips_for_moments(vod: str, moments: list, output_dir: Path, lead_offset: int,
                                pre_roll: int = CLIP_PRE_ROLL_S, post_roll: int = CLIP_POST_ROLL_S,
                                progress_callback=None) -> list:
    vod_url = build_vod_url(vod)
    clip_paths = []
    for i, m in enumerate(moments, 1):
        start_s, end_s = clip_window(m, lead_offset, pre_roll, post_roll)
        filename = f"{i:02d}_{format_timecode(start_s).replace(':', '-')}.mp4"
        output_path = output_dir / filename
        download_clip(vod_url, start_s, end_s, output_path)
        clip_paths.append(output_path)
        if progress_callback:
            progress_callback(i, len(moments), output_path)
    return clip_paths


def format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("o", "Ko", "Mo", "Go"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "o" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} To"


def list_vod_entries() -> list:
    data_dir = ROOT / "data"
    clips_dir = data_dir / "clips"

    vod_ids = set()
    if data_dir.exists():
        vod_ids.update(p.name[: -len("_chat.json")] for p in data_dir.glob("*_chat.json"))
    if clips_dir.exists():
        vod_ids.update(p.name for p in clips_dir.iterdir() if p.is_dir())

    entries = []
    for vod_id in sorted(vod_ids):
        chat_path = data_dir / f"{vod_id}_chat.json"
        report_paths = list(data_dir.glob(f"{vod_id}_highlights*.txt"))
        clip_dir = clips_dir / vod_id
        clip_files = list(clip_dir.glob("*.mp4")) if clip_dir.exists() else []

        chat_size = chat_path.stat().st_size if chat_path.exists() else 0
        report_size = sum(p.stat().st_size for p in report_paths)
        clips_size = sum(p.stat().st_size for p in clip_files)

        entries.append({
            "vod_id": vod_id,
            "has_chat": chat_path.exists(),
            "chat_size": chat_size + report_size,
            "clip_count": len(clip_files),
            "clips_size": clips_size,
            "total_size": chat_size + report_size + clips_size,
        })
    return entries


def delete_vod_chat(vod_id: str) -> None:
    data_dir = ROOT / "data"
    (data_dir / f"{vod_id}_chat.json").unlink(missing_ok=True)
    for report in data_dir.glob(f"{vod_id}_highlights*.txt"):
        report.unlink(missing_ok=True)


def delete_vod_clips(vod_id: str) -> None:
    clip_dir = ROOT / "data" / "clips" / vod_id
    if clip_dir.exists():
        shutil.rmtree(clip_dir)


def delete_vod_all(vod_id: str) -> None:
    delete_vod_chat(vod_id)
    delete_vod_clips(vod_id)


def main():
    parser = argparse.ArgumentParser(description="Detect chat activity spikes in a Twitch VOD")
    parser.add_argument("vod", help="VOD URL or ID")
    parser.add_argument("--chat-json", type=Path, default=None, help="Reuse an existing chat JSON instead of downloading")
    parser.add_argument("--output", type=Path, default=None, help="Output report path (default: <vod_id>_highlights.txt)")
    parser.add_argument("--tool-path", type=Path, default=DEFAULT_TOOL_PATH)
    parser.add_argument("--bin-size", type=int, default=BIN_SIZE_S)
    parser.add_argument("--ratio-threshold", type=float, default=SPIKE_RATIO)
    parser.add_argument("--min-count", type=int, default=MIN_SPIKE_COUNT)
    parser.add_argument("--merge-gap", type=int, default=MERGE_GAP_S)
    parser.add_argument("--lead-offset", type=int, default=LEAD_OFFSET_S)
    parser.add_argument("--extract-clips", action="store_true", help="Download a video clip for each detected moment")
    parser.add_argument("--clip-dir", type=Path, default=None, help="Output directory for clips (default: data/clips/<vod_id>)")
    parser.add_argument("--pre-roll", type=int, default=CLIP_PRE_ROLL_S)
    parser.add_argument("--post-roll", type=int, default=CLIP_POST_ROLL_S)
    args = parser.parse_args()

    vod_id = extract_vod_id(args.vod)
    chat_path = args.chat_json or ROOT / "data" / f"{vod_id}_chat.json"

    if not args.chat_json:
        download_chat(args.vod, chat_path, args.tool_path)
    elif not chat_path.exists():
        print(f"Chat file not found: {chat_path}", file=sys.stderr)
        sys.exit(1)

    comments = load_comments(chat_path)
    print(f"Loaded {len(comments)} chat messages")

    bins = build_bins(comments, args.bin_size)
    spike_bins = detect_spike_bins(bins, BASELINE_WINDOW_BINS, args.ratio_threshold, args.min_count)
    moments = merge_into_moments(spike_bins, bins, args.bin_size, args.merge_gap)
    moments = [enrich_moment(m, comments) for m in moments]

    report = build_report(moments, vod_id, args.lead_offset)

    output_path = args.output or ROOT / "data" / f"{vod_id}_highlights.txt"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")

    print(report)
    print(f"\nReport saved to: {output_path}")

    if args.extract_clips:
        clip_dir = args.clip_dir or ROOT / "data" / "clips" / vod_id
        clip_dir.mkdir(parents=True, exist_ok=True)
        print(f"\nDownloading {len(moments)} clip(s) to {clip_dir}...")
        for i, path in enumerate(
            download_clips_for_moments(args.vod, moments, clip_dir, args.lead_offset, args.pre_roll, args.post_roll), 1
        ):
            print(f"  [{i}/{len(moments)}] {path}")


if __name__ == "__main__":
    main()
