import ReactMarkdown from "react-markdown";
import type { Element, ElementContent, Root, RootContent, Text } from "hast";
import type { Plugin } from "unified";
import remarkGfm from "remark-gfm";

type TextPosition = { node: Text; start: number; end: number };
type QuoteRange = { start: number; end: number };

const OPEN_TO_CLOSE: Record<string, string> = {
  "“": "”",
  "«": "»",
  "「": "」",
  "『": "』",
  "｢": "｣",
  "〝": "〞",
};
const SYMMETRIC_QUOTES = new Set(["\"", "＂"]);
const CLOSING_QUOTES = new Set(Object.values(OPEN_TO_CLOSE));
const EXCLUDED_TAGS = new Set(["code", "pre", "script", "style"]);
const FLOW_TAGS = new Set([
  "p",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "td",
  "th",
  "li",
  "figcaption",
  "summary",
]);

function collectTextPositions(node: ElementContent, output: TextPosition[]): void {
  if (node.type === "text") {
    const text = node as Text;
    const start = output.length ? output[output.length - 1].end : 0;
    output.push({ node: text, start, end: start + text.value.length });
    return;
  }

  if (node.type !== "element" || EXCLUDED_TAGS.has(node.tagName)) return;
  for (const child of node.children) collectTextPositions(child, output);
}

function findQuoteRanges(value: string): QuoteRange[] {
  const ranges: QuoteRange[] = [];
  const stack: Array<{ quote: string; start: number; close: string }> = [];
  const htmlTagRanges: QuoteRange[] = [];

  for (let index = 0; index < value.length; index += 1) {
    if (value[index] !== "<" || !/[A-Za-z/]/.test(value[index + 1] ?? "")) continue;
    let quote: string | null = null;
    for (let end = index + 1; end < value.length; end += 1) {
      const character = value[end];
      if (quote) {
        if (character === quote) quote = null;
      } else if (character === "\"" || character === "'") {
        quote = character;
      } else if (character === ">") {
        htmlTagRanges.push({ start: index, end: end + 1 });
        index = end;
        break;
      }
    }
  }

  let tagRangeIndex = 0;
  for (let index = 0; index < value.length; index += 1) {
    const tagRange = htmlTagRanges[tagRangeIndex];
    if (tagRange && index >= tagRange.start && index < tagRange.end) {
      index = tagRange.end - 1;
      tagRangeIndex += 1;
      continue;
    }

    const character = value[index];
    const closingQuote = OPEN_TO_CLOSE[character];
    if (closingQuote) {
      stack.push({ quote: character, start: index, close: closingQuote });
      continue;
    }

    if (SYMMETRIC_QUOTES.has(character)) {
      const open = stack[stack.length - 1];
      if (open?.close === character) {
        stack.pop();
        ranges.push({ start: open.start, end: index + 1 });
      } else {
        stack.push({ quote: character, start: index, close: character });
      }
      continue;
    }

    if (CLOSING_QUOTES.has(character)) {
      const open = stack[stack.length - 1];
      if (open?.close === character) {
        stack.pop();
        ranges.push({ start: open.start, end: index + 1 });
      }
    }
  }

  return ranges;
}

function dialogueSpan(value: string): Element {
  return {
    type: "element",
    tagName: "span",
    properties: { className: ["chronicle-dialogue"] },
    children: [{ type: "text", value }],
  };
}

function splitTextNode(
  node: Text,
  start: number,
  ranges: QuoteRange[],
): ElementContent[] {
  const end = start + node.value.length;
  const cuts = new Set([start, end]);
  for (const range of ranges) {
    if (range.start < end && range.end > start) {
      cuts.add(Math.max(start, range.start));
      cuts.add(Math.min(end, range.end));
    }
  }

  const boundaries = [...cuts].sort((left, right) => left - right);
  const result: ElementContent[] = [];
  for (let index = 0; index < boundaries.length - 1; index += 1) {
    const segmentStart = boundaries[index];
    const segmentEnd = boundaries[index + 1];
    if (segmentStart === segmentEnd) continue;
    const value = node.value.slice(segmentStart - start, segmentEnd - start);
    const isDialogue = ranges.some(
      (range) => range.start <= segmentStart && range.end >= segmentEnd,
    );
    result.push(isDialogue ? dialogueSpan(value) : { type: "text", value });
  }
  return result;
}

function markDialogueInFlow(flow: Element): void {
  const positions: TextPosition[] = [];
  collectTextPositions(flow, positions);
  if (!positions.length) return;

  const rawText = positions.map(({ node }) => node.value).join("");
  const ranges = findQuoteRanges(rawText);
  if (!ranges.length) return;

  let textIndex = 0;
  const replace = (node: ElementContent): ElementContent[] => {
    if (node.type === "text") {
      const text = node as Text;
      const position = positions[textIndex++];
      return splitTextNode(text, position.start, ranges);
    }
    if (node.type !== "element" || EXCLUDED_TAGS.has(node.tagName)) return [node];
    const element = node as Element;
    element.children = element.children.flatMap(replace);
    return [element];
  };

  flow.children = flow.children.flatMap(replace);
}

function markDialogue(tree: Root): void {
  const visit = (node: RootContent): void => {
    if (node.type !== "element") return;
    const element = node as Element;
    if (FLOW_TAGS.has(element.tagName)) {
      markDialogueInFlow(element);
      return;
    }
    if (EXCLUDED_TAGS.has(element.tagName)) return;
    for (const child of element.children) visit(child);
  };

  for (const child of tree.children) visit(child);
}

const dialoguePlugin: Plugin<[], Root> = () => markDialogue;

export function ChronicleMarkdown({
  text,
  className,
}: {
  text: string;
  className?: string;
}) {
  return (
    <div className={className}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[dialoguePlugin]}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
