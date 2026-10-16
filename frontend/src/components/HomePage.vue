<script setup lang="ts">
import { computed } from "vue";
import type { Workspace } from "../workspace";
import { dateLabel, sourceLabels, statusLabels } from "../types";
import Icon from "./Icon.vue";
const props = defineProps<{ w: Workspace }>();
const overview = computed(() => {
  const groups = new Map<
    string,
    {
      title: string;
      info: string;
      count: number;
      chunks: number;
      indexed: boolean;
      project: boolean;
    }
  >();
  for (const source of props.w.s.sources) {
    const project = source.kind === "project_repository",
      key = project ? source.title.split(" · ")[0]! : source.source_id;
    const previous = groups.get(key);
    if (previous) {
      previous.count++;
      previous.chunks += source.chunk_count;
      previous.indexed &&= source.embedding_status === "indexed";
    } else
      groups.set(key, {
        title: project ? key : source.title,
        info: sourceLabels[source.kind],
        count: 1,
        chunks: source.chunk_count,
        indexed: source.embedding_status === "indexed",
        project,
      });
  }
  return [...groups.values()]
    .sort((a, b) => Number(a.project) - Number(b.project))
    .slice(0, 4);
});
</script>
<template>
  <div class="page-head">
    <div class="head-copy">
      <div class="eyebrow" style="margin-bottom: 8px">YOUR NEXT SESSION</div>
      <h1>准备好了，就开始。</h1>
      <p>以你的资料为起点，练习真实、清晰、有依据的回答。</p>
    </div>
    <button class="btn" :disabled="!!w.s.busy" @click="w.s.drawer = 'setup'">
      配置一场面试
    </button>
  </div>
  <div v-if="!w.s.profileId" class="empty-state">
    <h2>建立你的个人知识档案</h2>
    <p>简历、岗位和练习记录都归属于各自档案。</p>
    <button class="btn primary" @click="w.s.drawer = 'profile'">
      创建档案
    </button>
  </div>
  <template v-else>
    <div class="home-hero">
      <div>
        <h2>今天，从一个问题<br />或一次技术取舍开始。</h2>
        <p>你想练习哪道题，或深入理解什么？</p>
        <form
          @submit.prevent="
            w.s.mode === 'quick'
              ? w.startInterview()
              : ((w.s.studyTopic = w.s.focus), w.createStudy())
          "
        >
          <input
            v-model="w.s.focus"
            class="topic-input"
            aria-label="练习主题"
            placeholder="例如：围绕 AutoDeepSearch 的任务恢复面试我"
            maxlength="1000"
          />
          <div class="mode-row">
            <label
              ><input
                v-model="w.s.mode"
                type="radio"
                value="quick"
              />模拟面试</label
            ><label
              ><input
                v-model="w.s.mode"
                type="radio"
                value="deep"
              />深度复习</label
            >
          </div>
          <div class="actions">
            <button
              class="btn primary"
              :disabled="
                !!w.s.busy || (w.s.mode === 'deep' && !w.s.focus.trim())
              "
              type="submit"
            >
              {{ w.s.mode === "quick" ? "开始模拟面试" : "开始深度复习" }}
              <Icon name="arrow" /></button
            ><button
              v-if="w.s.session?.status === 'awaiting_answer'"
              class="btn quiet"
              type="button"
              @click="w.selectPage('interview')"
            >
              继续上次面试
            </button>
          </div>
        </form>
      </div>
      <div class="role-summary">
        <div class="eyebrow">TARGET ROLE</div>
        <h3>{{ w.activeRole.value?.title || "尚未设置目标岗位" }}</h3>
        <div class="tags">
          <span
            v-for="c in w.activeRole.value?.competencies.slice(0, 5)"
            :key="c"
            class="tag"
            >{{ c }}</span
          >
        </div>
        <button
          class="inline-link"
          :disabled="!!w.s.busy"
          @click="w.s.drawer = 'role'"
        >
          {{ w.activeRole.value ? "调整目标岗位" : "补充岗位信息" }} →
        </button>
      </div>
    </div>
    <div class="overview-columns">
      <div>
        <div class="section-heading">
          <h2>你的资料</h2>
          <button class="inline-link" @click="w.selectPage('library')">
            查看全部 →
          </button>
        </div>
        <div v-if="!w.s.sources.length" class="notice">
          还没有资料。添加简历后，提问将能围绕你的经历展开。<button
            class="inline-link"
            @click="w.s.drawer = 'upload'"
          >
            添加资料 →
          </button>
        </div>
        <div v-for="source in overview" :key="source.title" class="source-row">
          <div class="source-icon">
            <Icon :name="source.project ? 'folder' : 'file'" />
          </div>
          <div class="source-text">
            <h3>{{ source.title }}</h3>
            <p>
              {{ source.project ? `${source.count} 个关键文件` : source.info }}
              · {{ source.chunks }} 个分块
            </p>
          </div>
          <span class="source-status" :class="{ degraded: !source.indexed }"
            ><i />{{ source.indexed ? "已索引" : "文字检索可用" }}</span
          >
        </div>
      </div>
      <aside class="gap-area">
        <h2>
          {{ w.s.session?.review ? "上次复盘的资料缺口" : "补充真实经历" }}
        </h2>
        <p class="gap-intro">资料不足与学习不足，分别记录依据。</p>
        <template v-if="w.s.session?.review"
          ><div
            v-for="gap in w.s.session.review.evidence_gaps"
            :key="gap"
            class="gap"
          >
            <h3>{{ gap }}</h3>
            <button class="inline-link" @click="w.s.drawer = 'gap'">
              补充依据 →
            </button>
          </div>
          <p v-if="!w.s.session.review.evidence_gaps.length" class="empty-copy">
            本轮没有记录待补充的材料。
          </p></template
        ><template v-else
          ><div class="gap">
            <h3>记录你的职责、取舍与验证过程</h3>
            <p>代码能支持实现事实，个人贡献和指标需要各自的依据。</p>
            <button class="inline-link" @click="w.s.drawer = 'gap'">
              补充经历说明 →
            </button>
          </div>
          <p class="empty-copy">尚未答题的能力保持“尚未测评”。</p></template
        >
      </aside>
    </div>
    <div class="bottom-summary">
      <div class="quiet-metrics">
        <span
          ><b>{{ w.s.sources.length }}</b
          >份资料</span
        ><span
          ><b>{{ w.s.sources.reduce((n, item) => n + item.chunk_count, 0) }}</b
          >个知识分块</span
        ><span
          ><b>{{ w.s.history.length }}</b
          >场面试</span
        >
      </div>
    </div>
    <div v-if="w.s.history.length" class="recent">
      <div class="section-heading"><h2>最近的练习</h2></div>
      <button
        v-for="item in w.s.history.slice(0, 3)"
        :key="item.session_id"
        class="history-row"
        :disabled="!!w.s.busy"
        @click="w.openSession(item.session_id)"
      >
        <div>
          <b>{{ item.focus || item.role_title }}</b
          ><span
            >{{ dateLabel(item.created_at) }} ·
            {{ item.prompt_count }} 道提问</span
          >
        </div>
        <span class="tag">{{ statusLabels[item.status] }}</span
        ><Icon name="arrow" />
      </button>
    </div>
  </template>
</template>
