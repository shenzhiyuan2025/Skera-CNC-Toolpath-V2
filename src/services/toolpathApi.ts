export interface ToolpathIssue {
  code: string;
  title: string;
  description: string;
  severity: 'blocker' | 'high' | 'medium' | 'low';
  category: string;
  dimension: string;
  line_range?: number[] | null;
  segment_range?: string[] | null;
  evidence?: Record<string, unknown>;
  suggestion?: string;
}

export interface ToolpathEvaluationResult {
  final_conclusion: 'green' | 'yellow' | 'red';
  allow_continue: boolean;
  summary: string;
  total_score: number;
  dimension_scores: Record<string, number>;
  issue_counts: Record<'blocker' | 'high' | 'medium' | 'low', number>;
  issues: ToolpathIssue[];
  artifacts: Record<string, string>;
  metrics: Record<string, unknown>;
  task_meta: Record<string, unknown>;
}

export type ToolpathJobMode = 'sample' | 'full';

export interface ToolpathJobStartResponse {
  job_id: string;
  file_id: string;
  status: string;
}

export interface ToolpathJobStatusResponse {
  job_id: string;
  file_id: string;
  status: 'queued' | 'running' | 'done' | 'error';
  mode: ToolpathJobMode;
  progress: Record<string, unknown>;
  error?: string;
  result?: ToolpathEvaluationResult | null;
}

function buildEndpoints(path: string, payloadSizeBytes: number) {
  const hostname = typeof window !== 'undefined' ? window.location.hostname : '';
  const isLocalRuntime = hostname === 'localhost' || hostname === '127.0.0.1';
  if (!isLocalRuntime) {
    return [`/api${path}`];
  }
  if (payloadSizeBytes > 2 * 1024 * 1024) {
    return [
      `http://127.0.0.1:8000${path}`,
      `http://localhost:8000${path}`,
      `/api${path}`
    ];
  }
  return [
    `/api${path}`,
    `http://localhost:8000${path}`,
    `http://127.0.0.1:8000${path}`
  ];
}

async function parseResponseError(resp: Response) {
  const statusInfo = `请求失败(${resp.status})`;
  const contentType = resp.headers.get('content-type') || '';
  let detail = '';
  if (contentType.includes('application/json')) {
    try {
      const err = await resp.json();
      if (typeof err?.detail === 'string') {
        detail = err.detail;
      } else if (Array.isArray(err?.detail)) {
        detail = err.detail.map((item: unknown) => JSON.stringify(item)).join('; ');
      } else if (err?.detail) {
        detail = JSON.stringify(err.detail);
      } else {
        detail = JSON.stringify(err);
      }
    } catch {
      detail = '';
    }
  } else {
    try {
      detail = (await resp.text()).trim();
    } catch {
      detail = '';
    }
  }
  return detail ? `${statusInfo}: ${detail}` : statusInfo;
}

export async function startToolpathJob(payload: {
  file?: File;
  fileId?: string;
  gcodeText?: string;
  softwareSource?: string;
  machineModel?: string;
  mode: ToolpathJobMode;
  sampleLines?: number;
}): Promise<ToolpathJobStartResponse> {
  const createFormData = () => {
    const formData = new FormData();
    if (payload.file) {
      formData.append('file', payload.file);
    }
    if (payload.fileId) {
      formData.append('file_id', payload.fileId);
    }
    if (payload.gcodeText) {
      formData.append('gcode_text', payload.gcodeText);
    }
    if (payload.softwareSource) {
      formData.append('software_source', payload.softwareSource);
    }
    if (payload.machineModel) {
      formData.append('machine_model', payload.machineModel);
    }
    formData.append('mode', payload.mode);
    if (payload.mode === 'sample') {
      formData.append('sample_lines', String(payload.sampleLines ?? 50000));
    }
    return formData;
  };

  const payloadSizeBytes =
    payload.file?.size ?? new Blob([payload.gcodeText ?? '']).size;
  const endpoints = buildEndpoints('/toolpath/evaluate_job', payloadSizeBytes);
  let response: Response | null = null;
  let lastNetworkError: unknown = null;
  const fallbackStatuses = new Set([400, 404, 405, 500, 501, 502, 503, 504]);
  const requestTimeoutMs =
    payloadSizeBytes > 20 * 1024 * 1024
      ? 300000
      : payloadSizeBytes > 2 * 1024 * 1024
        ? 120000
        : 30000;
  const proxyEndpointTimeoutMs =
    payloadSizeBytes > 2 * 1024 * 1024 ? requestTimeoutMs : Math.min(requestTimeoutMs, 5000);

  for (let i = 0; i < endpoints.length; i += 1) {
    const endpoint = endpoints[i];
    const hasFallback = i < endpoints.length - 1;
    const endpointTimeoutMs = endpoint.startsWith('/api') ? proxyEndpointTimeoutMs : requestTimeoutMs;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), endpointTimeoutMs);
    try {
      response = await fetch(endpoint, {
        method: 'POST',
        body: createFormData(),
        signal: controller.signal
      });
      if (response.ok) {
        return response.json();
      }
      if (hasFallback && fallbackStatuses.has(response.status)) {
        continue;
      }
      throw new Error(await parseResponseError(response));
    } catch (error) {
      if (error instanceof Error && error.message.startsWith('请求失败(')) {
        throw error;
      }
      if (error instanceof DOMException && error.name === 'AbortError') {
        lastNetworkError = new Error(`请求超时(${endpointTimeoutMs}ms, ${payloadSizeBytes}B)`);
        continue;
      }
      lastNetworkError = error;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  if (lastNetworkError instanceof Error) {
    throw new Error(`服务不可用: ${lastNetworkError.message}`);
  }
  throw new Error('服务不可用: 无法连接评测服务');
}

