<script setup lang="ts">
import { computed } from "vue";
import {
  dateLabel,
  locatorLabel,
  type Turn,
  type MemoryAnswer,
} from "../types";
import Icon from "./Icon.vue";

const props = defineProps<{
  turns: Turn[];
  lastQuestionId?: string;
  memoryAnswers?: MemoryAnswer[];
  showMemoryAnswers?: boolean;
}>();
defineEmits<{ "open-source": [sourceId: string] }>();
const memoryByQuestion = computed(
  () =>
    new Map(
      (props.memoryAnswers || []).map((item) => [item.question_turn_id, item]),
    ),
);
function memoryPreview(questionId: string) {
  const memory = memoryByQuestion.value.get(questionId);
  if (memory?.status === "ready" && memory.content) {
    return memory.content.answer.trim().replace(/\s+/g, " ").slice(0, 120);
  }
  if (memory?.status === "queued") return "等待生成…";
  if (memory?.status === "generating") return "正在结合长短期记忆生成…";
  if (memory?.status === "error") return "生成失败，可重试未完成项";
  return "尚未生成，点击上方“生成本轮建议回答”";
}
const basisLabels = {
  user_material: "结合资料的参考回答",
  general_knowledge: "通用原理参考",
  insufficient_evidence: "资料不足，保守回答框架",
};
const questionGroups = computed(() => {
  const groups: { key: string; question: Turn | null; replies: Turn[] }[] = [];
  for (const turn of props.turns) {
    if (turn.speaker === "interviewer") {
      groups.push({ key: turn.turn_id, question: turn, replies: [] });
    } else {
      let group = groups.at(-1);
      if (!group) {
        group = { key: turn.turn_id, question: null, replies: [] };
        groups.push(group);
      }
      group.replies.push(turn);
    }
  }
  return groups;
});
</script>

<template>
  <div v-for="group in questionGroups" :key="group.key" class="message">
    <div v-if="group.question" class="message-avatar">AI</div>
    <div class="question-content">
      <template v-if="group.question">
        <div class="message-person">
          面试官<span>
            {{
              group.question.kind === "follow_up"
                ? "追问"
                : group.question.kind === "clarification"
                  ? "要求补充"
                  : "提问"
            }}
            · {{ dateLabel(group.question.created_at) }}
          </span>
        </div>
        <p
          :class="
            group.question.turn_id === lastQuestionId
              ? 'question-emphasis'
              : 'message-body'
          "
        >
          {{ group.question.content }}
        </p>
      </template>
      <div v-if="group.replies.length" class="question-replies">
        <div
          v-for="turn in group.replies"
          :key="turn.turn_id"
          class="message candidate"
        >
          <details class="answer-disclosure">
            <summary class="answer-summary">
              <span class="answer-label">{{
                turn.kind === "skip" ? "已跳过" : "你的回答"
              }}</span>
              <span class="answer-preview">{{
                turn.content.trim().replace(/\s+/g, " ").slice(0, 120)
              }}</span>
              <span class="answer-toggle">
                <span class="answer-expand">展开</span>
                <span class="answer-collapse">收起</span>
                <Icon name="arrow" />
              </span>
            </summary>
            <div class="answer-content">
              <div class="message-person">
                你<span>
                  {{ turn.kind === "skip" ? "跳过" : "回答" }} ·
                  {{ dateLabel(turn.created_at) }}
                </span>
              </div>
              <p class="message-body">{{ turn.content }}</p>
            </div>
          </details>
        </div>
      </div>
      <div v-if="showMemoryAnswers && group.question" class="memory-answer">
        <details class="answer-disclosure">
          <summary class="answer-summary">
            <span class="answer-label">建议回答</span>
            <span class="answer-preview">{{
              memoryPreview(group.question.turn_id)
            }}</span>
            <span class="answer-toggle">
              <span class="answer-expand">展开</span>
              <span class="answer-collapse">收起</span>
              <Icon name="arrow" />
            </span>
          </summary>
          <div class="answer-content">
            <template
              v-for="memory in [memoryByQuestion.get(group.question.turn_id)]"
              :key="group.question.turn_id"
            >
              <template v-if="memory?.status === 'ready' && memory.content">
                <p class="memory-answer-note">
                  AI 生成的参考回答 · {{ basisLabels[memory.content.basis] }}
                </p>
                <p class="message-body">{{ memory.content.answer }}</p>
                <details
                  v-if="memory.evidence.length"
                  class="memory-answer-sources"
                >
                  <summary class="memory-sources-summary">
                    <span>引用依据</span>
                    <span class="memory-sources-toggle">
                      <span class="memory-sources-expand">展开</span>
                      <span class="memory-sources-collapse">收起</span>
                      <Icon name="arrow" />
                    </span>
                  </summary>
                  <div class="memory-sources-content">
                    <div
                      v-for="source in memory.evidence"
                      :key="source.chunk_id"
                      class="memory-citation"
                    >
                      <button
                        type="button"
                        class="inline-link"
                        @click="$emit('open-source', source.source_id)"
                      >
                        {{ source.source_title }} ·
                        {{ locatorLabel(source.locator) }}
                      </button>
                      <p class="memory-excerpt">{{ source.text }}</p>
                    </div>
                  </div>
                </details>
                <div
                  v-if="memory.content.evidence_gaps.length"
                  class="memory-answer-gaps"
                >
                  <h3>待补信息</h3>
                  <ul>
                    <li v-for="gap in memory.content.evidence_gaps" :key="gap">
                      {{ gap }}
                    </li>
                  </ul>
                </div>
                <p
                  v-if="memory.diagnostics?.embedding_status === 'unavailable'"
                  class="memory-answer-note"
                >
                  向量检索暂不可用，本次采用文字检索。
                </p>
              </template>
              <p v-else class="memory-answer-note">
                {{ memoryPreview(group.question.turn_id) }}
              </p>
            </template>
          </div>
        </details>
      </div>
    </div>
  </div>
</template>
