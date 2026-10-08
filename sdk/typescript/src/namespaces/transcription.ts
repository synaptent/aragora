/**
 * Transcription Namespace API
 *
 * Provides audio/video transcription capabilities:
 * - Transcribe audio and video files
 * - Transcribe YouTube videos
 * - Manage transcription jobs
 * - Get timestamped segments
 */

/**
 * Transcription status.
 */
export type TranscriptionStatus = 'pending' | 'processing' | 'completed' | 'failed';

/**
 * Transcription backend.
 */
export type TranscriptionBackend = 'openai' | 'faster-whisper' | 'whisper-cpp';

/**
 * Whisper model size.
 */
export type WhisperModel = 'tiny' | 'base' | 'small' | 'medium' | 'large';

/**
 * Transcription configuration.
 */
export interface TranscriptionConfig {
  available: boolean;
  backends: TranscriptionBackend[];
  audio_formats: string[];
  video_formats: string[];
  max_audio_size_mb: number;
  max_video_size_mb: number;
  models: WhisperModel[];
  youtube_enabled: boolean;
}

/**
 * Supported formats.
 */
export interface TranscriptionFormats {
  audio: string[];
  video: string[];
  max_size_mb: number;
  model: string;
  note?: string;
}

/**
 * Transcription segment.
 */
export interface TranscriptionSegment {
  id: number;
  start: number;
  end: number;
  text: string;
  tokens?: number[];
  temperature?: number;
  avg_logprob?: number;
  compression_ratio?: number;
  no_speech_prob?: number;
}

/**
 * Transcription result.
 */
export interface TranscriptionResult {
  job_id: string;
  status: TranscriptionStatus;
  text: string;
  language: string;
  duration: number;
  segments: TranscriptionSegment[];
  backend: TranscriptionBackend;
  processing_time?: number;
}

/**
 * Transcription job details.
 */
export interface TranscriptionJob {
  id: string;
  filename: string;
  status: TranscriptionStatus;
  created_at: number;
  completed_at?: number;
  transcription_id?: string;
  error?: string;
  file_size_bytes: number;
  duration_seconds?: number;
  text?: string;
  language?: string;
  word_count: number;
  segment_count: number;
}

/**
 * Job status response.
 */
export interface JobStatusResponse {
  job_id: string;
  status: TranscriptionStatus;
  progress?: number;
  result?: TranscriptionResult;
  error?: string;
}

/**
 * Segments response.
 */
export interface SegmentsResponse {
  job_id: string;
  status: TranscriptionStatus;
  segments: TranscriptionSegment[];
  segment_count: number;
}

/**
 * YouTube video info.
 */
export interface YouTubeVideoInfo {
  video_id: string;
  title: string;
  duration: number;
  channel: string;
  description: string;
  upload_date?: string;
  view_count?: number;
  thumbnail_url?: string;
}

/**
 * Transcription options.
 */
export interface TranscriptionOptions {
  /** ISO-639-1 language code */
  language?: string;
  /** Transcription backend to use */
  backend?: TranscriptionBackend;
}

/**
 * YouTube transcription options.
 */
export interface YouTubeTranscriptionOptions extends TranscriptionOptions {
  /** Use cached audio if available */
  use_cache?: boolean;
}

/**
 * Upload response.
 */
export interface UploadResponse {
  success: boolean;
  job_id: string;
  filename: string;
  file_size_bytes: number;
  status: TranscriptionStatus;
  message: string;
}

/**
 * Client interface for transcription operations.
 */
interface TranscriptionClientInterface {
  request<T = unknown>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown>; json?: Record<string, unknown> }
  ): Promise<T>;
}

/**
 * Transcription API namespace.
 *
 * Provides methods for audio/video transcription:
 * - Transcribe audio and video files
 * - Transcribe YouTube videos
 * - Get transcription status and results
 * - Get timestamped segments
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai' });
 *
 * // Check transcription config
 * const config = await client.transcription.getConfig();
 *
 * // Transcribe a YouTube video
 * const result = await client.transcription.transcribeYouTube(
 *   'https://youtube.com/watch?v=dQw4w9WgXcQ',
 *   { language: 'en' }
 * );
 * ```
 */
export class TranscriptionAPI {
  constructor(private client: TranscriptionClientInterface) {}

  /**
   * Get transcription service configuration.
   */
  async getConfig(): Promise<TranscriptionConfig> {
    return this.client.request('POST', '/api/v1/transcription/config');
  }

  /**
   * Get supported audio/video formats.
   */
  async getFormats(): Promise<TranscriptionFormats> {
    return this.client.request('GET', '/api/v1/transcription/formats');
  }

  /**
   * Transcribe an audio file.
   * Note: File upload should be handled separately via multipart/form-data.
   * This method accepts base64-encoded audio data.
   */
  async transcribeAudio(
    audioData: string,
    options?: TranscriptionOptions
  ): Promise<TranscriptionResult> {
    return this.client.request('POST', '/api/v1/transcription/audio', {
      json: {
        audio_data: audioData,
        ...options,
      } as unknown as Record<string, unknown>,
    });
  }

  /**
   * Transcribe a video file.
   * Note: File upload should be handled separately via multipart/form-data.
   * This method accepts base64-encoded video data.
   */
  async transcribeVideo(
    videoData: string,
    options?: TranscriptionOptions
  ): Promise<TranscriptionResult> {
    return this.client.request('POST', '/api/v1/transcription/video', {
      json: {
        video_data: videoData,
        ...options,
      } as unknown as Record<string, unknown>,
    });
  }

  /**
   * Transcribe a YouTube video.
   */
  async transcribeYouTube(
    url: string,
    options?: YouTubeTranscriptionOptions
  ): Promise<TranscriptionResult> {
    return this.client.request('POST', '/api/v1/transcription/youtube', {
      json: {
        url,
        ...options,
      } as unknown as Record<string, unknown>,
    });
  }

  /**
   * Get YouTube video metadata without transcribing.
   */
  async getYouTubeInfo(url: string): Promise<YouTubeVideoInfo> {
    return this.client.request('POST', '/api/v1/transcription/youtube/info', {
      json: { url },
    });
  }

  /**
   * Get transcription job status.
   */
  async getStatus(jobId: string): Promise<JobStatusResponse> {
    return this.client.request('GET', `/api/v1/transcription/status/${encodeURIComponent(jobId)}`);
  }

  /**
   * Upload and queue audio/video for async transcription.
   * Note: File upload should be handled separately via multipart/form-data.
   */
  async upload(
    fileData: string,
    filename: string
  ): Promise<UploadResponse> {
    return this.client.request('POST', '/api/v1/transcription/upload', {
      json: {
        file_data: fileData,
        filename,
      },
    });
  }

}
