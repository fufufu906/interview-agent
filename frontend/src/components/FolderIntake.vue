<script setup lang="ts">
import { nextTick, reactive, ref, watch } from "vue";
import type { FolderImportProgress } from "../folderImport";
import type { Workspace } from "../workspace";
import type { SourceKind, FolderScan, FolderImportResult } from "../types";
const props = defineProps<{ w: Workspace; kind: SourceKind }>();
const folder = reactive({ path: "", focus: "", selected: [] as string[] });
const scan = ref<FolderScan | null>(null);
const result = ref<FolderImportResult | null>(null);
const localError = ref("");
const progress = ref<FolderImportProgress | null>(null);
const progressPanel = ref<HTMLElement>();
watch(
  () => [folder.path, folder.focus],
  () => {
    scan.value = null;
    result.value = null;
    progress.value = null;
    localError.value = "";
    folder.selected = [];
  },
);
async function scanFolder() {
  localError.value = "";
  scan.value = null;
  result.value = null;
  progress.value = null;
  folder.selected = [];
  scan.value = await props.w.scanFolder(
    folder.path.trim(),
    folder.focus.trim(),
  );
  if (!scan.value) localError.value = props.w.s.error;
  folder.selected =
    scan.value?.files.filter((f) => f.recommended).map((f) => f.file_id) || [];
}
async function importFolder() {
  if (!scan.value || !folder.selected.length) return;
  localError.value = "";
  result.value = null;
  progress.value = null;
  const selected = new Set(folder.selected);
  result.value = await props.w.importFolder(
    scan.value.scan_id,
    scan.value.files.filter((file) => selected.has(file.file_id)),
    props.kind,
    (update) => {
      const firstUpdate = progress.value === null;
      progress.value = update;
      if (firstUpdate)
        void nextTick(() =>
          progressPanel.value?.scrollIntoView({ block: "nearest" }),
        );
    },
  );
  localError.value = props.w.s.error;
  if (result.value) {
    const successful = new Set(
      result.value.files
        .filter((f) => f.status === "imported")
        .map((f) => f.file_id),
    );
    folder.selected = folder.selected.filter((id) => !successful.has(id));
  }
}
</script>
<template>
  <label for="folder-path">本机文件夹地址</label>
  <input
    id="folder-path"
    v-model="folder.path"
    maxlength="2048"
    placeholder="例如 E:\学习资料 或 E:\java-ai-xiaozhiyiliao"
    spellcheck="false"
    @keydown.enter.prevent="folder.path.trim() && scanFolder()"
  />
  <p class="empty-copy folder-hint">
    复制文件夹的完整地址。递归读取文档和 Python、Java、JS/TS、Vue
    代码；原文件保持只读。
  </p>
  <label for="folder-focus">扫描重点（可选）</label>
  <textarea
    id="folder-focus"
    v-model="folder.focus"
    maxlength="1000"
    placeholder="例如：重点看任务恢复、并发控制和后端架构；留空时参考当前岗位与简历。"
  />
  <button
    class="btn secondary"
    type="button"
    :disabled="!!w.s.busy || !folder.path.trim()"
    @click="scanFolder"
  >
    {{ scan ? "重新扫描" : "扫描并推荐文件" }}
  </button>
  <p v-if="localError" class="field-error" role="alert">{{ localError }}</p>
  <section
    v-if="scan"
    class="folder-scan"
    aria-label="文件夹扫描结果"
    aria-live="polite"
  >
    <div class="folder-scan-heading">
      <strong>{{ scan.files.length }} 个可导入文件</strong
      ><span>已选 {{ folder.selected.length }} 个</span>
    </div>
    <p class="empty-copy folder-hint">
      {{
        scan.model_status === "recommended"
          ? "模型已根据文件摘录推荐，可调整勾选。导入保留完整原文。"
          : scan.model_status === "unavailable"
            ? "请手动勾选需要导入的文件。"
            : "未找到可导入文件，请选择其他文件夹。"
      }}
    </p>
    <p v-for="warning in scan.warnings" :key="warning" class="folder-warning">
      {{ warning }}
    </p>
    <p class="empty-copy folder-hint">
      忽略依赖、构建目录、隐藏文件和常见凭据文件。每次最多 100 个文件、20
      MB；扫描结果保留 30 分钟。
    </p>
    <div v-if="scan.files.length" class="folder-selection-actions">
      <button
        type="button"
        class="inline-link"
        @click="folder.selected = scan.files.map((f) => f.file_id)"
      >
        全选
      </button>
      <button type="button" class="inline-link" @click="folder.selected = []">
        清空
      </button>
      <button
        v-if="scan.model_status === 'recommended'"
        type="button"
        class="inline-link"
        @click="
          folder.selected = scan.files
            .filter((f) => f.recommended)
            .map((f) => f.file_id)
        "
      >
        采用推荐
      </button>
    </div>
    <div class="folder-file-list">
      <label v-for="item in scan.files" :key="item.file_id" class="folder-file">
        <input
          v-model="folder.selected"
          type="checkbox"
          :value="item.file_id"
        />
        <span
          ><strong>{{ item.path }}</strong
          ><small
            >{{ item.reason }} ·
            {{ Math.max(1, Math.round(item.bytes / 1024)) }} KB</small
          ></span
        >
      </label>
    </div>
  </section>
  <section
    v-if="result && result.files.length"
    class="folder-result"
    aria-live="polite"
    aria-label="文件夹导入结果"
  >
    <strong
      >已导入 {{ result.imported }} 个文件<span v-if="result.failed"
        >，{{ result.failed }} 个失败</span
      ></strong
    >
    <p class="empty-copy folder-hint">
      新资料已加入当前档案，可在深度复习中检索。相同内容会自动去重。
    </p>
    <p
      v-if="result.files.some((f) => f.source?.embedding_status === 'degraded')"
      class="folder-warning"
    >
      部分正文已保存，向量暂未完成，可使用文字检索，之后重建向量。
    </p>
    <p
      v-for="item in result.files.filter((f) => f.status === 'failed')"
      :key="item.file_id"
      class="folder-warning"
    >
      {{ item.path }}：{{ item.error }}
    </p>
    <button class="inline-link" type="button" @click="w.s.drawer = 'sources'">
      查看资料库 →
    </button>
  </section>
  <button
    type="button"
    class="btn primary"
    :disabled="!!w.s.busy || !scan || !folder.selected.length"
    @click="importFolder"
  >
    {{
      progress?.status === "running"
        ? "正在导入…"
        : `导入所选 ${folder.selected.length} 个文件`
    }}
  </button>
  <section
    v-if="progress"
    ref="progressPanel"
    class="folder-progress"
    :class="{ 'is-running': progress.status === 'running' }"
    aria-label="文件导入进度"
    aria-live="polite"
    aria-atomic="true"
  >
    <div class="folder-progress-heading">
      <strong>{{
        progress.status === "running"
          ? "正在导入并建立索引"
          : progress.status === "interrupted"
            ? "导入已中断"
            : "本批次处理结束"
      }}</strong>
      <span
        >{{
          Math.floor((progress.completed * 100) / Math.max(progress.total, 1))
        }}%</span
      >
    </div>
    <progress
      :value="progress.completed"
      :max="Math.max(progress.total, 1)"
      aria-label="已处理文件数"
    />
    <p class="folder-progress-count">
      已处理 {{ progress.completed }} / {{ progress.total }} 个文件 · 成功
      {{ progress.imported }} · 失败 {{ progress.failed }}
    </p>
    <p v-if="progress.currentFile" class="folder-progress-file">
      {{ progress.status === "interrupted" ? "停在：" : "正在处理："
      }}{{ progress.currentFile }}
    </p>
    <p v-if="progress.status === 'running'" class="folder-hint">
      按文件完成情况更新；大文件建立向量索引时可能停留一段时间，请保持页面打开。
    </p>
    <p v-if="progress.status === 'interrupted'" class="folder-hint">
      已完成资料已保留。检查提示后可重试剩余文件；若扫描过期，请重新扫描。
    </p>
    <p
      v-if="progress.status === 'completed' && progress.failed"
      class="folder-hint"
    >
      失败文件仍保留勾选，可重试或重新扫描。
    </p>
  </section>
</template>
