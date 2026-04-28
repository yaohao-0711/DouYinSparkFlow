(() => {
  const TARGET = "/v1/message/send";
  const MAX_DEPTH = 8;
  const ID_RE = /^\d+:\d+:\d+:\d+$/;

  const textEncoder =
    typeof TextEncoder !== "undefined" ? new TextEncoder() : null;
  const textDecoder =
    typeof TextDecoder !== "undefined"
      ? new TextDecoder("utf-8", { fatal: false })
      : null;

  const strToBytes = (s) => {
    if (textEncoder) return textEncoder.encode(s);
    const u8 = new Uint8Array(s.length);
    for (let i = 0; i < s.length; i++) u8[i] = s.charCodeAt(i) & 0xff;
    return u8;
  };

  function getUserId() {
    try {
      const traceRaw = window.localStorage.getItem("LOG_TRACE");
      if (traceRaw) {
        const traceArr = JSON.parse(traceRaw);
        if (Array.isArray(traceArr) && traceArr.length > 0) {
          const lastItem = traceArr[traceArr.length - 1];
          const uid = lastItem && lastItem.uid;
          if (uid !== undefined && uid !== null && String(uid).trim() !== "") {
            return String(uid);
          }
        }
      }
    } catch {}

    try {
      const tokenRaw = window.localStorage.getItem("__tea_cache_tokens_2562");
      if (tokenRaw) {
        const tokenObj = JSON.parse(tokenRaw);
        const uid =
          tokenObj &&
          typeof tokenObj === "object" &&
          tokenObj.user_unique_id;
        if (uid !== undefined && uid !== null && String(uid).trim() !== "") {
          return String(uid);
        }
      }
    } catch {}

    return 0;
  }

  function getCookieString() {
    const raw = typeof document !== "undefined" ? document.cookie || "" : "";
    const list = raw
      .split(";")
      .map((item) => item.trim())
      .filter(Boolean);

    let xmst = "";
    try {
      xmst =
        typeof window !== "undefined" && window.localStorage
          ? window.localStorage.getItem("xmst") || ""
          : "";
    } catch {}

    const filtered = list.filter((item) => !/^ms_token=/.test(item));
    if (xmst) filtered.push("ms_token=" + xmst);
    return filtered.join("; ");
  }

  const toBase64 = (u8) => {
    let bin = "";
    const CHUNK = 0x8000;
    for (let i = 0; i < u8.length; i += CHUNK) {
      bin += String.fromCharCode(...u8.subarray(i, i + CHUNK));
    }
    return btoa(bin);
  };

  const anyToBytesSync = (body) => {
    if (body == null) return null;
    if (body instanceof Uint8Array) return body;
    if (body instanceof ArrayBuffer) return new Uint8Array(body);
    if (ArrayBuffer.isView(body)) {
      return new Uint8Array(body.buffer, body.byteOffset, body.byteLength);
    }
    if (typeof body === "string") return strToBytes(body);
    if (body instanceof URLSearchParams) return strToBytes(body.toString());
    return null;
  };

  const decodeUtf8 = (u8) => {
    try {
      let s = "";
      if (textDecoder) {
        s = textDecoder.decode(u8);
      } else {
        const CHUNK = 0x8000;
        for (let i = 0; i < u8.length; i += CHUNK) {
          s += String.fromCharCode(...u8.subarray(i, i + CHUNK));
        }
      }

      if (s.length === 0) return "";

      let bad = 0;
      for (let i = 0; i < s.length; i++) {
        const c = s.charCodeAt(i);
        if (c === 0xfffd) bad++;
        if (
          (c <= 0x08 || (c >= 0x0e && c <= 0x1f)) &&
          c !== 0x09 &&
          c !== 0x0a &&
          c !== 0x0d
        ) {
          bad++;
        }
      }

      return bad / s.length < 0.02 ? s : null;
    } catch {
      return null;
    }
  };

  const readVarint = (u8, offset) => {
    let val = 0n;
    let shift = 0n;

    for (let i = offset; i < u8.length; i++) {
      const b = BigInt(u8[i]);
      val |= (b & 0x7fn) << shift;
      if ((b & 0x80n) === 0n) return { value: val, nextOffset: i + 1 };
      shift += 7n;
      if (shift > 70n) throw new Error("varint too long");
    }

    throw new Error("truncated varint");
  };

  const parseMessage = (u8) => {
    let off = 0;
    const fields = [];

    while (off < u8.length) {
      const key = readVarint(u8, off);
      off = key.nextOffset;

      const fieldNumber = Number(key.value >> 3n);
      const wireType = Number(key.value & 0x07n);
      if (!Number.isFinite(fieldNumber) || fieldNumber <= 0) {
        throw new Error("invalid field number");
      }

      if (wireType === 0) {
        const v = readVarint(u8, off);
        off = v.nextOffset;
        fields.push({ fieldNumber, wireType, varint: v.value });
        continue;
      }

      if (wireType === 1) {
        if (off + 8 > u8.length) throw new Error("truncated fixed64");
        off += 8;
        continue;
      }

      if (wireType === 5) {
        if (off + 4 > u8.length) throw new Error("truncated fixed32");
        off += 4;
        continue;
      }

      if (wireType === 2) {
        const l = readVarint(u8, off);
        off = l.nextOffset;

        if (l.value > BigInt(Number.MAX_SAFE_INTEGER)) {
          throw new Error("length too large");
        }

        const len = Number(l.value);
        if (off + len > u8.length) throw new Error("truncated bytes");

        const bytes = u8.subarray(off, off + len);
        off += len;
        fields.push({ fieldNumber, wireType, bytes });
        continue;
      }

      throw new Error(`unsupported wireType=${wireType}`);
    }

    return fields;
  };

  const findConversation = (u8, depth = 0) => {
    if (depth > MAX_DEPTH) return null;

    let fields;
    try {
      fields = parseMessage(u8);
    } catch {
      return null;
    }

    const f1 = fields.find((f) => f.fieldNumber === 1 && f.wireType === 2);
    const f3 = fields.find((f) => f.fieldNumber === 3 && f.wireType === 0);
    let fallback = null;

    if (f1 && f3) {
      const conversationId = decodeUtf8(f1.bytes);
      if (conversationId !== null) {
        const candidate = {
          conversationId,
          conversationShortId: f3.varint.toString(),
        };
        if (ID_RE.test(conversationId)) return candidate;
        fallback = candidate;
      }
    }

    for (const f of fields) {
      if (f.wireType !== 2 || !f.bytes || f.bytes.length === 0) continue;
      const child = findConversation(f.bytes, depth + 1);
      if (!child) continue;
      if (ID_RE.test(child.conversationId)) return child;
      if (!fallback) fallback = child;
    }

    return fallback;
  };

  const logHit = (url, bytes) => {
    if (!url || !url.includes(TARGET)) return;
    if (!bytes || bytes.length === 0) return;

    const info = findConversation(bytes);
    if (!info) return;

    const base64 = toBase64(bytes);
    const now = new Date().toISOString();
    const titleStyle =
      "background:#000;color:#00e5ff;padding:6px 10px;border-radius:8px;" +
      "border:2px solid #00e5ff;font-weight:800;font-size:12px;";
    const labelStyle =
      "background:#000;color:#ffd60a;padding:2px 6px;border-radius:4px;font-weight:800;";
    const valueStyle =
      "background:#000;color:#ffffff;padding:2px 6px;border-radius:4px;font-weight:700;";
    const okStyle =
      "background:#000;color:#00ff7f;padding:2px 6px;border-radius:4px;font-weight:800;";
    const base64Style =
      "background:#000;color:#00ff7f;padding:10px 12px;border-radius:8px;" +
      "border:2px solid #00ff7f;font-family:Consolas,Monaco,'Courier New',monospace;" +
      "font-size:12px;line-height:1.55;font-weight:700;word-break:break-all;";

    console.groupCollapsed("%cDY Hook 捕获到消息发送", titleStyle);
    console.log("%c状态%c 已捕获", labelStyle, okStyle);
    console.log("%c时间%c " + now, labelStyle, valueStyle);
    console.log("%c接口%c " + TARGET, labelStyle, valueStyle);
    console.log(
      "%cconversationId%c " + info.conversationId,
      labelStyle,
      valueStyle
    );
    console.log(
      "%cconversationShortId%c " + info.conversationShortId,
      labelStyle,
      valueStyle
    );
    console.log("%cbase64(raw)", labelStyle);
    console.log("%c" + base64, base64Style);
    console.groupEnd();
  };

  const oldOpen = XMLHttpRequest.prototype.open;
  const oldSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function (method, url) {
    this.__dy_method = method;
    this.__dy_url = url;
    return oldOpen.apply(this, arguments);
  };

  XMLHttpRequest.prototype.send = function (body) {
    const url = this.__dy_url || "";
    const bytes = anyToBytesSync(body);
    logHit(url, bytes);

    if (!bytes && body instanceof Blob && url.includes(TARGET)) {
      body
        .arrayBuffer()
        .then((buf) => {
          logHit(url, new Uint8Array(buf));
        })
        .catch(() => {});
    }

    return oldSend.apply(this, arguments);
  };

  if (navigator && typeof navigator.sendBeacon === "function") {
    const oldBeacon = navigator.sendBeacon.bind(navigator);
    navigator.sendBeacon = function (url, data) {
      const bytes = anyToBytesSync(data);
      logHit(url, bytes);

      if (!bytes && data instanceof Blob && url && url.includes(TARGET)) {
        data
          .arrayBuffer()
          .then((buf) => {
            logHit(url, new Uint8Array(buf));
          })
          .catch(() => {});
      }

      return oldBeacon(url, data);
    };
  }

  const userId = getUserId();
  const cookieText = getCookieString();
  const titleStyle =
    "background:#000;color:#00e5ff;padding:6px 10px;border-radius:8px;" +
    "border:2px solid #00e5ff;font-weight:800;font-size:12px;";
  const labelStyle =
    "background:#000;color:#ffd60a;padding:2px 6px;border-radius:4px;font-weight:800;";
  const valueStyle =
    "background:#000;color:#ffffff;padding:2px 6px;border-radius:4px;font-weight:700;";

  console.groupCollapsed("%cDY Hook 注册成功", titleStyle);
  console.log("%cuser_id%c " + userId, labelStyle, valueStyle);
  console.log("%ccookies%c " + cookieText, labelStyle, valueStyle);
  console.groupEnd();
})();
