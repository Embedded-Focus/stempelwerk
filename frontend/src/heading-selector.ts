import type { Heading } from "./api";

export interface HeadingTreeOptions {
  headings: Heading[];
  /** Headings of other files are shown but disabled. */
  fileId: string;
  /** The heading the clock belongs to now. It is highlighted and cannot be picked. */
  currentHeadingId: string;
  onSelect: (heading: Heading) => void;
}

interface HeadingNode {
  heading: Heading;
  children: HeadingNode[];
  button: HTMLButtonElement;
  item: HTMLLIElement;
  details: HTMLDetailsElement | null;
}

/** Build the tree and return its root element. */
export function createHeadingTree(options: HeadingTreeOptions): HTMLElement {
  const root = document.createElement("div");
  root.className = "heading-tree";

  const search = document.createElement("input");
  search.type = "search";
  search.className = "heading-tree-search";
  search.placeholder = "Search headings";

  const list = document.createElement("div");
  list.className = "heading-tree-list";

  const empty = document.createElement("p");
  empty.className = "heading-tree-empty";
  empty.hidden = true;
  empty.textContent = "No headings match";

  root.append(search, list, empty);

  const files = new Map<string, HTMLDetailsElement>();
  const nodes: HeadingNode[] = [];

  const byFile = new Map<string, Heading[]>();
  for (const heading of options.headings) {
    const group = byFile.get(heading.file_id);
    if (group === undefined) {
      byFile.set(heading.file_id, [heading]);
    } else {
      group.push(heading);
    }
  }

  for (const [fileId, headings] of byFile) {
    const fileGroup = document.createElement("details");
    fileGroup.className = "heading-tree-file";
    const summary = document.createElement("summary");
    summary.textContent = fileId === options.fileId ? fileId : `${fileId} - other file`;
    fileGroup.append(summary);

    const ul = document.createElement("ul");
    fileGroup.append(ul);
    list.append(fileGroup);
    files.set(fileId, fileGroup);

    const stack: { level: number; node: HeadingNode; ul: HTMLUListElement }[] = [];
    for (const heading of headings) {
      const level = heading.outline.length;
      while (stack.length > 0 && stack[stack.length - 1].level >= level) {
        stack.pop();
      }

      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "heading-tree-node";
      button.textContent = nodeLabel(heading);
      button.title = heading.outline.join(" / ");
      const disabled = fileId !== options.fileId || heading.id === options.currentHeadingId;
      button.disabled = disabled;
      if (heading.id === options.currentHeadingId) {
        button.classList.add("heading-tree-current");
      }

      const isLeaf = stack.length === 0 || stack[stack.length - 1].level >= level + 1;
      const nextIsDeeper =
        headings.indexOf(heading) + 1 < headings.length &&
        headings[headings.indexOf(heading) + 1].outline.length > level;

      if (nextIsDeeper) {
        const details = document.createElement("details");
        const nodeSummary = document.createElement("summary");
        nodeSummary.append(button);
        details.append(nodeSummary);
        const childUl = document.createElement("ul");
        details.append(childUl);
        item.append(details);

        const node: HeadingNode = { heading, children: [], button, item, details };
        nodes.push(node);
        attachSelect(button, node, options);

        const parent = stack[stack.length - 1];
        if (parent === undefined) {
          ul.append(item);
        } else {
          parent.node.children.push(node);
          parent.ul.append(item);
        }
        stack.push({ level, node, ul: childUl });
      } else {
        item.append(button);
        const node: HeadingNode = { heading, children: [], button, item, details: null };
        nodes.push(node);
        attachSelect(button, node, options);

        const parent = stack[stack.length - 1];
        if (parent === undefined) {
          ul.append(item);
        } else {
          parent.node.children.push(node);
          parent.ul.append(item);
        }
      }
    }
  }

  applyInitialOpenState(files, nodes, options);
  restoreOrApplySearch(search, list, empty, files, nodes, options);

  search.addEventListener("input", () => {
    applySearch(search, list, empty, files, nodes, options);
  });
  search.addEventListener("keydown", (event: KeyboardEvent) => {
    if (event.key === "Enter") {
      event.preventDefault();
    }
  });

  requestAnimationFrame(() => {
    const current = nodes.find((node) => node.heading.id === options.currentHeadingId);
    current?.button.scrollIntoView({ block: "nearest" });
  });

  return root;
}

