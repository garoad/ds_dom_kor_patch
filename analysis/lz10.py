def decompress(data):
    if data[0] != 0x10:
        return data
    size = data[1] | (data[2] << 8) | (data[3] << 16)
    out = bytearray()
    pos = 4
    while len(out) < size:
        flags = data[pos]; pos += 1
        for bit in range(8):
            if len(out) >= size:
                break
            if flags & (0x80 >> bit):
                b1 = data[pos]; b2 = data[pos+1]; pos += 2
                length = (b1 >> 4) + 3
                disp = ((b1 & 0xF) << 8 | b2) + 1
                for _ in range(length):
                    out.append(out[-disp])
            else:
                out.append(data[pos]); pos += 1
    return bytes(out)


def compress(data, min_match=3, max_match=18, max_disp=4096, window=None):
    """Standard LZ10 (Nitro LZSS) compressor with greedy back-reference search.
    Produces output the reference decompress() above (and the real NDS BIOS
    decompressor) can decode byte-identically back to `data`.
    """
    n = len(data)
    out = bytearray()
    out.append(0x10)
    out += bytes([n & 0xFF, (n >> 8) & 0xFF, (n >> 16) & 0xFF])

    pos = 0
    while pos < n:
        flag_byte = 0
        chunk = bytearray()
        for bit in range(8):
            if pos >= n:
                chunk.append(0)  # padding literal, won't be read (size-bounded)
                continue
            best_len = 0
            best_disp = 0
            lo = max(0, pos - max_disp)
            search_start = pos - 1
            k = search_start
            while k >= lo:
                if data[k] == data[pos]:
                    L = 0
                    limit = min(max_match, n - pos)
                    while L < limit and data[k + L] == data[pos + L]:
                        L += 1
                    if L > best_len:
                        best_len = L
                        best_disp = pos - k
                        if best_len >= max_match:
                            break
                k -= 1
            if best_len >= min_match:
                flag_byte |= (0x80 >> bit)
                b1 = ((best_len - 3) << 4) | (((best_disp - 1) >> 8) & 0xF)
                b2 = (best_disp - 1) & 0xFF
                chunk.append(b1); chunk.append(b2)
                pos += best_len
            else:
                chunk.append(data[pos])
                pos += 1
        out.append(flag_byte)
        out += chunk

    while len(out) % 4 != 0:
        out.append(0)
    return bytes(out)


if __name__ == "__main__":
    import glob, random, os
    HERE = os.path.dirname(os.path.abspath(__file__))
    ROOT = os.path.abspath(os.path.join(HERE, "..", "unpack"))
    files = glob.glob(f"{ROOT}/data/**/*.mes", recursive=True)
    random.seed(0)
    sample = random.sample(files, min(40, len(files)))
    ok = 0
    for fp in sample:
        with open(fp, "rb") as f:
            raw = f.read()
        if not raw or raw[0] != 0x10:
            continue
        dec = decompress(raw)
        recompressed = compress(dec)
        redec = decompress(recompressed)
        if redec == dec:
            ok += 1
        else:
            print("MISMATCH", fp)
    print(f"round-trip verified on {ok} compressed .mes files (decompress->compress->decompress == original)")
