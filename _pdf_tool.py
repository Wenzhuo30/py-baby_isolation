"""Generic dependency-free PDF text extractor (same engine as _pdf_extract3.py).

Usage: python _pdf_tool.py <file.pdf> [out_prefix]
Writes <out_prefix>_pos.txt and <out_prefix>_plain.txt (default prefix = file stem).
"""
import re
import sys
import zlib

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj\b")
STREAM_RE = re.compile(rb"stream\r\n|stream\n|stream\r")


def load_objects(data):
    objs = {}
    marks = list(OBJ_RE.finditer(data))
    for i, m in enumerate(marks):
        num, start = int(m.group(1)), m.end()
        head = data[start:start + 400]
        sm = STREAM_RE.search(head)
        if sm and b"<<" in head[:sm.start()]:
            sstart = start + sm.end()
            eidx = data.find(b"endstream", sstart)
            if eidx == -1:
                eidx = sstart
            objs[num] = (data[start:sstart] + b"<STREAM>", data[sstart:eidx])
        else:
            end = marks[i + 1].start() if i + 1 < len(marks) else len(data)
            seg = data[start:end]
            e = seg.find(b"endobj")
            objs[num] = (seg[:e] if e != -1 else seg, None)
    return objs


def inflate(raw):
    if raw is None:
        return None
    try:
        return zlib.decompress(raw.rstrip(b"\r\n"))
    except Exception:
        return None


def parse_tounicode(cmap_bytes):
    text = cmap_bytes.decode("latin-1", "replace")
    mapping = {}
    for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        for lo, hi, dst in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            base = int(dst, 16)
            for off in range(int(hi, 16) - int(lo, 16) + 1):
                mapping[int(lo, 16) + off] = chr(base + off)
    for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            mapping[int(src, 16)] = bytes.fromhex(dst).decode("utf-16-be", "replace")
    return mapping


def fonts_by_basename(objs):
    by_name = {}
    for num, (body, _) in objs.items():
        if b"/Type /Font" not in body and b"/Type/Font" not in body:
            continue
        bm = re.search(rb"/BaseFont\s*/([#\w+.-]+)", body)
        if not bm:
            continue
        name = re.sub(r"^[A-Z]{6}\+", "", bm.group(1).decode("latin-1"))
        tu = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", body)
        mapping = {}
        if tu:
            cmap = inflate(objs.get(int(tu.group(1)), (b"", None))[1])
            if cmap:
                mapping = parse_tounicode(cmap)
        by_name.setdefault(name, mapping)
    return by_name


def unescape(raw):
    out = bytearray()
    i = 0
    simple = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12,
              0x28: 40, 0x29: 41, 0x5C: 92}
    while i < len(raw):
        c = raw[i]
        if c == 0x5C and i + 1 < len(raw):
            n = raw[i + 1]
            if n in simple:
                out.append(simple[n]); i += 2; continue
            if 0x30 <= n <= 0x37:
                digits = ""
                j = i + 1
                while j < len(raw) and len(digits) < 3 and 0x30 <= raw[j] <= 0x37:
                    digits += chr(raw[j]); j += 1
                out.append(int(digits, 8) & 0xFF); i = j; continue
            if n in (10, 13):
                i += 2; continue
            out.append(n); i += 2; continue
        out.append(c); i += 1
    return bytes(out)


TOKEN_RE = re.compile(rb"""
    (?P<str>\((?:\\.|[^\\()])*\))
  | (?P<hex><[0-9A-Fa-f\s]*>)
  | (?P<arr>[\[\]])
  | (?P<name>/[^\s/\[\]<>()]+)
  | (?P<num>[+-]?(?:\d+\.?\d*|\.\d+))
  | (?P<op>[A-Za-z'*"][A-Za-z0-9'*"]*)
""", re.X | re.S)


def decode_str(data, mapping, two_byte):
    if not mapping:
        return data.decode("latin-1", "replace")
    if two_byte:
        return "".join(mapping.get(int.from_bytes(data[i:i + 2], "big"), "")
                       for i in range(0, len(data) - 1, 2))
    return "".join(mapping.get(b, "") for b in data)


