/**
 * Rewrites ```mermaid fences into `<div data-mermaid="...">` so the diagram component
 * gets the raw source. Must run before rehype-pretty-code, which would otherwise
 * shred the source into Shiki spans.
 */

type HastNode = {
  type: string;
  value?: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
};

export const MERMAID_PROP = "data-mermaid";

export function rehypeMermaid() {
  return (tree: HastNode) => {
    transform(tree);
  };
}

function transform(node: HastNode): void {
  if (!node.children) {
    return;
  }

  node.children = node.children.map((child) => {
    const source = mermaidSource(child);
    if (source !== null) {
      return {
        type: "element",
        tagName: "div",
        properties: { [MERMAID_PROP]: source },
        children: [],
      };
    }
    transform(child);
    return child;
  });
}

function mermaidSource(node: HastNode): string | null {
  if (node.type !== "element" || node.tagName !== "pre") {
    return null;
  }

  const code = node.children?.length === 1 ? node.children[0] : undefined;
  if (!code || code.type !== "element" || code.tagName !== "code") {
    return null;
  }

  const languages = classNames(code.properties?.className);
  if (!languages.includes("language-mermaid")) {
    return null;
  }

  return textContent(code).replace(/\n$/, "");
}

function classNames(value: unknown): string[] {
  if (typeof value === "string") {
    return value.split(/\s+/).filter(Boolean);
  }
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === "string");
  }
  return [];
}

function textContent(node: HastNode): string {
  if (node.type === "text") {
    return node.value ?? "";
  }
  return (node.children ?? []).map(textContent).join("");
}
