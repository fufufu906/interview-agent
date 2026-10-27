<script setup lang="ts">
import { reactive, ref } from "vue";
import { publicDemo } from "../runtime";
import FolderIntake from "./FolderIntake.vue";
import type { Workspace } from "../workspace";
import type { SourceKind } from "../types";
const props = defineProps<{ w: Workspace }>();
const role = reactive({
  title: props.w.activeRole.value?.title || "",
  level: props.w.activeRole.value?.level || "",
  company: props.w.activeRole.value?.company || "",
  jd: props.w.activeRole.value?.jd_text || "",
  competencies: props.w.activeRole.value?.competencies.join("、") || "",
});
const upload = reactive({
  title: "",
  kind: "study_note" as SourceKind,
  text: "",
  origin: "",
  tab: "file",
});
const file = ref<File | null>(null),
  localError = ref("");
const gap = reactive({ text: "", title: "个人经历补充", origin: "" });
const profile = reactive({ id: "", name: "" });
async function saveRole() {
  await props.w.saveRole({
    title: role.title.trim(),
    level: role.level.trim(),
    company: role.company.trim(),
    jd_text: role.jd.trim(),
    competencies: role.competencies
      .split(/[、,，\n]/)
      .map((s) => s.trim())
      .filter(Boolean),
    activate: true,
  });
}
async function saveUpload() {
  localError.value = "";
  if (upload.tab === "folder") {
    return;
  }
  if (upload.tab === "file") {
    if (!file.value) {
      localError.value = "请先选择文件。";
      return;
    }
    if (file.value.size > (publicDemo.value ? 1_500_000 : 15 * 1024 * 1024)) {
      localError.value = publicDemo.value
        ? "演示版文件最大 1.5 MB。"
        : "文件超过 15 MB。";
      return;
    }
    const body = new FormData();
    body.append("file", file.value);
    body.append("kind", upload.kind);
    if (upload.title.trim()) body.append("title", upload.title.trim());
    await props.w.importSource(body);
  } else {
    await props.w.importSource({
      title: upload.title.trim(),
      kind: upload.kind,
      text: upload.text.trim(),
      origin_uri: upload.origin.trim(),
    });
  }
}
async function saveGap() {
  await props.w.importSource({
    kind: "confirmed_answer",
    title: gap.title.trim(),
    text: gap.text.trim(),
    origin_uri: gap.origin.trim(),
    metadata: { provenance: "user_declared", independently_verified: false },
  });
}
</script>
<template>
  <fieldset class="form-fields" :disabled="!!w.s.busy">
    <form
      v-if="w.s.drawer === 'setup'"
      @submit.prevent="
        w.s.mode === 'quick'
          ? w.startInterview()
          : ((w.s.studyTopic = w.s.focus), (w.s.drawer = ''), w.createStudy())
      "
    >
      <p class="empty-copy">选择岗位和练习主题，问题会围绕当前档案生成。</p>
      <label for="setup-role">目标岗位</label
      ><select
        id="setup-role"
        :value="w.activeRole.value?.role_target_id || ''"
        :disabled="!!w.s.busy"
        @change="w.activateRole(($event.target as HTMLSelectElement).value)"
      >
        <option value="" disabled>先补充岗位信息</option>
        <option
          v-for="r in w.s.roles"
          :key="r.role_target_id"
          :value="r.role_target_id"
        >
          {{ r.title }} {{ r.company }}
        </option></select
      ><button type="button" class="inline-link" @click="w.s.drawer = 'role'">
        补充或调整岗位 →
      </button>
      <label for="setup-focus">问题或本轮重点</label
      ><textarea
        id="setup-focus"
        v-model="w.s.focus"
        maxlength="1000"
        placeholder="例如：围绕任务恢复与业务幂等面试我"
      /><label for="setup-mode">模式</label
      ><select id="setup-mode" v-model="w.s.mode">
        <option value="quick">模拟面试 · 逐题提问</option>
        <option value="deep">深度复习 · 原理与项目证据</option></select
      ><template v-if="w.s.mode === 'quick'"
        ><label for="setup-rounds">提问数量（包含追问）</label
        ><select id="setup-rounds" v-model.number="w.s.maxPrompts">
          <option :value="3">3 道</option>
          <option :value="5">5 道</option>
          <option v-if="!publicDemo" :value="8">8 道</option>
          <option v-if="!publicDemo" :value="10">10 道</option></select
        ><label>反馈时机</label>
        <div class="notice">严格模拟 · 结束后统一复盘</div></template
      ><button
        class="btn primary"
        :disabled="
          !!w.s.busy ||
          !w.activeRole.value ||
          (w.s.mode === 'deep' && !w.s.focus.trim())
        "
      >
        {{ w.s.mode === "quick" ? "开始模拟面试" : "开始深度复习" }} →
      </button>
    </form>
    <form v-else-if="w.s.drawer === 'role'" @submit.prevent="saveRole">
      <p class="empty-copy">
        岗位信息决定题型与评价范围。保存后用于新面试；已有会话保持原岗位。
      </p>
      <label for="role-title">岗位名称</label
      ><input
        id="role-title"
        v-model="role.title"
        required
        maxlength="200"
        placeholder="例如：AI 应用平台开发 / 用户运营"
      /><label for="role-level">级别或招聘阶段</label
      ><input
        id="role-level"
        v-model="role.level"
        maxlength="100"
        placeholder="例如：2027 届校招"
      /><label for="role-company">公司（可选）</label
      ><input id="role-company" v-model="role.company" maxlength="200" /><label
        for="role-jd"
        >岗位 JD 或关键职责</label
      ><textarea
        id="role-jd"
        v-model="role.jd"
        required
        maxlength="100000"
        placeholder="粘贴岗位职责和任职要求…"
      /><label for="role-competencies">重点能力（可选，用顿号分隔）</label
      ><input
        id="role-competencies"
        v-model="role.competencies"
        placeholder="后端基础、系统设计、项目取舍"
      /><button
        class="btn primary"
        :disabled="!!w.s.busy || !role.title.trim() || !role.jd.trim()"
      >
        保存目标岗位
      </button>
    </form>
    <form v-else-if="w.s.drawer === 'upload'" @submit.prevent="saveUpload">
      <p class="empty-copy">资料会导入当前档案，保留原文与来源。</p>
      <div class="segmented">
        <button
          type="button"
          :aria-pressed="upload.tab === 'file'"
          @click="upload.tab = 'file'"
        >
          上传文件</button
        ><button
          type="button"
          :aria-pressed="upload.tab === 'text'"
          @click="upload.tab = 'text'"
        >
          粘贴正文</button
        ><button
          v-if="!publicDemo"
          type="button"
          :aria-pressed="upload.tab === 'folder'"
          @click="upload.tab = 'folder'"
        >
          文件夹地址
        </button>
      </div>
      <label for="upload-kind">资料类型</label
      ><select id="upload-kind" v-model="upload.kind">
        <option value="resume">简历</option>
        <option value="study_note">学习笔记</option>
        <option value="project_document">项目文档</option>
        <option value="external_reference">外部参考</option></select
      ><template v-if="upload.tab !== 'folder'"
        ><label for="upload-title">{{
          upload.tab === "text" ? "资料标题" : "资料标题（可选）"
        }}</label
        ><input
          id="upload-title"
          v-model="upload.title"
          :required="upload.tab === 'text'"
          maxlength="300"
          placeholder="留空时使用文件名" /></template
      ><template v-if="upload.tab === 'file'"
        ><label for="upload-file"
          >文件 · 最大 {{ publicDemo ? "1.5" : "15" }} MB</label
        ><input
          id="upload-file"
          type="file"
          required
          accept=".pdf,.txt,.md,.markdown,.rst,.json,.csv,.yaml,.yml"
          @change="
            file = ($event.target as HTMLInputElement).files?.[0] || null
          "
        />
        <p class="empty-copy">
          支持文本
          PDF、Markdown、TXT、RST、JSON、CSV、YAML；扫描件暂需转成文本。
        </p></template
      ><template v-else-if="upload.tab === 'text'"
        ><label for="upload-text">正文</label
        ><textarea
          id="upload-text"
          v-model="upload.text"
          required
          maxlength="2000000"
          placeholder="粘贴可检索的文档正文…"
        /><label for="upload-origin">来源链接或文档位置（可选）</label
        ><input id="upload-origin" v-model="upload.origin" maxlength="2048" />
        <p class="empty-copy">
          链接用于记录出处，本次导入的是你粘贴的正文。
        </p></template
      >
      <p v-if="localError" class="field-error" role="alert">{{ localError }}</p>
      <FolderIntake v-if="upload.tab === 'folder'" :w="w" :kind="upload.kind" />
      <button
        v-if="upload.tab !== 'folder'"
        class="btn primary"
        :disabled="
          !!w.s.busy ||
          (upload.tab === 'text' &&
            (!upload.title.trim() || !upload.text.trim()))
        "
      >
        导入并建立索引
      </button>
    </form>
    <form v-else-if="w.s.drawer === 'gap'" @submit.prevent="saveGap">
      <p class="empty-copy">
        写下你实际负责的工作、方案取舍或指标口径。保存为用户提供的经历说明，保留来源；未独立核实的内容不会标为已验证。
      </p>
      <label for="gap-title">说明标题</label
      ><input
        id="gap-title"
        v-model="gap.title"
        maxlength="300"
        required
      /><label for="gap-text">经历与依据</label
      ><textarea
        id="gap-text"
        v-model="gap.text"
        required
        maxlength="2000000"
        placeholder="例如：我独立负责的模块、测试环境、样本和指标口径…"
      /><label for="gap-origin">材料位置（可选）</label
      ><input id="gap-origin" v-model="gap.origin" maxlength="2048" /><button
        class="btn primary"
        :disabled="!!w.s.busy || !gap.text.trim()"
      >
        保存到当前档案
      </button>
    </form>
    <form
      v-else-if="w.s.drawer === 'profile'"
      @submit.prevent="w.createProfile(profile.id.trim(), profile.name.trim())"
    >
      <p class="empty-copy">
        每个人的资料、会话和复习记录分别保存。当前为本地个人使用。
      </p>
      <label for="profile-name">姓名或显示名称</label
      ><input
        id="profile-name"
        v-model="profile.name"
        required
        maxlength="120"
      /><label for="profile-id">档案编号</label
      ><input
        id="profile-id"
        v-model="profile.id"
        required
        pattern="[a-zA-Z0-9][a-zA-Z0-9_\-]{1,63}"
        maxlength="64"
        placeholder="例如：candidate_02"
      />
      <p class="empty-copy">
        2–64
        位英文字母、数字、下划线或短横线；从字母或数字开始。请使用新的编号。
      </p>
      <button
        class="btn primary"
        :disabled="!!w.s.busy || !profile.name.trim()"
      >
        创建独立档案
      </button>
    </form>
  </fieldset>
  <p v-if="w.s.busy" class="waiting" role="status">{{ w.s.busy }}</p>
  <p
    v-if="w.s.error && !(w.s.drawer === 'upload' && upload.tab === 'folder')"
    class="field-error"
    role="alert"
  >
    {{ w.s.error }}
  </p>
</template>
