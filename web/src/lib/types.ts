export interface Folder {
  id: number;
  name: string;
  parent_id: number | null;
  created_at: string;
  updated_at: string;
  children: Folder[];
}

export interface Note {
  id: number;
  title: string;
  content: string | null;
  raw_text: string | null;
  refined_title: string | null;
  refined_body: string | null;
  styled_body: string | null;
  folder_id: number | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface Script {
  id: number;
  note_id: number;
  version: number;
  style: string | null;
  content: ScriptContent | null;
  raw_content: string | null;
  created_at: string;
}

export interface ScriptContent {
  status: string;
  title: string;
  segments: Segment[];
  total_duration_hint: number;
  style: string;
  music_mood: string;
}

export interface Segment {
  id: number;
  text: string;
  duration_hint: number;
  emotion: string;
  visual_hint: string;
}

export interface Material {
  id: number;
  note_id: number;
  type: string;
  url: string | null;
  local_path: string | null;
  prompt: string | null;
  meta_data: Record<string, unknown> | null;
  duration: number | null;
  created_at: string;
}

export interface VideoOutput {
  id: number;
  note_id: number;
  url: string | null;
  local_path: string | null;
  duration: number | null;
  resolution: string | null;
  file_size: number | null;
  meta_data: Record<string, unknown> | null;
  created_at: string;
}

export interface ModelConfig {
  id: number;
  name: string;
  provider: string;
  model_id: string;
  api_key_masked: string;
  params: Record<string, unknown> | null;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}
