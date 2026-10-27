<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import type { Workspace } from "../workspace";
import { useExternalReviews, type TranscriptTurn } from "../externalReviews";
import { dateLabel, locatorLabel } from "../types";
const props = defineProps<{ w: Workspace }>();
const x = useExternalReviews(props.w);
const { items, samples, record, turns, role, busy, error, dirty } = x;
const inputMode = ref("text"),
  title = ref(""),
  text = ref(""),
  file = ref<File | null>(null),
  sample = ref("");
const importOpen = ref(false);
const roles = {
  interviewer: "面试官 / 问题",
  candidate: "候选人 / 回答",
  assistant: "助手建议",
  system: "系统提示",
  note: "标题 / 注释 / 场外内容",
  unknown: "待识别",
};
const statuses = {
  draft: "待确认问答",
  parsing: "正在识别角色",
  generating: "正在生成复盘",
  completed: "复盘已完成",
  error: "部分生成失败",
};
const unknown = computed(
  () => turns.value.filter((t) => t.role === "unknown").length,
);
const visibleTurns = computed(() =>
  turns.value.filter((t) => !onlyUnknown.value || t.role === "unknown"),
);
const onlyUnknown = ref(false);
const splitPositions = new Map<string, number>();
function rememberCursor(event: Event, turn: TranscriptTurn) {
  splitPositions.set(
    turn.turn_id,
    (event.target as HTMLTextAreaElement).selectionStart,
  );
}
async function importInput() {
  if (inputMode.value === "text")
    await x.importRecord("text", {
      title: title.value.trim() || "真实面试记录",
      text: text.value,
    });
  else if (inputMode.value === "file" && file.value)
    await x.importRecord("file", file.value);
  else if (sample.value) await x.importRecord("sample", sample.value);
  if (!error.value) importOpen.value = false;
}
onMounted(x.load);
</script>

