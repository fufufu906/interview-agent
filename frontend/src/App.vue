<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from "vue";
import { createWorkspace } from "./workspace";
import { publicDemo } from "./runtime";
import { locatorLabel } from "./types";
import type { Page } from "./types";
import Icon from "./components/Icon.vue";
import Drawer from "./components/Drawer.vue";
import IntakeForms from "./components/IntakeForms.vue";
import HomePage from "./components/HomePage.vue";
import InterviewPage from "./components/InterviewPage.vue";
import LibraryPage from "./components/LibraryPage.vue";
import ReviewPage from "./components/ReviewPage.vue";
import StudyPage from "./components/StudyPage.vue";
const w = createWorkspace(),
  { s, profile } = w;
const pages: { id: Page; name: string; icon: string }[] = [
  { id: "home", name: "工作台", icon: "grid" },
  { id: "interview", name: "模拟面试", icon: "chat" },
  { id: "deep", name: "深度复习", icon: "book" },
  { id: "library", name: "资料与档案", icon: "folder" },
  { id: "review", name: "面试复盘", icon: "book" },
];
const drawerTitles = {
  setup: "配置练习",
  role: "目标岗位",
  upload: "添加资料",
  gap: "补充经历依据",
  profile: "创建个人档案",
  sources: "关联资料来源",
  detail: "资料原文",
};
const title = computed(() => pages.find((p) => p.id === s.page)?.name);
const evidence = computed(() => {
  const list =
    s.session?.status === "completed"
      ? s.session.turns.flatMap((t) => t.evidence)
      : w.lastQuestion.value?.evidence || [];
  return [...new Map(list.map((item) => [item.chunk_id, item])).values()];
});
function hashChange() {
  const page = location.hash.slice(1) as Page;
  if (pages.some((p) => p.id === page)) s.page = page;
}
onMounted(() => {
  hashChange();
  window.addEventListener("hashchange", hashChange);
  void w.load();
  w.startPolling();
});
onBeforeUnmount(() => {
  window.removeEventListener("hashchange", hashChange);
  w.dispose();
});
function beforeUnload(e: BeforeUnloadEvent) {
  if (s.answer.trim() || s.busy) {
    e.preventDefault();
    e.returnValue = "";
  }
}
window.addEventListener("beforeunload", beforeUnload);
onBeforeUnmount(() => window.removeEventListener("beforeunload", beforeUnload));
</script>
<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark"><Icon name="chat" /></div>
        <span>Interview Agent</span>
      </div>
      <div class="nav-label">PERSONAL WORKSPACE</div>
      <nav class="nav" aria-label="主要页面">
        <button
          v-for="page in pages"
          :key="page.id"
          :aria-label="page.name"
          :aria-current="s.page === page.id ? 'page' : undefined"
          @click="w.selectPage(page.id)"
        >
          <Icon :name="page.icon" /><span class="nav-text">{{ page.name }}</span
          ><span v-if="page.id === 'library'" class="count">{{
            s.sources.length
          }}</span>
          <span class="nav-tooltip" aria-hidden="true">{{ page.name }}</span>
        </button>
      </nav>
      <div class="sidebar-bottom">
        <div class="shortcut">基于你的经历，<br />练习更好的回答。</div>
        <div class="profile">
          <div class="avatar">
            {{ profile?.display_name.slice(0, 1) || "你" }}
            <select
              class="compact-profile-select"
              aria-label="切换个人档案"
              :title="profile?.display_name || '切换个人档案'"
              :value="s.profileId"
              :disabled="!!s.busy || s.loading"
              @change="
                w.changeProfile(($event.target as HTMLSelectElement).value)
              "
            >
              <option v-if="!s.profiles.length" value="">尚无档案</option>
              <option
                v-for="p in s.profiles"
                :key="p.profile_id"
                :value="p.profile_id"
              >
                {{ p.display_name }}
              </option>
            </select>
          </div>
          <div class="profile-details">
            <label class="sr-only" for="profile-select">当前个人档案</label
            ><select
              id="profile-select"
              class="profile-select"
              :value="s.profileId"
              :disabled="!!s.busy || s.loading"
              @change="
                w.changeProfile(($event.target as HTMLSelectElement).value)
              "
            >
              <option v-if="!s.profiles.length" value="">尚无档案</option>
              <option
                v-for="p in s.profiles"
                :key="p.profile_id"
                :value="p.profile_id"
              >
                {{ p.display_name }}
              </option>
            </select>
            <div class="profile-type">
              <i class="local" />{{
                publicDemo ? "独立访客体验" : "本地个人工作区"
              }}
            </div>
          </div>
        </div>
        <button
          v-if="!publicDemo"
          class="new-profile"
          :disabled="!!s.busy || !!s.answer.trim()"
          aria-label="添加个人档案"
          @click="s.drawer = 'profile'"
        >
          <Icon name="plus" /><span>添加个人档案</span>
        </button>
      </div>
    </aside>
    <main class="main">
      <header class="topbar">
        <div class="crumb">
          个人工作区<span>/</span><b>{{ title }}</b>
        </div>
        <span class="connection"
          ><i class="local" />{{
            s.loading
              ? "正在连接"
              : s.profiles.length
                ? publicDemo
                  ? "访客档案"
                  : "本地档案"
                : "等待建档"
          }}</span
        >
      </header>
      <div class="content">
        <div v-if="s.error" class="banner" role="alert">
          <span>{{ s.error }}</span
          ><button
            class="inline-link"
            :disabled="!!s.busy || s.loading"
            @click="w.load"
          >
            重新连接</button
          ><button
            class="icon-btn"
            aria-label="关闭错误提示"
            @click="s.error = ''"
          >
            <Icon name="close" />
          </button>
        </div>
        <div v-if="s.loading" class="empty-state" role="status">
          <h2>正在读取你的工作区…</h2>
          <p>加载档案、岗位、资料与练习记录。</p>
        </div>
        <template v-else
          ><HomePage v-if="s.page === 'home'" :w="w" /><InterviewPage
            v-else-if="s.page === 'interview'"
            :w="w" /><LibraryPage
            v-else-if="s.page === 'library'"
            :w="w" /><ReviewPage
            v-else-if="s.page === 'review'"
            :w="w" /><StudyPage v-else :w="w"
        /></template>
      </div>
    </main>
  </div>
  <Drawer
    :open="!!s.drawer"
    :title="s.drawer ? drawerTitles[s.drawer] : ''"
    :busy="!!s.busy"
    @close="
      s.drawer = '';
      s.error = '';
    "
  >
    <template v-if="s.drawer === 'sources'"
      ><p class="empty-copy">
        {{
          s.session?.status === "completed"
            ? "本场提问关联的材料，保留原文定位。"
            : "严格模拟期间仅展示来源位置。原文与回答建议留到复盘后查看。"
        }}
      </p>
      <div
        v-for="item in evidence"
        :key="item.chunk_id"
        class="evidence-record"
      >
        <h3>{{ item.source_title }}</h3>
        <p>{{ locatorLabel(item.locator) }}</p>
        <template v-if="s.session?.status === 'completed'"
          ><p class="source-excerpt">{{ item.excerpt }}</p>
          <button
            class="inline-link"
            :disabled="!!s.busy"
            @click="w.openSource(item.source_id)"
          >
            查看原文 →
          </button></template
        >
      </div>
      <p v-if="!evidence.length" class="empty-copy">
        本题没有关联个人材料；涉及通用原理时，不需要先上传教材。
      </p>
      <div class="notice">
        材料中的实现不能自动证明个人贡献或项目效果。
      </div></template
    >
    <template v-else-if="s.drawer === 'detail' && s.detail"
      ><h3 class="detail-title">{{ s.detail.title }}</h3>
      <p class="empty-copy">
        来源：{{ s.detail.origin_uri || "用户提供正文" }}
      </p>
      <p class="small muted">
        版本哈希：{{ s.detail.content_hash.slice(0, 16) }}
      </p>
      <div class="notice">
        这是已导入的资料快照。代码可见与个人贡献分别核实。
      </div>
      <details v-if="Object.keys(s.detail.metadata).length" class="metadata">
        <summary>来源与版本信息</summary>
        <pre>{{ JSON.stringify(s.detail.metadata, null, 2) }}</pre>
      </details>
      <div
        v-for="chunk in s.detail.chunks"
        :key="chunk.chunk_id"
        class="evidence-record"
      >
        <p>{{ locatorLabel(chunk.locator) }}</p>
        <pre class="source-content">{{ chunk.text }}</pre>
      </div></template
    >
    <IntakeForms v-else-if="s.drawer" :key="s.drawer" :w="w" />
  </Drawer>
  <div class="toast" :class="{ open: !!s.notification }" role="status">
    <Icon name="check" /><span>{{ s.notification }}</span>
  </div>
</template>
