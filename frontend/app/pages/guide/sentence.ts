// Plain-English sentence splitter for Beginner Guide cards (v3.1 K1 / F5).
// Avoids splitting mid-sentence on corporate/country abbreviations like
// "Co., Ltd.", "Inc.", "U.S.", or "No.".

const ABBREVIATION_SUFFIX =
  /(?:^|[\s(,])(?:Co|Ltd|Inc|Corp|Plc|LLC|LP|NV|SA|AG|BV|US|USA|UK|EU|No|Nos|Dr|Mr|Mrs|Ms|St|Jr|Sr|vs|etc|approx|est|e\.g|i\.e|U\.S|U\.S\.A|U\.K|E\.U|L\.P|N\.V|S\.A|B\.V|[A-Z])\.$/i;

/**
 * Splits `text` into `[firstSentence, rest]` without splitting mid-sentence on
 * abbreviations like "Co., Ltd.", "Inc.", "U.S.", or "No.".
 */
export function splitFirstSentence(text: string): [string, string] {
  const trimmed = text.trim();
  if (!trimmed) return ["", ""];
  const re = /[.!?]\s+(?=[A-Z0-9"'(])/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(trimmed)) !== null) {
    const endIdx = match.index + 1;
    const prefix = trimmed.slice(0, endIdx);
    if (ABBREVIATION_SUFFIX.test(prefix)) {
      continue;
    }
    const rest = trimmed.slice(match.index + match[0].length).trim();
    return [prefix, rest];
  }
  return [trimmed, ""];
}
