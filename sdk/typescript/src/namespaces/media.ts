/**
 * Media Namespace API
 *
 * Provides access to media assets including audio files and podcast episodes.
 *
 * Features:
 * - Direct audio URL generation
 * - Audio file listing and upload
 * - Podcast episode management
 * - RSS feed access
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai', apiKey: 'your-key' });
 *
 * // Build a direct playback URL for a debate's audio
 * const url = client.media.getAudioUrl('debate_456');
 *
 * // List podcast episodes
 * const { episodes } = await client.media.listPodcastEpisodes({ limit: 10 });
 *
 * // Upload audio
 * const uploaded = await client.media.uploadAudio({
 *   filePath: '/path/to/audio.mp3',
 *   debateId: 'debate_456'
 * });
 * ```
 */

/**
 * Supported audio formats for upload.
 */
export type AudioFormat = 'mp3' | 'aac' | 'm4a' | 'wav' | 'ogg';

/**
 * Audio file metadata.
 */
export interface AudioFile {
  /** Unique audio file identifier */
  id: string;
  /** Associated debate ID, if any */
  debate_id?: string;
  /** Direct URL to the audio file */
  url: string;
  /** Audio duration in seconds */
  duration_seconds?: number;
  /** Audio format (mp3, aac, etc.) */
  format: string;
  /** File size in bytes */
  size_bytes?: number;
  /** ISO timestamp when the file was created */
  created_at?: string;
  /** Additional metadata */
  metadata?: Record<string, unknown>;
}

/**
 * Audio file list response.
 */
export interface AudioListResponse {
  /** List of audio files */
  audio_files: AudioFile[];
  /** Total count of audio files matching the filter */
  total: number;
}

/**
 * Audio upload parameters.
 */
export interface AudioUploadParams {
  /** Path to the audio file */
  filePath: string;
  /** Optional debate ID to associate with */
  debateId?: string;
  /** Audio format (mp3, aac, m4a, wav, ogg) */
  format?: AudioFormat;
  /** Optional metadata for the audio file */
  metadata?: Record<string, unknown>;
}

/**
 * Audio conversion parameters.
 */
export interface AudioConversionParams {
  /** Target audio format */
  targetFormat: AudioFormat;
  /** Optional target bitrate in kbps */
  bitrate?: number;
}

/**
 * Transcription result.
 */
export interface Transcription {
  /** The transcription text */
  text: string;
  /** Confidence score (0-1) */
  confidence?: number;
  /** Language detected */
  language?: string;
  /** Word-level timestamps, if available */
  words?: Array<{
    word: string;
    start_time: number;
    end_time: number;
    confidence?: number;
  }>;
  /** ISO timestamp when transcription was generated */
  created_at?: string;
}

/**
 * Podcast episode metadata.
 */
export interface PodcastEpisode {
  /** Unique episode identifier */
  id: string;
  /** Episode title */
  title: string;
  /** Episode description */
  description?: string;
  /** Direct URL to the episode audio */
  audio_url: string;
  /** Associated debate ID, if any */
  debate_id?: string;
  /** Episode duration in seconds */
  duration_seconds?: number;
  /** ISO timestamp when the episode was published */
  published_at?: string;
  /** Additional metadata */
  metadata?: Record<string, unknown>;
}

/**
 * Podcast feed metadata.
 */
export interface PodcastFeed {
  /** RSS feed URL */
  feed_url: string;
  /** Podcast title */
  title: string;
  /** Podcast description */
  description?: string;
  /** List of episodes */
  episodes: PodcastEpisode[];
  /** Total episode count */
  total: number;
}

/**
 * Client interface for media operations.
 */
interface MediaClientInterface {
  request<T = unknown>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown>; json?: Record<string, unknown> }
  ): Promise<T>;
}

/**
 * Media API namespace.
 *
 * Provides methods for media asset management:
 * - Direct audio URLs, audio listing and upload
 * - Podcast episode management
 * - RSS feed access
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai', apiKey: 'your-key' });
 *
 * // Build a direct playback URL for a debate's audio
 * const url = client.media.getAudioUrl('debate_456');
 *
 * // Browse podcast episodes
 * const { episodes } = await client.media.listPodcastEpisodes({ limit: 10 });
 * ```
 */
export class MediaAPI {
  constructor(private client: MediaClientInterface) {}

  // =========================================================================
  // Audio Files
  // =========================================================================

  /**
   * Get the direct audio file URL for a debate or audio file.
   *
   * This URL can be used to stream or download the audio file directly.
   *
   * @param audioId - The audio file identifier
   * @returns Direct URL to the audio file in MP3 format
   *
   * @example
   * ```typescript
   * const url = client.media.getAudioUrl('audio_123');
   * // Use url in audio player or for download
   * ```
   */
  getAudioUrl(audioId: string): string {
    return `/audio/${audioId}.mp3`;
  }

