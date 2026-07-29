"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import useSWR from "swr";
import { fetcher, apiPost, apiPatch, apiDelete } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { Note, Folder, Script, Material, VideoOutput, ModelConfig } from "@/lib/types";
import { Settings, PanelLeft, ChevronRight, Download, Loader2, RotateCcw, Wand2, X, Check, Bold, Italic, Heading1, Heading2, List, ListOrdered, Quote, Music, Video, Pencil, Subtitles, ChevronDown, ChevronUp, Image as ImageIcon } from "lucide-react";
import SlideDrawer from "@/components/SlideDrawer";
import XhsGenerator from "@/components/XhsGenerator";

/* ---------- helpers ---------- */

function flattenFolders(folders: Folder[]): Folder[] {
  return folders.flatMap((f) => [f, ...flattenFolders(f.children || [])]);
}

function buildFolderPath(folderId: number | null, folders: Folder[] | undefined): { id: number; name: string }[] {
  if (!folderId || !folders) return [];
  const flat = flattenFolders(folders);
  const path: { id: number; name: string }[] = [];
  const visited = new Set<number>();
  let current = flat.find((f) => f.id === folderId);
  while (current && !visited.has(current.id)) {
    visited.add(current.id);
    path.unshift({ id: current.id, name: current.name });
    current = current.parent_id ? flat.find((f) => f.id === current!.parent_id) : undefined;
  }
  return path;
}

/* ---------- Formatting toolbar ---------- */

function FormatToolbar({ onInsert }: { onInsert: (newText: string) => void }) {
  const wrap = (prefix: string, suffix: string = "") => {
    const el = document.querySelector<HTMLTextAreaElement>("#note-body-textarea");
    if (!el) return;
    const start = el.selectionStart;
    const end = el.selectionEnd;
    const text = el.value;
    const selected = text.slice(start, end);
    const before = text.slice(0, start);
    const after = text.slice(end);

    let newText: string;
    let cursorPos: number;
    let selectionEnd: number | undefined;

    if (!suffix) {
      const lineStart = before.lastIndexOf("\n") + 1;
      const lineBefore = before.slice(0, lineStart);
      const lineContent = before.slice(lineStart) + selected;
      newText = lineBefore + prefix + lineContent + after;
      cursorPos = lineStart + prefix.length + lineContent.length;
    } else {
      newText = before + prefix + selected + suffix + after;
      if (selected) {
        cursorPos = start + prefix.length;
        selectionEnd = end + prefix.length;
      } else {
        cursorPos = start + prefix.length;
      }
    }

    onInsert(newText);

    requestAnimationFrame(() => {
      const el2 = document.querySelector<HTMLTextAreaElement>("#note-body-textarea");
      if (el2) {
        el2.selectionStart = cursorPos;
        el2.selectionEnd = selectionEnd ?? cursorPos;
        el2.focus();
      }
    });
  };

  const btn = (icon: React.ReactNode, label: string, onClick: () => void) => (
    <button className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded transition-colors" onClick={onClick} title={label}>
      {icon}
    </button>
  );

  return (
    <div className="flex items-center gap-0.5 border-b border-gray-100 pb-2 mb-3">
      {btn(<Heading1 size={14} />, "一级标题", () => wrap("# "))}
      {btn(<Heading2 size={14} />, "二级标题", () => wrap("## "))}
      <div className="w-px h-4 bg-gray-200 mx-1" />
      {btn(<Bold size={14} />, "加粗", () => wrap("**", "**"))}
      {btn(<Italic size={14} />, "斜体", () => wrap("*", "*"))}
      <div className="w-px h-4 bg-gray-200 mx-1" />
      {btn(<List size={14} />, "无序列表", () => wrap("- "))}
      {btn(<ListOrdered size={14} />, "有序列表", () => wrap("1. "))}
      {btn(<Quote size={14} />, "引用", () => wrap("> "))}
    </div>
  );
}

/* ---------- Model selector ---------- */

function ModelSelector({ configs, selectedId, onChange, placeholder }: {
  configs: ModelConfig[] | undefined;
  selectedId: number | undefined;
  onChange: (id: number | undefined) => void;
  placeholder?: string;
}) {
  if (!configs || configs.length === 0) return null;
  return (
    <select className="text-xs border border-gray-200 rounded px-1.5 py-1 bg-white text-gray-600 max-w-[160px] truncate" value={selectedId ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : undefined)}>
      <option value="">{placeholder || "默认模型"}</option>
      {configs.map((c) => (<option key={c.id} value={c.id}>{c.model_id}</option>))}
    </select>
  );
}

/* ---------- Step section ---------- */

const STEP_ICONS: Record<number, React.ReactNode> = {
  1: <Pencil size={13} />,
  2: <Subtitles size={13} />,
  3: <Video size={13} />,
  4: <Music size={13} />,
  5: <Subtitles size={13} />,
  6: <Video size={13} />,
  7: <Wand2 size={13} />,
};

