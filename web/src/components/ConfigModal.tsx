"use client";

import { useState, useEffect } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import useSWR from "swr";
import { fetcher, apiPost, apiPatch, apiDelete } from "@/lib/api";
import { ModelConfig } from "@/lib/types";
import { X, Plus, Trash2, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { useAppStore } from "@/lib/store";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001/api";

const LLM_OPTIONS = [
  { value: "qwen2.5:7b", label: "Qwen2.5 7B (Ollama 本地，免费)" },
  { value: "llama3.1:8b", label: "Llama 3.1 8B (Ollama 本地，免费)" },
  { value: "gemma2:9b", label: "Gemma 2 9B (Ollama 本地，免费)" },
  { value: "deepseek-chat", label: "DeepSeek-V3 (DeepSeek 官方)" },
  { value: "deepseek-reasoner", label: "DeepSeek-R1 (DeepSeek 官方，推理)" },
  { value: "deepseek-ai/DeepSeek-V3", label: "DeepSeek-V3 (SiliconFlow)" },
  { value: "Qwen/Qwen3-8B", label: "Qwen3-8B (SiliconFlow)" },
  { value: "THUDM/GLM-4-9B-0414", label: "GLM-4-9B (SiliconFlow)" },
  { value: "coze-bot", label: "Coze 扣子 (自定义 Bot)" },
];

const LLM_BASE_URLS: Record<string, string> = {
  "qwen2.5:7b": "http://localhost:11434/v1",
  "llama3.1:8b": "http://localhost:11434/v1",
  "gemma2:9b": "http://localhost:11434/v1",
  "deepseek-chat": "https://api.deepseek.com/v1",
  "deepseek-reasoner": "https://api.deepseek.com/v1",
  "deepseek-ai/DeepSeek-V3": "https://api.siliconflow.cn/v1",
  "Qwen/Qwen3-8B": "https://api.siliconflow.cn/v1",
  "THUDM/GLM-4-9B-0414": "https://api.siliconflow.cn/v1",
  "coze-bot": "https://integration.coze.cn/api/v3",
};

const IMAGE_OPTIONS = [
  // --- 🆓 免费模型（无需付费，开箱即用） ---
  { value: "pollinations-flux", label: "🆓 Pollinations Flux (免费·无需Key)", base_url: "" },
  { value: "pollinations-turbo", label: "🆓 Pollinations Turbo (免费·超快)", base_url: "" },
  { value: "gemini-flash-image", label: "🆓 Gemini Flash Image (免费·500张/天)", base_url: "" },
  // --- SiliconFlow 可用（已验证 ✅） ---
  { value: "Qwen/Qwen-Image", label: "Qwen-Image ⭐ (通义万相，推荐)", base_url: "https://api.siliconflow.cn/v1" },
  { value: "Tongyi-MAI/Z-Image", label: "Z-Image (通义，高质量)", base_url: "https://api.siliconflow.cn/v1" },
  { value: "Tongyi-MAI/Z-Image-Turbo", label: "Z-Image Turbo (通义，快速)", base_url: "https://api.siliconflow.cn/v1" },
  { value: "baidu/ERNIE-Image-Turbo", label: "ERNIE-Image Turbo (百度文心)", base_url: "https://api.siliconflow.cn/v1" },
  { value: "Kwai-Kolors/Kolors", label: "Kolors 可图 (快手，中文优化)", base_url: "https://api.siliconflow.cn/v1" },
  // --- SiliconFlow 需开启权限（当前账户 Model disabled） ---
  { value: "black-forest-labs/FLUX.1-dev", label: "FLUX.1 Dev (需在 SiliconFlow 开启)", base_url: "https://api.siliconflow.cn/v1" },
  { value: "black-forest-labs/FLUX.1-schnell", label: "FLUX.1 Schnell (需在 SiliconFlow 开启)", base_url: "https://api.siliconflow.cn/v1" },
  { value: "stabilityai/stable-diffusion-3-5-large", label: "SD 3.5 Large (需在 SiliconFlow 开启)", base_url: "https://api.siliconflow.cn/v1" },
  // --- 自定义 ---
  { value: "custom", label: "自定义模型...", base_url: "" },
];

const IMAGE_BASE_URLS: Record<string, string> = Object.fromEntries(
  IMAGE_OPTIONS.filter((o) => o.value !== "custom").map((o) => [o.value, o.base_url])
);

const TTS_VOICE_OPTIONS = [
  { value: "zh-CN-XiaoxiaoNeural", label: "晓晓 (女声，推荐)" },
  { value: "zh-CN-YunxiNeural", label: "云希 (男声)" },
  { value: "zh-CN-YunjianNeural", label: "云健 (男声，沉稳)" },
  { value: "zh-CN-XiaoyiNeural", label: "晓伊 (女声，活泼)" },
  { value: "zh-CN-YunyangNeural", label: "云扬 (男声，新闻)" },
];

const VIDEO_OPTIONS = [
  { value: "Wan-AI/Wan2.2-T2V-A14B", label: "Wan 2.2 T2V (SiliconFlow，文生视频)" },
  { value: "Wan-AI/Wan2.2-I2V-A14B", label: "Wan 2.2 I2V (SiliconFlow，图生视频)" },
];

interface LlmConfigForm {
  model_id: string;
  base_url: string;
  api_key: string;
  temperature: number;
  bot_id?: string;
}

export default function ConfigModal() {
  const { configModalOpen, setConfigModalOpen } = useAppStore();
  const { data: configs, mutate } = useSWR<ModelConfig[]>("/model-configs", fetcher);

  // LLM: support multiple configs
  const [llmForms, setLlmForms] = useState<LlmConfigForm[]>([]);
  const [savingLlm, setSavingLlm] = useState<number | null>(null); // index or -1 for new

  // Image
  const [imageKey, setImageKey] = useState("");
  const [imageBaseUrl, setImageBaseUrl] = useState("https://api.siliconflow.cn/v1");
  const [imageModel, setImageModel] = useState("black-forest-labs/FLUX.1-dev");
  const [imageCustomModel, setImageCustomModel] = useState("");

  // TTS
  const [ttsVoice, setTtsVoice] = useState("zh-CN-XiaoxiaoNeural");

  // Video
  const [videoKey, setVideoKey] = useState("");
  const [videoBaseUrl, setVideoBaseUrl] = useState("https://api.siliconflow.cn/v1");
  const [videoModel, setVideoModel] = useState("Wan-AI/Wan2.2-T2V-A14B");

  const [saving, setSaving] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<number, { ok: boolean; message: string; testing: boolean }>>({});

  useEffect(() => {
    if (!configs) return;

    // LLM: load all llm configs as forms
    const llmConfigs = configs.filter((c) => c.provider === "llm");
    if (llmConfigs.length > 0) {
      setLlmForms(
        llmConfigs.map((c) => {
          const baseUrl = (c.params?.base_url as string) || LLM_BASE_URLS[c.model_id] || "http://localhost:11434/v1";
          const isCoze = baseUrl.includes("coze");
          return {
            model_id: isCoze ? "coze-bot" : c.model_id,
            base_url: baseUrl,
            api_key: "",
            temperature: (c.params?.temperature as number) ?? 0.5,
            bot_id: isCoze ? c.model_id : undefined,
          };
        })
      );
    } else {
      setLlmForms([{ model_id: "qwen2.5:7b", base_url: "http://localhost:11434/v1", api_key: "", temperature: 0.5 }]);
    }

    const image = configs.find((c) => c.provider === "image");
    if (image) {
      const knownIds = IMAGE_OPTIONS.filter((o) => o.value !== "custom").map((o) => o.value);
      if (knownIds.includes(image.model_id)) {
        setImageModel(image.model_id);
      } else {
        setImageModel("custom");
        setImageCustomModel(image.model_id);
      }
      if (image.params?.base_url) setImageBaseUrl(image.params.base_url as string);
    }
    const tts = configs.find((c) => c.provider === "tts");
    if (tts) {
      if (tts.model_id) setTtsVoice(tts.model_id);
    }
    const video = configs.find((c) => c.provider === "video");
    if (video) {
      setVideoModel(video.model_id);
      if (video.params?.base_url) setVideoBaseUrl(video.params.base_url as string);
    }
  }, [configs]);

  const llmConfigs = configs?.filter((c) => c.provider === "llm") || [];

  const handleSaveLlm = async (index: number) => {
    setSavingLlm(index);
    const form = llmForms[index];
    const existing = llmConfigs[index];
    // For Coze, actual model_id is the bot_id
    const actualModelId = form.model_id === "coze-bot" ? (form.bot_id || form.model_id) : form.model_id;
    const actualBaseUrl = form.model_id === "coze-bot" ? (form.base_url || LLM_BASE_URLS["coze-bot"]) : form.base_url;
    try {
      if (existing) {
        await apiPatch(`/model-configs/${existing.id}`, {
          model_id: actualModelId,
          api_key: form.api_key || undefined,
          params: { temperature: form.temperature, base_url: actualBaseUrl },
        });
      } else {
        await apiPost("/model-configs", {
          name: `llm-${actualModelId.replace(/[/:.]/g, "-")}`,
          provider: "llm",
          model_id: actualModelId,
          api_key: form.api_key || undefined,
          params: { temperature: form.temperature, base_url: actualBaseUrl },
        });
      }
      mutate();
    } catch {
      alert("保存失败");
    } finally {
      setSavingLlm(null);
    }
  };

  const handleAddLlm = () => {
    setLlmForms([...llmForms, { model_id: "deepseek-chat", base_url: "https://api.deepseek.com/v1", api_key: "", temperature: 0.5 }]);
  };

  const handleRemoveLlm = async (index: number) => {
    const existing = llmConfigs[index];
    if (existing) {
      try {
        await apiDelete(`/model-configs/${existing.id}`);
        mutate();
      } catch {
        alert("删除失败");
      }
    }
    setLlmForms(llmForms.filter((_, i) => i !== index));
  };

  const handleSave = async (name: string, provider: string, data: Record<string, unknown>) => {
    setSaving(name);
    try {
      const config = configs?.find((c) => c.provider === provider);
      if (config) {
        await apiPatch(`/model-configs/${config.id}`, data);
      } else {
        await apiPost("/model-configs", { name, provider, ...data });
      }
      mutate();
    } catch {
      alert("保存失败");
    } finally {
      setSaving(null);
    }
  };

  const handleTest = async (configId: number) => {
    setTestResults((prev) => ({ ...prev, [configId]: { ok: false, message: "", testing: true } }));
    try {
      const resp = await fetch(`${API_BASE}/model-configs/${configId}/test`, { method: "POST" });
      const data = await resp.json();
      if (!resp.ok) {
        setTestResults((prev) => ({ ...prev, [configId]: { ok: false, message: data.detail || `测试失败 (${resp.status})`, testing: false } }));
      } else {
        setTestResults((prev) => ({ ...prev, [configId]: { ok: data.ok, message: data.message, testing: false } }));
      }
    } catch {
      setTestResults((prev) => ({ ...prev, [configId]: { ok: false, message: "测试请求失败", testing: false } }));
    }
  };

  const TestResult = ({ configId }: { configId: number | null }) => {
    if (!configId) return null;
    const r = testResults[configId];
    if (!r) return null;
    if (r.testing) return <span className="text-xs text-gray-400 flex items-center gap-1"><Loader2 size={12} className="animate-spin" />测试中</span>;
    if (r.ok) return <span className="text-xs text-green-600 flex items-center gap-1"><CheckCircle2 size={12} />{r.message}</span>;
    return <span className="text-xs text-red-500 flex items-center gap-1"><XCircle size={12} />{r.message}</span>;
  };

  return (
    <Dialog.Root open={configModalOpen} onOpenChange={setConfigModalOpen}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/30 z-40" />
        <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-white rounded-lg border border-gray-200 w-[560px] max-h-[80vh] overflow-y-auto z-50 p-5">
          <div className="flex items-center justify-between mb-4">
            <Dialog.Title className="text-sm font-medium text-gray-700">
              模型配置
            </Dialog.Title>
            <Dialog.Close className="text-gray-400 hover:text-gray-600">
              <X size={16} />
            </Dialog.Close>
          </div>

          {/* LLM — multiple configs */}
          <div className="mb-4">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-medium text-gray-500">LLM 文本优化</h3>
              <button className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700" onClick={handleAddLlm}>
                <Plus size={12} /> 添加模型
              </button>
            </div>
            <div className="space-y-3">
              {llmForms.map((form, index) => {
                const existing = llmConfigs[index];
                return (
                  <div key={index} className="border border-gray-200 rounded p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-500">{existing ? existing.name : "新配置"}</span>
                      {llmForms.length > 1 && (
                        <button className="text-gray-300 hover:text-red-500" onClick={() => handleRemoveLlm(index)}>
                          <Trash2 size={12} />
                        </button>
                      )}
                    </div>
                    <select
                      className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 bg-white"
                      value={form.model_id === "coze-bot" || (form.bot_id && form.base_url.includes("coze")) ? "coze-bot" : form.model_id}
                      onChange={(e) => {
                        const v = e.target.value;
                        const next = [...llmForms];
                        if (v === "coze-bot") {
                          next[index] = { ...next[index], model_id: "coze-bot", base_url: LLM_BASE_URLS["coze-bot"], bot_id: next[index].bot_id || "" };
                        } else {
                          next[index] = { ...next[index], model_id: v, base_url: LLM_BASE_URLS[v] || next[index].base_url, bot_id: undefined };
                        }
                        if (v.includes(":") && !v.includes("/")) next[index].api_key = "";
                        setLlmForms(next);
                      }}
                    >
                      {LLM_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                    {form.model_id === "coze-bot" && (
                      <input
                        type="text"
                        placeholder="Bot ID（在 Coze 平台获取）"
                        className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 outline-none focus:border-blue-300"
                        value={form.bot_id || ""}
                        onChange={(e) => {
                          const next = [...llmForms];
                          next[index] = { ...next[index], bot_id: e.target.value };
                          setLlmForms(next);
                        }}
                      />
                    )}
                    <input
                      type="text"
                      placeholder="API Base URL"
                      className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 outline-none focus:border-blue-300"
                      value={form.base_url}
                      onChange={(e) => {
                        const next = [...llmForms];
                        next[index] = { ...next[index], base_url: e.target.value };
                        setLlmForms(next);
                      }}
                    />
                    <input
                      type="password"
                      placeholder={form.base_url.includes("11434") ? "API Key (Ollama 本地无需填写)" : "API Key"}
                      className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 outline-none focus:border-blue-300"
                      value={form.api_key}
                      onChange={(e) => {
                        const next = [...llmForms];
                        next[index] = { ...next[index], api_key: e.target.value };
                        setLlmForms(next);
                      }}
                    />
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-gray-500 shrink-0">Temperature</span>
                      <input
                        type="range"
                        min="0"
                        max="1"
                        step="0.1"
                        value={form.temperature}
                        onChange={(e) => {
                          const next = [...llmForms];
                          next[index] = { ...next[index], temperature: parseFloat(e.target.value) };
                          setLlmForms(next);
                        }}
                        className="flex-1"
                      />
                      <span className="text-xs text-gray-500 w-6 text-right">{form.temperature}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <button
                        className="text-xs text-blue-600 hover:text-blue-700 disabled:text-gray-300"
                        disabled={savingLlm === index}
                        onClick={() => handleSaveLlm(index)}
                      >
                        {savingLlm === index ? "保存中..." : "保存"}
                      </button>
                      {existing && (
                        <button
                          className="text-xs text-gray-400 hover:text-gray-600 disabled:text-gray-300"
                          disabled={testResults[existing.id]?.testing}
                          onClick={() => handleTest(existing.id)}
                        >
                          测试
                        </button>
                      )}
                    </div>
                    <TestResult configId={existing?.id ?? null} />
                  </div>
                );
              })}
            </div>
          </div>

          {/* Image */}
          <div className="mb-4">
            <h3 className="text-xs font-medium text-gray-500 mb-2">
              画面生成
            </h3>
            <div className="border border-gray-200 rounded p-3 space-y-2">
              <p className="text-xs text-amber-600 bg-amber-50 rounded px-2 py-1.5">
                推荐 Qwen-Image（通义万相），中文场景画质优秀。Z-Image Turbo 速度快。Kolors 对中文提示词理解最好。
              </p>
              <select
                className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 bg-white"
                value={imageModel}
                onChange={(e) => {
                  const v = e.target.value;
                  setImageModel(v);
                  if (v !== "custom" && IMAGE_BASE_URLS[v]) {
                    setImageBaseUrl(IMAGE_BASE_URLS[v]);
                  }
                }}
              >
                {IMAGE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
              {imageModel === "custom" && (
                <input
                  type="text"
                  placeholder="自定义模型 ID（如 black-forest-labs/FLUX.1-dev）"
                  className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 outline-none focus:border-blue-300"
                  value={imageCustomModel}
                  onChange={(e) => setImageCustomModel(e.target.value)}
                />
              )}
              <input
                type="text"
                placeholder="API Base URL"
                className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 outline-none focus:border-blue-300"
                value={imageBaseUrl}
                onChange={(e) => setImageBaseUrl(e.target.value)}
              />
              <input
                type="password"
                placeholder="API Key (与 LLM 共享同一 Key)"
                className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 outline-none focus:border-blue-300"
                value={imageKey}
                onChange={(e) => setImageKey(e.target.value)}
              />
              <div className="flex items-center gap-3">
                <button
                  className="text-xs text-blue-600 hover:text-blue-700 disabled:text-gray-300"
                  disabled={saving === "image"}
                  onClick={() =>
                    handleSave("image", "image", {
                      model_id: imageModel === "custom" ? imageCustomModel : imageModel,
                      api_key: imageKey || undefined,
                      params: { base_url: imageBaseUrl },
                    })
                  }
                >
                  {saving === "image" ? "保存中..." : "保存"}
                </button>
                {configs?.find((c) => c.provider === "image") && (
                  <button
                    className="text-xs text-gray-400 hover:text-gray-600 disabled:text-gray-300"
                    disabled={testResults[configs.find((c) => c.provider === "image")!.id]?.testing}
                    onClick={() => handleTest(configs.find((c) => c.provider === "image")!.id)}
                  >
                    测试
                  </button>
                )}
              </div>
              <TestResult configId={configs?.find((c) => c.provider === "image")?.id ?? null} />
            </div>
          </div>

          {/* TTS */}
          <div className="mb-4">
            <h3 className="text-xs font-medium text-gray-500 mb-2">
              语音合成 TTS（Edge TTS，免费无需 Key）
            </h3>
            <div className="border border-gray-200 rounded p-3 space-y-2">
              <select
                className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 bg-white"
                value={ttsVoice}
                onChange={(e) => setTtsVoice(e.target.value)}
              >
                {TTS_VOICE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
              <div className="flex items-center gap-3">
                <button
                  className="text-xs text-blue-600 hover:text-blue-700 disabled:text-gray-300"
                  disabled={saving === "tts"}
                  onClick={() =>
                    handleSave("tts", "tts", {
                      model_id: ttsVoice,
                      api_key: undefined,
                    })
                  }
                >
                  {saving === "tts" ? "保存中..." : "保存"}
                </button>
                {configs?.find((c) => c.provider === "tts") && (
                  <button
                    className="text-xs text-gray-400 hover:text-gray-600 disabled:text-gray-300"
                    disabled={testResults[configs.find((c) => c.provider === "tts")!.id]?.testing}
                    onClick={() => handleTest(configs.find((c) => c.provider === "tts")!.id)}
                  >
                    测试
                  </button>
                )}
              </div>
              <TestResult configId={configs?.find((c) => c.provider === "tts")?.id ?? null} />
            </div>
          </div>

          {/* Video */}
          <div className="mb-4">
            <h3 className="text-xs font-medium text-gray-500 mb-2">
              AI 视频生成
            </h3>
            <div className="border border-gray-200 rounded p-3 space-y-2">
              <p className="text-xs text-amber-600 bg-amber-50 rounded px-2 py-1.5">
                注册 SiliconFlow 账号可获得免费额度：siliconflow.cn → 注册 → 个人中心获取 API Key
              </p>
              <select
                className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 bg-white"
                value={videoModel}
                onChange={(e) => setVideoModel(e.target.value)}
              >
                {VIDEO_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
              <input
                type="text"
                placeholder="API Base URL"
                className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 outline-none focus:border-blue-300"
                value={videoBaseUrl}
                onChange={(e) => setVideoBaseUrl(e.target.value)}
              />
              <input
                type="password"
                placeholder="API Key（SiliconFlow）"
                className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 outline-none focus:border-blue-300"
                value={videoKey}
                onChange={(e) => setVideoKey(e.target.value)}
              />
              <div className="flex items-center gap-3">
                <button
                  className="text-xs text-blue-600 hover:text-blue-700 disabled:text-gray-300"
                  disabled={saving === "video"}
                  onClick={() =>
                    handleSave("video", "video", {
                      model_id: videoModel,
                      api_key: videoKey || undefined,
                      params: { base_url: videoBaseUrl },
                    })
                  }
                >
                  {saving === "video" ? "保存中..." : "保存"}
                </button>
                {configs?.find((c) => c.provider === "video") && (
                  <button
                    className="text-xs text-gray-400 hover:text-gray-600 disabled:text-gray-300"
                    disabled={testResults[configs.find((c) => c.provider === "video")!.id]?.testing}
                    onClick={() => handleTest(configs.find((c) => c.provider === "video")!.id)}
                  >
                    测试
                  </button>
                )}
              </div>
              <TestResult configId={configs?.find((c) => c.provider === "video")?.id ?? null} />
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
