/**
 * Voice Namespace API
 *
 * Provides endpoints for voice/TTS integration including
 * voice sessions, speech-to-text, Twilio webhook handling,
 * and debate audio synthesis.
 */

import type { AragoraClient } from '../client';

/** Voice session state */
export interface VoiceSession {
  id: string;
  status: 'active' | 'completed' | 'failed';
  caller_number?: string;
  debate_id?: string;
  started_at: string;
  ended_at?: string;
  duration_seconds?: number;
}

/** TTS synthesis request */
export interface SynthesizeRequest {
  text: string;
  voice?: string;
  format?: 'mp3' | 'wav' | 'ogg';
  speed?: number;
}

/** TTS synthesis result */
export interface SynthesizeResult {
  audio_url: string;
  duration_seconds: number;
  format: string;
  voice: string;
}

/** Voice configuration */
export interface VoiceConfig {
  enabled: boolean;
  default_voice: string;
  available_voices: string[];
  tts_provider: string;
}

/** Available voice entry */
export interface VoiceEntry {
  id: string;
  name: string;
  language: string;
  gender?: string;
  provider: string;
}

/** Device association request */
export interface DeviceAssociationRequest {
  call_sid: string;
  device_id: string;
}

/** Device association result */
export interface DeviceAssociationResult {
  status: string;
  call_sid: string;
  device_id: string;
}

/**
 * Voice namespace for TTS, Twilio webhook, and voice integration.
 *
 * @example
 * ```typescript
 * const config = await client.voice.getConfig();
 * const audio = await client.voice.synthesize({ text: 'Hello world' });
 * ```
 */
export class VoiceNamespace {
  constructor(private client: AragoraClient) {}

  // -- TTS and session management -------------------------------------------

  /** Get voice configuration. */
  async getConfig(): Promise<VoiceConfig> {
    /** @route GET /api/v1/voice/config */
    return this.client.request('GET', '/api/v1/voice/config');
  }

  /** List available voices. */
  async listVoices(): Promise<VoiceEntry[]> {
    /** @route GET /api/v1/voice/voices */
    return this.client.request('GET', '/api/v1/voice/voices');
  }

  /** List voice sessions. */
  async listSessions(options?: {
    limit?: number;
    offset?: number;
    status?: string;
  }): Promise<VoiceSession[]> {
    /** @route GET /api/v1/voice/sessions */
    const response = await this.client.request<{ sessions: VoiceSession[] }>(
      'GET',
      '/api/v1/voice/sessions',
      { params: options }
    );
    return response.sessions;
  }

  /** Get a voice session by ID. */
  async getSession(sessionId: string): Promise<VoiceSession> {
    /** @route GET /api/v1/voice/sessions/{session_id} */
    return this.client.request('GET', `/api/v1/voice/sessions/${encodeURIComponent(sessionId)}`);
  }

  /** Synthesize text to speech. */
  async synthesize(request: SynthesizeRequest): Promise<SynthesizeResult> {
    /** @route POST /api/v1/voice/synthesize */
    return this.client.request('POST', '/api/v1/voice/synthesize', { body: request });
  }

  // -- Twilio voice webhook endpoints ---------------------------------------

  /** Trigger the inbound call webhook handler. */
  async handleInbound(callSid: string, caller: string = '', called: string = ''): Promise<any> {
    /** @route POST /api/v1/voice/inbound */
    return this.client.request('POST', '/api/v1/voice/inbound', {
      body: { CallSid: callSid, From: caller, To: called },
    });
  }

  /** Send a call status callback. */
  async getCallStatus(
    callSid: string,
    callStatus: string = '',
    options?: { CallDuration?: string; RecordingUrl?: string }
  ): Promise<any> {
    /** @route POST /api/v1/voice/status */
    return this.client.request('POST', '/api/v1/voice/status', {
      body: { CallSid: callSid, CallStatus: callStatus, ...options },
    });
  }

  /** Submit speech gather result from a call. */
  async submitGather(
    callSid: string,
    speechResult: string = '',
    confidence: number = 0.0
  ): Promise<any> {
    /** @route POST /api/v1/voice/gather */
    return this.client.request('POST', '/api/v1/voice/gather', {
      body: {
        CallSid: callSid,
        SpeechResult: speechResult,
        Confidence: String(confidence),
      },
    });
  }

  /** Submit confirmation digit press for a gather result. */
  async confirmGather(callSid: string, digits: string = ''): Promise<any> {
    /** @route POST /api/v1/voice/gather/confirm */
    return this.client.request('POST', '/api/v1/voice/gather/confirm', {
      body: { CallSid: callSid, Digits: digits },
    });
  }

  /** Associate a voice call with a registered device. */
  async associateDevice(callSid: string, deviceId: string): Promise<DeviceAssociationResult> {
    /** @route POST /api/v1/voice/device */
    return this.client.request('POST', '/api/v1/voice/device', {
      body: { call_sid: callSid, device_id: deviceId },
    });
  }
}