  /**
   * List audio files with optional filtering.
   *
   * @param options - Filtering and pagination options
   * @param options.limit - Maximum number of files to return
   * @param options.offset - Pagination offset
   * @param options.debateId - Filter by associated debate ID
   * @returns List of audio files and total count
   *
   * @example
   * ```typescript
   * // List all audio files
   * const { audio_files, total } = await client.media.listAudio({ limit: 20 });
   *
   * // List audio for a specific debate
   * const debateAudio = await client.media.listAudio({ debateId: 'debate_456' });
   * ```
   */
  async listAudio(options?: {
    limit?: number;
    offset?: number;
    debateId?: string;
  }): Promise<AudioListResponse> {
    const params: Record<string, unknown> = {};
    if (options?.limit !== undefined) params.limit = options.limit;
    if (options?.offset !== undefined) params.offset = options.offset;
    if (options?.debateId !== undefined) params.debate_id = options.debateId;

    return this.client.request('GET', '/api/v1/media/audio', {
      params: Object.keys(params).length > 0 ? params : undefined,
    });
  }

  /**
   * Upload an audio file.
   *
   * @param params - Upload parameters
   * @param params.filePath - Path to the audio file
   * @param params.debateId - Optional debate ID to associate with
   * @param params.format - Audio format (mp3, aac, m4a, wav, ogg)
   * @param params.metadata - Optional metadata for the audio file
   * @returns Uploaded audio file details
   *
   * @example
   * ```typescript
   * const uploaded = await client.media.uploadAudio({
   *   filePath: '/path/to/recording.mp3',
   *   debateId: 'debate_123',
   *   format: 'mp3',
   *   metadata: { speaker: 'Agent A' }
   * });
   * ```
   */
  async uploadAudio(params: AudioUploadParams): Promise<AudioFile> {
    const json: Record<string, unknown> = {
      file_path: params.filePath,
    };
    if (params.debateId !== undefined) json.debate_id = params.debateId;
    if (params.format !== undefined) json.format = params.format;
    if (params.metadata !== undefined) json.metadata = params.metadata;

    return this.client.request('POST', '/api/v1/media/audio', { json });
  }

  // =========================================================================
  // Podcast Episodes
  // =========================================================================

  /**
   * List podcast episodes.
   *
   * @param options - Pagination options
   * @param options.limit - Maximum number of episodes to return
   * @param options.offset - Pagination offset
   * @returns List of episodes and total count
   *
   * @example
   * ```typescript
   * const { episodes, total } = await client.media.listPodcastEpisodes({ limit: 10 });
   * episodes.forEach(ep => console.log(`${ep.title}: ${ep.duration_seconds}s`));
   * ```
   */
  async listPodcastEpisodes(options?: {
    limit?: number;
    offset?: number;
  }): Promise<{ episodes: PodcastEpisode[]; total: number }> {
    const params: Record<string, unknown> = {};
    if (options?.limit !== undefined) params.limit = options.limit;
    if (options?.offset !== undefined) params.offset = options.offset;

    return this.client.request('GET', '/api/v1/podcast/episodes', {
      params: Object.keys(params).length > 0 ? params : undefined,
    });
  }

  /**
   * Get a specific podcast episode by ID.
   *
   * @param episodeId - The episode identifier
   * @returns Episode details including title, description, audio URL, and duration
   *
   * @example
   * ```typescript
   * const episode = await client.media.getPodcastEpisode('episode_123');
   * console.log(`${episode.title}: ${episode.description}`);
   * ```
   */
  async getPodcastEpisode(episodeId: string): Promise<PodcastEpisode> {
    return this.client.request('GET', `/api/v1/podcast/episodes/${episodeId}`);
  }

  /**
   * Get the podcast RSS feed URL.
   *
   * This URL can be used in podcast apps like Apple Podcasts, Spotify, etc.
   *
   * @returns RSS feed URL for podcast subscription
   *
   * @example
   * ```typescript
   * const feedUrl = client.media.getFeedUrl();
   * // Subscribe to the podcast using this URL
   * ```
   */
  getFeedUrl(): string {
    return '/api/v1/podcast/feed.xml';
  }

  /**
   * Get the full podcast feed metadata.
   *
   * @returns Feed metadata including title, description, and episodes
   *
   * @example
   * ```typescript
   * const feed = await client.media.getFeed();
   * console.log(`${feed.title}: ${feed.total} episodes`);
   * ```
   */
  async getFeed(): Promise<PodcastFeed> {
    return this.client.request('GET', '/api/v1/podcast/feed');
  }

  // =========================================================================
  // Unsupported Media Operations
  // =========================================================================

  /**
   * Guard unsupported conversion access until the API publishes this route.
   *
   * @param audioId - The source audio file identifier
   * @param options - Conversion options
   * @param options.targetFormat - Target format (mp3, aac, m4a, wav, ogg)
   * @param options.bitrate - Optional target bitrate in kbps
   * @throws Error because the public API does not expose this route
   */
  async convertAudio(
    _audioId: string,
    _options: AudioConversionParams
  ): Promise<AudioFile> {
    throw new Error(
      'POST /api/v1/media/audio/{audioId}/convert is not part of the current Aragora API contract.'
    );
  }

  /**
   * Guard unsupported transcription access until the API publishes this route.
   *
   * @param audioId - The audio file identifier
   * @throws Error because the public API does not expose this route
   */
  async getTranscription(_audioId: string): Promise<Transcription> {
    throw new Error(
      'GET /api/v1/media/audio/{audioId}/transcription is not part of the current Aragora API contract.'
    );
  }
}