function nodeLabel(heading: Heading): string {
  const parts: string[] = [];
  if (heading.todo !== null) {
    parts.push(heading.todo);
  }
  parts.push(heading.title);
  return parts.join(" ");
}

function attachSelect(
  button: HTMLButtonElement,
  node: HeadingNode,
  options: HeadingTreeOptions
): void {
  button.addEventListener("click", (event: MouseEvent) => {
    event.preventDefault();
    options.onSelect(node.heading);
    for (const other of document.querySelectorAll(".heading-tree-selected")) {
      other.classList.remove("heading-tree-selected");
    }
    button.classList.add("heading-tree-selected");
  });
}

function applyInitialOpenState(
  files: Map<string, HTMLDetailsElement>,
  nodes: HeadingNode[],
  options: HeadingTreeOptions
): void {
  const currentPath = pathOfCurrent(nodes, options.currentHeadingId);
  for (const [fileId, details] of files) {
    details.open = fileId === options.fileId;
  }
  for (const node of nodes) {
    if (currentPath.has(node.heading.id) && node.details !== null) {
      node.details.open = true;
    }
  }
}

function pathOfCurrent(nodes: HeadingNode[], currentHeadingId: string): Set<string> {
  const path = new Set<string>();
  const find = (list: HeadingNode[], trail: string[]): string[] | null => {
    for (const node of list) {
      const next = [...trail, node.heading.id];
      if (node.heading.id === currentHeadingId) {
        return next;
      }
      const found = find(node.children, next);
      if (found !== null) {
        return found;
      }
    }
    return null;
  };
  const found = find(nodes, []);
  if (found !== null) {
    for (const id of found) {
      path.add(id);
    }
  }
  return path;
}

function restoreOrApplySearch(
  search: HTMLInputElement,
  list: HTMLElement,
  empty: HTMLElement,
  files: Map<string, HTMLDetailsElement>,
  nodes: HeadingNode[],
  options: HeadingTreeOptions
): void {
  if (search.value.trim() === "") {
    applyInitialOpenState(files, nodes, options);
    for (const node of nodes) {
      node.item.hidden = false;
    }
    for (const details of files.values()) {
      details.hidden = false;
    }
    empty.hidden = true;
    list.hidden = false;
  } else {
    applySearch(search, list, empty, files, nodes, options);
  }
}

function applySearch(
  search: HTMLInputElement,
  list: HTMLElement,
  empty: HTMLElement,
  files: Map<string, HTMLDetailsElement>,
  nodes: HeadingNode[],
  options: HeadingTreeOptions
): void {
  const query = search.value.trim().toLowerCase();

  if (query === "") {
    restoreOrApplySearch(search, list, empty, files, nodes, options);
    return;
  }

  const childrenOf = new Map<string, HeadingNode[]>();
  for (const node of nodes) {
    node.item.hidden = true;
    childrenOf.set(node.heading.id, node.children);
  }

  const matches = (node: HeadingNode): boolean => {
    const heading = node.heading;
    return (
      heading.outline.join(" / ").toLowerCase().includes(query) ||
      (heading.todo !== null && heading.todo.toLowerCase().includes(query))
    );
  };

  const visibleIds = new Set<string>();
  for (const node of nodes) {
    if (matches(node)) {
      visibleIds.add(node.heading.id);
      let parent: HeadingNode | undefined = findParent(nodes, node);
      while (parent !== undefined) {
        visibleIds.add(parent.heading.id);
        parent = findParent(nodes, parent);
      }
    }
  }

  for (const node of nodes) {
    if (visibleIds.has(node.heading.id)) {
      node.item.hidden = false;
      node.details?.setAttribute("open", "");
    }
  }

  let anyVisible = false;
  for (const [fileId, details] of files) {
    const hasVisible = nodes.some(
      (node) => node.heading.file_id === fileId && visibleIds.has(node.heading.id)
    );
    details.hidden = !hasVisible;
    if (hasVisible) {
      details.setAttribute("open", "");
      anyVisible = true;
    }
  }
  void options;
  empty.hidden = anyVisible;
  list.hidden = !anyVisible;
}

function findParent(nodes: HeadingNode[], node: HeadingNode): HeadingNode | undefined {
  for (const candidate of nodes) {
    if (candidate.children.includes(node)) {
      return candidate;
    }
  }
  return undefined;
}
