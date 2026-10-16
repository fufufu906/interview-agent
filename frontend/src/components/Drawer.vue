<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from "vue";
import Icon from "./Icon.vue";
const props = defineProps<{ open: boolean; title: string; busy?: boolean }>();
const emit = defineEmits<{ close: [] }>();
const panel = ref<HTMLElement>(),
  close = ref<HTMLButtonElement>();
let origin: HTMLElement | null = null;
function backgroundInert(value: boolean) {
  const shell = document.querySelector<HTMLElement>(".shell");
  if (shell) shell.inert = value;
}
function keydown(e: KeyboardEvent) {
  if (!props.open) return;
  if (e.key === "Escape" && !props.busy) {
    emit("close");
    e.preventDefault();
  }
  if (e.key !== "Tab") return;
  const items = Array.from(
    panel.value?.querySelectorAll<HTMLElement>(
      "button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]",
    ) || [],
  ).filter((el) => el.getClientRects().length);
  const first = items[0],
    last = items.at(-1);
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last?.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first?.focus();
  }
}
watch(
  () => props.open,
  async (open) => {
    if (open) {
      origin = document.activeElement as HTMLElement;
      await nextTick();
      backgroundInert(true);
      close.value?.focus();
      document.addEventListener("keydown", keydown);
      document.body.style.overflow = "hidden";
    } else {
      document.removeEventListener("keydown", keydown);
      document.body.style.overflow = "";
      backgroundInert(false);
      await nextTick();
      origin?.focus();
    }
  },
);
onBeforeUnmount(() => {
  document.removeEventListener("keydown", keydown);
  document.body.style.overflow = "";
  backgroundInert(false);
});
</script>
<template>
  <Teleport to="body">
    <div class="scrim" :class="{ open }" @click="!busy && emit('close')" />
    <aside
      ref="panel"
      class="drawer"
      :class="{ open }"
      role="dialog"
      aria-modal="true"
      :aria-hidden="!open"
      :inert="!open"
      aria-labelledby="drawer-title"
    >
      <div class="drawer-head">
        <h2 id="drawer-title">{{ title }}</h2>
        <button
          ref="close"
          class="icon-btn"
          aria-label="关闭"
          :disabled="busy"
          @click="emit('close')"
        >
          <Icon name="close" />
        </button>
      </div>
      <slot />
    </aside>
  </Teleport>
</template>