export async function getToolpathJob(jobId: string): Promise<ToolpathJobStatusResponse> {
  const endpoints = buildEndpoints(`/toolpath/jobs/${encodeURIComponent(jobId)}`, 0);
  let response: Response | null = null;
  let lastNetworkError: unknown = null;
  const fallbackStatuses = new Set([404, 405, 500, 501, 502, 503, 504]);
  const requestTimeoutMs = 15000;
  const proxyEndpointTimeoutMs = 5000;

  for (let i = 0; i < endpoints.length; i += 1) {
    const endpoint = endpoints[i];
    const hasFallback = i < endpoints.length - 1;
    const endpointTimeoutMs = endpoint.startsWith('/api') ? proxyEndpointTimeoutMs : requestTimeoutMs;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), endpointTimeoutMs);
    try {
      response = await fetch(endpoint, { method: 'GET', signal: controller.signal });
      if (response.ok) {
        return response.json();
      }
      if (hasFallback && fallbackStatuses.has(response.status)) {
        continue;
      }
      throw new Error(await parseResponseError(response));
    } catch (error) {
      if (error instanceof Error && error.message.startsWith('请求失败(')) {
        throw error;
      }
      if (error instanceof DOMException && error.name === 'AbortError') {
        lastNetworkError = new Error(`请求超时(${endpointTimeoutMs}ms)`);
        continue;
      }
      lastNetworkError = error;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  if (lastNetworkError instanceof Error) {
    throw new Error(`服务不可用: ${lastNetworkError.message}`);
  }
  throw new Error('服务不可用: 无法连接评测服务');
}

export async function evaluateToolpath(payload: {
  file?: File;
  gcodeText?: string;
  softwareSource?: string;
  machineModel?: string;
}): Promise<ToolpathEvaluationResult> {
  const createFormData = () => {
    const formData = new FormData();
    if (payload.file) {
      formData.append('file', payload.file);
    }
    if (payload.gcodeText) {
      formData.append('gcode_text', payload.gcodeText);
    }
    if (payload.softwareSource) {
      formData.append('software_source', payload.softwareSource);
    }
    if (payload.machineModel) {
      formData.append('machine_model', payload.machineModel);
    }
    return formData;
  };

  const payloadSizeBytes = payload.file?.size ?? new Blob([payload.gcodeText ?? '']).size;
  const endpoints = buildEndpoints('/toolpath/evaluate', payloadSizeBytes);
  let response: Response | null = null;
  let lastNetworkError: unknown = null;
  const fallbackStatuses = new Set([400, 404, 405, 500, 501, 502, 503, 504]);
  const requestTimeoutMs = payloadSizeBytes > 20 * 1024 * 1024 ? 300000 : payloadSizeBytes > 2 * 1024 * 1024 ? 120000 : 30000;
  const proxyEndpointTimeoutMs = payloadSizeBytes > 2 * 1024 * 1024 ? requestTimeoutMs : Math.min(requestTimeoutMs, 5000);

  for (let i = 0; i < endpoints.length; i += 1) {
    const endpoint = endpoints[i];
    const hasFallback = i < endpoints.length - 1;
    const endpointTimeoutMs = endpoint.startsWith('/api') ? proxyEndpointTimeoutMs : requestTimeoutMs;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), endpointTimeoutMs);
    try {
      response = await fetch(endpoint, {
        method: 'POST',
        body: createFormData(),
        signal: controller.signal
      });
      if (response.ok) {
        return response.json();
      }
      if (hasFallback && fallbackStatuses.has(response.status)) {
        continue;
      }
      throw new Error(await parseResponseError(response));
    } catch (error) {
      if (error instanceof Error && error.message.startsWith('请求失败(')) {
        throw error;
      }
      if (error instanceof DOMException && error.name === 'AbortError') {
        lastNetworkError = new Error(`请求超时(${endpointTimeoutMs}ms, ${payloadSizeBytes}B)`);
        continue;
      }
      lastNetworkError = error;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  if (!response) {
    if (lastNetworkError instanceof Error) {
      throw new Error(`服务不可用: ${lastNetworkError.message}`);
    }
    throw new Error('服务不可用: 无法连接评测服务');
  }

  if (!response.ok) {
    throw new Error(await parseResponseError(response));
  }

  return response.json();
}
