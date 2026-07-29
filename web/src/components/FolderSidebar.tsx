"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher, apiPost, apiDelete } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { Folder } from "@/lib/types";
import {
  FolderIcon,
  ChevronRight,
  ChevronDown,
  Plus,
  Trash2,
  Settings,
  PanelLeftClose,
} from "lucide-react";

function FolderNode({
  folder,
  depth,
  onMutate,
}: {
  folder: Folder;
  depth: number;
  onMutate: () => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const [hovered, setHovered] = useState(false);
  const { currentFolderId, setFolderId } = useAppStore();
  const selected = currentFolderId === folder.id;

  return (
    <div>
      <div
        className={`flex items-center gap-1 py-1.5 cursor-pointer text-sm rounded-md mx-1 ${
          selected ? "bg-blue-500/10 text-blue-600" : "text-gray-700 hover:bg-gray-100"
        }`}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        onClick={() => setFolderId(folder.id)}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {folder.children && folder.children.length > 0 ? (
          <button
            className="p-0 w-4 h-4 flex items-center justify-center shrink-0"
            onClick={(e) => {
              e.stopPropagation();
              setExpanded(!expanded);
            }}
          >
            {expanded ? (
              <ChevronDown size={12} className="text-gray-400" />
            ) : (
              <ChevronRight size={12} className="text-gray-400" />
            )}
          </button>
        ) : (
          <span className="w-4 shrink-0" />
        )}
        <FolderIcon size={14} className={selected ? "text-blue-500" : "text-gray-400"} style={{ fill: selected ? "currentColor" : "none" }} />
        <span className="truncate flex-1">{folder.name}</span>
        {hovered && !selected && (
          <button
            className="p-0.5 text-gray-300 hover:text-red-400 shrink-0"
            onClick={async (e) => {
              e.stopPropagation();
              if (!confirm(`删除「${folder.name}」？`)) return;
              try {
                await apiDelete(`/folders/${folder.id}`);
                onMutate();
              } catch (e) {
                console.error("Failed to delete folder:", e);
                alert("删除文件夹失败");
              }
            }}
          >
            <Trash2 size={11} />
          </button>
        )}
      </div>
      {expanded &&
        folder.children?.map((child) => (
          <FolderNode key={child.id} folder={child} depth={depth + 1} onMutate={onMutate} />
        ))}
    </div>
  );
}

export default function FolderSidebar() {
  const { data: folders, mutate } = useSWR<Folder[]>("/folders", fetcher);
  const { currentFolderId, setFolderId, setConfigModalOpen, setSidebarCollapsed } = useAppStore();
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");

  const handleCreate = async () => {
    if (!newName.trim()) return;
    try {
      await apiPost("/folders", { name: newName, parent_id: currentFolderId });
      setNewName("");
      setCreating(false);
      mutate();
    } catch (e) {
      console.error("Failed to create folder:", e);
      alert("创建文件夹失败");
    }
  };

  return (
    <div className="w-[200px] h-screen bg-gray-50 border-r border-gray-200 flex flex-col shrink-0">
      {/* Header */}
      <div className="px-3 py-3 flex items-center justify-between">
        <span className="text-sm font-semibold text-gray-500 uppercase tracking-wider">文件夹</span>
        <div className="flex items-center gap-1">
          <button
            className="p-1 text-gray-400 hover:text-gray-600 rounded"
            onClick={() => setCreating(true)}
          >
            <Plus size={13} />
          </button>
          <button
            className="p-1 text-gray-400 hover:text-gray-600 rounded"
            onClick={() => setSidebarCollapsed(true)}
          >
            <PanelLeftClose size={13} />
          </button>
        </div>
      </div>

      {/* All notes */}
      <div
        className={`flex items-center gap-2 py-1.5 px-3 mx-1 cursor-pointer text-sm rounded-md ${
          currentFolderId === null ? "bg-blue-500/10 text-blue-600" : "text-gray-700 hover:bg-gray-100"
        }`}
        onClick={() => setFolderId(null)}
      >
        <FolderIcon size={14} className={currentFolderId === null ? "text-blue-500" : "text-gray-400"} />
        <span className="truncate">全部笔记</span>
      </div>

      {/* Folder tree */}
      <div className="flex-1 overflow-y-auto py-1">
        {folders?.map((folder) => (
          <FolderNode key={folder.id} folder={folder} depth={0} onMutate={() => mutate()} />
        ))}
      </div>

      {/* New folder input */}
      {creating && (
        <div className="px-2 pb-2">
          <input
            className="w-full text-sm border border-gray-200 rounded-md px-2 py-1.5 outline-none focus:border-blue-300 bg-white"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleCreate();
              if (e.key === "Escape") { setCreating(false); setNewName(""); }
            }}
            placeholder="新建文件夹"
            autoFocus
            onBlur={() => { if (!newName.trim()) { setCreating(false); setNewName(""); } }}
          />
        </div>
      )}

      {/* Bottom actions */}
      <div className="p-2 border-t border-gray-200">
        <button
          className="flex items-center gap-2 text-sm text-gray-400 hover:text-gray-600 w-full px-2 py-1.5 rounded-md hover:bg-gray-100"
          onClick={() => setConfigModalOpen(true)}
        >
          <Settings size={12} />
          模型配置
        </button>
      </div>
    </div>
  );
}
