#!/usr/bin/env python3
"""Hazır sahne görsellerinden Instagram Reels videosu (MP4) üretir.

Her sahne `hold` sn (sonuncusu `last_hold` sn) ekranda kalır; sahneler `fade` sn'lik xfade
geçişiyle bağlanır ve her sahneye çok hafif bir Ken Burns hareketi (en çok %6) uygulanır.
Hareket, zoompan yerine `perspective` filtresiyle alt piksel hassasiyetinde üretilir; böylece
zoompan'in tamsayı kırpmadan gelen titremesi oluşmaz.

Çıktı: 1080x1920, H.264 High, yuv420p (BT.709), 30 fps, kapalı GOP, faststart, sessiz AAC
stereo 48 kHz. Süre = (N-1)*(hold-fade) + last_hold, en az 4 sn.

Kullanım:
    python3 scripts/reel.py cikti.mp4 sahne1.jpg sahne2.jpg ...
    python3 scripts/reel.py cikti.mp4 sahne*.jpg --hold 2.3 --fade 0.45 --last-hold 3.2 --fps 30

ffmpeg sırayla FFMPEG_BIN ortam değişkeninde, PATH'te ve imageio-ffmpeg paketinde aranır.
"""
from __future__ import annotations

import argparse
import functools
import math
import os
import re
import shutil
import subprocess
import sys
import warnings
from pathlib import Path

W, H = 1080, 1920  # Reels tuvali (9:16)
ZOOM = 1.06  # Ken Burns üst sınırı: hiçbir kenardan ~54 px'ten fazlası kırpılmaz
TRANSITIONS = ("fade", "smoothleft", "smoothup", "circleopen")  # sırayla döner
MIN_SECONDS = 4.0  # Instagram alt sınırı 3 sn; kısa girdide son sahne uzatılır
AUDIO_RATE = 48000
PRESET, CRF, MAXRATE, BUFSIZE = "medium", 21, "6M", "12M"

Box = tuple[float, float, float, float]  # kaynak pikselinde sol, üst, sağ, alt


def ffmpeg_bin() -> str:
    """ffmpeg yolunu döndürür: FFMPEG_BIN, PATH'teki ffmpeg, sonra imageio-ffmpeg."""
    env = os.environ.get("FFMPEG_BIN", "").strip()
    if env:
        found = shutil.which(env)
        if found:
            return found
        warnings.warn(f"FFMPEG_BIN çalıştırılabilir değil, yok sayılıyor: {env}", stacklevel=2)
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
    except ImportError:
        pass
    else:
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # paket kurulu ama ikili dosyası yok: aşağıdaki hataya düş
            pass
    raise RuntimeError(
        "ffmpeg bulunamadı. FFMPEG_BIN ortam değişkeniyle yolunu ver, ffmpeg'i PATH'e ekle "
        "ya da `pip install imageio-ffmpeg` çalıştır."
    )


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Komutu çıktısını yakalayarak çalıştırır; başlatılamazsa RuntimeError verir."""
    try:
        return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    except OSError as e:
        raise RuntimeError(f"ffmpeg çalıştırılamadı ({cmd[0]}): {e}") from e


@functools.lru_cache(maxsize=None)
def _xfade_names(ffmpeg: str) -> frozenset[str]:
    """Bu ffmpeg'in tanıdığı xfade geçiş adları; xfade filtresi yoksa boş küme."""
    text = _run([ffmpeg, "-hide_banner", "-h", "filter=xfade"]).stdout
    if "Filter xfade" not in text:
        return frozenset()
    # Sabit satırları: "  fade   0   ..FV....... açıklama"; eski sürümler sayıyı yazmaz.
    return frozenset(re.findall(r"^\s+(\w+)\s+(?:-?\d+\s+)?[.A-Z]{5,}(?:\s|$)", text, re.M)) | {"fade"}


def _round(x: float) -> int:
    """Yarımları yukarı yuvarlar (kayan nokta gürültüsüne karşı küçük payla)."""
    return int(math.floor(x + 0.5 + 1e-9))


