<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import type { Workspace } from "../workspace";
import { dateLabel } from "../types";
import Icon from "./Icon.vue";
import InterviewTranscript from "./InterviewTranscript.vue";
const props = defineProps<{ w: Workspace }>();
const hasActiveSession = computed(
  () => props.w.s.session && props.w.s.session.status !== "completed",
);
const messages = ref<HTMLElement>();
watch(
  () => [props.w.s.session?.turns.length, props.w.s.busy],
  async () => {
    await nextTick();
    if (messages.value) messages.value.scrollTop = messages.value.scrollHeight;
  },
  { immediate: true },
);
</script>
<template>
  <div class="page-head">
    <div class="head-copy">
      <h1>把经历，说清楚。</h1>
      <p>一场围绕真实项目的面试，反馈在结束后统一给出。</p>
    </div>
    <div class="actions">
      <button
        class="btn quiet"
        :disabled="!!w.s.busy"
        @click="w.s.drawer = 'setup'"
      >
        面试设置</button
      ><button
        v-if="hasActiveSession"
        class="btn"
        :disabled="!!w.s.busy || w.s.session?.status !== 'awaiting_answer'"
        @click="w.finish"
      >
        结束并复盘
      </button>
    </div>
  </div>
  <div v-if="!hasActiveSession" class="empty-state interview-ready">
    <Icon name="chat" />
    <h2>
      {{
        w.s.session?.status === "completed"
          ? "本轮已完成，准备下一场。"
          : "开始你的第一场练习"
      }}
    </h2>
    <p>
      {{
        w.s.session?.status === "completed"
          ? "本轮回答与复盘已保存。调整岗位或主题，开始新一轮模拟面试。"
          : "选择目标岗位，输入问题或主题，让面试官逐题提问。"
      }}
    </p>
    <p v-if="w.s.busy" class="waiting" role="status">{{ w.s.busy }}</p>
    <div class="actions interview-ready-actions">
      <button
        class="btn primary"
        :disabled="!!w.s.busy"
        @click="w.s.drawer = 'setup'"
      >
        {{
          w.s.session?.status === "completed" ? "开始新一轮" : "配置一场面试"
        }}
        <Icon name="arrow" />
      </button>
      <button
        v-if="w.s.session?.review"
        class="btn quiet"
        :disabled="!!w.s.busy"
        @click="w.selectPage('review')"
      >
        查看上一轮复盘 <Icon name="arrow" />
      </button>
    </div>
  </div>
  <template v-else>
    <div class="stage-bar">
      <div>
        <div class="stage-title">
          {{ w.currentRole.value?.title || w.activeRole.value?.title }}
        </div>
        <div class="stage-meta">
          中文 · 严格模拟 ·
          {{ w.s.session ? dateLabel(w.s.session.created_at) : "准备中" }}
        </div>
      </div>
      <span v-if="w.s.session?.focus" class="tag ellipsis">{{
        w.s.session.focus
      }}</span>
      <div
        class="progress-dots"
        :aria-label="`第 ${w.s.session?.prompt_count || 0} 题`"
      >
        <i
          v-for="n in Math.min(w.s.session?.max_prompts || w.s.maxPrompts, 10)"
          :key="n"
          :class="{
            done: n < (w.s.session?.prompt_count || 0),
            current: n === w.s.session?.prompt_count,
          }"
        />
      </div>
      <span class="step"
        >{{ w.s.session?.prompt_count || 0 }} /
        {{ w.s.session?.max_prompts || w.s.maxPrompts }}</span
      >
    </div>
    <div class="interview-grid">
      <div class="conversation">
        <div class="conversation-head">
          <span class="status-dot" /><span>{{
            w.s.session?.status === "completed"
              ? "本场已结束"
              : w.s.session?.status === "error"
                ? "生成遇到问题"
                : "面试进行中"
          }}</span
          ><span style="margin-left: auto">结束后统一复盘</span>
        </div>
        <div
          ref="messages"
          class="message-list"
          role="log"
          aria-label="面试对话"
          aria-live="polite"
        >
          <InterviewTranscript
            :key="w.s.session?.session_id"
            :turns="w.s.session?.turns || []"
            :last-question-id="w.lastQuestion.value?.turn_id"
          />
          <p v-if="w.s.busy" class="waiting" role="status">{{ w.s.busy }}</p>
          <div
            v-else-if="w.s.session?.status === 'error'"
            class="notice error-notice"
          >
            <p>上次生成未完成，已保留对话。重试不会再次写入回答。</p>
            <button class="btn" @click="w.retry">重试生成</button>
          </div>
          <div v-else-if="w.s.session?.status === 'generating'" class="notice">
            服务正在生成内容，页面会自动同步状态。<button
              class="inline-link"
              @click="w.refreshSession"
            >
              刷新状态
            </button>
          </div>
        </div>
        <form class="composer" @submit.prevent="w.answer()">
          <div
            v-if="
              w.lastQuestion.value?.kind === 'clarification' &&
              w.s.session?.status === 'awaiting_answer'
            "
            class="notice clarification-notice"
          >
            <p>本题待补充，补充说明不占用新的提问次数。你也可以选择跳过。</p>
            <button
              type="button"
              class="inline-link"
              :disabled="!!w.s.busy || !!w.s.answer.trim()"
              @click="w.answer('skip')"
            >
              跳过本题 →
            </button>
          </div>
          <div class="composer-box">
            <textarea
              v-model="w.s.answer"
              aria-label="你的面试回答"
              placeholder="从你的思考过程开始回答…"
              maxlength="20000"
              :disabled="
                !!w.s.busy || w.s.session?.status !== 'awaiting_answer'
              "
              @keydown.ctrl.enter.prevent="w.answer()"
              @keydown.meta.enter.prevent="w.answer()"
            />
            <div class="composer-tools">
              <span>支持换行 · 输入不会自动发送</span
              ><span>{{ w.s.answer.length }} / 20000 字</span>
            </div>
          </div>
          <div class="composer-actions">
            <span class="small muted"
              ><span class="key">Ctrl</span> +
              <span class="key">Enter</span> 提交</span
            ><button
              class="btn primary"
              type="submit"
              :disabled="
                !w.s.answer.trim() ||
                !!w.s.busy ||
                w.s.session?.status !== 'awaiting_answer'
              "
            >
              {{
                w.lastQuestion.value?.kind === "clarification"
                  ? "提交补充"
                  : "提交回答"
              }}
              <Icon name="arrow" />
            </button>
          </div>
        </form>
      </div>
      <aside class="context">
        <div class="context-section">
          <div class="eyebrow">THIS SESSION</div>
          <h3 style="margin-top: 10px">本轮重点</h3>
          <p>
            {{
              w.s.session?.focus ||
              "围绕岗位要求和你的材料，练习清晰、有依据的回答。"
            }}
          </p>
          <div class="tags">
            <span
              v-for="c in w.currentRole.value?.competencies.slice(0, 4)"
              :key="c"
              class="tag"
              >{{ c }}</span
            >
          </div>
        </div>
        <div class="context-section">
          <h3>资料来源</h3>
          <p>先独立完成回答。面试期间仅展示本题关联材料的位置。</p>
          <button class="evidence-button" @click="w.s.drawer = 'sources'">
            查看来源位置 <Icon name="arrow" />
          </button>
          <div class="notice">代码片段与回答建议在复盘后查看。</div>
        </div>
        <button
          class="btn quiet"
          :disabled="!!w.s.busy"
          @click="w.refreshSession"
        >
          刷新会话状态
        </button>
      </aside>
    </div>
  </template>
</template>
