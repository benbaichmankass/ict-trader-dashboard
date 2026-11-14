// Minimal, dependency-free markdown → HTML for repo docs served by the bot
// (first consumer: Work → Pipeline map, GET /api/bot/work/pipeline-map).
//
// SAFETY: every byte of source text is HTML-escaped BEFORE any markup is added,
// so raw HTML in a doc renders as text, never as markup. Only the constructs
// below become tags; link hrefs are limited to http(s) and resolved against the
// doc's own location on GitHub. No innerHTML of unescaped input anywhere.
//
// Supported: ATX headings, paragraphs, blockquotes, - / * / 1. lists, GFM pipe
// tables, fenced code (```lang; ```mermaid becomes <pre class="mermaid"> for the
// caller to render), inline `code`, **bold**, *em* / _em_, [text](href).
// HTML comments (<!-- ... -->) are dropped.

export const BOT_REPO_BLOB = "https://github.com/benbaichmankass/JTA-Trader/blob/main/";

export function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function resolveHref(raw: string, docPath: string): string | null {
  const href = raw.replace(/&amp;/g, "&").trim();
  try {
    const u = new URL(href, BOT_REPO_BLOB + docPath);
    return u.protocol === "http:" || u.protocol === "https:" ? u.toString() : null;
  } catch {
    return null;
  }
}

/** Inline markup over ALREADY-ESCAPED text. */
function inline(escaped: string, docPath: string): string {
  const codes: string[] = [];
  let s = escaped.replace(/`([^`]+)`/g, (_m, c) => {
    codes.push(`<code>${c}</code>`);
    return `\u0000${codes.length - 1}\u0000`;
  });
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, text, href) => {
    const url = resolveHref(href, docPath);
    return url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${text}</a>` : text;
  });
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^*\w])\*([^*\n]+)\*(?=[^*\w]|$)/g, "$1<em>$2</em>");
  s = s.replace(/(^|[^\w])_([^_\n]+)_(?=[^\w]|$)/g, "$1<em>$2</em>");
  return s.replace(/\u0000(\d+)\u0000/g, (_m, i) => codes[Number(i)]);
}

function splitRow(line: string): string[] {
  let t = line.trim();
  if (t.startsWith("|")) t = t.slice(1);
  if (t.endsWith("|")) t = t.slice(0, -1);
  // split on pipes that are not inside a code span
  const cells: string[] = [];
  let cur = "";
  let inCode = false;
  for (let k = 0; k < t.length; k++) {
    const ch = t[k];
    if (ch === "\\" && t[k + 1] === "|") { cur += "|"; k++; continue; } // GFM escaped pipe
    if (ch === "`") inCode = !inCode;
    if (ch === "|" && !inCode) {
      cells.push(cur);
      cur = "";
    } else cur += ch;
  }
  cells.push(cur);
  return cells.map((c) => c.trim());
}

const isSep = (l: string) => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/.test(l);

export function renderMarkdown(md: string, docPath = ""): string {
  const src = md.replace(/\r\n/g, "\n").replace(/<!--[\s\S]*?-->/g, "");
  const lines = src.split("\n");
  const out: string[] = [];
  let i = 0;
  const inl = (t: string) => inline(escapeHtml(t), docPath);

  while (i < lines.length) {
    const line = lines[i];
    const fence = line.match(/^```\s*([\w-]*)\s*$/);
    if (fence) {
      const lang = fence[1];
      const body: string[] = [];
      i++;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) body.push(lines[i++]);
      i++;
      const code = escapeHtml(body.join("\n"));
      out.push(lang === "mermaid" ? `<pre class="mermaid">${code}</pre>` : `<pre class="code"><code>${code}</code></pre>`);
      continue;
    }
    if (!line.trim()) { i++; continue; }
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      out.push(`<h${h[1].length}>${inl(h[2])}</h${h[1].length}>`);
      i++;
      continue;
    }
    if (line.trim().startsWith("|") && i + 1 < lines.length && isSep(lines[i + 1])) {
      const head = splitRow(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(splitRow(lines[i++]));
      out.push(
        `<div class="mdtable"><table><thead><tr>${head.map((c) => `<th>${inl(c)}</th>`).join("")}</tr></thead><tbody>` +
          rows.map((r) => `<tr>${r.map((c) => `<td>${inl(c)}</td>`).join("")}</tr>`).join("") +
          "</tbody></table></div>",
      );
      continue;
    }
    if (/^\s*>/.test(line)) {
      const body: string[] = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) body.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push(`<blockquote>${renderMarkdown(body.join("\n"), docPath)}</blockquote>`);
      continue;
    }
    const li = line.match(/^(\s*)([-*]|\d+\.)\s+(.*)$/);
    if (li) {
      const ordered = /\d/.test(li[2]);
      const items: string[] = [];
      while (i < lines.length) {
        const m = lines[i].match(/^(\s*)([-*]|\d+\.)\s+(.*)$/);
        if (m) { items.push(m[3]); i++; continue; }
        if (lines[i].trim() && /^\s{2,}/.test(lines[i]) && items.length) { items[items.length - 1] += " " + lines[i].trim(); i++; continue; }
        break;
      }
      const tag = ordered ? "ol" : "ul";
      out.push(`<${tag}>${items.map((t) => `<li>${inl(t)}</li>`).join("")}</${tag}>`);
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|```|\s*>|\s*([-*]|\d+\.)\s)/.test(lines[i]) &&
      !(lines[i].trim().startsWith("|") && i + 1 < lines.length && isSep(lines[i + 1]))) para.push(lines[i++]);
    out.push(`<p>${inl(para.join(" "))}</p>`);
  }
  return out.join("\n");
}
