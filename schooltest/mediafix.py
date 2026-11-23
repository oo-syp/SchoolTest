# -*- coding: utf-8 -*-
"""Облегчение загружаемых медиафайлов без внешних библиотек (1.5).
JPEG — удаление EXIF/комментариев (APPn, COM), PNG — служебных текстовых блоков,
MP3 — тегов ID3/APE, WAV — метаданных и (для PCM 16 бит) перевод в моно и 22 кГц.
Если рядом есть ffmpeg, MP3/OGG/M4A дополнительно пережимаются до 96 кбит/с."""
import array
import io
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import wave

WAV_RATE = 22050


def _jpeg_orientation(seg):
    """Ориентация из EXIF-сегмента (1 — обычная)."""
    try:
        if seg[:6] != b"Exif\0\0":
            return 1
        t = seg[6:]
        end = "<" if t[:2] == b"II" else ">"
        off = struct.unpack(end + "I", t[4:8])[0]
        n = struct.unpack(end + "H", t[off:off + 2])[0]
        for i in range(n):
            e = t[off + 2 + 12 * i: off + 14 + 12 * i]
            if struct.unpack(end + "H", e[:2])[0] == 0x0112:
                return struct.unpack(end + "H", e[8:10])[0]
    except (struct.error, IndexError):
        pass
    return 1


def strip_jpeg(data):
    if data[:2] != b"\xff\xd8":
        return data
    out, i, n = [b"\xff\xd8"], 2, len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            return data                   # неожиданная структура — не рискуем
        m = data[i + 1]
        if m == 0xDA:                     # начало данных изображения: остальное копируем как есть
            out.append(data[i:])
            return b"".join(out)
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            out.append(data[i:i + 2]); i += 2; continue
        ln = struct.unpack(">H", data[i + 2:i + 4])[0]
        seg = data[i:i + 2 + ln]
        body = data[i + 4:i + 2 + ln]
        keep = True
        if m == 0xFE or (0xE1 <= m <= 0xEF and m != 0xEE):
            keep = False
            if m == 0xE1 and _jpeg_orientation(body) != 1:
                keep = True               # поворот хранится в EXIF — сохраняем, иначе фото «упадёт набок»
        if keep:
            out.append(seg)
        i += 2 + ln
    return data


_PNG_DROP = (b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"tIME")


def strip_png(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return data
    out, i = [data[:8]], 8
    while i + 8 <= len(data):
        ln = struct.unpack(">I", data[i:i + 4])[0]
        typ = data[i + 4:i + 8]
        chunk = data[i:i + 12 + ln]
        if typ not in _PNG_DROP:
            out.append(chunk)
        i += 12 + ln
        if typ == b"IEND":
            break
    return b"".join(out)


def strip_mp3(data):
    if data[:3] == b"ID3" and len(data) > 10:
        size = ((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14) | ((data[8] & 0x7F) << 7) | (data[9] & 0x7F)
        data = data[10 + size:]
    if len(data) > 128 and data[-128:-125] == b"TAG":
        data = data[:-128]
    return data


def shrink_wav(data):
    try:
        src = wave.open(io.BytesIO(data), "rb")
        ch, sw, rate, nf = src.getnchannels(), src.getsampwidth(), src.getframerate(), src.getnframes()
        if src.getcomptype() != "NONE" or sw != 2 or ch not in (1, 2):
            return data
        raw = src.readframes(nf)
        src.close()
    except (wave.Error, EOFError, struct.error):
        return data
    s = array.array("h")
    s.frombytes(raw)
    if sys.byteorder == "big":
        s.byteswap()
    if ch == 2:
        s = array.array("h", [(s[i] + s[i + 1]) // 2 for i in range(0, len(s) - 1, 2)])
    k = max(1, int(rate // WAV_RATE)) if rate > WAV_RATE else 1
    if k > 1:
        s = array.array("h", [sum(s[i:i + k]) // k for i in range(0, len(s) - k + 1, k)])
    new_rate = rate // k
    if sys.byteorder == "big":
        s.byteswap()
    buf = io.BytesIO()
    w = wave.open(buf, "wb")
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(new_rate)
    w.writeframes(s.tobytes())
    w.close()
    out = buf.getvalue()
    return out if len(out) < len(data) else data


def _ffmpeg(data, ext):
    exe = shutil.which("ffmpeg")
    if not exe:
        return data
    d = tempfile.mkdtemp()
    try:
        a, b = os.path.join(d, "in." + ext), os.path.join(d, "out." + ext)
        with open(a, "wb") as f:
            f.write(data)
        r = subprocess.run([exe, "-y", "-loglevel", "error", "-i", a, "-map_metadata", "-1", "-vn", "-b:a", "96k", "-ac", "1", b],
                           timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode == 0 and os.path.exists(b):
            out = open(b, "rb").read()
            if 0 < len(out) < len(data):
                return out
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return data


def optimize(name, kind, data):
    """Возвращает (новые_данные, описание действий). Ошибки разбора оставляют файл без изменений."""
    ext = (name.rsplit(".", 1)[-1] if "." in name else "").lower()
    try:
        if kind == "image":
            if ext in ("jpg", "jpeg"):
                return strip_jpeg(data), "метаданные JPEG удалены"
            if ext == "png":
                return strip_png(data), "служебные блоки PNG удалены"
        elif kind == "audio":
            if ext == "mp3":
                d = _ffmpeg(strip_mp3(data), "mp3")
                return d, "теги MP3 удалены" + (", битрейт снижен" if d is not data and len(d) < len(data) else "")
            if ext == "wav":
                return shrink_wav(data), "WAV: моно, 22 кГц, без метаданных"
            if ext in ("ogg", "m4a"):
                return _ffmpeg(data, ext), "перекодировано, если доступен ffmpeg"
    except Exception:       # noqa: BLE001 — сжатие необязательно, оригинал важнее
        return data, ""
    return data, ""
