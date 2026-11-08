"""Cut demo/raw/* into the final video, timed to the voice-over.

Each scene lasts as long as its voice-over clip demo/vo/vo_XX.mp3 (+ air);
without the clip it uses the planned length, so a silent draft works too.
Waiting parts (generation, chat reply) are sped up to fit; the rest plays 1x,
and a scene that is still short holds its last frame.

    uv run python demo/assemble.py        # -> demo/socklock-variants-demo.mp4
"""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW, VO, BUILD = ROOT / "raw", ROOT / "vo", ROOT / "build"
OUT = ROOT / "socklock-variants-demo.mp4"
FONT = "/usr/share/fonts/truetype/noto/NotoSans-SemiBold.ttf"
LEAD, TAIL, FADE = 0.35, 0.45, 0.25

# planned seconds per scene when there is no voice-over yet (docs/demo/plan.md)
PLAN = {1: 8, 2: 22, 3: 18, 4: 10, 5: 14, 6: 8, 7: 4, 8: 20, 9: 14, 10: 22, 11: 10, 12: 20, 13: 5}


def dur(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out)


def parts_for(n: int, m: dict) -> tuple[Path, list[tuple[float, float, bool]]]:
    """Source file and (start, end, elastic) parts for scene n."""
    if n in (1, 2, 3, 4, 12, 13):
        src = RAW / f"scene{n}.mp4"
        return src, [(0.3, dur(src), False)]
    app = RAW / "app.mp4"
    sent = m["s10"] + 5.6  # message is sent ~5.6 s after the chat scene starts (see record.py)
    return app, {
        5: [(m["s05"] + 0.3, m["s06"], False)],
        6: [(m["s06"], m["s07"], False)],
        7: [(m["s07"], m["s07_end"], True)],
        8: [(m["s07_end"], m["s09"], False)],
        9: [(m["s09"], m["s10"], False)],
        10: [(m["s10"], sent, False), (sent, m["s10_reply"], True), (m["s10_reply"], m["s11"], False)],
        11: [(m["s11"], m["end"], False)],
    }[n]


def render(n: int, m: dict) -> Path:
    vo = VO / f"vo_{n:02d}.mp3"
    target = (dur(vo) + LEAD + TAIL) if vo.exists() else PLAN[n]
    src, parts = parts_for(n, m)

    rigid = sum(e - s for s, e, el in parts if not el)
    elastic = sum(e - s for s, e, el in parts if el)
    speed_el = min(12.0, max(1.0, elastic / max(target - rigid, 1.0))) if elastic else 1.0
    total = rigid + elastic / speed_el
    speed_all = total / target if 1.0 < total / target <= 1.35 else 1.0
    total /= speed_all

    chains, labels = [], []
    for i, (s, e, el) in enumerate(parts):
        sp = (speed_el if el else 1.0) * speed_all
        chains.append(f"[0:v]trim={s:.3f}:{e:.3f},setpts=(PTS-STARTPTS)/{sp:.4f}[p{i}]")
        labels.append(f"[p{i}]")
    vf = ";".join(chains) + f";{''.join(labels)}concat=n={len(parts)}:v=1:a=0,fps=30"
    if total < target:
        vf += f",tpad=stop_mode=clone:stop_duration={target - total:.3f}"
    vf += f",trim=0:{target:.3f},setpts=PTS-STARTPTS"
    if n == 7:
        vf += (f",drawtext=fontfile={FONT}:text='Генерація 20 варіантів\: {elastic:.0f} с, тут прискорено ×{speed_el:.0f}'"
               ":fontsize=34:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=22:x=(w-tw)/2:y=60")
    vf += f",fade=t=in:st=0:d={FADE},fade=t=out:st={target - FADE:.3f}:d={FADE}[v]"

    cmd = ["ffmpeg", "-loglevel", "error", "-y", "-i", str(src)]
    if vo.exists():
        cmd += ["-i", str(vo)]
        af = f"[1:a]adelay={int(LEAD * 1000)}:all=1,apad,atrim=0:{target:.3f},aresample=48000[a]"
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        af = f"[1:a]atrim=0:{target:.3f}[a]"
    out = BUILD / f"seg{n:02d}.mp4"
    cmd += ["-filter_complex", vf + ";" + af, "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "192k", "-ac", "2", str(out)]
    subprocess.run(cmd, check=True)
    print(f"scene {n:2d}: {target:5.1f}s{'  (vo)' if vo.exists() else ''}"
          + (f"  wait x{speed_el:.1f}" if elastic else "") + (f"  all x{speed_all:.2f}" if speed_all > 1 else ""))
    return out


def main():
    BUILD.mkdir(exist_ok=True)
    marks = json.loads((RAW / "marks.json").read_text())
    segs = [render(n, marks) for n in range(1, 14)]
    lst = BUILD / "list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in segs))
    joined = BUILD / "joined.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(joined)], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(joined), "-c:v", "copy",
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(OUT)], check=True)
    print(f"{OUT.name}: {dur(OUT):.1f}s")


if __name__ == "__main__":
    main()
