"use client";

import { useState, useEffect } from "react";
import Image from "next/image";
import { apiPost, fetcher } from "@/lib/api";
import useSWR from "swr";

// ── Types ──────────────────────────────────────────────

interface XhsModel {
  id: string;
  label: string;
  description: string;
  features: string[];
  speed: string;
  quality: string;
  best_for: string;
  requires_key: boolean;
  icon: string;
}

interface StyleItem {
  key: string;
  label: string;
  icon: string;
  desc: string;
}

interface GenerateResult {
  success: boolean;
  format: string;
  page_count: number;
  image_paths: string[];
  zip_path: string;
  model_used: string;
  title: string;
}

// ── Constants ──────────────────────────────────────────

const SPEED_COLORS: Record<string, string> = {
  "快": "bg-green-100 text-green-700",
  "中": "bg-yellow-100 text-yellow-700",
  "慢": "bg-orange-100 text-orange-700",
};

const QUALITY_COLORS: Record<string, string> = {
  "高": "bg-purple-100 text-purple-700",
  "中": "bg-blue-100 text-blue-700",
};

const DEFAULT_STYLES: StyleItem[] = [
  { key: "realistic", label: "写实摄影", icon: "📷", desc: "自然光影，氛围感强" },
  { key: "illustration", label: "现代插画", icon: "🎨", desc: "清新扁平，色彩柔和" },
  { key: "anime", label: "动漫风", icon: "🌸", desc: "日系美学，治愈温暖" },
  { key: "watercolor", label: "水彩手绘", icon: "🖌️", desc: "柔和晕染，文艺质感" },
  { key: "cinematic", label: "电影质感", icon: "🎬", desc: "戏剧光影，氛围大片" },
  { key: "dreamy", label: "梦幻柔焦", icon: "✨", desc: "柔光朦胧，浪漫梦幻" },
  { key: "minimal", label: "极简风格", icon: "◻️", desc: "干净留白，北欧美学" },
  { key: "vintage", label: "复古胶片", icon: "📽️", desc: "怀旧暖调，胶片质感" },
  { key: "nature", label: "自然风光", icon: "🌿", desc: "植物光影，清新治愈" },
];

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001/api";

// ── Component ──────────────────────────────────────────

interface XhsGeneratorProps {
  initialTitle?: string;
  initialContent?: string;
  onClose?: () => void;
}

