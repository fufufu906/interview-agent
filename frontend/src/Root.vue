<script setup lang="ts">
import { onMounted, ref } from "vue";
import App from "./App.vue";
import DemoShell from "./components/DemoShell.vue";
import { publicDemo } from "./runtime";

const ready = ref(false),
  failed = ref(false),
  models = ref<string[]>([]);
async function load() {
  failed.value = false;
  try {
    const response = await fetch("/api/runtime", { cache: "no-store" });
    if (!response.ok) throw new Error();
    const info = await response.json();
    if (info.mode !== "local" && info.mode !== "public_demo") throw new Error();
    publicDemo.value = info.mode === "public_demo";
    models.value = info.models || [];
    ready.value = true;
  } catch {
    failed.value = true;
  }
}
onMounted(load);
</script>
<template>
  <DemoShell v-if="ready && publicDemo" :models="models" />
  <App v-else-if="ready" />
  <main v-else class="demo-startup" role="status">
    <h1>Interview Agent</h1>
    <p>{{ failed ? "暂时无法连接应用，请稍后重试。" : "正在打开工作区…" }}</p>
    <button v-if="failed" class="btn primary" @click="load">重新连接</button>
  </main>
</template>
