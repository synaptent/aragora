/**
 * Tests for the /review-queue/packets/[receiptId] settlement-packet
 * sign-off route — file pick, SHA verification, per-PR decision
 * capture, and signed-download trigger.
 */
import { webcrypto } from 'node:crypto';
import { TextDecoder as NodeTextDecoder, TextEncoder as NodeTextEncoder } from 'node:util';
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';
import { useParams } from 'next/navigation';

// jsdom does not expose TextEncoder/TextDecoder nor crypto.subtle —
// install polyfills with Object.defineProperty since jsdom locks
// `globalThis.crypto` as a non-writable property in newer builds.
if (typeof globalThis.TextEncoder === 'undefined') {
  Object.defineProperty(globalThis, 'TextEncoder', {
    value: NodeTextEncoder,
    configurable: true,
    writable: true,
  });
}
if (typeof globalThis.TextDecoder === 'undefined') {
  Object.defineProperty(globalThis, 'TextDecoder', {
    value: NodeTextDecoder,
    configurable: true,
    writable: true,
  });
}
const existingCrypto = (globalThis as { crypto?: { subtle?: unknown } }).crypto;
if (!existingCrypto || !existingCrypto.subtle) {
  Object.defineProperty(globalThis, 'crypto', {
    value: webcrypto,
    configurable: true,
    writable: true,
  });
}

jest.mock('../src/config', () => ({
  API_BASE_URL: 'http://localhost:8080',
  WS_URL: 'ws://localhost:8765/ws',
}));

jest.mock('@/components/MatrixRain', () => ({ Scanlines: () => null, CRTVignette: () => null }));

import PacketsClient from '../src/app/(app)/review-queue/packets/[receiptId]/PacketsClient';
import { canonicalJson, type SettlementReceipt } from '../src/hooks/useReviewQueueFromPacket';

const RECEIPT_ID_HINT = 'open-queue-settlement-20260517T142811Z';

function buildReceipt(): SettlementReceipt {
  return {
    schema_version: 'aragora-open-queue-settlement/1.0',
    generated_at_utc: '2026-05-17T14:28:11.000Z',
    repo: 'synaptent/aragora',
    pinned_state: [
      {
        number: 7240,
        head_sha: 'aaaaaaaaaaaaaaaa',
        draft: false,
        decision: 'REVIEW_REQUIRED',
        merge_state: 'BLOCKED',
        tier: '2',
        in_flight: 0,
        failures: 0,
        successes: 57,
        files_touched_count: 18,
        recommended_action: 'APPROVE Tier 2',
      },
      {
        number: 7245,
        head_sha: 'bbbbbbbbbbbbbbbb',
        draft: false,
        decision: 'REVIEW_REQUIRED',
        merge_state: 'BLOCKED',
        tier: '2',
        in_flight: 1,
        failures: 0,
        successes: 56,
        files_touched_count: 22,
        recommended_action: 'APPROVE Tier 2',
      },
    ],
  };
}

async function withSha(receipt: SettlementReceipt): Promise<SettlementReceipt> {
  const verifyCopy: Record<string, unknown> = { ...receipt };
  delete verifyCopy.sha256;
  delete verifyCopy.hmac_sha256;
  delete verifyCopy.signed_at_utc;
  const canonical = canonicalJson(verifyCopy);
  const bytes = new TextEncoder().encode(canonical);
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  const hex = Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
  return { ...receipt, sha256: hex };
}

function fakeFile(payload: unknown, name = 'receipt.json'): File {
  const text = JSON.stringify(payload);
  // jsdom's File supports .text() in recent versions; provide a guard
  // in case the test env lacks it.
  const file = new File([text], name, { type: 'application/json' });
  if (typeof (file as unknown as { text?: () => Promise<string> }).text !== 'function') {
    Object.defineProperty(file, 'text', { value: () => Promise.resolve(text), configurable: true });
  }
  return file;
}

