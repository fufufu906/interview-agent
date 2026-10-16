<script setup lang="ts">
import { computed } from "vue";
import type { Workspace } from "../workspace";
import { groupSourceFolders } from "../sourceTree";
import { sourceLabels, dateLabel } from "../types";
import Icon from "./Icon.vue";
import SourceTreeItem from "./SourceTreeItem.vue";
const props = defineProps<{ w: Workspace }>();
const tree = computed(() => groupSourceFolders(props.w.filteredSources.value));
</script>
<template>
  <div class="page-head">
    <div class="head-copy">
      <h1>资料与档案</h1>
      <p>每一段经历，都能回到它的来源。</p>
    </div>
    <button
      class="btn primary"
      :disabled="!!w.s.busy || !w.s.profileId"
      @click="w.s.drawer = 'upload'"
    >
      <Icon name="plus" />添加资料
    </button>
  </div>
  <div class="stage-bar">
    <div>
      <div class="stage-title">
        {{ w.profile.value?.display_name || "个人" }} · 个人知识档案
      </div>
      <div class="stage-meta">
        {{ w.s.sources.length }} 份资料 ·
        {{ w.s.sources.reduce((n, item) => n + item.chunk_count, 0) }}
        个知识分块
      </div>
    </div>
    <button
      class="btn quiet"
      style="margin-left: auto"
      :disabled="!!w.s.busy"
      @click="w.s.drawer = 'role'"
    >
      目标岗位 <Icon name="arrow" />
    </button>
  </div>
  <div class="overview-columns">
    <div>
      <div class="filter-row">
        <input
          v-model="w.s.sourceQuery"
          aria-label="搜索资料"
          placeholder="搜索名称…"
        /><select v-model="w.s.sourceKind" aria-label="资料类型筛选">
          <option value="">全部类型</option>
          <option
            v-for="(label, kind) in sourceLabels"
            :key="kind"
            :value="kind"
          >
            {{ label }}
          </option>
        </select>
      </div>
      <p v-if="!w.filteredSources.value.length" class="empty-copy">
        {{
          w.s.sources.length
            ? "没有匹配的资料。"
            : "添加简历、学习笔记或项目材料，开始构建档案。"
        }}
      </p>
      <p v-if="tree.folders.length" class="source-tree-hint">
        按导入时的目录显示 · 仅包含已入库文件
      </p>
      <div
        v-for="folder in tree.folders"
        :key="`${w.s.profileId}:${folder.key}`"
        class="source-folder-group"
      >
        <SourceTreeItem
          :node="folder"
          :w="w"
          :depth="0"
          :searching="!!w.s.sourceQuery.trim() || !!w.s.sourceKind"
        />
      </div>
      <div
        v-for="source in tree.standalone"
        :key="source.source_id"
        class="source-row"
      >
        <div class="source-icon">
          <Icon
            :name="source.kind === 'project_repository' ? 'folder' : 'file'"
          />
        </div>
        <div class="source-text">
          <h3>{{ source.title }}</h3>
          <p>
            {{ sourceLabels[source.kind] }} · {{ source.chunk_count }} 个分块 ·
            {{ dateLabel(source.created_at) }}
          </p>
          <span
            class="source-status"
            :class="{ degraded: source.embedding_status !== 'indexed' }"
            >{{
              source.embedding_status === "indexed"
                ? "混合检索已就绪"
                : "向量待建 · 文字检索可用"
            }}</span
          >
        </div>
        <button
          class="btn quiet"
          :disabled="!!w.s.busy"
          @click="w.openSource(source.source_id)"
        >
          查看
        </button>
      </div>
    </div>
    <aside class="gap-area">
      <h2>档案中的信息状态</h2>
      <div class="gap">
        <h3>用户提供</h3>
        <p>简历或你明确陈述的个人经历。</p>
      </div>
      <div class="gap">
        <h3>代码可见</h3>
        <p>该版本存在的实现，可定位到文件和行号。</p>
      </div>
      <div class="gap">
        <h3>待确认</h3>
        <p>贡献边界、项目效果或缺少材料的指标。</p>
      </div>
      <p class="gap-intro" style="margin-top: 18px">
        通用原理解释单独标注，不写成个人经历。
      </p>
      <button
        class="btn"
        :disabled="!!w.s.busy || !w.s.profileId"
        @click="w.reindex"
      >
        重建缺失向量
      </button>
    </aside>
  </div>
</template>
