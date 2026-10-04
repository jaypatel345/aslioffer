import { Offer, OfferUploadResponse, VerificationReport } from '../types';

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

  return (await res.json()) as T;
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
   */
  async uploadOffer(formData: FormData): Promise<OfferUploadResponse> {
    return request('/offers/upload', { method: 'POST', body: formData }, 'Upload failed');
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
    return request(`/offers/${id}`, undefined, 'Could not load the offer');
  },

  async getOfferReport(id: number): Promise<VerificationReport> {
    return request(`/offers/${id}/report`, undefined, 'Could not load the report');
  },

  async runAnalysis(offer_id: number): Promise<VerificationReport> {
    return request(
      '/analysis/run',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ offer_id }),
      },
      'Investigation failed',
    );
  },
};
