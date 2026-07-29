"use client";

import useSWR from "swr";
import { fetcher, apiPost } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { Note } from "@/lib/types";
import { Plus } from "lucide-react";

const STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  parsed: "已解析",
  scripted: "已生成脚本",
  materials_ready: "素材就绪",
  subtitles_ready: "字幕就绪",
  ai_video_ready: "视频就绪",
  slides_ready: "图文就绪",
  composed: "已合成",
};

export default function NoteList() {
  const { currentFolderId, currentNoteId, setNoteId } = useAppStore();

  const { data: notes, mutate } = useSWR<Note[]>(
    `/notes${currentFolderId ? `?folder_id=${currentFolderId}` : ""}`,
    fetcher
  );

  const handleCreate = async () => {
    try {
      const note = await apiPost("/notes", {
        title: "新笔记",
        folder_id: currentFolderId,
      });
      if (note?.id) {
        mutate();
        setNoteId(note.id);
      }
    } catch (e) {
      console.error("Failed to create note:", e);
      alert("创建笔记失败");
    }
  };

  const formatDate = (dateStr: string) => {
    if (!dateStr) return "";
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return "";
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    if (isToday) return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
    return `${d.getMonth() + 1}/${d.getDate()}`;
  };

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <div className="px-3 py-2.5 flex items-center justify-between border-b border-gray-200">
        <span className="text-sm font-semibold text-gray-500 uppercase tracking-wider">
          笔记 {notes ? `(${notes.length})` : ""}
        </span>
        <button
          className="p-1 text-gray-400 hover:text-gray-600 rounded"
          onClick={handleCreate}
        >
          <Plus size={15} />
        </button>
      </div>

      {/* Note items */}
      <div className="flex-1 overflow-y-auto">
        {notes?.map((note) => {
          const selected = currentNoteId === note.id;
          const preview = (note.raw_text || note.content || "")
            .replace(/^#+\s.*/gm, "")
            .replace(/\n/g, " ")
            .trim()
            .slice(0, 60);
          const status = STATUS_LABEL[note.status] || note.status;

          return (
            <div
              key={note.id}
              className={`px-3 py-2.5 cursor-pointer border-b border-gray-100 ${
                selected
                  ? "bg-blue-500 text-white"
                  : "hover:bg-gray-50"
              }`}
              onClick={() => setNoteId(note.id)}
            >
              <div className="flex items-center justify-between mb-0.5">
                <span className={`text-sm font-medium truncate ${selected ? "text-white" : "text-gray-800"}`}>
                  {note.title}
                </span>
                <span className={`text-xs shrink-0 ml-2 ${selected ? "text-blue-100" : "text-gray-400"}`}>
                  {formatDate(note.updated_at)}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className={`text-xs truncate flex-1 ${selected ? "text-blue-100" : "text-gray-400"}`}>
                  {preview || "空笔记"}
                </span>
                <span className={`text-xs px-1.5 py-0.5 rounded-full shrink-0 ${
                  selected
                    ? "bg-blue-400/30 text-blue-100"
                    : "bg-gray-100 text-gray-500"
                }`}>
                  {status}
                </span>
              </div>
            </div>
          );
        })}

        {notes?.length === 0 && (
          <div className="py-12 text-center text-xs text-gray-300">
            暂无笔记
          </div>
        )}
      </div>
    </div>
  );
}
