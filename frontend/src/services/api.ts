import {
  ClaimPreview,
  ConfirmedClaim,
  Offer,
  OfferUploadResponse,
  RunSnapshot,
} from '../types';
import { caseAccess } from './caseAccess';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

/**
 * A failed API call. `status` is the HTTP status, or 0 when the server could not
 * be reached at all. Callers show `message` to the user.
 *
 * There is deliberately no fallback data in this module: a real case that fails
 * to load must show as failed, never as a built-in sample report.
 */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }

  get isNotFound() {
    return this.status === 404;
  }

  /** The case exists but has no finished report yet. */
  get isNoReport() {
    return this.status === 409;
  }
}

async function request<T>(path: string, init?: RequestInit, fallbackMessage = 'Request failed'): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new ApiError(0, 'Could not reach the verification service. Check that the backend is running and try again.');
  }

  if (!res.ok) {
    // Surface the server's own reason (FastAPI: {"detail": "..."}).
    let detail = `${fallbackMessage} (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      /* response had no JSON body */
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Headers for a case-scoped call. A case with no stored token reads as not found. */
function caseHeaders(offerId: number, extra: Record<string, string> = {}): Record<string, string> {
  const token = caseAccess.get(offerId);
  if (!token) {
    throw new ApiError(
      404,
      `Offer ${offerId} is not available in this browser. Cases can only be opened on the device that uploaded them, for 7 days.`,
    );
  }
  return { 'X-Case-Token': token, ...extra };
}

export const api = {
  async checkHealth(): Promise<{ status: string; service?: string }> {
    try {
      return await request('/health');
    } catch {
      return { status: 'offline' };
    }
  },

  /**
   * Upload an offer. Pass `sample=true` only for the built-in preset texts; the
   * backend then titles the case "Sample: …" so it is never mistaken for a real offer.
   * The returned access token is stored for this browser.
   */
  async uploadOffer(formData: FormData): Promise<OfferUploadResponse> {
    const res = await request<OfferUploadResponse>('/offers/upload', { method: 'POST', body: formData }, 'Upload failed');
    caseAccess.set(res.offer_id, res.access_token, res.expires_at);
    return res;
  },

  async uploadOfferText(title: string, raw_content: string, sample = false): Promise<OfferUploadResponse> {
    const formData = new FormData();
    formData.append('title', title);
    formData.append('source_type', 'text');
    formData.append('raw_content', raw_content);
    if (sample) formData.append('sample', 'true');
    return this.uploadOffer(formData);
  },

  async getOffer(id: number): Promise<Offer> {
    return request(`/offers/${id}`, { headers: caseHeaders(id) }, 'Could not load the offer');
  },

  async getClaims(id: number): Promise<ClaimPreview> {
    return request(`/offers/${id}/claims`, { headers: caseHeaders(id) }, 'Could not read the offer claims');
  },

  /** Latest finished report. Throws ApiError with isNoReport when none exists yet. */
  async getReport(id: number): Promise<RunSnapshot> {
    return request(`/offers/${id}/report`, { headers: caseHeaders(id) }, 'Could not load the report');
  },

  /** Every run for the case, newest version first. */
  async getRuns(id: number): Promise<RunSnapshot[]> {
    return request(`/offers/${id}/runs`, { headers: caseHeaders(id) }, 'Could not load the investigation runs');
  },

  async startRun(offerId: number, confirmedClaims: ConfirmedClaim[] = [], forceRefresh = false): Promise<RunSnapshot> {
    return request(
      '/analysis/run',
      {
        method: 'POST',
        headers: caseHeaders(offerId, { 'Content-Type': 'application/json' }),
        body: JSON.stringify({ offer_id: offerId, force_refresh: forceRefresh, confirmed_claims: confirmedClaims }),
      },
      'Could not start the investigation',
    );
  },

  async getRun(offerId: number, runId: string): Promise<RunSnapshot> {
    return request(`/analysis/runs/${encodeURIComponent(runId)}`, { headers: caseHeaders(offerId) }, 'Could not load the run');
  },

  async deleteOffer(id: number): Promise<void> {
    await request(`/offers/${id}`, { method: 'DELETE', headers: caseHeaders(id) }, 'Could not delete the case');
    caseAccess.forget(id);
  },
};