async function pickReceiptFile(receipt: SettlementReceipt) {
  const input = screen.getByTestId('packets-file-input') as HTMLInputElement;
  const file = fakeFile(receipt);
  Object.defineProperty(input, 'files', { value: [file], configurable: true });
  await act(async () => {
    fireEvent.change(input);
  });
}

beforeEach(() => {
  (useParams as jest.Mock).mockReturnValue({ receiptId: RECEIPT_ID_HINT });
});

describe('ReviewQueuePacketsPage', () => {
  it('shows the placeholder before any receipt is loaded', () => {
    render(<PacketsClient />);
    expect(screen.getByTestId('packets-placeholder')).toBeInTheDocument();
    expect(screen.getByTestId('packets-receipt-hint')).toHaveTextContent(RECEIPT_ID_HINT);
  });

  it('renders parse error when the file is not JSON', async () => {
    render(<PacketsClient />);
    const input = screen.getByTestId('packets-file-input') as HTMLInputElement;
    const bogus = new File(['not json'], 'bogus.json', { type: 'application/json' });
    Object.defineProperty(bogus, 'text', {
      value: () => Promise.resolve('not json'),
      configurable: true,
    });
    Object.defineProperty(input, 'files', { value: [bogus], configurable: true });
    await act(async () => {
      fireEvent.change(input);
    });

    await waitFor(() => {
      expect(screen.getByTestId('packets-load-error')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('packets-decision-list')).toBeNull();
  });

  it('rejects receipts that are missing pinned_state[]', async () => {
    render(<PacketsClient />);
    const input = screen.getByTestId('packets-file-input') as HTMLInputElement;
    const malformed = fakeFile({ schema_version: 'x' });
    Object.defineProperty(input, 'files', { value: [malformed], configurable: true });
    await act(async () => {
      fireEvent.change(input);
    });

    await waitFor(() => {
      expect(screen.getByTestId('packets-load-error')).toHaveTextContent(/pinned_state/);
    });
  });

  it('renders one PacketDecisionCard per pinned PR after a valid receipt loads', async () => {
    const receipt = buildReceipt();
    render(<PacketsClient />);
    await pickReceiptFile(receipt);

    await waitFor(() => {
      expect(screen.getByTestId('packets-decision-list')).toBeInTheDocument();
    });

    expect(screen.getByTestId('packet-decision-card-7240')).toBeInTheDocument();
    expect(screen.getByTestId('packet-decision-card-7245')).toBeInTheDocument();
    expect(screen.getByTestId('packets-pr-count')).toHaveTextContent('2');
    expect(screen.getByTestId('packets-decided-count')).toHaveTextContent('0/2');
    expect(screen.getByTestId('packets-remaining-count')).toHaveTextContent(/2 PRs undecided/);
    expect(screen.getByTestId('packet-decision-recommendation-7240')).toHaveTextContent(
      'APPROVE Tier 2',
    );
  });

  it('surfaces sha256 payload match when receipt carries a matching hash', async () => {
    const receipt = await withSha(buildReceipt());
    render(<PacketsClient />);
    await pickReceiptFile(receipt);

    await waitFor(() => {
      expect(screen.getByTestId('packets-sha-check')).toHaveTextContent(/payload match/);
    });
    expect(screen.getByTestId('packets-hmac-check')).toHaveTextContent(/hash-only receipt/);
  });

  it('does not claim browser-side HMAC verification for signed receipts', async () => {
    const receipt = await withSha({
      ...buildReceipt(),
      hmac_sha256: 'f'.repeat(64),
      signed_at_utc: '2026-05-17T14:29:11.000Z',
    });
    render(<PacketsClient />);
    await pickReceiptFile(receipt);

    await waitFor(() => {
      expect(screen.getByTestId('packets-sha-check')).toHaveTextContent(/payload match/);
    });
    expect(screen.getByTestId('packets-hmac-check')).toHaveTextContent(/not verified in browser/);
  });

  it('detects sha256 mismatch when the claimed hash is wrong', async () => {
    const receipt: SettlementReceipt = { ...buildReceipt(), sha256: 'deadbeef' };
    render(<PacketsClient />);
    await pickReceiptFile(receipt);

    await waitFor(() => {
      expect(screen.getByTestId('packets-sha-check')).toHaveTextContent(/payload mismatch/);
    });
  });

  it('updates the decided counter when an option is chosen', async () => {
    render(<PacketsClient />);
    await pickReceiptFile(buildReceipt());

    await waitFor(() => {
      expect(screen.getByTestId('packet-decision-card-7240')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('packet-decision-option-7240-approve_tier'));
    await waitFor(() => {
      expect(screen.getByTestId('packets-decided-count')).toHaveTextContent('1/2');
    });
    expect(screen.getByTestId('packets-remaining-count')).toHaveTextContent(/1 PR undecided/);
  });

  it('disables download until at least one decision is recorded, then triggers a Blob download', async () => {
    const blobs: Array<{ body: string }> = [];
    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;
    const createObjectURL = jest.fn((blob: Blob) => {
      const reader = new FileReader();
      reader.readAsText(blob);
      // sync test capture — push placeholder; we'll inspect by mocking JSON.stringify
      blobs.push({ body: '' });
      return 'blob://test';
    });
    Object.defineProperty(URL, 'createObjectURL', {
      value: createObjectURL,
      configurable: true,
      writable: true,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      value: jest.fn(),
      configurable: true,
      writable: true,
    });

    // Spy on Blob construction so we can verify download body shape.
    const blobBodies: string[] = [];
    const RealBlob = globalThis.Blob;
    class SpyBlob extends RealBlob {
      constructor(parts: BlobPart[], options?: BlobPropertyBag) {
        super(parts, options);
        blobBodies.push(parts.map(String).join(''));
      }
    }
    Object.defineProperty(globalThis, 'Blob', {
      value: SpyBlob,
      configurable: true,
      writable: true,
    });

    try {
      render(<PacketsClient />);
      await pickReceiptFile(buildReceipt());

      await waitFor(() => {
        expect(screen.getByTestId('packets-decision-list')).toBeInTheDocument();
      });

      const downloadBtn = screen.getByTestId('packets-download-button') as HTMLButtonElement;
      expect(downloadBtn.disabled).toBe(true);

      fireEvent.click(screen.getByTestId('packet-decision-option-7245-reject'));
      fireEvent.change(screen.getByTestId('packet-decision-comment-7245'), {
        target: { value: 'duplicate of #7240' },
      });

      await waitFor(() => {
        expect(downloadBtn.disabled).toBe(false);
      });

      await act(async () => {
        fireEvent.click(downloadBtn);
      });

      await waitFor(() => {
        expect(screen.getByTestId('packets-download-status')).toHaveTextContent(
          /downloaded operator-decisions-/,
        );
      });
      expect(createObjectURL).toHaveBeenCalledTimes(1);
      expect(blobBodies).toHaveLength(1);
      const parsed = JSON.parse(blobBodies[0]) as {
        schema_version: string;
        receipt_id_hint: string;
        receipt_hmac_sha256_present: boolean;
        receipt_hmac_sha256_verified: boolean;
        decisions: Array<{ pr_number: number; decision: string | null; comment: string }>;
        payload_sha256: string;
      };
      expect(parsed.schema_version).toBe('aragora-operator-decisions/1.0');
      expect(parsed.receipt_id_hint).toBe(RECEIPT_ID_HINT);
      expect(parsed.payload_sha256).toMatch(/^[0-9a-f]{64}$/);
      expect(parsed.receipt_hmac_sha256_present).toBe(false);
      expect(parsed.receipt_hmac_sha256_verified).toBe(false);
      const reject = parsed.decisions.find((d) => d.pr_number === 7245);
      expect(reject?.decision).toBe('reject');
      expect(reject?.comment).toBe('duplicate of #7240');
      const undecided = parsed.decisions.find((d) => d.pr_number === 7240);
      expect(undecided?.decision).toBeNull();
    } finally {
      Object.defineProperty(globalThis, 'Blob', {
        value: RealBlob,
        configurable: true,
        writable: true,
      });
      Object.defineProperty(URL, 'createObjectURL', {
        value: originalCreate,
        configurable: true,
        writable: true,
      });
      Object.defineProperty(URL, 'revokeObjectURL', {
        value: originalRevoke,
        configurable: true,
        writable: true,
      });
    }
  });
});

describe('ReviewQueuePacketsPage keyboard sign-off', () => {
  beforeEach(() => {
    (useParams as jest.Mock).mockReturnValue({ receiptId: RECEIPT_ID_HINT });
  });

  it('auto-selects the first card after a receipt loads', async () => {
    render(<PacketsClient />);
    await pickReceiptFile(buildReceipt());
    await waitFor(() => {
      expect(screen.getByTestId('packets-decision-list')).toBeInTheDocument();
    });
    expect(screen.getByTestId('packet-decision-card-7240')).toHaveAttribute(
      'data-selected',
      'true',
    );
    expect(screen.getByTestId('packet-decision-card-7245')).toHaveAttribute(
      'data-selected',
      'false',
    );
  });

  it('moves selection on j and k', async () => {
    render(<PacketsClient />);
    await pickReceiptFile(buildReceipt());
    await waitFor(() => {
      expect(screen.getByTestId('packet-decision-card-7240')).toHaveAttribute(
        'data-selected',
        'true',
      );
    });

    fireEvent.keyDown(window, { key: 'j' });
    await waitFor(() => {
      expect(screen.getByTestId('packet-decision-card-7245')).toHaveAttribute(
        'data-selected',
        'true',
      );
    });

    fireEvent.keyDown(window, { key: 'k' });
    await waitFor(() => {
      expect(screen.getByTestId('packet-decision-card-7240')).toHaveAttribute(
        'data-selected',
        'true',
      );
    });
  });

  it('digit 1..5 picks the decision option in PACKET_DECISION_OPTIONS order', async () => {
    render(<PacketsClient />);
    await pickReceiptFile(buildReceipt());
    await waitFor(() => {
      expect(screen.getByTestId('packets-decision-list')).toBeInTheDocument();
    });

    // First card is 7240 — digit "1" should select approve_tier.
    fireEvent.keyDown(window, { key: '1' });
    await waitFor(() => {
      const input = screen.getByTestId(
        'packet-decision-option-7240-approve_tier',
      ) as HTMLInputElement;
      expect(input.checked).toBe(true);
    });

    // Move to second card and press 4 → reject.
    fireEvent.keyDown(window, { key: 'j' });
    fireEvent.keyDown(window, { key: '4' });
    await waitFor(() => {
      const input = screen.getByTestId('packet-decision-option-7245-reject') as HTMLInputElement;
      expect(input.checked).toBe(true);
    });

    expect(screen.getByTestId('packets-decided-count')).toHaveTextContent('2/2');
  });

  it('does not treat Tab as a global packet shortcut', async () => {
    render(<PacketsClient />);
    await pickReceiptFile(buildReceipt());
    await waitFor(() => {
      expect(screen.getByTestId('packets-decision-list')).toBeInTheDocument();
    });

    const event = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
    window.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(false);
    expect(document.activeElement).not.toBe(screen.getByTestId('packet-decision-comment-7240'));
  });

  it('? toggles the keyboard help overlay; Esc closes it', async () => {
    render(<PacketsClient />);
    await pickReceiptFile(buildReceipt());
    await waitFor(() => {
      expect(screen.getByTestId('packets-decision-list')).toBeInTheDocument();
    });

    fireEvent.keyDown(window, { key: '?' });
    await waitFor(() => {
      expect(screen.getByTestId('packets-help-overlay')).toBeInTheDocument();
    });

    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => {
      expect(screen.queryByTestId('packets-help-overlay')).toBeNull();
    });
  });

  it('does not handle digit keys while the comment textarea has focus', async () => {
    render(<PacketsClient />);
    await pickReceiptFile(buildReceipt());
    await waitFor(() => {
      expect(screen.getByTestId('packets-decision-list')).toBeInTheDocument();
    });

    const textarea = screen.getByTestId('packet-decision-comment-7240') as HTMLTextAreaElement;
    textarea.focus();
    fireEvent.keyDown(textarea, { key: '1' });

    // No decision should have been recorded because the textarea swallowed it.
    const input = screen.getByTestId(
      'packet-decision-option-7240-approve_tier',
    ) as HTMLInputElement;
    expect(input.checked).toBe(false);
  });

  it('does not toggle keyboard help while typing ? in the comment textarea', async () => {
    render(<PacketsClient />);
    await pickReceiptFile(buildReceipt());
    await waitFor(() => {
      expect(screen.getByTestId('packets-decision-list')).toBeInTheDocument();
    });

    const textarea = screen.getByTestId('packet-decision-comment-7240') as HTMLTextAreaElement;
    textarea.focus();
    fireEvent.keyDown(textarea, { key: '?' });

    expect(screen.queryByTestId('packets-help-overlay')).toBeNull();
  });

  it('records per-decision timing fields in the downloaded JSON', async () => {
    // Spy on Blob to capture the body, mock URL.createObjectURL to noop.
    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;
    Object.defineProperty(URL, 'createObjectURL', {
      value: jest.fn(() => 'blob://test'),
      configurable: true,
      writable: true,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      value: jest.fn(),
      configurable: true,
      writable: true,
    });
    const blobBodies: string[] = [];
    const RealBlob = globalThis.Blob;
    class SpyBlob extends RealBlob {
      constructor(parts: BlobPart[], options?: BlobPropertyBag) {
        super(parts, options);
        blobBodies.push(parts.map(String).join(''));
      }
    }
    Object.defineProperty(globalThis, 'Blob', {
      value: SpyBlob,
      configurable: true,
      writable: true,
    });

    try {
      render(<PacketsClient />);
      await pickReceiptFile(buildReceipt());
      await waitFor(() => {
        expect(screen.getByTestId('packets-decision-list')).toBeInTheDocument();
      });

      // Press digit 3 → request_changes on the auto-selected first card.
      fireEvent.keyDown(window, { key: '3' });
      await waitFor(() => {
        const input = screen.getByTestId(
          'packet-decision-option-7240-request_changes',
        ) as HTMLInputElement;
        expect(input.checked).toBe(true);
      });

      const downloadBtn = screen.getByTestId('packets-download-button') as HTMLButtonElement;
      await act(async () => {
        fireEvent.click(downloadBtn);
      });

      await waitFor(() => {
        expect(screen.getByTestId('packets-download-status')).toHaveTextContent(
          /downloaded operator-decisions-/,
        );
      });

      expect(blobBodies).toHaveLength(1);
      const parsed = JSON.parse(blobBodies[0]) as {
        decisions: Array<{
          pr_number: number;
          decision: string | null;
          first_focused_at_utc: string | null;
          decided_at_utc: string | null;
          decision_seconds: number | null;
        }>;
      };
      const decided = parsed.decisions.find((d) => d.pr_number === 7240);
      expect(decided?.decision).toBe('request_changes');
      // Both timestamps should be ISO-8601 strings on the decided entry.
      expect(decided?.first_focused_at_utc).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/);
      expect(decided?.decided_at_utc).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/);
      expect(typeof decided?.decision_seconds).toBe('number');
      expect(decided?.decision_seconds ?? -1).toBeGreaterThanOrEqual(0);

      const undecided = parsed.decisions.find((d) => d.pr_number === 7245);
      // Never focused (and never decided) → both null.
      expect(undecided?.first_focused_at_utc).toBeNull();
      expect(undecided?.decided_at_utc).toBeNull();
      expect(undecided?.decision_seconds).toBeNull();
    } finally {
      Object.defineProperty(globalThis, 'Blob', {
        value: RealBlob,
        configurable: true,
        writable: true,
      });
      Object.defineProperty(URL, 'createObjectURL', {
        value: originalCreate,
        configurable: true,
        writable: true,
      });
      Object.defineProperty(URL, 'revokeObjectURL', {
        value: originalRevoke,
        configurable: true,
        writable: true,
      });
    }
  });
});
