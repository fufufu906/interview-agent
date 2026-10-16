<script setup lang="ts">
import type { SourceTreeNode } from "../sourceTree";
import type { Workspace } from "../workspace";
import { sourceLabels, dateLabel } from "../types";
import Icon from "./Icon.vue";
defineProps<{
  node: SourceTreeNode;
  w: Workspace;
  depth: number;
  searching: boolean;
}>();
</script>
<template>
  <details
    v-if="!node.source"
    class="source-directory"
    :open="depth === 0 || searching"
  >
    <summary :style="{ '--folder-depth': depth }">
      <span class="directory-chevron" aria-hidden="true">›</span>
      <Icon name="folder" />
      <span class="directory-name">{{ node.name }}</span>
      <span class="directory-count">{{ node.count }} 份资料</span>
    </summary>
    <p v-if="depth === 0" class="directory-origin">{{ node.key }}</p>
    <SourceTreeItem
      v-for="child in node.children"
      :key="child.key"
      :node="child"
      :w="w"
      :depth="depth + 1"
      :searching="searching"
    />
  </details>
  <div
    v-else
    class="source-row source-tree-file"
    :style="{ '--folder-depth': depth }"
  >
    <div class="source-icon"><Icon name="file" /></div>
    <div class="source-text">
      <h3 :title="node.source.title">{{ node.name }}</h3>
      <p>
        {{ sourceLabels[node.source.kind] }} ·
        {{ node.source.chunk_count }} 个分块 ·
        {{ dateLabel(node.source.created_at) }}
      </p>
      <span
        class="source-status"
        :class="{ degraded: node.source.embedding_status !== 'indexed' }"
        >{{
          node.source.embedding_status === "indexed"
            ? "混合检索已就绪"
            : "向量待建 · 文字检索可用"
        }}</span
      >
    </div>
    <button
      class="btn quiet"
      :disabled="!!w.s.busy"
      :aria-label="`查看 ${node.name}`"
      @click="w.openSource(node.source.source_id)"
    >
      查看
    </button>
  </div>
</template>