function StepSection({ index, title, done, enabled, processing, expanded, onToggle, children }: {
  index: number;
  title: string;
  done: boolean;
  enabled: boolean;
  processing: boolean;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className={`rounded-xl border transition-all ${enabled ? (expanded ? "border-blue-200 bg-white shadow-sm" : "border-gray-200 bg-white hover:border-gray-300") : "border-gray-100 bg-gray-50/50 opacity-60"}`}>
      <button
        className="w-full flex items-center gap-3 px-4 py-3 text-left"
        onClick={onToggle}
        disabled={!enabled}
      >
        {done ? (
          <span className="w-7 h-7 rounded-full bg-gradient-to-br from-green-400 to-green-500 text-white flex items-center justify-center shrink-0 shadow-sm"><Check size={13} /></span>
        ) : processing ? (
          <span className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-400 to-blue-500 text-white flex items-center justify-center shrink-0 shadow-sm"><Loader2 size={13} className="animate-spin" /></span>
        ) : (
          <span className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-xs font-semibold ${enabled ? "bg-gray-100 text-gray-500" : "bg-gray-100 text-gray-300"}`}>{STEP_ICONS[index] ?? index}</span>
        )}
        <span className={`text-sm font-medium flex-1 ${enabled ? "text-gray-800" : "text-gray-300"}`}>{title}</span>
        {done && !expanded && <span className="text-xs text-green-500 mr-1">已完成</span>}
        {expanded ? <ChevronUp size={15} className="text-gray-400" /> : <ChevronDown size={15} className="text-gray-400" />}
      </button>
      {expanded && enabled && (
        <div className="px-4 pb-4 pt-0 border-t border-gray-100">
          {children}
        </div>
      )}
    </div>
  );
}

/* ---------- Main detail ---------- */

export default function NoteDetail() {
  const { currentNoteId, setFolderId, setConfigModalOpen, setNoteId, sidebarCollapsed, setSidebarCollapsed, slideDrawerOpen, setSlideDrawerOpen } = useAppStore();

  // Inline editing
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const lastSavedTitleRef = useRef("");
  const lastSavedBodyRef = useRef("");
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Drawer state
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [style, setStyle] = useState("knowledge");
  const [resolution, setResolution] = useState<"landscape" | "portrait">("landscape");
  const [xhsGenOpen, setXhsGenOpen] = useState(false);
  const [processing, setProcessing] = useState<string | null>(null);

  // Progress
  const [progressMessage, setProgressMessage] = useState("");

  // Expanded steps
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set([0]));

  const toggleStep = (i: number) => {
    setExpandedSteps((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i); else next.add(i);
      return next;
    });
  };

  // Refine result
  const [refinedTitle, setRefinedTitle] = useState("");
  const [refinedBody, setRefinedBody] = useState("");
  const [bodyEditing, setBodyEditing] = useState(false);
  const refineTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saveRefinedDebounced = (t: string, b: string) => {
    if (refineTimerRef.current) clearTimeout(refineTimerRef.current);
    refineTimerRef.current = setTimeout(async () => {
      if (currentNoteId) {
        await apiPatch(`/notes/${currentNoteId}`, { refined_title: t, refined_body: b });
      }
    }, 800);
  };

  // Script segments (editable)
  const [editedSegs, setEditedSegs] = useState<{ id: number; text: string; emotion: string; visual_hint: string }[]>([]);
  const [editingScript, setEditingScript] = useState(false);

  // Model selection per step
  const [refineModelId, setRefineModelId] = useState<number | undefined>(undefined);
  const [scriptModelId, setScriptModelId] = useState<number | undefined>(undefined);
  const [imageLlmId, setImageLlmId] = useState<number | undefined>(undefined);
  const [imageModelStr, setImageModelStr] = useState<string>("Qwen/Qwen-Image");
  const [imageStyle, setImageStyle] = useState<string>("realistic");
  const [ttsVoice, setTtsVoice] = useState("zh-TW-HsiaoChenNeural");
  const [ttsStyle, setTtsStyle] = useState("clear");

  const TTS_VOICE_OPTIONS = [
    { value: "zh-TW-HsiaoChenNeural", label: "清新女声·晓臻", group: "女声" },
    { value: "zh-TW-HsiaoChenNeural|anchor", label: "播音女声·晓臻", group: "女声" },
    { value: "zh-CN-XiaoxiaoNeural", label: "温柔女声·晓晓", group: "女声" },
    { value: "zh-CN-XiaoxiaoNeural|intellectual", label: "知性女声·晓晓", group: "女声" },
    { value: "zh-CN-XiaoyiNeural", label: "活泼女声·晓伊", group: "女声" },
    { value: "zh-CN-XiaoyiNeural|crisp", label: "清脆女声·晓伊", group: "女声" },
    { value: "zh-CN-liaoning-XiaobeiNeural", label: "爽朗女声·晓北(东北)", group: "女声" },
    { value: "zh-CN-shaanxi-XiaoniNeural", label: "明亮女声·晓妮(陕西)", group: "女声" },
    { value: "zh-TW-HsiaoYuNeural", label: "轻柔女声·晓雨(台湾)", group: "女声" },
    { value: "zh-HK-HiuGaaiNeural", label: "亲切女声·曉佳(粤语)", group: "女声" },
    { value: "zh-HK-HiuMaanNeural", label: "甜美女声·曉曼(粤语)", group: "女声" },
    { value: "en-US-AvaMultilingualNeural", label: "知性女声·Ava(多语)", group: "女声" },
    { value: "en-US-EmmaMultilingualNeural", label: "明快女声·Emma(多语)", group: "女声" },
    { value: "fr-FR-VivienneMultilingualNeural", label: "优雅女声·Vivienne(多语)", group: "女声" },
    { value: "zh-CN-YunyangNeural", label: "播音男声·云扬", group: "男声" },
    { value: "zh-CN-YunjianNeural", label: "沉稳男声·云健", group: "男声" },
    { value: "zh-CN-YunxiNeural", label: "阳光男声·云希", group: "男声" },
    { value: "zh-CN-YunfengNeural", label: "磁性男声·云枫", group: "男声" },
    { value: "zh-CN-YunfengNeural|magnetic", label: "深沉磁性·云枫", group: "男声" },
    { value: "zh-CN-YunjianNeural|magnetic", label: "沉稳磁性·云健", group: "男声" },
    { value: "zh-CN-YunyangNeural|magnetic", label: "播音磁性·云扬", group: "男声" },
    { value: "zh-CN-YunxiaNeural", label: "可爱男声·云夏", group: "男声" },
    { value: "zh-TW-YunJheNeural", label: "亲切男声·云哲(台湾)", group: "男声" },
    { value: "zh-HK-WanLungNeural", label: "亲切男声·雲龍(粤语)", group: "男声" },
    { value: "en-US-AndrewMultilingualNeural", label: "温暖男声·Andrew(多语)", group: "男声" },
    { value: "en-US-BrianMultilingualNeural", label: "随和男声·Brian(多语)", group: "男声" },
  ];

  // Data
  const { data: note, mutate: mutateNote } = useSWR<Note>(
    currentNoteId ? `/notes/${currentNoteId}` : null, fetcher
  );
  const { data: folders } = useSWR<Folder[]>("/folders", fetcher);
  const { data: script, mutate: mutateScript } = useSWR<Script>(
    currentNoteId ? `/notes/${currentNoteId}/scripts/latest` : null, fetcher, { shouldRetryOnError: false }
  );
  const { data: materials, mutate: mutateMaterials } = useSWR<Material[]>(
    currentNoteId ? `/notes/${currentNoteId}/materials` : null, fetcher
  );
  const { data: videos, mutate: mutateVideos } = useSWR<VideoOutput[]>(
    currentNoteId ? `/notes/${currentNoteId}/videos` : null, fetcher
  );

  // Model configs per provider
  const { data: llmConfigs } = useSWR<ModelConfig[]>("/model-configs?provider=llm", fetcher);
  const { data: imageConfigs, mutate: mutateImageConfigs } = useSWR<ModelConfig[]>("/model-configs?provider=image", fetcher);

  // Image model preset list
  const IMAGE_MODEL_OPTIONS = [
    { value: "Qwen/Qwen-Image", label: "Qwen-Image ⭐" },
    { value: "Tongyi-MAI/Z-Image", label: "Z-Image" },
    { value: "Tongyi-MAI/Z-Image-Turbo", label: "Z-Image Turbo" },
    { value: "baidu/ERNIE-Image-Turbo", label: "ERNIE-Image" },
    { value: "Kwai-Kolors/Kolors", label: "Kolors 可图" },
  ];

  // Sync imageModelStr from DB
  const imageConfigModelId = imageConfigs?.[0]?.model_id;
  useEffect(() => {
    const img = imageConfigs?.[0];
    if (img?.model_id) setImageModelStr(img.model_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageConfigModelId]);

  // Auto-save image model change to DB
  const handleImageModelChange = async (newModel: string) => {
    setImageModelStr(newModel);
    const img = imageConfigs?.[0];
    if (img) {
      await apiPatch(`/model-configs/${img.id}`, { model_id: newModel });
      mutateImageConfigs();
    } else {
      await apiPost("/model-configs", { name: "image", provider: "image", model_id: newModel });
      mutateImageConfigs();
    }
  };

  // Diff: compute changed segments
  const computeDiff = (original: string, refined: string) => {
    if (original === refined) return [{ text: refined, isChanged: false }];
    const tokenize = (s: string) => {
      const tokens: string[] = [];
      let buf = "";
      for (const ch of s) {
        const isCjk = /[一-鿿　-〿＀-￯]/.test(ch);
        if (isCjk) {
          if (buf) { tokens.push(buf); buf = ""; }
          tokens.push(ch);
        } else {
          buf += ch;
        }
      }
      if (buf) tokens.push(buf);
      return tokens;
    };
    const a = tokenize(original);
    const b = tokenize(refined);
    const m = a.length, n = b.length;
    if (m * n > 500000) return [{ text: refined, isChanged: false }];
    const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
    for (let i = 1; i <= m; i++)
      for (let j = 1; j <= n; j++)
        dp[i][j] = a[i-1] === b[j-1] ? dp[i-1][j-1] + 1 : Math.max(dp[i-1][j], dp[i][j-1]);
    const changed = new Set<number>();
    let i = m, j = n;
    while (i > 0 && j > 0) {
      if (a[i-1] === b[j-1]) { i--; j--; }
      else if (dp[i-1][j] >= dp[i][j-1]) { i--; }
      else { changed.add(j-1); j--; }
    }
    while (j > 0) { changed.add(j-1); j--; }
    const segments: { text: string; isChanged: boolean }[] = [];
    let curText = "", curChanged = changed.has(0);
    for (let k = 0; k < b.length; k++) {
      const isCh = changed.has(k);
      if (isCh !== curChanged) {
        if (curText) segments.push({ text: curText, isChanged: curChanged });
        curText = ""; curChanged = isCh;
      }
      curText += b[k];
    }
    if (curText) segments.push({ text: curText, isChanged: curChanged });
    return segments;
  };

  const renderDiff = (original: string, refined: string) => {
    const segments = computeDiff(original, refined);
    return <>{segments.map((seg, idx) =>
      seg.isChanged
        ? <mark key={idx} className="bg-amber-200 text-amber-900 rounded-sm px-0.5">{seg.text}</mark>
        : <span key={idx}>{seg.text}</span>
    )}</>;
  };

  // Sync note data
  useEffect(() => {
    if (note) {
      const t = note.title || "";
      const b = note.raw_text || note.content || "";
      setTitle(t);
      setBody(b);
      lastSavedTitleRef.current = t;
      lastSavedBodyRef.current = b;
      setRefinedTitle(note.refined_title || t);
      setRefinedBody(note.refined_body || b);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [note?.id]);

  // Sync script segments to editable state
  useEffect(() => {
    const segs = script?.content?.segments || [];
    if (segs.length > 0) {
      setEditedSegs(segs.map((s: { id: number; text: string; emotion?: string; visual_hint?: string }) => ({
        id: s.id,
        text: s.text || "",
        emotion: s.emotion || "",
        visual_hint: s.visual_hint || "",
      })));
    }
  }, [script?.content?.segments]);

  // Auto-save
  const saveNote = async (newTitle: string, newBody: string) => {
    if (!currentNoteId) return;
    if (newTitle === lastSavedTitleRef.current && newBody === lastSavedBodyRef.current) return;
    try {
      await apiPatch(`/notes/${currentNoteId}`, { title: newTitle, raw_text: newBody });
      lastSavedTitleRef.current = newTitle;
      lastSavedBodyRef.current = newBody;
      mutateNote();
    } catch (e) {
      console.error("Auto-save failed:", e);
    }
  };

  // Cleanup debounce timers on unmount
  useEffect(() => {
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      if (refineTimerRef.current) clearTimeout(refineTimerRef.current);
    };
  }, []);

  const scheduleSave = (newTitle: string, newBody: string) => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => saveNote(newTitle, newBody), 800);
  };

  const handleTitleChange = (val: string) => { setTitle(val); scheduleSave(val, body); };
  const handleBodyChange = (val: string) => { setBody(val); scheduleSave(title, val); };

  const folderPath = buildFolderPath(note?.folder_id ?? null, folders);
  const status = note?.status || "draft";

  const imageMaterials = materials?.filter((m) => m.type === "image") || [];
  const audioMaterials = materials?.filter((m) => m.type === "audio") || [];
  const subtitleMaterials = materials?.filter((m) => m.type === "subtitle") || [];
  const videoMaterials = materials?.filter((m) => m.type === "video") || [];
  const latestVideo = useMemo(() => {
    if (!videos || videos.length === 0) return undefined;
    return [...videos].sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )[0];
  }, [videos]);
  const MEDIA_BASE = process.env.NEXT_PUBLIC_API_URL?.replace("/api", "") || "http://localhost:8001";
  const videoSrc = latestVideo?.url || (latestVideo?.local_path ? `${MEDIA_BASE}/${latestVideo.local_path}` : null);

  const parsed = status !== "draft";
  const scripted = ["scripted", "materials_ready", "subtitles_ready", "ai_video_ready", "composed"].includes(status);
  const materialReady = ["materials_ready", "subtitles_ready", "ai_video_ready", "composed"].includes(status);
  const subtitlesReady = ["subtitles_ready", "ai_video_ready", "composed"].includes(status) || subtitleMaterials.length > 0;

  /* --- handlers --- */

  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const run = async (step: string, fn: () => Promise<void>) => {
    setProcessing(step);
    setErrorMsg(null);
    try { await fn(); }
    catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      console.error(`${step} failed:`, msg);
      setErrorMsg(msg.includes("API error") ? "请求失败，请检查模型配置后重试" : msg.slice(0, 100));
    }
    finally { setProcessing(null); }
  };

  // Step 1: Refine
  const handleRefine = () => run("refine", async () => {
    if (!currentNoteId) return;
    await saveNote(title, body);
    const result = await apiPost(`/notes/${currentNoteId}/refine`, { model_config_id: refineModelId });
    setRefinedTitle(result?.refined_title || title);
    setRefinedBody(result?.refined_body || body);
    await mutateNote();
  });

  // Step 2: Optimize script
  const handleOptimize = () => run("optimize", async () => {
    if (!currentNoteId) return;
    await apiPost(`/notes/${currentNoteId}/optimize`, { style, model_config_id: scriptModelId });
    await mutateScript();
    await mutateNote();
    setEditingScript(false);
  });

  // Save edited script segments
  const handleSaveScript = async () => {
    if (!currentNoteId || !script) return;
    const updatedContent = { ...script.content, segments: editedSegs };
    await apiPatch(`/notes/${currentNoteId}/scripts/${script.id}`, { content: updatedContent });
    await mutateScript();
    setEditingScript(false);
  };

  // Step 3: Generate images from script
  const handleGenerateMaterials = () => run("materials", async () => {
    if (!currentNoteId) return;
    await apiPost(`/notes/${currentNoteId}/materials`, { model_config_id: imageConfigs?.[0]?.id, llm_config_id: imageLlmId, image_style: imageStyle });
    await mutateMaterials();
    await mutateNote();
  });

  // Step 4: Generate TTS audio
  const handleGenerateTts = () => run("tts", async () => {
    if (!currentNoteId) return;
    await apiPost(`/notes/${currentNoteId}/tts`, { voice: ttsVoice, tts_style: ttsStyle });
    await mutateMaterials();
  });

  // Step 5: Generate subtitles
  const handleGenerateSubtitles = () => run("subtitles", async () => {
    if (!currentNoteId) return;
    await apiPost(`/notes/${currentNoteId}/subtitles`);
    await mutateMaterials();
    await mutateNote();
  });

  // Step 6: Generate segment videos
  const handleGenerateSegmentVideos = () => run("segment_video", async () => {
    if (!currentNoteId) return;
    setProgressMessage("正在生成分段视频...");
    await apiPost(`/notes/${currentNoteId}/segment-videos`);
    await mutateMaterials();
    await mutateNote();
    setProgressMessage("分段视频生成完成");
  });

  // Step 7: Compose
  const handleCompose = () => run("compose", async () => {
    if (!currentNoteId) return;
    setProgressMessage("正在合成最终视频...");
    await apiPost(`/notes/${currentNoteId}/compose`, {
      resolution: resolution === "landscape" ? "1920x1080" : "1080x1920",
    });
    await mutateVideos();
    await mutateNote();
    setProgressMessage("合成完成");
  });

  // One-click: run all steps sequentially
  const handleOneClick = () => run("oneclick", async () => {
    if (!currentNoteId) return;

    setProgressMessage("① 优化文案...");
    await saveNote(title, body);
    const refineResult = await apiPost(`/notes/${currentNoteId}/refine`, { model_config_id: refineModelId });
    if (refineResult?.refined_title) setRefinedTitle(refineResult.refined_title);
    if (refineResult?.refined_body) setRefinedBody(refineResult.refined_body);
    await mutateNote();

    setProgressMessage("② 优化脚本...");
    await apiPost(`/notes/${currentNoteId}/optimize`, { style, model_config_id: scriptModelId });
    await mutateScript();
    await mutateNote();

    setProgressMessage("③ 生成图片...");
    await apiPost(`/notes/${currentNoteId}/materials`, { model_config_id: imageConfigs?.[0]?.id, llm_config_id: imageLlmId, image_style: imageStyle });
    await mutateMaterials();
    await mutateNote();

    setProgressMessage("④ 生成音频...");
    await apiPost(`/notes/${currentNoteId}/tts`, { voice: ttsVoice, tts_style: ttsStyle });
    await mutateMaterials();

    setProgressMessage("⑤ 生成字幕...");
    await apiPost(`/notes/${currentNoteId}/subtitles`);
    await mutateMaterials();
    await mutateNote();

    setProgressMessage("⑥ 生成分段视频...");
    await apiPost(`/notes/${currentNoteId}/segment-videos`);
    await mutateMaterials();
    await mutateNote();

    setProgressMessage("⑦ 合成最终视频...");
    await apiPost(`/notes/${currentNoteId}/compose`, {
      resolution: resolution === "landscape" ? "1920x1080" : "1080x1920",
    });
    await mutateVideos();
    await mutateNote();
    setProgressMessage("全部完成！");
  });

  return (
    <div className="flex h-screen">
      {/* Content area — full width */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <div className="flex items-center justify-between px-5 py-2 border-b border-gray-200 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            {sidebarCollapsed && (
              <button className="p-1 text-gray-400 hover:text-gray-600 rounded" onClick={() => setSidebarCollapsed(false)}>
                <PanelLeft size={15} />
              </button>
            )}
            <nav className="flex items-center gap-0.5 text-xs text-gray-400 min-w-0">
              <button className="hover:text-gray-600 shrink-0" onClick={() => setNoteId(null)}>全部笔记</button>
              {folderPath.map((f) => (
                <span key={f.id} className="flex items-center gap-0.5 shrink-0">
                  <ChevronRight size={10} />
                  <button className="hover:text-gray-600" onClick={() => setFolderId(f.id)}>{f.name}</button>
                </span>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button className={`text-xs px-2.5 py-1 rounded-md border transition-colors flex items-center gap-1 ${slideDrawerOpen ? "border-emerald-300 bg-emerald-50 text-emerald-600" : "border-gray-200 text-gray-500 hover:text-gray-700 hover:bg-gray-50"}`} onClick={() => { setSlideDrawerOpen(!slideDrawerOpen); if (!slideDrawerOpen) { setDrawerOpen(false); setXhsGenOpen(false); } }}>
              <ImageIcon size={12} />
              图文生成
            </button>
            <button className={`text-xs px-2.5 py-1 rounded-md border transition-colors flex items-center gap-1 ${xhsGenOpen ? "border-rose-300 bg-rose-50 text-rose-600" : "border-gray-200 text-gray-500 hover:text-gray-700 hover:bg-gray-50"}`} onClick={() => { setXhsGenOpen(!xhsGenOpen); if (!xhsGenOpen) { setSlideDrawerOpen(false); setDrawerOpen(false); } }}>
              <ImageIcon size={12} />
              小红书图文
            </button>
            <button className={`text-xs px-2.5 py-1 rounded-md border transition-colors flex items-center gap-1 ${drawerOpen ? "border-blue-300 bg-blue-50 text-blue-600" : "border-gray-200 text-gray-500 hover:text-gray-700 hover:bg-gray-50"}`} onClick={() => { setDrawerOpen(!drawerOpen); if (!drawerOpen) setSlideDrawerOpen(false); }}>
              <Video size={12} />
              视频生成
            </button>
            <button className="p-1 text-gray-400 hover:text-gray-600 rounded" onClick={() => setConfigModalOpen(true)}>
              <Settings size={14} />
            </button>
          </div>
        </div>

        {/* Article body */}
        <div className="flex-1 overflow-y-auto">
          <div className="p-6">
            <input type="text" className="w-full text-xl font-bold text-gray-900 outline-none border-none mb-3 placeholder:text-gray-300 bg-transparent" value={title} onChange={(e) => handleTitleChange(e.target.value)} placeholder="标题" />
            <FormatToolbar onInsert={(newText) => { setBody(newText); scheduleSave(title, newText); }} />
            <textarea id="note-body-textarea" className="w-full min-h-[60vh] text-sm text-gray-700 leading-relaxed outline-none border-none resize-none bg-transparent placeholder:text-gray-300" value={body} onChange={(e) => handleBodyChange(e.target.value)} placeholder="开始输入..." />
          </div>
        </div>
      </div>

      {/* Floating overlay: Workflow panel */}
      {drawerOpen && (
        <>
          <div className="fixed inset-0 bg-black/30 backdrop-blur-sm z-40" onClick={() => setDrawerOpen(false)} />
          <div className="fixed top-0 right-0 w-1/2 h-full bg-white/95 backdrop-blur-md border-l border-gray-200/60 flex flex-col z-50 shadow-2xl">
          {/* Drawer header */}
          <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-500 flex items-center justify-center shadow-sm">
                <Wand2 size={15} className="text-white" />
              </div>
              <div>
                <span className="text-sm font-semibold text-gray-800">视频生成</span>
                <span className="text-xs text-gray-400 ml-2">7 步工作流</span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                className="text-xs px-3 py-1.5 rounded-lg bg-gradient-to-r from-blue-500 to-indigo-500 text-white hover:from-blue-600 hover:to-indigo-600 disabled:from-gray-300 disabled:to-gray-300 disabled:text-white flex items-center gap-1.5 transition-all font-medium shadow-sm"
                onClick={handleOneClick}
                disabled={processing !== null}
              >
                {processing === "oneclick" && <Loader2 size={12} className="animate-spin" />}
                <Wand2 size={12} />
                一键生成
              </button>
              <button className="w-7 h-7 flex items-center justify-center rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors" onClick={() => setDrawerOpen(false)}>
                <X size={16} />
              </button>
            </div>
          </div>

          {/* Steps list — scrollable */}
          <div className="flex-1 overflow-y-auto px-4 py-4">
            <div className="space-y-2.5">
              {/* Step 1: 优化文案 */}
              <StepSection index={1} title="优化文案" done={parsed} enabled={true} processing={processing === "refine"} expanded={expandedSteps.has(0)} onToggle={() => toggleStep(0)}>
                <div className="space-y-3 pt-3">
                  <div className="flex items-center justify-between">
                    <ModelSelector configs={llmConfigs} selectedId={refineModelId} onChange={setRefineModelId} placeholder="LLM 模型" />
                    <button className="text-xs px-3 py-1.5 rounded-lg bg-blue-500 text-white hover:bg-blue-600 disabled:bg-gray-200 disabled:text-gray-400 flex items-center gap-1.5 transition-colors font-medium" onClick={handleRefine} disabled={processing !== null}>
                      {processing === "refine" && <Loader2 size={12} className="animate-spin" />}
                      {!parsed ? "优化" : "重新优化"}
                    </button>
                  </div>
                  {parsed && (
                    <div className="space-y-2">
                      <div className="rounded-md bg-green-50 border border-transparent focus-within:border-blue-200 focus-within:bg-white px-3 py-2">
                        <input type="text" className="w-full text-sm text-gray-800 outline-none bg-transparent" value={refinedTitle} onChange={(e) => { setRefinedTitle(e.target.value); saveRefinedDebounced(e.target.value, refinedBody); }} />
                      </div>
                      <div className={`rounded-md border px-3 py-2.5 max-h-[200px] overflow-y-auto ${bodyEditing ? "bg-white border-blue-200" : "bg-green-50 border-transparent"}`}>
                        {bodyEditing ? (
                          <textarea className="w-full text-sm text-gray-800 outline-none bg-transparent resize-none leading-relaxed" rows={4} value={refinedBody} autoFocus onChange={(e) => { setRefinedBody(e.target.value); saveRefinedDebounced(refinedTitle, e.target.value); }} onBlur={() => setBodyEditing(false)} />
                        ) : (
                          <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap cursor-text" onClick={() => setBodyEditing(true)}>{renderDiff(body, refinedBody)}</p>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </StepSection>

              {/* Step 2: 优化脚本 */}
              <StepSection index={2} title="优化脚本" done={scripted} enabled={parsed} processing={processing === "optimize"} expanded={expandedSteps.has(1)} onToggle={() => toggleStep(1)}>
                <div className="space-y-3 pt-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className="flex gap-1">
                        {["knowledge", "story", "checklist"].map((s) => (
                          <button key={s} className={`text-xs px-2.5 py-1 rounded-lg border transition-colors ${style === s ? "border-blue-300 bg-blue-50 text-blue-600" : "border-gray-200 text-gray-500 hover:border-gray-300"}`} onClick={() => setStyle(s)}>
                            {{ knowledge: "知识解读", story: "故事讲述", checklist: "清单体" }[s]}
                          </button>
                        ))}
                      </div>
                      <ModelSelector configs={llmConfigs} selectedId={scriptModelId} onChange={setScriptModelId} placeholder="LLM 模型" />
                    </div>
                    {parsed && (
                      <button className="text-xs px-3 py-1.5 rounded-lg bg-blue-500 text-white hover:bg-blue-600 disabled:bg-gray-200 disabled:text-gray-400 flex items-center gap-1.5 transition-colors font-medium" onClick={handleOptimize} disabled={processing !== null}>
                        {processing === "optimize" && <Loader2 size={12} className="animate-spin" />}
                        {scripted ? "重新生成" : "生成脚本"}
                      </button>
                    )}
                  </div>
                  {!parsed && <p className="text-sm text-gray-400">请先完成「优化文案」</p>}
                  {parsed && scripted && editedSegs.length > 0 && (
                    <div className="space-y-2 max-h-[300px] overflow-y-auto">
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-gray-400">{editedSegs.length} 段</span>
                        {editingScript
                          ? <button className="text-xs text-blue-600 hover:text-blue-700" onClick={handleSaveScript}>保存修改</button>
                          : <button className="text-xs text-gray-400 hover:text-gray-600 flex items-center gap-1" onClick={() => setEditingScript(true)}><Pencil size={12} /> 编辑</button>
                        }
                      </div>
                      {editedSegs.map((seg, idx) => (
                        <div key={seg.id} className="bg-white rounded-md p-2.5">
                          {editingScript ? (
                            <div className="space-y-1.5">
                              <textarea className="w-full text-sm border border-gray-200 rounded px-2 py-1 outline-none focus:border-blue-300 resize-y min-h-[36px]" value={seg.text} onChange={(e) => { const next = [...editedSegs]; next[idx] = { ...next[idx], text: e.target.value }; setEditedSegs(next); }} />
                              <div className="flex gap-1.5">
                                <input className="flex-1 text-xs border border-gray-200 rounded px-1.5 py-0.5 outline-none focus:border-blue-300" placeholder="情绪" value={seg.emotion} onChange={(e) => { const next = [...editedSegs]; next[idx] = { ...next[idx], emotion: e.target.value }; setEditedSegs(next); }} />
                                <input className="flex-1 text-xs border border-gray-200 rounded px-1.5 py-0.5 outline-none focus:border-blue-300" placeholder="画面提示" value={seg.visual_hint} onChange={(e) => { const next = [...editedSegs]; next[idx] = { ...next[idx], visual_hint: e.target.value }; setEditedSegs(next); }} />
                              </div>
                            </div>
                          ) : (
                            <>
                              <p className="text-sm text-gray-700 leading-relaxed">{seg.text}</p>
                              <div className="flex gap-1.5 mt-1">
                                {seg.emotion && <span className="text-xs px-1.5 py-0.5 rounded bg-purple-50 text-purple-500">{seg.emotion}</span>}
                                {seg.visual_hint && <span className="text-xs px-1.5 py-0.5 rounded bg-blue-50 text-blue-500">{seg.visual_hint}</span>}
                              </div>
                            </>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </StepSection>

              {/* Step 3: 图片生成 */}
              <StepSection index={3} title="图片生成" done={materialReady} enabled={scripted} processing={processing === "materials"} expanded={expandedSteps.has(2)} onToggle={() => toggleStep(2)}>
                <div className="space-y-3 pt-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 flex-wrap">
                      <div className="flex gap-1">
                        {[{ key: "realistic", label: "真实" }, { key: "comic", label: "漫画" }, { key: "illustration", label: "插画" }, { key: "anime", label: "动漫" }, { key: "watercolor", label: "水彩" }].map((s) => (
                          <button key={s.key} className={`text-xs px-2.5 py-1 rounded-lg border transition-colors ${imageStyle === s.key ? "border-blue-300 bg-blue-50 text-blue-600" : "border-gray-200 text-gray-500 hover:border-gray-300"}`} onClick={() => setImageStyle(s.key)}>{s.label}</button>
                        ))}
                      </div>
                      <select
                        className="text-xs border border-gray-200 rounded px-1.5 py-1 bg-white text-gray-600 max-w-[140px] truncate"
                        value={imageModelStr}
                        onChange={(e) => handleImageModelChange(e.target.value)}
                      >
                        {IMAGE_MODEL_OPTIONS.map((opt) => (
                          <option key={opt.value} value={opt.value}>{opt.label}</option>
                        ))}
                      </select>
                      <ModelSelector configs={llmConfigs} selectedId={imageLlmId} onChange={setImageLlmId} placeholder="LLM 模型" />
                    </div>
                    {scripted && (
                      <button className="text-xs px-3 py-1.5 rounded-lg bg-blue-500 text-white hover:bg-blue-600 disabled:bg-gray-200 disabled:text-gray-400 flex items-center gap-1.5 transition-colors font-medium" onClick={handleGenerateMaterials} disabled={processing !== null}>
                        {processing === "materials" && <Loader2 size={12} className="animate-spin" />}
                        {imageMaterials.length > 0 ? "重新生成" : "生成图片"}
                      </button>
                    )}
                  </div>
                  {!scripted && <p className="text-sm text-gray-400">请先完成「优化脚本」</p>}
                  {processing === "materials" && (
                    <div className="flex items-center gap-2"><Loader2 size={14} className="animate-spin text-blue-500" /><span className="text-sm text-gray-600">正在生成图片...</span></div>
                  )}
                  {imageMaterials.length > 0 && !processing && (
                    <div className="grid grid-cols-3 gap-2">
                      {imageMaterials.map((m) => (
                        <div key={m.id} className="rounded-lg overflow-hidden bg-gray-50 group relative ring-1 ring-gray-100 hover:ring-blue-200 transition-all">
                          {m.url ? <img src={m.url} alt={m.prompt || "生成图片"} className="w-full aspect-video object-cover" /> : m.local_path ? <img src={`${MEDIA_BASE}/${m.local_path}`} alt={m.prompt || "生成图片"} className="w-full aspect-video object-cover" /> : <div className="w-full aspect-video bg-gray-100 flex items-center justify-center text-xs text-gray-300">...</div>}
                          <div className="absolute top-1.5 right-1.5 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                            <button className="p-1 bg-white/90 rounded-md shadow-sm hover:bg-blue-50" title="重新生成" disabled={processing !== null} onClick={async () => { try { await apiPost(`/materials/${m.id}/regenerate`, { model_config_id: imageConfigs?.[0]?.id }); await mutateMaterials(); } catch (e) { console.error("Regenerate failed:", e); alert("重新生成失败"); } }}><RotateCcw size={12} className="text-blue-500" /></button>
                            <button className="p-1 bg-white/90 rounded-md shadow-sm hover:bg-red-50" title="删除" disabled={processing !== null} onClick={async () => { try { await apiDelete(`/materials/${m.id}`); await mutateMaterials(); } catch (e) { console.error("Delete failed:", e); alert("删除失败"); } }}><X size={12} className="text-red-400" /></button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </StepSection>

              {/* Step 4: 音频生成 */}
              <StepSection index={4} title="音频生成" done={audioMaterials.length > 0} enabled={scripted} processing={processing === "tts"} expanded={expandedSteps.has(3)} onToggle={() => toggleStep(3)}>
                <div className="space-y-3 pt-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className="flex gap-1">
                        {[{ key: "clear", label: "清晰" }, { key: "normal", label: "标准" }, { key: "brisk", label: "轻快" }, { key: "gentle", label: "温柔" }, { key: "serious", label: "严肃" }, { key: "magnetic", label: "磁性" }].map((s) => (
                          <button key={s.key} className={`text-xs px-2.5 py-1 rounded-lg border transition-colors ${ttsStyle === s.key ? "border-blue-300 bg-blue-50 text-blue-600" : "border-gray-200 text-gray-500 hover:border-gray-300"}`} onClick={() => setTtsStyle(s.key)}>{s.label}</button>
                        ))}
                      </div>
                      <select className="text-xs border border-gray-200 rounded-lg px-2 py-1 bg-white text-gray-600 max-w-[130px] truncate" value={ttsVoice} onChange={(e) => setTtsVoice(e.target.value)}>
                        <optgroup label="女声">{TTS_VOICE_OPTIONS.filter((o) => o.group === "女声").map((opt) => (<option key={opt.value} value={opt.value}>{opt.label}</option>))}</optgroup>
                        <optgroup label="男声">{TTS_VOICE_OPTIONS.filter((o) => o.group === "男声").map((opt) => (<option key={opt.value} value={opt.value}>{opt.label}</option>))}</optgroup>
                      </select>
                    </div>
                    {scripted && (
                      <button className="text-xs px-3 py-1.5 rounded-lg bg-blue-500 text-white hover:bg-blue-600 disabled:bg-gray-200 disabled:text-gray-400 flex items-center gap-1.5 transition-colors font-medium" onClick={handleGenerateTts} disabled={processing !== null}>
                        {processing === "tts" && <Loader2 size={12} className="animate-spin" />}
                        {audioMaterials.length > 0 ? "重新生成" : "生成音频"}
                      </button>
                    )}
                  </div>
                  {!scripted && <p className="text-sm text-gray-400">请先完成「优化脚本」</p>}
                  {processing === "tts" && (
                    <div className="flex items-center gap-2"><Loader2 size={14} className="animate-spin text-blue-500" /><span className="text-sm text-gray-600">正在生成语音...</span></div>
                  )}
                  {audioMaterials.length > 0 && !processing && (
                    <div className="space-y-1.5">
                      {audioMaterials.map((m) => (
                        <div key={m.id} className="flex items-center gap-2 bg-white rounded-md px-3 py-1.5">
                          <Music size={14} className="text-gray-400" />
                          <span className="text-sm text-gray-600 flex-1 truncate">{m.prompt || "音频"}</span>
                          {m.local_path && <audio controls className="h-6" src={`${MEDIA_BASE}/${m.local_path}`} />}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </StepSection>

              {/* Step 5: 生成字幕 */}
              <StepSection index={5} title="生成字幕" done={subtitlesReady} enabled={materialReady} processing={processing === "subtitles"} expanded={expandedSteps.has(4)} onToggle={() => toggleStep(4)}>
                <div className="space-y-3 pt-3">
                  <div className="flex items-center justify-between">
                    {!materialReady && <p className="text-sm text-gray-400">请先完成「图片生成」</p>}
                    {materialReady && (
                      <button className="text-xs px-3 py-1.5 rounded-lg bg-blue-500 text-white hover:bg-blue-600 disabled:bg-gray-200 disabled:text-gray-400 flex items-center gap-1.5 transition-colors font-medium ml-auto" onClick={handleGenerateSubtitles} disabled={processing !== null}>
                        {processing === "subtitles" && <Loader2 size={12} className="animate-spin" />}
                        {subtitleMaterials.length > 0 ? "重新生成" : "生成字幕"}
                      </button>
                    )}
                  </div>
                  {processing === "subtitles" && (
                    <div className="flex items-center gap-2"><Loader2 size={14} className="animate-spin text-blue-500" /><span className="text-sm text-gray-600">正在生成字幕...</span></div>
                  )}
                  {subtitleMaterials.length > 0 && !processing && (
                    <div className="space-y-1.5">
                      {subtitleMaterials.map((m) => {
                        const segId = String((m.meta_data as Record<string, unknown>)?.segment_id ?? "");
                        const phases = ((m.meta_data as Record<string, unknown>)?.phases as string[]) || [];
                        return (
                          <div key={m.id} className="bg-white rounded-md px-3 py-2">
                            <div className="flex items-center gap-2 mb-1">
                              <Subtitles size={14} className="text-gray-400" />
                              <span className="text-xs text-gray-400">片段 {segId}</span>
                            </div>
                            <div className="space-y-0.5">
                              {phases.map((p, pi) => (
                                <p key={pi} className="text-sm text-gray-600">{p.replace(/\n/g, " ")}</p>
                              ))}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </StepSection>

              {/* Step 6: 生成视频 */}
              <StepSection index={6} title="生成视频" done={videoMaterials.length > 0} enabled={subtitlesReady && audioMaterials.length > 0} processing={processing === "segment_video"} expanded={expandedSteps.has(5)} onToggle={() => toggleStep(5)}>
                <div className="space-y-3 pt-3">
                  <div className="flex items-center justify-between">
                    {!(subtitlesReady && audioMaterials.length > 0) && <p className="text-sm text-gray-400">请先完成「音频生成」和「生成字幕」</p>}
                    {subtitlesReady && audioMaterials.length > 0 && (
                      <button className="text-xs px-3 py-1.5 rounded-lg bg-blue-500 text-white hover:bg-blue-600 disabled:bg-gray-200 disabled:text-gray-400 flex items-center gap-1.5 transition-colors font-medium ml-auto" onClick={handleGenerateSegmentVideos} disabled={processing !== null}>
                        {processing === "segment_video" && <Loader2 size={12} className="animate-spin" />}
                        {videoMaterials.length > 0 ? "重新生成" : "生成视频"}
                      </button>
                    )}
                  </div>
                  {processing === "segment_video" && (
                    <div className="flex items-center gap-2"><Loader2 size={14} className="animate-spin text-blue-500" /><span className="text-sm text-gray-600">{progressMessage || "正在生成分段视频..."}</span></div>
                  )}
                  {videoMaterials.length > 0 && !processing && (
                    <div className="grid grid-cols-2 gap-2">
                      {videoMaterials.map((m) => {
                        const segId = String((m.meta_data as Record<string, unknown>)?.segment_id ?? "");
                        const duration = (m.meta_data as Record<string, unknown>)?.duration as number | undefined;
                        return (
                          <div key={m.id} className="rounded-lg overflow-hidden bg-gray-50 ring-1 ring-gray-100">
                            {m.local_path ? <video src={`${MEDIA_BASE}/${m.local_path}`} controls className="w-full aspect-video object-cover" /> : m.url ? <video src={m.url} controls className="w-full aspect-video object-cover" /> : <div className="w-full aspect-video bg-gray-100 flex items-center justify-center text-xs text-gray-300">...</div>}
                            <div className="px-2.5 py-1.5 text-xs text-gray-500 flex items-center justify-between">
                              <span className="truncate">片段 {segId}</span>
                              {duration && <span className="font-medium">{Number(duration).toFixed(1)}s</span>}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </StepSection>

              {/* Step 7: 合成视频 */}
              <StepSection index={7} title="合成视频" done={!!videoSrc} enabled={videoMaterials.length > 0} processing={processing === "compose"} expanded={expandedSteps.has(6)} onToggle={() => toggleStep(6)}>
                <div className="space-y-3 pt-3">
                  <div className="flex items-center justify-between">
                    <div className="flex gap-2">
                      <button className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${resolution === "landscape" ? "border-blue-300 bg-blue-50 text-blue-600" : "border-gray-200 text-gray-500 hover:border-gray-300"}`} onClick={() => setResolution("landscape")}>横屏</button>
                      <button className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${resolution === "portrait" ? "border-blue-300 bg-blue-50 text-blue-600" : "border-gray-200 text-gray-500 hover:border-gray-300"}`} onClick={() => setResolution("portrait")}>竖屏</button>
                    </div>
                    {videoMaterials.length > 0 && (
                      <button className="text-xs px-3 py-1.5 rounded-lg bg-blue-500 text-white hover:bg-blue-600 disabled:bg-gray-200 disabled:text-gray-400 flex items-center gap-1.5 transition-colors font-medium" onClick={handleCompose} disabled={processing !== null}>
                        {processing === "compose" && <Loader2 size={12} className="animate-spin" />}
                        {videoSrc ? "重新合成" : "合成"}
                      </button>
                    )}
                  </div>
                  {videoMaterials.length === 0 && <p className="text-sm text-gray-400">请先完成「生成视频」</p>}
                  {processing === "compose" && (
                    <div className="space-y-2">
                      <div className="w-full bg-gray-100 rounded-full h-2 overflow-hidden"><div className="bg-blue-500 h-full rounded-full animate-pulse" style={{ width: "60%" }} /></div>
                      <span className="text-sm text-gray-600">{progressMessage}</span>
                    </div>
                  )}
                  {videoSrc && !processing && (
                    <div className="space-y-3">
                      <div className="rounded-lg overflow-hidden bg-gray-50 ring-1 ring-gray-100">
                        <video src={videoSrc} controls className="w-full" />
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-gray-400">{latestVideo?.resolution} | {latestVideo?.duration?.toFixed(1)}s</span>
                        <a href={videoSrc} download className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg border border-gray-200 text-gray-500 hover:text-gray-700 hover:border-gray-300 transition-colors"><Download size={12} /> 下载</a>
                      </div>
                    </div>
                  )}
                </div>
              </StepSection>
            </div>
          </div>

          {/* One-click progress */}
          {processing === "oneclick" && (
            <div className="px-5 py-2 border-t border-gray-100 shrink-0 bg-blue-50/50">
              <p className="text-xs text-blue-600 text-center">{progressMessage}</p>
            </div>
          )}

          {/* Error message */}
          {errorMsg && (
            <div className="px-5 py-3 border-t border-red-100 shrink-0 bg-red-50">
              <div className="flex items-start gap-2">
                <span className="text-xs font-medium text-red-700">操作失败</span>
                <span className="text-xs text-red-500 flex-1">{errorMsg}</span>
              </div>
            </div>
          )}
        </div>
        </>
      )}

      {/* Slide generation drawer */}
      {slideDrawerOpen && <SlideDrawer />}

      {/* Xiaohongshu generator */}
      {xhsGenOpen && (
        <XhsGenerator
          initialTitle={title}
          initialContent={body}
          onClose={() => setXhsGenOpen(false)}
        />
      )}
    </div>
  );
}
