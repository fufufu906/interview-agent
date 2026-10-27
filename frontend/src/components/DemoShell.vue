<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import App from "../App.vue";
import Icon from "./Icon.vue";
import { ApiError, errorMessage, post, request } from "../api";

const props = defineProps<{ models: string[] }>();
type Example = {
  label: string;
  question: string;
  answer: string;
  review: string;
  suggestion: string;
  evidence: { title: string; text: string };
  gaps: string[];
};
type CredentialState = {
  connected: boolean;
  model: string;
  bound: boolean;
  expires_at: number | null;
};
const example = ref<Example | null>(null),
  status = ref<CredentialState | null>(null);
const entered = ref(false),
  hasWorkspace = ref(false),
  busy = ref(false),
  error = ref("");
const dialog = ref<HTMLDialogElement | null>(null),
  key = ref("");
const model = ref(props.models[0] || "deepseek-flash");
let timer: ReturnType<typeof setInterval>;

async function refresh() {
  try {
    status.value = await request<CredentialState>("/api/demo/credentials");
    model.value = status.value.model;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      status.value = null;
      if (entered.value) error.value = "本次体验已到期，请重新开始。";
    } else throw e;
  }
}
async function run(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await action();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
function configure() {
  key.value = "";
  dialog.value?.showModal();
}
async function enter() {
  await run(async () => {
    await post("/api/demo/visit");
    await refresh();
    hasWorkspace.value = true;
    entered.value = true;
    if (!status.value?.connected) configure();
  });
}
async function connect() {
  await run(async () => {
    try {
      status.value = await post<CredentialState>("/api/demo/credentials", {
        api_key: key.value.trim(),
        model: model.value,
      });
      dialog.value?.close();
    } finally {
      key.value = "";
    }
  });
}
async function disconnect() {
  await run(async () => {
    status.value = await request<CredentialState>("/api/demo/credentials", {
      method: "DELETE",
    });
  });
}
async function reset() {
  await run(async () => {
    await post("/api/demo/reset");
    dialog.value?.close();
    key.value = "";
    status.value = null;
    entered.value = false;
    hasWorkspace.value = false;
    localStorage.removeItem("mianshi.session.visitor");
    location.hash = "";
  });
}
function scrollExample() {
  document
    .getElementById("demo-example")
    ?.scrollIntoView({ behavior: "smooth" });
}
onMounted(async () => {
  await run(async () => {
    example.value = await request<Example>("/api/demo/example");
    await refresh();
  });
  timer = setInterval(() => {
    if (entered.value) void refresh().catch(() => {});
  }, 15000);
});
onBeforeUnmount(() => {
  clearInterval(timer);
  key.value = "";
});
</script>

<template>
  <div class="public-demo">
    <header class="demo-topbar">
      <a class="demo-brand" href="#" @click.prevent="entered = false"
        ><span class="demo-brand-mark"><Icon name="chat" /></span>Interview
        Agent</a
      >
      <span class="demo-top-label">公开演示</span>
      <div v-if="entered" class="demo-top-actions">
        <span
          class="demo-key-state"
          :class="{ connected: status?.connected }"
          >{{
            status?.connected ? `已配置 ${status.model}` : "尚未配置 Key"
          }}</span
        >
        <button class="btn quiet" @click="configure">配置 DeepSeek</button>
        <button
          v-if="status?.connected"
          class="inline-link"
          :disabled="busy"
          @click="disconnect"
        >
          断开
        </button>
      </div>
      <a
        v-else
        class="demo-github"
        href="https://github.com/fufufu906/interview-agent"
        target="_blank"
        rel="noopener noreferrer"
        >GitHub ↗</a
      >
    </header>

    <p v-if="error && !dialog?.open" class="demo-error" role="alert">
      {{ error }}
    </p>
    <main v-show="!entered" class="demo-landing">
      <section class="demo-hero">
        <div>
          <p class="demo-eyebrow">
            PRACTICE WITH CONTEXT. REVIEW WITH EVIDENCE.
          </p>
          <h1>练习你的回答，<br />也看清回答的依据。</h1>
          <p class="demo-intro">
            把资料、岗位和实际回答串起来。从一场模拟面试，到带着引用与待补信息的复盘，让下一次准备有据可循。
          </p>
          <div class="demo-hero-actions">
            <button class="btn primary" :disabled="busy" @click="enter">
              {{ busy ? "正在准备…" : "进入我的体验" }}
              <Icon name="arrow" /></button
            ><button class="btn" @click="scrollExample">先看示例</button>
          </div>
          <p class="demo-footnote">
            示例无需 Key · 实际生成使用你自己的 DeepSeek Key
          </p>
        </div>
        <aside class="demo-flow" aria-label="体验流程">
          <div>
            <span>01</span><strong>带着材料练习</strong>
            <p>目标岗位、项目资料与学习笔记。</p>
          </div>
          <div>
            <span>02</span><strong>留下实际回答</strong>
            <p>逐题提问，沿着你的回答继续追问。</p>
          </div>
          <div>
            <span>03</span><strong>对照证据复盘</strong>
            <p>实际回答、建议和资料缺口分开查看。</p>
          </div>
        </aside>
      </section>

      <section
        id="demo-example"
        class="demo-example"
        aria-labelledby="demo-example-title"
      >
        <div class="demo-section-heading">
          <div>
            <p class="demo-eyebrow">ONE QUESTION, WITH EVIDENCE</p>
            <h2 id="demo-example-title">先看一题如何复盘</h2>
          </div>
          <span class="demo-pill">{{ example?.label || "正在读取示例" }}</span>
        </div>
        <template v-if="example">
          <div class="demo-question">
            <div class="demo-avatar">AI</div>
            <div>
              <p class="demo-speaker">面试官的问题</p>
              <h3>{{ example.question }}</h3>
            </div>
          </div>
          <div class="demo-example-body">
            <details class="demo-answer">
              <summary>候选人回答<span>展开</span></summary>
              <p>{{ example.answer }}</p>
            </details>
            <div class="demo-feedback">
              <p class="demo-eyebrow">基于实际回答的反馈</p>
              <p>{{ example.review }}</p>
            </div>
            <details class="demo-answer">
              <summary>建议回答<span>展开</span></summary>
              <p>{{ example.suggestion }}</p>
              <details class="demo-evidence">
                <summary>引用依据</summary>
                <p class="demo-speaker">{{ example.evidence.title }}</p>
                <p>{{ example.evidence.text }}</p>
              </details>
              <p class="demo-speaker">待补信息</p>
              <ul>
                <li v-for="gap in example.gaps" :key="gap">{{ gap }}</li>
              </ul>
            </details>
          </div>
        </template>
      </section>

      <section class="demo-boundaries">
        <div>
          <h3>每位访客独立体验</h3>
          <p>
            预置的是虚构材料。体验记录最多保留 24
            小时，不会访问项目作者的私人资料。
          </p>
        </div>
        <div>
          <h3>你决定什么时候调用</h3>
          <p>
            实际生成经本站后端转发至 DeepSeek，使用你的 Key，由你的 DeepSeek
            账户计费。
          </p>
        </div>
        <div>
          <h3>密钥只在本次连接中使用</h3>
          <p>
            不保存到数据库或日志。连接 30 分钟后失效，服务重启后需要重新填写。
          </p>
        </div>
      </section>
      <footer class="demo-footer">
        <span>Interview Agent · 让材料、回答和证据各归其位。</span
        ><button class="inline-link" :disabled="busy" @click="enter">
          开始体验 →
        </button>
      </footer>
    </main>

    <div v-if="hasWorkspace" v-show="entered" class="demo-workspace">
      <div class="demo-workspace-note">
        访客体验 · 每轮最多六题 · 上传文件最大 1.5 MB ·
        演示材料暂未生成向量，可在资料库重建
        <button class="inline-link" :disabled="busy" @click="reset">
          清空并重新开始
        </button>
      </div>
      <App />
    </div>

    <dialog ref="dialog" class="demo-key-dialog" @close="key = ''">
      <form @submit.prevent="connect">
        <div class="demo-dialog-head">
          <h2>连接你自己的 DeepSeek</h2>
          <button
            type="button"
            class="icon-btn"
            aria-label="关闭配置"
            @click="dialog?.close()"
          >
            <Icon name="close" />
          </button>
        </div>
        <p>
          资料与问答会经本站后端发送至 DeepSeek。调用费用由该 Key
          的账户承担，本站不会使用共享密钥代付。
        </p>
        <label for="demo-model">模型</label
        ><select id="demo-model" v-model="model" :disabled="status?.bound">
          <option v-for="id in models" :key="id" :value="id">{{ id }}</option>
        </select>
        <label for="demo-key">API Key</label
        ><input
          id="demo-key"
          v-model="key"
          type="password"
          autocomplete="off"
          autocapitalize="off"
          :spellcheck="false"
          maxlength="256"
          required
          placeholder="填写你的 DeepSeek API Key"
        />
        <p class="demo-footnote">
          仅在服务端内存中保留 30
          分钟，不写入数据库或日志。保存不代表密钥已通过官方验证，实际调用时会显示鉴权和额度状态。
        </p>
        <p v-if="status?.bound" class="demo-footnote">
          本次体验已固定模型和 Key；可重新连接原
          Key。更换配置请先清空并重新开始，避免后台任务使用另一套凭据。
        </p>
        <p v-if="error" class="demo-error" role="alert">{{ error }}</p>
        <button class="btn primary" :disabled="busy || !key.trim()">
          {{ busy ? "正在保存…" : "保存本次凭据" }}
        </button>
        <a
          class="demo-api-link"
          href="https://platform.deepseek.com/api_keys"
          target="_blank"
          rel="noopener noreferrer"
          >前往 DeepSeek 获取 Key ↗</a
        >
      </form>
    </dialog>
  </div>
</template>
