<script setup lang="ts">
import { computed, ref } from "vue";
import type { Workspace } from "../workspace";
import { dateLabel, ratingLabels, statusLabels } from "../types";
import Icon from "./Icon.vue";
import InterviewTranscript from "./InterviewTranscript.vue";
import ExternalReviews from "./ExternalReviews.vue";
const props = defineProps<{ w: Workspace }>();
const reviewMode = ref(
  sessionStorage.getItem("mianshi.review.mode") || "simulation",
);
function selectReviewMode(mode: string) {
  reviewMode.value = mode;
  sessionStorage.setItem("mianshi.review.mode", mode);
}
const memoryAnswers = computed(() => props.w.s.session?.memory_answers || []);
const memoryPending = computed(() =>
  memoryAnswers.value.some(
    (item) => item.status === "queued" || item.status === "generating",
  ),
);
const memoryReady = computed(
  () => memoryAnswers.value.filter((item) => item.status === "ready").length,
);
const questionCount = computed(
  () =>
    props.w.s.session?.turns.filter((turn) => turn.speaker === "interviewer")
      .length || 0,
);
</script>
<template>
  <div class="page-head">
    <div class="head-copy">
      <h1>把这一场，变成下一步。</h1>
      <p>反馈只依据本场实际回答，未涉及的能力保持尚未测评。</p>
    </div>
    <button class="btn" @click="w.selectPage('interview')">
      {{ w.s.session?.status === "completed" ? "返回模拟面试" : "返回对话" }}
      <Icon name="arrow" />
    </button>
  </div>
  <div
    class="external-tabs review-mode-tabs"
    role="group"
    aria-label="复盘类型"
  >
    <button
      class="btn"
      :aria-pressed="reviewMode === 'simulation'"
      @click="selectReviewMode('simulation')"
    >
      模拟面试复盘
    </button>
    <button
      class="btn"
      :aria-pressed="reviewMode === 'external'"
      @click="selectReviewMode('external')"
    >
      真实面试复盘
    </button>
  </div>
  <ExternalReviews
    v-if="reviewMode === 'external'"
    :key="w.s.profileId"
    :w="w"
  />
  <template v-else>
    <div class="filter-row" v-if="w.s.history.length">
      <label for="review-history">练习记录</label
      ><select
        id="review-history"
        :value="w.s.session?.session_id"
        :disabled="!!w.s.busy"
        @change="w.openSession(($event.target as HTMLSelectElement).value)"
      >
        <option
          v-for="item in w.s.history"
          :key="item.session_id"
          :value="item.session_id"
        >
          {{ dateLabel(item.created_at) }} ·
          {{ item.focus || item.role_title }} ·
          {{ statusLabels[item.status] }}
        </option>
      </select>
    </div>
    <section
      v-if="w.s.session?.turns.length"
      class="review-transcript"
      aria-labelledby="review-transcript-title"
    >
      <div class="review-transcript-head">
        <h2 id="review-transcript-title">本轮问答</h2>
        <p>问题完整展示，点击回答可展开全文。</p>
        <div
          v-if="w.s.session.status === 'completed'"
          class="review-memory-actions"
        >
          <span v-if="memoryAnswers.length"
            >建议回答 {{ memoryReady }} / {{ questionCount }}</span
          >
          <button
            v-if="memoryReady < questionCount"
            type="button"
            class="btn"
            :disabled="!!w.s.busy || memoryPending"
            @click="w.generateMemoryAnswers"
          >
            {{
              memoryPending
                ? "正在生成建议回答…"
                : memoryAnswers.length
                  ? "重试未完成的建议回答"
                  : "生成本轮建议回答"
            }}
          </button>
        </div>
      </div>
      <div class="review-transcript-body">
        <InterviewTranscript
          :key="w.s.session.session_id"
          :turns="w.s.session.turns"
          :memory-answers="memoryAnswers"
          :show-memory-answers="w.s.session.status === 'completed'"
          @open-source="w.openSource"
        />
      </div>
    </section>
    <div v-if="!w.s.session?.review" class="empty-state">
      <Icon name="book" />
      <h2>完成一场面试后，复盘会出现在这里。</h2>
      <p>先练习回答，再发现值得改进和需要补证据的地方。</p>
      <button
        class="btn primary"
        @click="
          w.s.session ? w.selectPage('interview') : (w.s.drawer = 'setup')
        "
      >
        {{ w.s.session ? "继续当前面试" : "开始模拟面试" }}
      </button>
    </div>
    <template v-else>
      <div class="review-lead">
        <div>
          <div class="eyebrow">SESSION REVIEW</div>
          <h2>{{ w.s.session.review.summary }}</h2>
          <p>
            {{ w.currentRole.value?.title }} ·
            {{ dateLabel(w.s.session.created_at) }}
          </p>
        </div>
        <div class="review-duration">
          <div class="duration-item">
            <b>{{ w.s.session.prompt_count }}</b
            ><span>道提问与追问</span>
          </div>
          <div class="duration-item">
            <b>{{
              w.s.session.turns.filter(
                (t) => t.speaker === "candidate" && t.kind === "answer",
              ).length
            }}</b
            ><span>次实际回答</span>
          </div>
        </div>
      </div>
      <div class="dimensions">
        <div
          v-for="dimension in w.s.session.review.dimensions"
          :key="dimension.dimension"
          class="dimension"
        >
          <span class="label">{{ dimension.dimension }}</span
          ><b
            :class="
              dimension.rating === 'strong' ? 'rating-good' : 'rating-mixed'
            "
            >{{ ratingLabels[dimension.rating] || dimension.rating }}</b
          >
          <p>{{ dimension.advice }}</p>
        </div>
      </div>
      <div class="review-grid">
        <div class="review-detail">
          <h2>从你的回答出发</h2>
          <div
            v-for="(dimension, index) in w.s.session.review.dimensions"
            :key="dimension.dimension"
            class="review-entry"
          >
            <h3>
              {{ String(index + 1).padStart(2, "0") }} ·
              {{ dimension.dimension }}
            </h3>
            <div class="quote">回答依据：{{ dimension.evidence }}</div>
            <p>{{ dimension.advice }}</p>
          </div>
          <div class="review-entry" v-if="w.s.session.review.strengths.length">
            <h3>已经做得好的部分</h3>
            <ul>
              <li v-for="item in w.s.session.review.strengths" :key="item">
                {{ item }}
              </li>
            </ul>
          </div>
          <div
            class="review-entry"
            v-if="w.s.session.review.next_practice.length"
          >
            <h3>下一步练习</h3>
            <button
              v-for="topic in w.s.session.review.next_practice"
              :key="topic"
              class="practice-topic"
              :disabled="!!w.s.busy"
              @click="
                w.s.focus = topic;
                w.s.drawer = 'setup';
              "
            >
              {{ topic }} <Icon name="arrow" />
            </button>
          </div>
          <button class="inline-link" @click="w.s.drawer = 'sources'">
            查看本场关联材料 →
          </button>
          <div class="review-footer">
            <span>反馈保留本轮回答和材料依据。</span
            ><button class="btn primary" @click="w.s.drawer = 'setup'">
              开始下一轮 <Icon name="arrow" />
            </button>
          </div>
        </div>
        <aside class="review-side">
          <div class="section">
            <h3>学习缺口 · 来自回答</h3>
            <p
              v-if="!w.s.session.review.knowledge_gaps.length"
              class="empty-copy"
            >
              本轮没有记录明确的知识缺口。
            </p>
            <div
              v-for="gap in w.s.session.review.knowledge_gaps"
              :key="gap"
              class="practice-row"
            >
              <div>
                <b>{{ gap }}</b
                ><span>结合回答进一步理解</span>
              </div>
              <button
                class="small-action"
                :disabled="!!w.s.busy"
                @click="w.studyFromReview(gap)"
              >
                复习
              </button>
            </div>
          </div>
          <div class="section">
            <h3>资料缺口 · 来自证据</h3>
            <p
              v-if="!w.s.session.review.evidence_gaps.length"
              class="empty-copy"
            >
              本轮没有记录待补充的材料。
            </p>
            <div
              v-for="gap in w.s.session.review.evidence_gaps"
              :key="gap"
              class="practice-row"
            >
              <div>
                <b>{{ gap }}</b
                ><span>不据此判定知识不足</span>
              </div>
              <button class="small-action" @click="w.s.drawer = 'gap'">
                补充
              </button>
            </div>
          </div>
          <div class="notice">
            代码实现存在、用户个人贡献和项目效果，各自需要依据。
          </div>
        </aside>
      </div>
    </template>
  </template>
</template>
