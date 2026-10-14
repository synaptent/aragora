/**
 * Podcast Namespace API
 *
 * Provides endpoints for generating podcast feeds from debates,
 * including RSS feed generation and episode management.
 */

import type { AragoraClient } from '../client';

/**
 * Podcast episode
 */
export interface PodcastEpisode {
  id: string;
  debate_id: string;
  title: string;
  description: string;
  audio_url: string;
  duration_seconds: number;
  published_at: string;
  file_size_bytes: number;
  format: 'mp3' | 'aac' | 'm4a';
  participants: string[];
  topics: string[];
  transcript_url?: string;
}

/**
 * Podcast feed metadata
 */
export interface PodcastFeed {
  title: string;
  description: string;
  author: string;
  email?: string;
  image_url?: string;
  language: string;
  category: string;
  explicit: boolean;
  feed_url: string;
  website_url?: string;
  episodes: PodcastEpisode[];
  total_episodes: number;
  last_updated: string;
}

/**
 * Episode generation options
 */
export interface GenerateEpisodeOptions {
  title?: string;
  description?: string;
  voice?: string;
  format?: 'mp3' | 'aac' | 'm4a';
  include_intro?: boolean;
  include_outro?: boolean;
  background_music?: boolean;
}

/**
 * Podcast namespace for audio content generation.
 *
 * @example
 * ```typescript
 * // Get podcast episodes
 * const episodes = await client.podcast.listEpisodes();
 * console.log(`${episodes.length} episodes available`);
 *
 * // Get RSS feed URL
 * const feedUrl = client.podcast.getFeedUrl();
 * console.log(`Subscribe at: ${feedUrl}`);
 * ```
 */
export class PodcastNamespace {
  constructor(private client: AragoraClient) {}

  /**
   * List all podcast episodes.
   *
   * @param options.limit - Maximum episodes to return
   * @param options.offset - Pagination offset
   * @param options.since - Only episodes after this date
   */
  async listEpisodes(options?: {
    limit?: number;
    offset?: number;
    since?: string;
  }): Promise<PodcastEpisode[]> {
    const response = await this.client.request<{ episodes: PodcastEpisode[] }>(
      'GET',
      '/api/v1/podcast/episodes',
      { params: options }
    );
    return response.episodes;
  }

  /**
   * Get the full podcast feed metadata.
   */
  async getFeed(): Promise<PodcastFeed> {
    return this.client.request<PodcastFeed>('GET', '/api/v1/podcast/feed');
  }

  /**
   * Get the RSS feed URL for podcast subscription.
   *
   * This URL can be used in podcast apps like Apple Podcasts, Spotify, etc.
   */
  getFeedUrl(): string {
    return `${this.client.getBaseUrl()}/api/v1/podcast/feed.xml`;
  }

  /**
   * Generate a podcast episode from a debate.
   *
   * @param debateId - The debate to convert to audio
   * @param options - Episode generation options
   */
  async generateEpisode(
    debateId: string,
    options?: GenerateEpisodeOptions
  ): Promise<PodcastEpisode> {
    return this.client.request<PodcastEpisode>(
      'POST',
      `/api/v1/debates/${encodeURIComponent(debateId)}/podcast`,
      { body: options }
    );
  }

}