<template>
  <div class="external-review">
    <div class="external-toolbar">
      <div>
        <h2>真实面试复盘</h2>
        <p>导入会议转写，确认问答后，逐题生成有依据的完整复盘。</p>
      </div>
      <button
        class="btn primary"
        :disabled="!!busy"
        @click="importOpen = !importOpen"
      >
        导入真实面试
      </button>
    </div>
    <section
      v-if="importOpen || !items.length"
      class="external-import"
      aria-label="导入真实面试"
    >
      <div class="external-tabs" role="group" aria-label="输入方式">
        <button
          v-for="m in [
            { id: 'text', name: '粘贴文本' },
            { id: 'file', name: '上传 TXT' },
            { id: 'sample', name: '已有文档' },
          ]"
          :key="m.id"
          class="btn quiet"
          :aria-pressed="inputMode === m.id"
          @click="inputMode = m.id"
        >
          {{ m.name }}
        </button>
      </div>
      <form @submit.prevent="importInput">
        <template v-if="inputMode === 'text'">
          <label for="external-title">面试记录名称</label
          ><input
            id="external-title"
            v-model="title"
            maxlength="200"
            placeholder="例如：AI 应用开发面试"
          />
          <label for="external-text">面试原文</label
          ><textarea
            id="external-text"
            v-model="text"
            rows="8"
            maxlength="200000"
            placeholder="粘贴完整会议转写。原文会单独保存，语气词和重复不会被直接删除。"
          />
        </template>
        <template v-else-if="inputMode === 'file'">
          <label for="external-file">面试转写 TXT</label
          ><input
            id="external-file"
            type="file"
            accept=".txt,text/plain"
            @change="
              file = ($event.target as HTMLInputElement).files?.[0] || null
            "
          />
          <p>
            支持 UTF-8 和 GB18030；最多 20 万字符。DOCX
            是导出结果，首版不作为输入。
          </p>
        </template>
        <template v-else>
          <label for="external-sample">选择已保存的面试文档</label
          ><select id="external-sample" v-model="sample">
            <option value="">请选择</option>
            <option
              v-for="s in samples"
              :key="s.sample_id"
              :value="s.sample_id"
            >
              {{ s.filename }}
            </option>
          </select>
          <p v-if="!samples.length">
            本机没有登记过面试文档，可使用粘贴或上传。
          </p>
        </template>
        <button
          class="btn primary"
          :disabled="
            !!busy ||
            (inputMode === 'text'
              ? !text.trim()
              : inputMode === 'file'
                ? !file
                : !sample)
          "
        >
          导入并预览问答
        </button>
      </form>
    </section>
    <p v-if="error" class="external-error" role="alert">{{ error }}</p>
    <p v-if="busy" class="waiting" role="status">{{ busy }}</p>
    <div v-if="items.length" class="filter-row">
      <label for="external-history">真实面试记录</label
      ><select
        id="external-history"
        :value="record?.review_id"
        :disabled="!!busy"
        @change="x.open(($event.target as HTMLSelectElement).value)"
      >
        <option
          v-for="item in items"
          :key="item.review_id"
          :value="item.review_id"
        >
          {{ dateLabel(item.created_at) }} · {{ item.title }}
        </option>
      </select>
    </div>
    <template v-if="record">
      <div class="external-progress">
        <strong>{{ statuses[record.status] }}</strong
        ><span
          >原文覆盖 {{ record.coverage.covered_characters }} /
          {{ record.coverage.characters }} 字符 ·
          {{ record.coverage.question_count }} 个问题及追问 · 已复盘
          {{ record.coverage.reviewed_questions }}</span
        >
      </div>
      <div class="actions external-actions">
        <button class="btn quiet" :disabled="!!busy" @click="x.download('raw')">
          下载原文
        </button>
        <button
          v-if="record.status === 'completed'"
          class="btn primary"
          :disabled="!!busy"
          @click="x.download('docx')"
        >
          导出复盘文档
        </button>
        <button
          v-if="record.status === 'error'"
          class="btn"
          :disabled="!!busy"
          @click="x.action('retry')"
        >
          重试未完成部分
        </button>
      </div>
      <template v-if="record.status === 'draft' || record.status === 'parsing'">
        <section class="external-confirm">
          <h3>确认场次与问答</h3>
          <p>
            user
            标签不代表候选人。助手建议和系统提示会保留，但不当作实际回答。每个面试官问题单独复盘，追问也保留。
          </p>
          <div class="external-role-fields">
            <label
              >岗位名称（可后补）<input
                v-model="role.title"
                :disabled="record.status !== 'draft'"
                maxlength="200"
                @input="dirty = true" /></label
            ><label
              >本场 JD（可后补）<textarea
                v-model="role.jd_text"
                :disabled="record.status !== 'draft'"
                rows="3"
                maxlength="20000"
                @input="dirty = true"
              />
            </label>
          </div>
          <div class="actions external-actions">
            <label class="external-checkbox"
              ><input type="checkbox" v-model="onlyUnknown" />只看待识别片段（{{
                unknown
              }}）</label
            >
            <button
              class="btn"
              :disabled="!!busy || record.status !== 'draft' || !unknown"
              @click="x.action('parse')"
            >
              智能拆分待识别片段
            </button>
            <button
              class="btn"
              :disabled="!!busy || record.status !== 'draft' || !dirty"
              @click="x.save"
            >
              保存拆分修改
            </button>
          </div>
          <p
            v-for="job in record.jobs.filter((j) => j.status === 'error')"
            :key="job.item_id"
            class="external-error"
          >
            片段识别失败，原文完整保留；可手动拆分或重新识别。{{ job.error }}
          </p>
          <details
            v-for="(turn, index) in visibleTurns"
            :key="turn.turn_id"
            class="external-turn"
            :open="turn.role === 'unknown' && visibleTurns.length < 10"
          >
            <summary>
              <span
                >{{ index + 1 }} · {{ roles[turn.role] }} ·
                {{ turn.session }}</span
              ><span>字符 {{ turn.start + 1 }}–{{ turn.end }}</span>
            </summary>
            <div class="external-turn-fields">
              <label
                >角色<select
                  v-model="turn.role"
                  :disabled="record.status !== 'draft'"
                  @change="dirty = true"
                >
                  <option
                    v-for="(name, value) in roles"
                    :key="value"
                    :value="value"
                  >
                    {{ name }}
                  </option>
                </select></label
              >
              <label
                >所属场次<input
                  v-model="turn.session"
                  :disabled="record.status !== 'draft'"
                  maxlength="80"
                  @input="dirty = true"
              /></label>
              <label
                >主题分组<input
                  v-model="turn.topic"
                  :disabled="record.status !== 'draft'"
                  maxlength="200"
                  @input="dirty = true"
              /></label>
            </div>
            <label :for="`raw-${turn.turn_id}`"
              >原文（只读；可把光标放到需要拆分的位置）</label
            >
            <textarea
              :id="`raw-${turn.turn_id}`"
              class="external-raw"
              readonly
              rows="5"
              :value="record.raw_text.slice(turn.start, turn.end)"
              @click="rememberCursor($event, turn)"
              @keyup="rememberCursor($event, turn)"
              @select="rememberCursor($event, turn)"
            />
            <button
              class="btn quiet"
              :disabled="!!busy || record.status !== 'draft'"
              @click="x.split(turn, splitPositions.get(turn.turn_id) || 0)"
            >
              在光标位置拆成两段
            </button>
            <label
              >补充说明（不改写当时原文）<textarea
                v-model="turn.correction"
                :disabled="record.status !== 'draft'"
                rows="2"
                maxlength="24000"
                @input="dirty = true"
              />
            </label>
          </details>
          <p
            v-if="record.coverage.orphan_answers.length"
            class="external-error"
          >
            有
            {{
              record.coverage.orphan_answers.length
            }}
            段回答尚未归属问题，请检查角色、顺序及场次。
          </p>
          <p>
            没有 JD
            时先分析回答内容，岗位匹配保持未评估。确认后进入后台生成，完成前可以离开页面。
          </p>
          <button
            class="btn primary"
            :disabled="!!busy || record.status !== 'draft' || !!unknown"
            @click="x.action('confirm')"
          >
            确认问答并生成完整复盘
          </button>
        </section>
      </template>
      <section v-if="record.summary" class="external-conclusion">
        <h2>本轮结论</h2>
        <p class="external-prose">{{ record.summary.conclusion }}</p>
      </section>
      <div v-if="record.status === 'generating'" class="notice" role="status">
        正在逐题处理完整问答。已完成的结果会逐步显示，全部完成后生成本轮结论及准备重点。
      </div>
      <section
        v-if="record.status !== 'draft' && record.status !== 'parsing'"
        class="external-report"
        aria-label="完整面试复盘"
      >
        <article
          v-for="(question, index) in record.questions"
          :key="question.question_id"
          class="external-question"
        >
          <h2>
            {{ index + 1 }} · {{ question.session }} ·
            {{ question.topic || "面试问答" }}
          </h2>
          <span v-if="question.parent_question_id" class="small muted"
            >同一主题的追问，单独保留</span
          >
          <h3>面试问题</h3>
          <p class="external-prose">{{ question.question }}</p>
          <details class="external-original">
            <summary>
              查看实际回答原文 · 字符 {{ question.start + 1 }}–{{
                question.end
              }}
            </summary>
            <p class="external-prose">
              {{ question.answer || "该题回答未记录" }}
            </p>
          </details>
          <template v-if="question.result">
            <h3>实际回答整理</h3>
            <p class="external-prose">
              {{
                question.result.content.answer_clean ||
                "该题回答未记录，保持尚未测评。"
              }}
            </p>
            <h3>逐题分析</h3>
            <p class="external-prose">{{ question.result.content.analysis }}</p>
            <blockquote
              v-for="quote in question.result.content.quotes"
              :key="quote"
            >
              回答原文依据：“{{ quote }}”
            </blockquote>
            <h3>建议回答</h3>
            <p class="external-prose">
              {{ question.result.content.suggestion }}
            </p>
            <template v-if="question.result.content.explanation"
              ><h3>补充说明</h3>
              <p class="external-prose">
                {{ question.result.content.explanation }}
              </p></template
            >
            <template v-if="question.result.content.gaps.length"
              ><h3>待补信息</h3>
              <ul>
                <li v-for="gap in question.result.content.gaps" :key="gap">
                  {{ gap }}
                </li>
              </ul></template
            >
            <details
              v-if="question.result.evidence.length"
              class="external-evidence"
            >
              <summary>
                引用依据 · {{ question.result.evidence.length }} 处
              </summary>
              <div
                v-for="source in question.result.evidence"
                :key="source.chunk_id"
              >
                <button
                  class="inline-link"
                  @click="w.openSource(source.source_id)"
                >
                  {{ source.source_title }} · {{ locatorLabel(source.locator) }}
                </button>
                <p class="memory-excerpt">{{ source.text }}</p>
              </div>
            </details>
            <p class="small muted">
              {{
                question.result.diagnostics?.embedding_status === "ok"
                  ? "本题已使用向量与文字混合检索。"
                  : question.result.diagnostics?.embedding_status ===
                      "unavailable"
                    ? "生成时向量服务不可用，本题使用文字检索。"
                    : ""
              }}
            </p>
          </template>
          <p v-else class="small muted">
            {{
              question.status === "error"
                ? `本题生成失败：${question.error}，可重试未完成部分。`
                : "等待生成…"
            }}
          </p>
        </article>
      </section>
      <section v-if="record.summary" class="external-next">
        <h2>下一步准备重点</h2>
        <ol>
          <li v-for="item in record.summary.priorities" :key="item">
            {{ item }}
          </li>
        </ol>
        <h2>记录与证据边界</h2>
        <ul>
          <li v-for="item in record.summary.limitations" :key="item">
            {{ item }}
          </li>
        </ul>
        <p>原始面试、复盘与建议回答不自动写入长期个人事实。</p>
        <button
          class="btn primary"
          :disabled="!!busy"
          @click="x.download('docx')"
        >
          导出复盘文档
        </button>
      </section>
    </template>
  </div>
</template>
