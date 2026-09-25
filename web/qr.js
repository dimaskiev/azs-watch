/* Compact QR (byte mode, ECC M, versions 1-6) */
(function (global) {
  const CAP = [0, 16, 28, 44, 64, 86, 108];
  const ECC = [0, 10, 16, 26, 18, 24, 16];
  const BLOCKS = [0, 1, 1, 1, 2, 2, 4];
  const ALIGN = [null, [], [18], [22], [26], [30], [34]];
  const EXP = new Uint8Array(512);
  const LOG = new Uint8Array(256);
  let x = 1;
  for (let i = 0; i < 255; i++) {
    EXP[i] = x;
    LOG[x] = i;
    x <<= 1;
    if (x & 256) x ^= 285;
  }
  for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];

  function mul(a, b) {
    return a && b ? EXP[LOG[a] + LOG[b]] : 0;
  }

  function rs(data, ec) {
    const gen = [1];
    for (let i = 0; i < ec; i++) {
      const next = new Array(gen.length + 1).fill(0);
      for (let j = 0; j < gen.length; j++) {
        next[j] ^= mul(gen[j], EXP[i]);
        next[j + 1] ^= gen[j];
      }
      gen.length = 0;
      gen.push(...next);
    }
    const out = new Array(ec).fill(0);
    for (const byte of data) {
      const factor = byte ^ out[0];
      out.shift();
      out.push(0);
      if (!factor) continue;
      for (let i = 0; i < ec; i++) out[i] ^= mul(gen[i + 1], factor);
    }
    return out;
  }

  function bits(n, w) {
    return n.toString(2).padStart(w, "0");
  }

  function encode(text) {
    const bytes = Array.from(new TextEncoder().encode(text));
    let ver = 1;
    while (ver <= 6 && bytes.length + 2 > CAP[ver]) ver += 1;
    if (ver > 6) throw new Error("QR too long");
    const cap = CAP[ver];
    let stream = "0100" + bits(bytes.length, 8);
    for (const b of bytes) stream += bits(b, 8);
    stream += "0000";
    while (stream.length % 8) stream += "0";
    const data = [];
    for (let i = 0; i < stream.length; i += 8) data.push(parseInt(stream.slice(i, i + 8), 2));
    const pads = [0xec, 0x11];
    let p = 0;
    while (data.length < cap) data.push(pads[p++ % 2]);

    const nblocks = BLOCKS[ver];
    const blockLen = Math.floor(cap / nblocks);
    const shortBlocks = nblocks * blockLen === cap ? 0 : nblocks * (blockLen + 1) - cap;
    const groups = [];
    let offset = 0;
    for (let i = 0; i < nblocks; i++) {
      const len = i < nblocks - shortBlocks ? blockLen : blockLen + 1;
      const block = data.slice(offset, offset + len);
      offset += len;
      groups.push({ data: block, ecc: rs(block, ECC[ver]) });
    }
    const interleaved = [];
    const maxD = Math.max(...groups.map((g) => g.data.length));
    for (let i = 0; i < maxD; i++) {
      for (const g of groups) if (i < g.data.length) interleaved.push(g.data[i]);
    }
    for (let i = 0; i < ECC[ver]; i++) {
      for (const g of groups) interleaved.push(g.ecc[i]);
    }
    return { ver, bits: interleaved.flatMap((b) => bits(b, 8).split("").map(Number)) };
  }

  function matrix(text) {
    const { ver, bits: payload } = encode(text);
    const n = ver * 4 + 17;
    const m = Array.from({ length: n }, () => Array(n).fill(null));
    function placeFinder(r, c) {
      for (let y = -1; y <= 7; y++) {
        for (let x = -1; x <= 7; x++) {
          const rr = r + y;
          const cc = c + x;
          if (rr < 0 || cc < 0 || rr >= n || cc >= n) continue;
          const on = x >= 0 && x <= 6 && y >= 0 && y <= 6 && (x === 0 || x === 6 || y === 0 || y === 6 || (x >= 2 && x <= 4 && y >= 2 && y <= 4));
          m[rr][cc] = on;
        }
      }
    }
    placeFinder(0, 0);
    placeFinder(0, n - 7);
    placeFinder(n - 7, 0);
    for (const pos of ALIGN[ver]) {
      for (let y = -2; y <= 2; y++) {
        for (let x = -2; x <= 2; x++) {
          m[pos + y][pos + x] = Math.max(Math.abs(x), Math.abs(y)) !== 1;
        }
      }
    }
    for (let i = 8; i < n - 8; i++) {
      if (m[6][i] == null) m[6][i] = i % 2 === 0;
      if (m[i][6] == null) m[i][6] = i % 2 === 0;
    }
    m[n - 8][8] = true;
    for (let i = 0; i < 9; i++) {
      if (m[8][i] == null) m[8][i] = false;
      if (m[i][8] == null) m[i][8] = false;
    }
    for (let i = 0; i < 8; i++) {
      if (m[8][n - 1 - i] == null) m[8][n - 1 - i] = false;
      if (m[n - 1 - i][8] == null) m[n - 1 - i][8] = false;
    }

    const dirs = [];
    let up = true;
    for (let col = n - 1; col > 0; col -= 2) {
      if (col === 6) col -= 1;
      for (let i = 0; i < n; i++) {
        const row = up ? n - 1 - i : i;
        for (const c of [col, col - 1]) {
          if (m[row][c] == null) dirs.push([row, c]);
        }
      }
      up = !up;
    }
    function maskBit(r, c, k) {
      if (k === 0) return (r + c) % 2 === 0;
      if (k === 1) return r % 2 === 0;
      if (k === 2) return c % 3 === 0;
      if (k === 3) return (r + c) % 3 === 0;
      if (k === 4) return (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0;
      if (k === 5) return ((r * c) % 2) + ((r * c) % 3) === 0;
      if (k === 6) return (((r * c) % 2) + ((r * c) % 3)) % 2 === 0;
      return (((r + c) % 2) + ((r * c) % 3)) % 2 === 0;
    }
    function applyMask(k) {
      const copy = m.map((row) => row.slice());
      let i = 0;
      for (const [r, c] of dirs) {
        const bit = i < payload.length ? payload[i] : 0;
        copy[r][c] = Boolean(bit) !== maskBit(r, c, k);
        i += 1;
      }
      const fmt = formatBits(k);
      const pos = [
        [8, 0], [8, 1], [8, 2], [8, 3], [8, 4], [8, 5], [8, 7], [8, 8],
        [7, 8], [5, 8], [4, 8], [3, 8], [2, 8], [1, 8], [0, 8],
      ];
      const pos2 = [
        [n - 1, 8], [n - 2, 8], [n - 3, 8], [n - 4, 8], [n - 5, 8], [n - 6, 8], [n - 7, 8],
        [8, n - 8], [8, n - 7], [8, n - 6], [8, n - 5], [8, n - 4], [8, n - 3], [8, n - 2], [8, n - 1],
      ];
      for (let b = 0; b < 15; b++) {
        copy[pos[b][0]][pos[b][1]] = fmt[b];
        copy[pos2[b][0]][pos2[b][1]] = fmt[b];
      }
      return copy;
    }
    let best = null;
    let bestScore = Infinity;
    for (let k = 0; k < 8; k++) {
      const cand = applyMask(k);
      const score = penalty(cand);
      if (score < bestScore) {
        best = cand;
        bestScore = score;
      }
    }
    return best;
  }

  function formatBits(mask) {
    let data = (0b00 << 3) | mask;
    let bits = data << 10;
    const gen = 0b10100110111;
    for (let i = 14; i >= 10; i--) {
      if (bits & (1 << i)) bits ^= gen << (i - 10);
    }
    const raw = ((data << 10) | bits) ^ 0b101010000010010;
    return Array.from({ length: 15 }, (_, i) => Boolean((raw >> (14 - i)) & 1));
  }

  function penalty(m) {
    const n = m.length;
    let score = 0;
    for (let r = 0; r < n; r++) {
      for (const row of [m[r], m.map((x) => x[r])]) {
        let run = 1;
        for (let i = 1; i <= n; i++) {
          if (i < n && row[i] === row[i - 1]) run += 1;
          else {
            if (run >= 5) score += run - 2;
            run = 1;
          }
        }
      }
    }
    return score;
  }

  function svg(text) {
    const m = matrix(text);
    const n = m.length;
    const quiet = 2;
    const size = n + quiet * 2;
    let d = "";
    for (let r = 0; r < n; r++) {
      for (let c = 0; c < n; c++) {
        if (m[r][c]) d += `M${c + quiet} ${r + quiet}h1v1h-1z`;
      }
    }
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}" shape-rendering="crispEdges" aria-hidden="true"><rect width="${size}" height="${size}" fill="#ece6d4"/><path fill="#0b0d0a" d="${d}"/></svg>`;
  }

  global.azsQrSvg = svg;
})(window);
