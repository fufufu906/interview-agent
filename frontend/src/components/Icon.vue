<script setup lang="ts">
defineProps<{ name: string }>();
const paths: Record<string, string> = {
  chat: "M5 4h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-5 3V6a2 2 0 0 1 1-2Z M8 9h8 M8 13h5",
  folder: "M3 7h7l2-3h8v15H3Z M3 8h18",
  grid: "M3 3h7v7H3Z M14 3h7v7h-7Z M3 14h7v7H3Z M14 14h7v7h-7Z",
  book: "M12 5v16 M12 5C8 2 4 3 2 4v15c4-2 7-1 10 2 3-3 6-4 10-2V4c-3-1-6-2-10 1Z",
  arrow: "M4 12h16 M14 6l6 6-6 6",
  plus: "M12 5v14 M5 12h14",
  close: "M6 6l12 12 M6 18 18 6",
  check: "M5 12l4 4L19 6",
  file: "M5 3h9l5 5v13H5Z M14 3v5h5 M9 12h6 M9 16h6",
  search: "M11 3a8 8 0 1 0 0 16 8 8 0 0 0 0-16 M17 17l5 5",
};
</script>
<template>
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path :d="paths[name] || paths.file" />
  </svg>
</template>
