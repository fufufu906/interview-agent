import type { FolderImportResult } from "./types.js";

export interface FolderImportProgress {
  total: number;
  completed: number;
  imported: number;
  failed: number;
  currentFile: string;
  status: "running" | "completed" | "interrupted";
}

/** Confirm each file before advancing; retain results after an uncertain request. */
export async function importFolderBatch(
  files: { file_id: string; path: string }[],
  importFile: (fileId: string) => Promise<FolderImportResult>,
  onProgress: (progress: FolderImportProgress) => void,
) {
  const selected = [
    ...new Map(files.map((file) => [file.file_id, file])).values(),
  ];
  const result: FolderImportResult = { files: [], imported: 0, failed: 0 };
  const progress: FolderImportProgress = {
    total: selected.length,
    completed: 0,
    imported: 0,
    failed: 0,
    currentFile: "",
    status: "running",
  };
  const emit = () => onProgress({ ...progress });
  for (const file of selected) {
    progress.currentFile = file.path;
    emit();
    let response: FolderImportResult;
    try {
      response = await importFile(file.file_id);
    } catch (error) {
      progress.status = "interrupted";
      emit();
      return { result, error };
    }
    result.files.push(...response.files);
    result.imported += response.imported;
    result.failed += response.failed;
    progress.completed += 1;
    progress.imported = result.imported;
    progress.failed = result.failed;
    emit();
  }
  progress.currentFile = "";
  progress.status = "completed";
  emit();
  return { result, error: null };
}