def extract(content, fonts):
    items = []
    i, n = 0, len(content)
    stack, names = [], []
    font, two_byte = None, False
    x = y = 0.0
    leading = 0.0
    pending = []

    def emit():
        if pending:
            text = "".join(pending).rstrip()
            if text.strip():
                items.append((round(y, 1), round(x, 1), text))
            pending.clear()

    while i < n:
        m = TOKEN_RE.match(content, i)
        if not m:
            i += 1
            continue
        i = m.end()
        kind, raw = m.lastgroup, m.group(0)
        if kind == "num":
            stack.append(float(raw.decode("latin-1"))); continue
        if kind == "name":
            names.append(raw.decode("latin-1")[1:]); continue
        if kind == "arr":
            if raw == b"]":
                emit()
            continue
        if kind in ("str", "hex"):
            if kind == "str":
                data = unescape(raw[1:-1])
            else:
                hx = re.sub(rb"\s", b"", raw[1:-1])
                if len(hx) % 2:
                    hx += b"0"
                data = bytes.fromhex(hx.decode())
            pending.append(decode_str(data, fonts.get(font, {}), two_byte))
            continue
        op = raw.decode("latin-1")
        if op == "Tf":
            if names:
                font = names[-1]
                mapping = fonts.get(font, {})
                two_byte = bool(mapping) and max(mapping, default=0) > 255
            stack, names = [], []
            continue
        if op == "Tm":
            if len(stack) >= 6:
                x, y = stack[-2], stack[-1]
            emit()
        elif op in ("Td", "TD"):
            if len(stack) >= 2:
                if op == "TD":
                    leading = -stack[-1]
                x += stack[-2]; y += stack[-1]
            emit()
        elif op == "TL":
            if stack:
                leading = stack[-1]
        elif op == "T*":
            y -= leading; emit()
        elif op in ("Tj", "'", '"', "TJ"):
            emit()
        elif op == "ET":
            emit(); x = y = 0.0
        elif op == "BT":
            x = y = 0.0
        stack, names = [], []
    emit()
    return items


def convert(path, prefix):
    data = open(path, "rb").read()
    objs = load_objects(data)
    by_name = fonts_by_basename(objs)
    pages = sorted(num for num, (body, _) in objs.items()
                   if re.search(rb"/Type\s*/Page[^s]", body))

    fonts = {}
    for other, (obody, _) in objs.items():
        fm = re.search(rb"/Font\s*<<(.*?)>>", obody, re.S)
        if not fm:
            continue
        for name, fnum in re.findall(rb"/([A-Za-z0-9]+)\s+(\d+)\s+0\s+R", fm.group(1)):
            key = name.decode("latin-1")
            if key in fonts:
                continue
            fbody = objs.get(int(fnum), (b"", None))[0]
            bm = re.search(rb"/BaseFont\s*/([#\w+.-]+)", fbody)
            base = re.sub(r"^[A-Z]{6}\+", "", bm.group(1).decode("latin-1")) if bm else ""
            tu = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", fbody)
            mapping = {}
            if tu:
                cmap = inflate(objs.get(int(tu.group(1)), (b"", None))[1])
                if cmap:
                    mapping = parse_tounicode(cmap)
            if not mapping and base:
                mapping = by_name.get(base, {})
            fonts[key] = mapping

    pos, plain = [], []
    for pageno, num in enumerate(pages, 1):
        body = objs[num][0]
        stream = b""
        for c in re.findall(rb"/Contents\s+(\d+)\s+0\s+R", body):
            s = inflate(objs.get(int(c), (b"", None))[1])
            if s:
                stream += s + b"\n"
        items = extract(stream, fonts)
        items.sort(key=lambda t: (-t[0], t[1]))
        pos.append("\n" + "=" * 72)
        pos.append("PAGE %d (obj %d)" % (pageno, num))
        pos.append("=" * 72)
        last_y = None
        for y, x, text in items:
            if last_y is not None and abs(y - last_y) > 1.0:
                pos.append("")
            pos.append("[y=%8.1f x=%7.1f] %s" % (y, x, text))
            last_y = y
        plain.append("\n\n########## PAGE %d ##########" % pageno)
        line, last_y = [], None
        for y, x, text in items:
            if last_y is not None and abs(y - last_y) > 1.0:
                plain.append(" ".join(line)); line = []
            line.append(text)
            last_y = y
        if line:
            plain.append(" ".join(line))

    open(prefix + "_pos.txt", "w", encoding="utf-8").write("\n".join(pos) + "\n")
    open(prefix + "_plain.txt", "w", encoding="utf-8").write("\n".join(plain) + "\n")
    print("converted %s -> %s_plain.txt (%d pages)" % (path, prefix, len(pages)))


if __name__ == "__main__":
    convert(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "out")
