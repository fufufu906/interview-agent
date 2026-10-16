import type { Source } from "./types";

export interface SourceTreeNode {
  key: string;
  name: string;
  children: SourceTreeNode[];
  source?: Source;
  count: number;
}

export function groupSourceFolders(sources: Source[]) {
  const roots = new Map<string, SourceTreeNode>();
  const standalone: Source[] = [];
  for (const source of sources) {
    const root = source.folder_root;
    const parts = source.relative_path
      ?.replace(/\\/g, "/")
      .split("/")
      .filter(Boolean);
    if (
      !root ||
      !parts?.length ||
      parts.some((part) => part === ".." || part === ".")
    ) {
      standalone.push(source);
      continue;
    }
    // The full origin keeps two directories with identical names separate.
    let group = roots.get(root);
    if (!group) {
      group = {
        key: root,
        name:
          root.replace(/\\/g, "/").split("/").filter(Boolean).at(-1) || root,
        children: [],
        count: 0,
      };
      roots.set(root, group);
    }
    let node: SourceTreeNode = group;
    node.count++;
    let relative = "";
    for (const part of parts.slice(0, -1)) {
      relative += `/${part}`;
      let child: SourceTreeNode | undefined = node.children.find(
        (item) => !item.source && item.name === part,
      );
      if (!child) {
        child = {
          key: `${root}${relative}`,
          name: part,
          children: [],
          count: 0,
        };
        node.children.push(child);
      }
      child.count++;
      node = child;
    }
    node.children.push({
      key: source.source_id,
      name: parts.at(-1)!,
      children: [],
      source,
      count: 1,
    });
  }
  function sort(node: SourceTreeNode) {
    node.children.sort(
      (a, b) =>
        Number(!!a.source) - Number(!!b.source) ||
        a.name.localeCompare(b.name, "zh-CN"),
    );
    node.children.forEach(sort);
  }
  const folders = [...roots.values()];
  folders.forEach(sort);
  return { folders, standalone };
}
