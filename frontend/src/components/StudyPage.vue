<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { Workspace } from "../workspace";
import type { Study } from "../types";
import { dateLabel, locatorLabel } from "../types";
import Icon from "./Icon.vue";
const props = defineProps<{ w: Workspace }>();
const studyInput = ref<HTMLTextAreaElement | null>(null);
const historyDetails = ref<HTMLDetailsElement | null>(null);

function resizeStudyInput() {
  const input = studyInput.value;
  if (!input) return;
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight + 2, 220)}px`;
}
watch(() => props.w.s.studyTopic, resizeStudyInput, { flush: "post" });
onMounted(() => {
  resizeStudyInput();
  window.addEventListener("resize", resizeStudyInput);
});
onBeforeUnmount(() => window.removeEventListener("resize", resizeStudyInput));

async function selectSavedStudy(study: Study) {
  props.w.s.study = study;
  if (historyDetails.value) historyDetails.value.open = false;
  await nextTick();
  historyDetails.value?.querySelector("summary")?.focus({ preventScroll: true });
}

async function prepareNextStudy(question: string) {
  props.w.s.studyTopic = question;
  await nextTick();
  studyInput.value?.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}
</script>
<template>
  <div class="page-head">
    <div class="head-copy">
      <h1>把问题，理解透。</h1>
      <p>从原理到项目证据，留下能够继续练习的答案。</p>
    </div>
  </div>
  <form class="study-form" @submit.prevent="w.createStudy()">
    <label class="study-input-label" for="study-topic">下一次复习</label>
    <textarea
      id="study-topic"
      ref="studyInput"
      v-model="w.s.studyTopic"
      rows="2"
      aria-label="深度复习主题"
      placeholder="输入一道问题或知识点，例如：事务边界与部分提交"
      maxlength="2000"
    />
    <div class="study-form-actions">
      <span>写下问题，也可以补充你想弄清楚的细节。</span>
      <button
        class="btn primary"
        :disabled="!w.s.studyTopic.trim() || !!w.s.busy"
      >
        开始复习 <Icon name="arrow" />
      </button>
    </div>
  </form>
  <p v-if="w.s.busy" class="waiting" role="status">{{ w.s.busy }}</p>
  <details v-if="w.s.studies.length" ref="historyDetails" class="study-history">
    <summary>
      <span class="study-history-label">复习记录</span>
      <span class="study-history-current">
        {{
          w.s.study
            ? `当前 · ${dateLabel(w.s.study.created_at)}`
            : "选择已保存的复习"
        }}
      </span>
      <span class="disclosure-count">{{ w.s.studies.length }} 条</span>
    </summary>
    <div class="study-history-list" role="group" aria-label="已保存的复习">
      <button
        v-for="item in w.s.studies"
        :key="item.study_id"
        type="button"
        class="study-history-item"
        :aria-current="item.study_id === w.s.study?.study_id ? 'true' : undefined"
        :disabled="!!w.s.busy"
        @click="selectSavedStudy(item)"
      >
        <span class="study-history-copy">
          <span class="study-history-date">{{ dateLabel(item.created_at) }}</span>
          <span class="study-history-topic">{{ item.topic }}</span>
        </span>
        <span
          v-if="item.study_id === w.s.study?.study_id"
          class="study-history-selected"
        >
          <Icon name="check" /><span class="sr-only">当前记录</span>
        </span>
      </button>
    </div>
  </details>
  <div v-if="!w.s.study && !w.s.busy" class="empty-state">
    <Icon name="book" />
    <h2>从一个具体问题开始。</h2>
    <p>通用原理无需先上传教材。涉及你的项目时，系统会检索材料并保留来源。</p>
  </div>
  <div v-if="w.s.study" class="study-grid">
    <article>
      <div class="eyebrow">
        STUDY NOTE · {{ dateLabel(w.s.study.created_at) }}
      </div>
      <h2 class="study-title">{{ w.s.study.topic }}</h2>
      <div class="study-short">
        <h3>先练习这个短答</h3>
        <p>{{ w.s.study.short_answer }}</p>
        <span class="small muted">通用原理短答 · 模型解释</span>
      </div>
      <div
        class="study-section"
        v-for="(section, index) in w.s.study.sections"
        :key="index"
      >
        <div class="section-heading">
          <h2>{{ section.title }}</h2>
          <span class="tag">{{
            section.basis === "user_material"
              ? "基于用户材料"
              : "通用知识 · 模型解释"
          }}</span>
        </div>
        <p>{{ section.content }}</p>
        <div v-if="section.citations.length" class="citation-list">
          <button
            v-for="id in section.citations"
            :key="id"
            class="inline-link"
            :disabled="!!w.s.busy"
            @click="
              w.openSource(
                w.s.study.evidence.find((e) => e.chunk_id === id)!.source_id,
              )
            "
          >
            {{
              w.s.study.evidence.find((e) => e.chunk_id === id)?.source_title
            }}
            ·
            {{
              locatorLabel(
                w.s.study.evidence.find((e) => e.chunk_id === id)?.locator ||
                  {},
              )
            }}
            →
          </button>
        </div>
      </div>
      <div v-if="w.s.study.follow_up_questions.length" class="study-section">
        <h2>继续练习</h2>
        <button
          class="practice-topic"
          v-for="q in w.s.study.follow_up_questions"
          :key="q"
          :disabled="!!w.s.busy"
          @click="prepareNextStudy(q)"
        >
          {{ q }} <Icon name="arrow" />
        </button>
      </div>
    </article>
    <aside class="review-side">
      <div class="section">
        <h3>问题拆解</h3>
        <ol class="deep-outline">
          <li v-for="q in w.s.study.plan" :key="q">{{ q }}</li>
        </ol>
      </div>
      <details
        :key="`sources-${w.s.study.study_id}`"
        class="section study-disclosure"
      >
        <summary>
          <span>关联资料</span>
          <span class="disclosure-count">{{ w.s.study.evidence.length }} 条</span>
        </summary>
        <div class="disclosure-content">
          <div
            v-for="e in w.s.study.evidence"
            :key="e.chunk_id"
            class="evidence-record"
          >
            <h3>{{ e.source_title }}</h3>
            <p>{{ locatorLabel(e.locator) }}</p>
            <button
              class="inline-link"
              :disabled="!!w.s.busy"
              @click="w.openSource(e.source_id)"
            >
              查看原文 →
            </button>
          </div>
          <p v-if="!w.s.study.evidence.length" class="empty-copy">
            本次未检索到个人材料，解释以通用知识为主。
          </p>
          <div
            class="notice"
            v-if="w.s.study.diagnostics.embedding_status === 'unavailable'"
          >
            向量服务不可用，本次使用文字与关联资料检索。
          </div>
        </div>
      </details>
      <details
        :key="`gaps-${w.s.study.study_id}`"
        class="section study-disclosure"
      >
        <summary>
          <span>资料缺口</span>
          <span class="disclosure-count">
            {{ w.s.study.evidence_gaps.length }} 项
          </span>
        </summary>
        <div class="disclosure-content">
          <p class="empty-copy" v-if="!w.s.study.evidence_gaps.length">
            没有记录需要补充的依据。
          </p>
          <div v-for="gap in w.s.study.evidence_gaps" :key="gap" class="gap">
            <p>{{ gap }}</p>
            <button class="inline-link" @click="w.s.drawer = 'gap'">
              补充 →
            </button>
          </div>
        </div>
      </details>
      <div class="section">
        <h3>学习缺口</h3>
        <p class="empty-copy" v-if="!w.s.study.knowledge_gaps.length">
          没有实际回答依据时，不判定知识不足。
        </p>
        <p
          v-for="gap in w.s.study.knowledge_gaps"
          :key="gap"
          class="empty-copy"
        >
          {{ gap }}
        </p>
      </div>
      <div class="notice">
        通用解释尚未联网核验。个人材料引用保留定位，不能据此推断你的职责或项目指标。
      </div>
    </aside>
  </div>
</template>
