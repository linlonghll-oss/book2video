"use client";

import { useState, useEffect, useRef } from "react";
import useSWR from "swr";
import { fetcher, apiPost, apiPatch } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { Note, Script, Material, ModelConfig } from "@/lib/types";
import {
  Loader2, Check, ChevronDown, ChevronUp,
  Wand2, Pencil, Image as ImageIcon,
  Download, Presentation, RefreshCw, Zap,
  Info, AlertTriangle, X,
} from "lucide-react";

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
  2: <Wand2 size={13} />,
  3: <Presentation size={13} />,
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
    <div className={`rounded-xl border transition-all ${enabled ? (expanded ? "border-emerald-200 bg-white shadow-sm" : "border-gray-200 bg-white hover:border-gray-300") : "border-gray-100 bg-gray-50/50 opacity-60"}`}>
      <button className="w-full flex items-center gap-3 px-4 py-3 text-left" onClick={onToggle} disabled={!enabled}>
        {done ? (
          <span className="w-7 h-7 rounded-full bg-gradient-to-br from-green-400 to-green-500 text-white flex items-center justify-center shrink-0 shadow-sm"><Check size={13} /></span>
        ) : processing ? (
          <span className="w-7 h-7 rounded-full bg-gradient-to-br from-emerald-400 to-emerald-500 text-white flex items-center justify-center shrink-0 shadow-sm"><Loader2 size={13} className="animate-spin" /></span>
        ) : (
          <span className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-xs font-semibold ${enabled ? "bg-gray-100 text-gray-500" : "bg-gray-100 text-gray-300"}`}>{STEP_ICONS[index] ?? index}</span>
        )}
        <span className={`text-sm font-medium flex-1 ${enabled ? "text-gray-800" : "text-gray-300"}`}>{title}</span>
        {done && !expanded && <span className="text-xs text-green-500 mr-1">已完成</span>}
        {expanded ? <ChevronUp size={15} className="text-gray-400" /> : <ChevronDown size={15} className="text-gray-400" />}
      </button>
      {expanded && enabled && (
        <div className="px-4 pb-4 pt-0 border-t border-gray-100">{children}</div>
      )}
    </div>
  );
}

/* ---------- Image model options ---------- */

const IMAGE_MODEL_OPTIONS = [
  { value: "pollinations-flux", label: "🆓 Pollinations Flux" },
  { value: "pollinations-turbo", label: "🆓 Pollinations Turbo" },
  { value: "gemini-flash-image", label: "🆓 Gemini Flash" },
  { value: "Qwen/Qwen-Image", label: "Qwen-Image ⭐" },
  { value: "Tongyi-MAI/Z-Image", label: "Z-Image" },
  { value: "Tongyi-MAI/Z-Image-Turbo", label: "Z-Image Turbo" },
  { value: "baidu/ERNIE-Image-Turbo", label: "ERNIE-Image" },
  { value: "Kwai-Kolors/Kolors", label: "Kolors 可图" },
];

/* ---------- Style presets ---------- */
interface StylePreset {
  key: string;
  label: string;
  icon: string;
  desc: string;
}

// Default styles (fallback if API unavailable)
const DEFAULT_STYLES: StylePreset[] = [
  { key: "realistic", label: "写实摄影", icon: "📷", desc: "电影级实拍质感，光影细腻" },
  { key: "illustration", label: "现代插画", icon: "🎨", desc: "扁平化数字插画，色彩明快" },
  { key: "anime", label: "动漫风", icon: "🌸", desc: "日系动漫风格，明快鲜艳" },
  { key: "watercolor", label: "水彩手绘", icon: "🖌️", desc: "柔和水彩质感，清新文艺" },
  { key: "minimal", label: "极简商务", icon: "◻️", desc: "简约几何构图，高级灰调" },
  { key: "cinematic", label: "电影质感", icon: "🎬", desc: "宽银幕电影色调，景深感强" },
];

/* ---------- Main drawer ---------- */

export default function SlideDrawer() {
  const { currentNoteId, setSlideDrawerOpen } = useAppStore();

  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const lastSavedTitleRef = useRef("");
  const lastSavedBodyRef = useRef("");

  // Workflow state
  const [style, setStyle] = useState("knowledge");
  const [processing, setProcessing] = useState<string | null>(null);
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

  // Script segments
  const [editedSegs, setEditedSegs] = useState<{ id: number; text: string; emotion: string; visual_hint: string }[]>([]);
  const [editingScript, setEditingScript] = useState(false);

  // Model selection
  const [refineModelId, setRefineModelId] = useState<number | undefined>(undefined);
  const [scriptModelId, setScriptModelId] = useState<number | undefined>(undefined);
  const [slideLlmId, setSlideLlmId] = useState<number | undefined>(undefined);
  const [slideImageModel, setSlideImageModel] = useState<string>("pollinations-flux");
  const [slideImageStyle, setSlideImageStyle] = useState<string>("realistic");
  const [outputFormat, setOutputFormat] = useState<string>("pptx");
  const [geminiApiKey, setGeminiApiKey] = useState<string>("");

  // Style presets from API
  const [stylePresets, setStylePresets] = useState<StylePreset[]>(DEFAULT_STYLES);

  // Progress tracking for one-click generation
  const [progressStep, setProgressStep] = useState<string>("");
  const [progressDetail, setProgressDetail] = useState<string>("");

  // Data
  const { data: note, mutate: mutateNote } = useSWR<Note>(
    currentNoteId ? `/notes/${currentNoteId}` : null, fetcher
  );
  const { data: script, mutate: mutateScript } = useSWR<Script>(
    currentNoteId ? `/notes/${currentNoteId}/scripts/latest` : null, fetcher, { shouldRetryOnError: false }
  );
  const { data: materials, mutate: mutateMaterials } = useSWR<Material[]>(
    currentNoteId ? `/notes/${currentNoteId}/materials` : null, fetcher
  );
  const { data: llmConfigs } = useSWR<ModelConfig[]>("/model-configs?provider=llm", fetcher);
  const { data: imageConfigs, mutate: mutateImageConfigs } = useSWR<ModelConfig[]>("/model-configs?provider=image", fetcher);

  // Close on Escape key
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSlideDrawerOpen(false);
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [setSlideDrawerOpen]);

  // Fetch image style presets from API
  useEffect(() => {
    fetcher("/image-styles").then((data: { styles: StylePreset[] }) => {
      if (data?.styles?.length) setStylePresets(data.styles);
    }).catch((e) => { console.error("Failed to load image styles:", e); }); // Keep defaults on error
  }, []);

  // Sync slideImageModel from DB image config
  const imageConfigModelId = imageConfigs?.[0]?.model_id;
  useEffect(() => {
    const img = imageConfigs?.[0];
    if (img?.model_id) setSlideImageModel(img.model_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageConfigModelId]);

  // When user picks a different image model, auto-save to DB
  const handleImageModelChange = async (newModel: string) => {
    setSlideImageModel(newModel);
    const img = imageConfigs?.[0];
    if (img) {
      await apiPatch(`/model-configs/${img.id}`, { model_id: newModel });
      mutateImageConfigs();
    } else {
      await apiPost("/model-configs", { name: "image", provider: "image", model_id: newModel });
      mutateImageConfigs();
    }
  };

  const status = note?.status || "draft";

  // Find the PPT/XHS material
  const slideMaterial = materials?.find((m) => m.type === "slide");
  const slideMeta = slideMaterial?.meta_data as Record<string, unknown> | undefined;
  const pageCount = (slideMeta?.page_count as number) || 0;
  const hasAiBg = (slideMeta?.has_ai_bg as boolean) || false;
  const slideFormat = (slideMeta?.output_format as string) || "pptx";
  const xhsImagePaths = (slideMeta?.image_paths as string[]) || [];

  // Check if the existing slide matches the currently selected format
  const slideFormatMatch = slideMaterial && slideFormat === outputFormat;

  const parsed = status !== "draft";
  const scripted = ["scripted", "materials_ready", "subtitles_ready", "ai_video_ready", "slides_ready", "composed"].includes(status);

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

  // Sync script segments
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
      if (refineTimerRef.current) clearTimeout(refineTimerRef.current);
    };
  }, []);

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

  // Step 3: Generate PPT
  const handleGenerateSlides = () => run("slides", async () => {
    if (!currentNoteId) return;
    const imageConfigId = imageConfigs?.[0]?.id;
    await apiPost(`/notes/${currentNoteId}/slides`, { model_config_id: imageConfigId, model_id: slideImageModel, llm_config_id: slideLlmId, image_style: slideImageStyle, output_format: outputFormat, gemini_api_key: geminiApiKey || undefined });
    await mutateMaterials();
    await mutateNote();
  });

  // One-click
  const handleOneClick = () => run("oneclick", async () => {
    if (!currentNoteId) return;

    setProgressStep("refine");
    setProgressDetail("正在优化文案内容...");
    await saveNote(title, body);
    const refineResult = await apiPost(`/notes/${currentNoteId}/refine`, { model_config_id: refineModelId });
    if (refineResult?.refined_title) setRefinedTitle(refineResult.refined_title);
    if (refineResult?.refined_body) setRefinedBody(refineResult.refined_body);
    await mutateNote();

    setProgressStep("optimize");
    setProgressDetail("正在生成脚本分镜...");
    await apiPost(`/notes/${currentNoteId}/optimize`, { style, model_config_id: scriptModelId });
    await mutateScript();
    await mutateNote();

    setProgressStep("slides");
    setProgressDetail(`正在生成${outputFormat === "xiaohongshu" ? "小红书图文" : "PPT"}（AI 绘图需要较长时间）...`);
    await apiPost(`/notes/${currentNoteId}/slides`, { model_config_id: imageConfigs?.[0]?.id, model_id: slideImageModel, llm_config_id: slideLlmId, image_style: slideImageStyle, output_format: outputFormat, gemini_api_key: geminiApiKey || undefined });
    await mutateMaterials();
    await mutateNote();

    setProgressStep("");
    setProgressDetail("");
  });

  // Download PPT
  const MEDIA_BASE = process.env.NEXT_PUBLIC_API_URL?.replace("/api", "") || "http://localhost:8001";
  const pptDownloadUrl = slideMaterial?.local_path
    ? `${MEDIA_BASE}/${slideMaterial.local_path}`
    : null;

  return (
    <>
      <div className="fixed inset-0 bg-black/30 backdrop-blur-sm z-40" onClick={() => setSlideDrawerOpen(false)} />
      <div className="fixed top-0 right-0 w-1/2 h-full bg-white/95 backdrop-blur-md border-l border-gray-200/60 flex flex-col z-50 shadow-2xl">
        {/* Drawer header */}
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-500 to-teal-500 flex items-center justify-center shadow-sm">
              <Presentation size={15} className="text-white" />
            </div>
            <div>
              <span className="text-sm font-semibold text-gray-800">图文生成</span>
              <span className="text-xs text-gray-400 ml-2">3 步工作流</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              className="text-xs px-3 py-1.5 rounded-lg bg-gradient-to-r from-emerald-500 to-teal-500 text-white hover:from-emerald-600 hover:to-teal-600 disabled:from-gray-300 disabled:to-gray-300 disabled:text-white flex items-center gap-1.5 transition-all font-medium shadow-sm"
              onClick={handleOneClick}
              disabled={processing !== null}
            >
              {processing === "oneclick" && <Loader2 size={12} className="animate-spin" />}
              <Wand2 size={12} />
              一键生成
            </button>
            <button
              className="w-7 h-7 flex items-center justify-center rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
              onClick={() => setSlideDrawerOpen(false)}
              title="关闭 (Esc)"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Steps list */}
        <div className="flex-1 overflow-y-auto px-4 py-4">
          <div className="space-y-2.5">
            {/* Step 1: 优化文案 */}
            <StepSection index={1} title="优化文案" done={parsed} enabled={true} processing={processing === "refine"} expanded={expandedSteps.has(0)} onToggle={() => toggleStep(0)}>
              <div className="space-y-3 pt-3">
                <div className="flex items-center justify-between">
                  <ModelSelector configs={llmConfigs} selectedId={refineModelId} onChange={setRefineModelId} placeholder="LLM 模型" />
                  <button className="text-xs px-3 py-1.5 rounded-lg bg-emerald-500 text-white hover:bg-emerald-600 disabled:bg-gray-200 disabled:text-gray-400 flex items-center gap-1.5 transition-colors font-medium" onClick={handleRefine} disabled={processing !== null}>
                    {processing === "refine" && <Loader2 size={12} className="animate-spin" />}
                    {!parsed ? "优化" : "重新优化"}
                  </button>
                </div>
                {parsed && (
                  <div className="space-y-2">
                    <div className="rounded-md bg-green-50 border border-transparent focus-within:border-emerald-200 focus-within:bg-white px-3 py-2">
                      <input type="text" className="w-full text-sm text-gray-800 outline-none bg-transparent" value={refinedTitle} onChange={(e) => { setRefinedTitle(e.target.value); saveRefinedDebounced(e.target.value, refinedBody); }} />
                    </div>
                    <div className={`rounded-md border px-3 py-2.5 max-h-[200px] overflow-y-auto ${bodyEditing ? "bg-white border-emerald-200" : "bg-green-50 border-transparent"}`}>
                      {bodyEditing ? (
                        <textarea className="w-full text-sm text-gray-800 outline-none bg-transparent resize-none leading-relaxed" rows={4} value={refinedBody} autoFocus onChange={(e) => { setRefinedBody(e.target.value); saveRefinedDebounced(refinedTitle, e.target.value); }} onBlur={() => setBodyEditing(false)} />
                      ) : (
                        <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap cursor-text" onClick={() => setBodyEditing(true)}>{refinedBody}</p>
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
                        <button key={s} className={`text-xs px-2.5 py-1 rounded-lg border transition-colors ${style === s ? "border-emerald-300 bg-emerald-50 text-emerald-600" : "border-gray-200 text-gray-500 hover:border-gray-300"}`} onClick={() => setStyle(s)}>
                          {{ knowledge: "知识解读", story: "故事讲述", checklist: "清单体" }[s]}
                        </button>
                      ))}
                    </div>
                    <ModelSelector configs={llmConfigs} selectedId={scriptModelId} onChange={setScriptModelId} placeholder="LLM 模型" />
                  </div>
                  {parsed && (
                    <button className="text-xs px-3 py-1.5 rounded-lg bg-emerald-500 text-white hover:bg-emerald-600 disabled:bg-gray-200 disabled:text-gray-400 flex items-center gap-1.5 transition-colors font-medium" onClick={handleOptimize} disabled={processing !== null}>
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
                        ? <button className="text-xs text-emerald-600 hover:text-emerald-700" onClick={handleSaveScript}>保存修改</button>
                        : <button className="text-xs text-gray-400 hover:text-gray-600 flex items-center gap-1" onClick={() => setEditingScript(true)}><Pencil size={12} /> 编辑</button>
                      }
                    </div>
                    {editedSegs.map((seg, idx) => (
                      <div key={seg.id} className="bg-white rounded-md p-2.5">
                        {editingScript ? (
                          <div className="space-y-1.5">
                            <textarea className="w-full text-sm border border-gray-200 rounded px-2 py-1 outline-none focus:border-emerald-300 resize-y min-h-[36px]" value={seg.text} onChange={(e) => { const next = [...editedSegs]; next[idx] = { ...next[idx], text: e.target.value }; setEditedSegs(next); }} />
                            <div className="flex gap-1.5">
                              <input className="flex-1 text-xs border border-gray-200 rounded px-1.5 py-0.5 outline-none focus:border-emerald-300" placeholder="情绪" value={seg.emotion} onChange={(e) => { const next = [...editedSegs]; next[idx] = { ...next[idx], emotion: e.target.value }; setEditedSegs(next); }} />
                              <input className="flex-1 text-xs border border-gray-200 rounded px-1.5 py-0.5 outline-none focus:border-emerald-300" placeholder="画面提示" value={seg.visual_hint} onChange={(e) => { const next = [...editedSegs]; next[idx] = { ...next[idx], visual_hint: e.target.value }; setEditedSegs(next); }} />
                            </div>
                          </div>
                        ) : (
                          <>
                            <p className="text-sm text-gray-700 leading-relaxed">{seg.text}</p>
                            <div className="flex gap-1.5 mt-1">
                              {seg.emotion && <span className="text-xs px-1.5 py-0.5 rounded bg-purple-50 text-purple-500">{seg.emotion}</span>}
                              {seg.visual_hint && <span className="text-xs px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-500">{seg.visual_hint}</span>}
                            </div>
                          </>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </StepSection>

            {/* Step 3: 生成图文 */}
            <StepSection index={3} title={outputFormat === "xiaohongshu" ? "生成小红书图文" : "生成 PPT"} done={!!slideFormatMatch} enabled={scripted} processing={processing === "slides"} expanded={expandedSteps.has(2)} onToggle={() => toggleStep(2)}>
              <div className="space-y-3 pt-3">
                {!scripted && <p className="text-sm text-gray-400">请先完成「优化脚本」</p>}
                {scripted && (
                  <>
                    {/* Output format selector */}
                    <div className="space-y-2">
                      <span className="text-xs text-gray-500 font-medium">输出格式</span>
                      <div className="flex gap-2">
                        <button
                          className={`flex-1 text-xs py-2 rounded-lg border-2 transition-all ${outputFormat === "pptx" ? "border-emerald-400 bg-emerald-50 text-emerald-700 font-medium" : "border-gray-200 text-gray-500 hover:border-gray-300"}`}
                          onClick={() => setOutputFormat("pptx")}
                        >
                          <div className="font-semibold">PPT 文稿</div>
                          <div className="text-xs text-gray-400 mt-0.5">16:9 横版</div>
                        </button>
                        <button
                          className={`flex-1 text-xs py-2 rounded-lg border-2 transition-all ${outputFormat === "xiaohongshu" ? "border-rose-400 bg-rose-50 text-rose-700 font-medium" : "border-gray-200 text-gray-500 hover:border-gray-300"}`}
                          onClick={() => setOutputFormat("xiaohongshu")}
                        >
                          <div className="font-semibold">小红书图文</div>
                          <div className="text-xs text-gray-400 mt-0.5">3:4 竖版</div>
                        </button>
                      </div>
                    </div>

                    {/* Model & API Key config */}
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-gray-500 font-medium">图片模型</span>
                        <div className="flex items-center gap-1.5">
                          <Info size={11} className="text-gray-300 cursor-help" />
                        </div>
                      </div>
                      <div className="flex items-center gap-2 flex-wrap">
                        <select
                          className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white text-gray-600 max-w-[150px] truncate"
                          value={slideImageModel}
                          onChange={(e) => handleImageModelChange(e.target.value)}
                        >
                          {IMAGE_MODEL_OPTIONS.map((opt) => (
                            <option key={opt.value} value={opt.value}>{opt.label}</option>
                          ))}
                        </select>
                        <ModelSelector configs={llmConfigs} selectedId={slideLlmId} onChange={setSlideLlmId} placeholder="LLM 提示词" />
                      </div>
                      {slideImageModel === "gemini-flash-image" && (
                        <div className="flex items-center gap-2 mt-1.5 bg-amber-50 rounded-lg px-2.5 py-1.5 border border-amber-100">
                          <span className="text-xs text-amber-700 whitespace-nowrap font-medium">Key:</span>
                          <input
                            type="password"
                            className="text-xs border-0 bg-transparent text-gray-700 flex-1 outline-none placeholder-gray-400"
                            placeholder="从 aistudio.google.com 获取（免费 500张/天）"
                            value={geminiApiKey}
                            onChange={(e) => setGeminiApiKey(e.target.value)}
                          />
                        </div>
                      )}
                    </div>

                    {/* Style selector — visual cards */}
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-gray-500 font-medium">画面风格</span>
                        <button
                          className="text-xs text-emerald-500 hover:text-emerald-600 flex items-center gap-1"
                          onClick={() => setSlideImageStyle("realistic")}
                          title="恢复默认风格"
                        >
                          <RefreshCw size={10} /> 重置
                        </button>
                      </div>
                      <div className="grid grid-cols-3 gap-1.5">
                        {stylePresets.map((s) => (
                          <button
                            key={s.key}
                            className={`text-left px-2 py-1.5 rounded-lg border transition-all group ${
                              slideImageStyle === s.key
                                ? "border-emerald-400 bg-emerald-50 shadow-sm"
                                : "border-gray-150 bg-white hover:border-gray-300 hover:bg-gray-50"
                            }`}
                            onClick={() => setSlideImageStyle(s.key)}
                            title={s.desc}
                          >
                            <div className="flex items-center gap-1">
                              <span className="text-sm">{s.icon}</span>
                              <span className={`text-[11px] font-medium truncate ${slideImageStyle === s.key ? "text-emerald-700" : "text-gray-600"}`}>
                                {s.label}
                              </span>
                            </div>
                            <div className="text-[10px] text-gray-400 mt-0.5 line-clamp-1">{s.desc}</div>
                          </button>
                        ))}
                      </div>
                      {slideImageStyle && (
                        <p className="text-[10px] text-gray-400 italic">
                          {stylePresets.find(s => s.key === slideImageStyle)?.desc || "选择一个风格以获得最佳效果"}
                        </p>
                      )}
                    </div>

                    {/* Format mismatch hint */}
                    {slideMaterial && !slideFormatMatch && (
                      <div className={`text-xs px-3 py-2 rounded-lg flex items-center gap-2 ${outputFormat === "xiaohongshu" ? "bg-rose-50 text-rose-600" : "bg-emerald-50 text-emerald-600"}`}>
                        <AlertTriangle size={12} />
                        当前已有{slideFormat === "xiaohongshu" ? "小红书" : "PPT"}格式结果，切换格式后需重新生成
                      </div>
                    )}

                    {/* Generate button */}
                    <div className="flex items-center justify-end gap-2">
                      {processing === "slides" && (
                        <div className="flex items-center gap-2 text-xs text-gray-500">
                          <Loader2 size={12} className="animate-spin text-emerald-500" />
                          <span>AI 正在绘制背景图中...</span>
                        </div>
                      )}
                      <button
                        className={`text-xs px-4 py-1.5 rounded-lg text-white disabled:bg-gray-200 disabled:text-gray-400 flex items-center gap-1.5 transition-all font-medium shadow-sm ${
                          outputFormat === "xiaohongshu"
                            ? "bg-rose-500 hover:bg-rose-600 active:scale-95"
                            : "bg-emerald-500 hover:bg-emerald-600 active:scale-95"
                        }`}
                        onClick={handleGenerateSlides}
                        disabled={processing !== null}
                      >
                        {processing === "slides" && <Loader2 size={12} className="animate-spin" />}
                        {slideFormatMatch ? (
                          <><RefreshCw size={12} /> 重新生成</>
                        ) : outputFormat === "xiaohongshu" ? (
                          <><Zap size={12} /> 生成小红书图文</>
                        ) : (
                          <><Zap size={12} /> 生成 PPT</>
                        )}
                      </button>
                    </div>
                  </>
                )}
                {processing === "slides" && (
                  <div className="flex items-center gap-2"><Loader2 size={14} className="animate-spin text-emerald-500" /><span className="text-sm text-gray-600">正在生成{outputFormat === "xiaohongshu" ? "小红书图文" : "PPT"}（AI 绘图中，耗时较长请耐心等待）...</span></div>
                )}
                {/* Result card */}
                {slideFormatMatch && !processing && (
                  <>
                    {/* 小红书 image previews */}
                    {slideFormat === "xiaohongshu" && xhsImagePaths.length > 0 && (
                      <div className="grid grid-cols-3 gap-2">
                        {xhsImagePaths.map((p, i) => (
                          <div key={i} className="rounded-lg overflow-hidden bg-gray-50 ring-1 ring-gray-100 hover:ring-rose-200 transition-all">
                            <img src={`${MEDIA_BASE}/${p}`} alt={`小红书图片 ${i + 1}`} className="w-full aspect-[3/4] object-cover" />
                          </div>
                        ))}
                      </div>
                    )}
                    {/* Download card */}
                    <div className={`rounded-xl border p-5 ${slideFormat === "xiaohongshu" ? "border-rose-100 bg-gradient-to-br from-rose-50 to-pink-50" : "border-emerald-100 bg-gradient-to-br from-emerald-50 to-teal-50"}`}>
                      <div className="flex items-start gap-4">
                        <div className={`w-14 h-14 rounded-xl flex items-center justify-center shadow-md shrink-0 ${slideFormat === "xiaohongshu" ? "bg-gradient-to-br from-rose-500 to-pink-500" : "bg-gradient-to-br from-emerald-500 to-teal-500"}`}>
                          {slideFormat === "xiaohongshu" ? <ImageIcon size={24} className="text-white" /> : <Presentation size={24} className="text-white" />}
                        </div>
                        <div className="flex-1 min-w-0">
                          <h4 className="text-sm font-semibold text-gray-800">{slideFormat === "xiaohongshu" ? "小红书图文已生成" : "PPT 文件已生成"}</h4>
                          <p className="text-xs text-gray-500 mt-1">
                            {pageCount} 页 · {hasAiBg ? "AI 生成背景" : "渐变背景"}
                          </p>
                          <div className="flex items-center gap-3 mt-3">
                            {pptDownloadUrl && (
                              <a
                                href={pptDownloadUrl}
                                download
                                className={`text-xs px-3 py-1.5 rounded-lg text-white flex items-center gap-1.5 transition-colors font-medium ${slideFormat === "xiaohongshu" ? "bg-rose-500 hover:bg-rose-600" : "bg-emerald-500 hover:bg-emerald-600"}`}
                              >
                                <Download size={12} />
                                {slideFormat === "xiaohongshu" ? "下载图片包" : "下载 PPT"}
                              </a>
                            )}
                            <button
                              className={`text-xs px-3 py-1.5 rounded-lg border flex items-center gap-1.5 transition-colors font-medium ${slideFormat === "xiaohongshu" ? "border-rose-200 text-rose-600 hover:bg-rose-50" : "border-emerald-200 text-emerald-600 hover:bg-emerald-50"}`}
                              onClick={handleGenerateSlides}
                              disabled={processing !== null}
                            >
                              重新生成
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  </>
                )}
              </div>
            </StepSection>
          </div>
        </div>

        {/* One-click progress */}
        {processing === "oneclick" && (
          <div className="px-5 py-3 border-t border-emerald-100 shrink-0 bg-gradient-to-r from-emerald-50 to-teal-50">
            <div className="flex items-center gap-3">
              <Loader2 size={16} className="animate-spin text-emerald-500 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-emerald-700">
                  一键生成中{outputFormat === "xiaohongshu" ? " · 小红书图文" : " · PPT"}
                </p>
                <div className="flex items-center gap-2 mt-1">
                  {["refine", "optimize", "slides"].map((step) => (
                    <div key={step} className="flex items-center gap-1">
                      <div className={`w-1.5 h-1.5 rounded-full ${
                        progressStep === step ? "bg-emerald-500 animate-pulse" :
                        ["refine", "optimize", "slides"].indexOf(progressStep) > ["refine", "optimize", "slides"].indexOf(step)
                          ? "bg-emerald-400" : "bg-gray-200"
                      }`} />
                    </div>
                  ))}
                  <span className="text-[10px] text-emerald-500">{progressDetail}</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Error message */}
        {errorMsg && (
          <div className="px-5 py-3 border-t border-red-100 shrink-0 bg-gradient-to-r from-red-50 to-orange-50">
            <div className="flex items-start gap-2">
              <AlertTriangle size={14} className="text-red-400 mt-0.5 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-red-700">生成失败</p>
                <p className="text-xs text-red-500 mt-0.5">{errorMsg}</p>
                <p className="text-[10px] text-red-400 mt-1">
                  建议：检查模型配置和网络连接后重试，或切换为免费模型（Pollinations Flux）
                </p>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
