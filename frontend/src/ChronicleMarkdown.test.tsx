// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";
import { ChronicleMarkdown } from "./ChronicleMarkdown";

afterEach(cleanup);

describe("ChronicleMarkdown", () => {
  test("styles paired dialogue across emphasis and keeps the quote marks", () => {
    const { container } = render(
      <ChronicleMarkdown text={'She said, “stay **bold** and *clear*.” Then \'leave\'.'} />,
    );
    const dialogue = [...container.querySelectorAll(".chronicle-dialogue")];

    expect(dialogue.map((span) => span.textContent).join("")).toBe(
      "“stay bold and clear.”",
    );
    expect(container.querySelector(".chronicle-dialogue strong")).toBeNull();
    expect(container.querySelector("strong .chronicle-dialogue")?.textContent).toBe("bold");
    expect(container.textContent).toContain("'leave'");
    expect(container.querySelectorAll(".chronicle-dialogue").length).toBeGreaterThan(1);
  });

  test("supports quote families and leaves inline and fenced code untouched", () => {
    const { container } = render(
      <ChronicleMarkdown
        text={`“curly” «guillemet» 「Japanese」 『book』 ｢corner｣ ＂full width＂ and \`"code"\`.\n\n\`\`\`txt\n"fenced"\n\`\`\``}
      />,
    );
    const dialogue = [...container.querySelectorAll(".chronicle-dialogue")];
    const dialogueText = dialogue.map((span) => span.textContent).join("");

    expect(dialogueText).toContain("“curly”");
    expect(dialogueText).toContain("«guillemet»");
    expect(dialogueText).toContain("「Japanese」");
    expect(dialogueText).toContain("『book』");
    expect(dialogueText).toContain("｢corner｣");
    expect(dialogueText).toContain("＂full width＂");
    expect(container.querySelector("code .chronicle-dialogue")).toBeNull();
    expect(container.querySelectorAll("code")[0]?.textContent).toBe('"code"');
    expect(container.querySelectorAll("pre code")[0]?.textContent?.trim()).toBe('"fenced"');
  });

  test("renders GitHub Markdown and ignores raw HTML", () => {
    const { container } = render(
      <ChronicleMarkdown
        text={`| Item | Status |\n| --- | --- |\n| **Key** | ~~old~~ |\n\n<img src=x onerror=alert(1)>`}
      />,
    );

    expect(container.querySelector("table")).toBeTruthy();
    expect(container.querySelector("strong")?.textContent).toBe("Key");
    expect(container.querySelector("del")?.textContent).toBe("old");
    expect(container.querySelector("img")).toBeNull();
  });

  test("does not treat double quotes inside HTML attributes as dialogue", () => {
    const { container } = render(
      <ChronicleMarkdown
        text={`&lt;span class=&quot;foo&quot;&gt; &quot;spoken&quot; &lt;/span&gt;`}
      />,
    );
    const dialogue = [...container.querySelectorAll(".chronicle-dialogue")];

    expect(dialogue.map((span) => span.textContent).join("")).toBe('"spoken"');
    expect(container.querySelector("span.foo")).toBeNull();
    expect(container.textContent).toContain('<span class="foo">');
  });

  test("colors dialogue in rendered list items", () => {
    const { container } = render(
      <ChronicleMarkdown text={'- “First choice”\n- "Second choice"'} />,
    );

    expect([...container.querySelectorAll("li .chronicle-dialogue")].map((span) => span.textContent).join(""))
      .toBe('“First choice”"Second choice"');
  });
});