def _schedule(count: int, hold: float, fade: float, last_hold: float, fps: int) -> tuple[list[int], int, int]:
    """Sahnelerin başlangıç kareleri, geçiş uzunluğu (kare) ve toplam kare sayısı."""
    fade = min(fade, hold / 2, last_hold / 2)  # giriş ve çıkış geçişi üst üste binmesin
    xf = max(1, _round(fade * fps))  # 1 karelik xfade düz kesmeye denktir
    step = (hold - fade) * fps
    starts = [_round(i * step) for i in range(count)]
    total = _round((count - 1) * step + last_hold * fps)
    floor = math.ceil(MIN_SECONDS * fps - 1e-9)
    return starts, xf, max(total, floor, starts[-1] + xf + 1)


def _windows(index: int) -> tuple[Box, Box]:
    """Sahnenin ilk ve son karesinde ekrana gelen kaynak penceresi; hareket sahneden sahneye döner."""
    full: Box = (0.0, 0.0, float(W), float(H))
    mx, my = W * (1 - 1 / ZOOM) / 2, H * (1 - 1 / ZOOM) / 2
    tight: Box = (mx, my, W - mx, H - my)
    kind = index % 3
    if kind == 0:  # yakınlaş: %100 -> %106
        return full, tight
    if kind == 1:  # uzaklaş: %106 -> %100
        return tight, full
    # Kaydırma: sabit ~%3 zoom; pencere hiçbir kenarda %6 zoom'un kırptığından fazlasını kırpmaz.
    direction = (index // 3) % 4  # sağ, yukarı, sol, aşağı
    if direction % 2 == 0:
        a: Box = (0.0, my / 2, W - mx, H - my / 2)
        b: Box = (mx, my / 2, float(W), H - my / 2)
    else:
        a = (mx / 2, my, W - mx / 2, float(H))
        b = (mx / 2, 0.0, W - mx / 2, H - my)
    return (a, b) if direction < 2 else (b, a)


def _scene_filter(index: int, length: int) -> str:
    """Tek sahnenin zinciri: tuvale oturt, `length` kareye çoğalt, titreşimsiz Ken Burns uygula."""
    (l0, t0, r0, b0), (l1, t1, r1, b1) = _windows(index)
    den = max(1, length - 1)

    def lerp(a: float, b: float) -> str:
        # `on` 1'den başlayan çıktı kare sayacı; ifade virgül içermediği için kaçış gerekmez.
        return f"{a:.4f}" if abs(b - a) < 1e-6 else f"{a:.4f}{b - a:+.4f}*(on-1)/{den}"

    left, top, right, bottom = lerp(l0, l1), lerp(t0, t1), lerp(r0, r1), lerp(b0, b1)
    return (
        # Görsel bir kez RGB'ye (gbrp) çevrilir: xfade 4:4:4 ister, renk de tek yerde dönüşür.
        f"scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos+accurate_rnd+full_chroma_int,"
        f"format=gbrp,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
        f"loop=loop={length}:size=1:start=0,trim=end_frame={length},"
        # Pencerenin dört köşesi kare kare kesirli pikselle verilir; kübik örnekleme titretmez.
        f"perspective=x0={left}:y0={top}:x1={right}:y1={top}:x2={left}:y2={bottom}:x3={right}:y3={bottom}"
        ":interpolation=cubic:sense=source:eval=frame"
    )


def _filtergraph(starts: list[int], xf: int, total: int, fps: int, names: frozenset[str]) -> str:
    """Bütün videoyu ve sessiz ses izini üreten tek filter_complex metni."""
    count = len(starts)
    # Sahne k, kendinden öncekinin son `xf` karesiyle üst üste biner.
    lengths = [starts[i + 1] + xf - starts[i] for i in range(count - 1)] + [total - starts[-1]]
    parts = [f"[{i}:v]{_scene_filter(i, n)}[s{i}]" for i, n in enumerate(lengths)]
    last = "s0"
    for k in range(1, count):
        name = TRANSITIONS[(k - 1) % len(TRANSITIONS)]
        if name not in names:
            name = "fade"
        parts.append(f"[{last}][s{k}]xfade=transition={name}:duration={xf / fps:.6f}"
                     f":offset={starts[k] / fps:.6f}[x{k}]")
        last = f"x{k}"
    # ffmpeg 7+ renk etiketlerini kodlayıcı seçeneklerinden değil kareden alır: burada da yaz.
    parts.append(f"[{last}]scale=out_color_matrix=bt709:out_range=tv"
                 ":flags=bicubic+accurate_rnd+full_chroma_inp+full_chroma_int,format=yuv420p,"
                 "setparams=color_primaries=bt709:color_trc=bt709[v]")
    samples = -(-total * AUDIO_RATE // fps)  # videodan kısa kalmasın diye yukarı yuvarla
    parts.append(f"anullsrc=channel_layout=stereo:sample_rate={AUDIO_RATE},atrim=end_sample={samples}[a]")
    return ";".join(parts)


def make_reel(frames: list[Path], out: Path, *, hold: float = 2.3, fade: float = 0.45,
              last_hold: float = 3.2, fps: int = 30) -> Path:
    """Sahne görsellerinden geçişli, hafif hareketli bir Reels MP4'ü üretir; `out` yolunu döndürür."""
    paths = [Path(f) for f in frames]
    if not paths:
        raise ValueError("En az bir sahne görseli gerekli.")
    for p in paths:
        if not p.is_file():
            raise FileNotFoundError(f"Sahne görseli bulunamadı: {p}")
    if not 1 <= fps <= 60:
        raise ValueError(f"fps 1-60 arasında olmalı: {fps}")
    if fade < 0 or last_hold <= 0 or hold * fps < 2:
        raise ValueError(f"Geçersiz süre: hold={hold}, fade={fade}, last_hold={last_hold}")

    ffmpeg = ffmpeg_bin()
    names = _xfade_names(ffmpeg) if len(paths) > 1 else frozenset()
    if len(paths) > 1 and not names:
        raise RuntimeError("Bu ffmpeg'de xfade filtresi yok; 4.3 veya daha yeni bir sürüm gerekli.")
    starts, xf, total = _schedule(len(paths), hold, fade, last_hold, fps)

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + ".part")  # yarım dosya `out` yerine geçmesin
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
    for p in paths:
        cmd += ["-framerate", str(fps), "-i", str(p.resolve())]
    cmd += [
        "-filter_complex", _filtergraph(starts, xf, total, fps, names),
        "-map", "[v]", "-map", "[a]", "-map_metadata", "-1",
        "-c:v", "libx264", "-preset", PRESET, "-profile:v", "high",
        "-level:v", "4.0" if fps <= 30 else "4.2", "-pix_fmt", "yuv420p",
        "-crf", str(CRF), "-maxrate", MAXRATE, "-bufsize", BUFSIZE,
        "-g", str(2 * fps), "-flags:v", "+cgop",
        "-colorspace:v", "bt709", "-color_primaries:v", "bt709", "-color_trc:v", "bt709",
        "-color_range:v", "tv",
        "-c:a", "aac", "-b:a", "128k", "-ar", str(AUDIO_RATE), "-ac", "2",
        "-shortest", "-movflags", "+faststart", "-f", "mp4", str(part.resolve()),
    ]
    try:
        res = _run(cmd)
        if res.returncode != 0 or not part.is_file() or part.stat().st_size == 0:
            tail = "\n".join(res.stderr.strip().splitlines()[-20:])
            raise RuntimeError(f"ffmpeg başarısız (çıkış kodu {res.returncode}):\n{tail}")
        os.replace(part, out)
    finally:
        part.unlink(missing_ok=True)
    return out


def main(argv: list[str] | None = None) -> None:
    """Komut satırı: çıktı yolu ve sırayla sahne görselleri."""
    ap = argparse.ArgumentParser(description="Sahne görsellerinden Instagram Reels videosu üretir.")
    ap.add_argument("out", type=Path, help="çıktı .mp4 yolu")
    ap.add_argument("frames", type=Path, nargs="+", help="1080x1920 sahne görselleri (sırayla)")
    ap.add_argument("--hold", type=float, help="her sahnenin süresi, sn (varsayılan 2.3)")
    ap.add_argument("--fade", type=float, help="geçiş süresi, sn (varsayılan 0.45)")
    ap.add_argument("--last-hold", type=float, help="son sahnenin süresi, sn (varsayılan 3.2)")
    ap.add_argument("--fps", type=int, help="kare hızı (varsayılan 30)")
    args = ap.parse_args(argv)
    opts = {k: v for k, v in vars(args).items() if k not in ("out", "frames") and v is not None}
    try:
        print(make_reel(args.frames, args.out, **opts))
    except (OSError, RuntimeError, ValueError) as e:
        sys.exit(f"Hata: {e}")


if __name__ == "__main__":
    main()