export default function XhsGenerator({ initialTitle = "", initialContent = "", onClose }: XhsGeneratorProps) {
  // ── Step state ──
  const [step, setStep] = useState<1 | 2 | 3>(1);

  // ── Selection state ──
  const [selectedModel, setSelectedModel] = useState<string>("pollinations-flux");
  const [selectedStyle, setSelectedStyle] = useState<string>("realistic");
  const [geminiKey, setGeminiKey] = useState<string>("");
  const [title, setTitle] = useState(initialTitle);
  const [content, setContent] = useState(initialContent);

  // ── Generation state ──
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<GenerateResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [, setProgressMsg] = useState("");

  // ── Data fetching ──
  const { data: modelsData } = useSWR("/xhs/models", fetcher, {
    fallbackData: null,
    revalidateOnFocus: false,
  });
  const { data: stylesData } = useSWR("/image-styles", fetcher, {
    fallbackData: null,
    revalidateOnFocus: false,
  });

  const models: XhsModel[] = modelsData?.models || [];
  const styles: StyleItem[] = stylesData?.styles || DEFAULT_STYLES;

  const selectedModelMeta = models.find((m) => m.id === selectedModel);
  const needsKey = selectedModelMeta?.requires_key ?? false;

  // ── Sync initial props ──
  useEffect(() => {
    if (initialTitle) setTitle(initialTitle);
    if (initialContent) setContent(initialContent);
  }, [initialTitle, initialContent]);

  // ── Generate ──
  const handleGenerate = async () => {
    if (!title.trim() || !content.trim()) {
      setError("请填写标题和内容");
      return;
    }
    if (needsKey && !geminiKey.trim()) {
      setError("Gemini 模型需要 API Key，请在 aistudio.google.com 免费获取");
      return;
    }

    setError(null);
    setGenerating(true);
    setResult(null);
    setProgressMsg("正在生成封面...");

    try {
      const res = await apiPost("/xhs/generate", {
        model_id: selectedModel,
        title: title.trim(),
        content: content.trim(),
        image_style: selectedStyle,
        gemini_api_key: geminiKey || undefined,
      });
      setResult(res as GenerateResult);
      setStep(3);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "生成失败，请重试";
      setError(msg);
    } finally {
      setGenerating(false);
      setProgressMsg("");
    }
  };

  const handleBack = () => {
    if (step === 3) {
      setResult(null);
      setStep(2);
    } else if (step === 2) {
      setStep(1);
    }
  };

  // ── Step indicator ──
  const steps = [
    { num: 1, label: "选择模型" },
    { num: 2, label: "输入内容" },
    { num: 3, label: "生成预览" },
  ];

  return (
    <div className="fixed inset-y-0 right-0 w-[520px] bg-white shadow-2xl border-l border-gray-200 z-50 flex flex-col animate-slide-in-right">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100 shrink-0">
        <div className="flex items-center gap-2.5">
          <span className="text-lg">📕</span>
          <h2 className="text-sm font-semibold text-gray-800">小红书图文生成</h2>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-md transition-colors"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M4 4l8 8M12 4l-8 8" />
          </svg>
        </button>
      </div>

      {/* Step progress bar */}
      <div className="px-5 pt-4 pb-2 shrink-0">
        <div className="flex items-center gap-2">
          {steps.map((s, i) => (
            <div key={s.num} className="flex items-center gap-2 flex-1 last:flex-none">
              <button
                onClick={() => s.num < step ? setStep(s.num as 1 | 2 | 3) : undefined}
                className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold transition-all shrink-0 ${
                  step === s.num
                    ? "bg-rose-500 text-white shadow-md shadow-rose-200"
                    : step > s.num
                    ? "bg-rose-100 text-rose-600 cursor-pointer"
                    : "bg-gray-100 text-gray-400"
                }`}
              >
                {step > s.num ? "✓" : s.num}
              </button>
              <span className={`text-xs ${step === s.num ? "text-rose-600 font-medium" : "text-gray-400"}`}>
                {s.label}
              </span>
              {i < steps.length - 1 && (
                <div className={`flex-1 h-0.5 rounded-full ${step > s.num ? "bg-rose-300" : "bg-gray-200"}`} />
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {/* ── STEP 1: Choose model ── */}
        {step === 1 && (
          <div className="space-y-4">
            <div className="text-xs text-gray-500 mb-2">
              以下模型均<b className="text-gray-700">完全免费</b>，无需付费 API Key 即可使用
            </div>

            {models.length === 0 && (
              <div className="text-center py-10 text-gray-400 text-sm">加载模型列表...</div>
            )}

            {models.map((model) => (
              <button
                key={model.id}
                onClick={() => {
                  setSelectedModel(model.id);
                  setGeminiKey("");
                }}
                className={`w-full text-left p-4 rounded-xl border-2 transition-all duration-200 ${
                  selectedModel === model.id
                    ? "border-rose-400 bg-rose-50 shadow-sm"
                    : "border-gray-100 bg-white hover:border-gray-200 hover:bg-gray-50"
                }`}
              >
                <div className="flex items-start gap-3">
                  <span className="text-2xl shrink-0 mt-0.5">{model.icon}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-semibold text-gray-800">{model.label}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${SPEED_COLORS[model.speed] || "bg-gray-100 text-gray-600"}`}>
                        {model.speed}速
                      </span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${QUALITY_COLORS[model.quality] || "bg-gray-100 text-gray-600"}`}>
                        {model.quality}画质
                      </span>
                      {model.requires_key && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 font-medium">
                          需Key
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-gray-500 mt-1.5 leading-relaxed">{model.description}</p>
                    <div className="flex flex-wrap gap-1 mt-2">
                      {model.features.map((f) => (
                        <span key={f} className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">
                          {f}
                        </span>
                      ))}
                    </div>
                    <p className="text-[10px] text-gray-400 mt-1.5">
                      适合：{model.best_for}
                    </p>
                  </div>
                  {selectedModel === model.id && (
                    <span className="text-rose-500 shrink-0 mt-1">
                      <svg width="18" height="18" viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                      </svg>
                    </span>
                  )}
                </div>
              </button>
            ))}

            {/* Gemini Key input */}
            {needsKey && (
              <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 space-y-2">
                <p className="text-xs text-amber-700">
                  🔑 Gemini 需要 API Key（免费，每天 500 张）。前往{" "}
                  <a href="https://aistudio.google.com" target="_blank" rel="noopener noreferrer" className="underline font-medium">
                    aistudio.google.com
                  </a>{" "}
                  获取。
                </p>
                <input
                  type="password"
                  value={geminiKey}
                  onChange={(e) => setGeminiKey(e.target.value)}
                  placeholder="粘贴 Gemini API Key..."
                  className="w-full text-xs px-3 py-2 rounded-md border border-amber-300 bg-white placeholder:text-gray-300 focus:outline-none focus:ring-2 focus:ring-amber-200"
                />
              </div>
            )}

            <button
              onClick={() => setStep(2)}
              className="w-full py-3 rounded-xl bg-rose-500 text-white text-sm font-medium hover:bg-rose-600 transition-colors shadow-md shadow-rose-200"
            >
              下一步：输入内容 →
            </button>
          </div>
        )}

        {/* ── STEP 2: Input content ── */}
        {step === 2 && (
          <div className="space-y-4">
            {/* Title */}
            <div>
              <label className="text-xs font-medium text-gray-600 mb-1.5 block">
                标题 <span className="text-rose-400">*</span>
              </label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="给你的小红书笔记起个吸引人的标题..."
                className="w-full text-sm px-4 py-2.5 rounded-lg border border-gray-200 bg-white placeholder:text-gray-300 focus:outline-none focus:ring-2 focus:ring-rose-200 focus:border-rose-300"
                maxLength={40}
              />
              <span className="text-[10px] text-gray-400 mt-1 block text-right">{title.length}/40</span>
            </div>

            {/* Content */}
            <div>
              <label className="text-xs font-medium text-gray-600 mb-1.5 block">
                正文内容 <span className="text-rose-400">*</span>
              </label>
              <textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder={
                  "写下你的小红书正文...\n\n用空行分隔不同页面，每页开头作为标题。\n例如：\n\n☕ 这家隐藏咖啡馆绝了！\n藏在老城区的巷子里，推开门就是另一个世界...\n\n🍰 必点提拉米苏\n入口即化，咖啡味浓郁但不会太苦，配上奶泡简直完美..."
                }
                rows={10}
                className="w-full text-sm px-4 py-3 rounded-lg border border-gray-200 bg-white placeholder:text-gray-300 focus:outline-none focus:ring-2 focus:ring-rose-200 focus:border-rose-300 resize-none"
              />
              <span className="text-[10px] text-gray-400 mt-1 block">
                用<b>空行</b>分隔不同页面，最多 10 页
              </span>
            </div>

            {/* Style picker */}
            <div>
              <label className="text-xs font-medium text-gray-600 mb-2 block">视觉风格</label>
              <div className="grid grid-cols-3 gap-2">
                {styles.map((s) => (
                  <button
                    key={s.key}
                    onClick={() => setSelectedStyle(s.key)}
                    className={`text-left p-2.5 rounded-lg border transition-all ${
                      selectedStyle === s.key
                        ? "border-rose-400 bg-rose-50 shadow-sm"
                        : "border-gray-100 bg-white hover:border-gray-200"
                    }`}
                  >
                    <span className="text-base">{s.icon}</span>
                    <span className="text-[11px] font-medium text-gray-700 block mt-0.5">{s.label}</span>
                    <span className="text-[9px] text-gray-400 block truncate">{s.desc}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Selected model summary */}
            {selectedModelMeta && (
              <div className="bg-gray-50 rounded-lg p-3 flex items-center gap-2.5">
                <span className="text-lg">{selectedModelMeta.icon}</span>
                <div>
                  <span className="text-xs font-medium text-gray-700">{selectedModelMeta.label}</span>
                  <span className="text-[10px] text-gray-400 ml-1.5">
                    ({selectedModelMeta.speed}速 · {selectedModelMeta.quality}画质)
                  </span>
                </div>
              </div>
            )}

            {/* Buttons */}
            <div className="flex gap-3">
              <button
                onClick={handleBack}
                className="flex-1 py-2.5 rounded-xl border border-gray-200 text-sm text-gray-500 hover:bg-gray-50 transition-colors"
              >
                ← 返回选模型
              </button>
              <button
                onClick={handleGenerate}
                disabled={generating || !title.trim() || !content.trim()}
                className="flex-[2] py-2.5 rounded-xl bg-rose-500 text-white text-sm font-medium hover:bg-rose-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors shadow-md shadow-rose-200 flex items-center justify-center gap-2"
              >
                {generating ? (
                  <>
                    <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4 31.4" strokeLinecap="round" className="opacity-30" />
                      <path d="M12 2a10 10 0 019.95 9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
                    </svg>
                    生成中...
                  </>
                ) : (
                  "✨ 一键生成小红书图文"
                )}
              </button>
            </div>

            {error && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-3">
                <p className="text-xs text-red-600">{error}</p>
              </div>
            )}
          </div>
        )}

        {/* ── STEP 3: Preview & Export ── */}
        {step === 3 && result && (
          <div className="space-y-4">
            {/* Success banner */}
            <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-3">
              <div className="flex items-center gap-2">
                <span className="text-base">✅</span>
                <div>
                  <p className="text-xs font-medium text-emerald-700">生成成功！</p>
                  <p className="text-[10px] text-emerald-600">
                    共 {result.page_count} 页 · 使用 {result.model_used}
                  </p>
                </div>
              </div>
            </div>

            {/* Image preview grid */}
            <div>
              <label className="text-xs font-medium text-gray-600 mb-2 block">
                图文预览（{result.page_count} 页）
              </label>
              <div className="grid grid-cols-3 gap-3">
                {result.image_paths.map((imgPath, i) => {
                  const fileName = imgPath.split("/").pop() || `page_${i}`;
                  const isCover = i === 0;
                  return (
                    <div key={i} className="space-y-1.5">
                      <div className={`relative aspect-[3/4] rounded-lg overflow-hidden border-2 ${isCover ? "border-rose-300 shadow-md" : "border-gray-200"}`}>
                        <Image
                          src={`${API_BASE.replace("/api", "")}/storage/slides/${fileName}`}
                          alt={isCover ? "封面" : `第${i}页`}
                          fill
                          className="object-cover"
                          sizes="(max-width: 520px) 30vw, 150px"
                        />
                        {isCover && (
                          <span className="absolute top-1.5 left-1.5 text-[9px] px-1.5 py-0.5 rounded bg-rose-500 text-white font-medium">
                            封面
                          </span>
                        )}
                        <span className="absolute bottom-1 right-1 text-[9px] px-1 py-0.5 rounded bg-black/50 text-white">
                          {isCover ? "Cover" : i}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Actions */}
            <div className="flex gap-3">
              <button
                onClick={handleBack}
                className="flex-1 py-2.5 rounded-xl border border-gray-200 text-sm text-gray-500 hover:bg-gray-50 transition-colors"
              >
                ← 重新生成
              </button>
              <a
                href={`${API_BASE.replace("/api", "")}/storage/slides/xhs_post.zip`}
                download
                className="flex-[2] py-2.5 rounded-xl bg-emerald-500 text-white text-sm font-medium hover:bg-emerald-600 transition-colors shadow-md shadow-emerald-200 flex items-center justify-center gap-2"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                  <polyline points="7 10 12 15 17 10" />
                  <line x1="12" y1="15" x2="12" y2="3" />
                </svg>
                下载全部图片 (ZIP)
              </a>
            </div>

            {/* Tip */}
            <div className="bg-gray-50 rounded-lg p-3">
              <p className="text-[10px] text-gray-400 leading-relaxed">
                💡 提示：下载 ZIP 解压后可直接导入小红书 App 发布。图片尺寸为 1080×1440（3:4 竖版），完美适配小红书发布规格。
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
