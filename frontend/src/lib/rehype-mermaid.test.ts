import assert from "node:assert/strict";
import test from "node:test";

import { MERMAID_PROP, rehypeMermaid } from "./rehype-mermaid";

type Node = {
  type: string;
  value?: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: Node[];
};

function fence(language: string, ...lines: string[]): Node {
  return {
    type: "element",
    tagName: "pre",
    children: [
      {
        type: "element",
        tagName: "code",
        properties: { className: [`language-${language}`] },
        children: [{ type: "text", value: `${lines.join("\n")}\n` }],
      },
    ],
  };
}

function run(tree: Node): Node {
  rehypeMermaid()(tree);
  return tree;
}

test("rewrites a mermaid fence into a data-mermaid div", () => {
  const tree = run({
    type: "root",
    children: [fence("mermaid", "graph TD", "  A --> B")],
  });

  const node = tree.children?.[0];
  assert.equal(node?.tagName, "div");
  assert.equal(node?.properties?.[MERMAID_PROP], "graph TD\n  A --> B");
  assert.deepEqual(node?.children, []);
});

test("leaves other fences untouched", () => {
  const tree = run({
    type: "root",
    children: [fence("python", "print('hi')")],
  });

  assert.equal(tree.children?.[0]?.tagName, "pre");
});

test("rewrites nested fences", () => {
  const tree = run({
    type: "root",
    children: [
      {
        type: "element",
        tagName: "blockquote",
        children: [fence("mermaid", "pie title Votes")],
      },
    ],
  });

  assert.equal(tree.children?.[0]?.children?.[0]?.tagName, "div");
});
