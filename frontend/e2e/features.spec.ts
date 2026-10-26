import { expect, test, type Page, type Route } from '@playwright/test';

const documentId = '11111111-1111-4111-8111-111111111111';
const uploadedDocumentId = '11111111-1111-4111-8111-111111111112';
const incidentId = '22222222-2222-4222-8222-222222222222';
const existingIncidentId = '22222222-2222-4222-8222-222222222223';
const evaluationId = '33333333-3333-4333-8333-333333333333';
const createdEvaluationId = '33333333-3333-4333-8333-333333333334';
const jobId = '44444444-4444-4444-8444-444444444444';
const now = '2026-01-01T00:00:00Z';

const analysis = {
  incident_id: incidentId,
  status: 'completed',
  summary: 'A connection pool saturation is supported by the supplied evidence.',
  hypotheses: [{
    rank: 1,
    title: 'Connection pool saturation',
    confidence: 'high',
    reasoning: 'The retrieved runbook describes the observed timeout pattern.',
    supporting_evidence: [{ source: 'pool-runbook.md', document_id: documentId, chunk_id: 'chunk-1', quote: 'Pool exhaustion causes request timeouts.' }],
    contradictory_evidence: [],
    missing_evidence: [],
  }],
  diagnostic_steps: [{ step: 1, action: 'Inspect pool utilization metrics.', reason: 'Confirm saturation.', risk: 'read_only' }],
  citations: [{ document_id: documentId, chunk_id: 'chunk-1', source: 'pool-runbook.md' }],
  limitations: [],
  quality: { result: 'evidence_found', abstained: false },
  run: { run_id: 'run-1', provider: 'groq', model: 'test-model', routing_policy: 'static', latency_ms: 120, input_tokens: 100, output_tokens: 30, estimated_cost_usd: 0, routing_decision: {} },
};

function document(filename: string, id = documentId) {
  return {
    document_id: id, filename, source_type: 'runbook', service: 'payments-api',
    environment: 'test', status: 'indexed', chunk_count: 1, content_sha256: 'a'.repeat(64),
    error: null, created_at: now, updated_at: now,
  };
}

function incident(id = existingIncidentId) {
  return {
    incident_id: id, title: 'Payment timeouts', description: 'Requests time out under load.',
    service: 'payments-api', environment: 'test', severity: 'SEV-2', status: 'completed',
    latest_run_id: 'run-1', latest_result: analysis, created_at: now,
  };
}

function evaluation(name = 'baseline-run', id = evaluationId) {
  return {
    evaluation_run_id: id, experiment_name: name, dataset_id: 'incidentiq_demo',
    dataset_version: 'v1', split: 'validation', status: 'completed', config_hash: 'config-hash', created_at: now,
  };
}

async function installApiMocks(page: Page) {
  const docs = [document('pool-runbook.md')];
  const incidents = [incident()];
  const evaluations = [evaluation()];
  const requests: Array<{ method: string; path: string; body: unknown }> = [];

  await page.route('**/api/backend/**', async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = decodeURIComponent(url.pathname.split('/api/backend/')[1] || '');
    const method = request.method();
    let body: unknown = null;
    if (method === 'POST') {
      try { body = request.postDataJSON(); } catch { body = '[multipart upload]'; }
    }
    requests.push({ method, path: `${path}${url.search}`, body });

    if (method === 'GET' && path === 'health/ready') {
      return route.fulfill({ json: { status: 'ready', dependencies: { postgres: 'ok', redis: 'ok' } } });
    }
    if (method === 'GET' && path === 'api/v1/metrics/summary') {
      return route.fulfill({ json: { window: url.searchParams.get('window') || '24h', requests: { total: 12, success_rate: 1, error_rate: 0 }, latency_ms: { p50: 30, p95: 90, p99: 120 }, llm: { input_tokens: 100, output_tokens: 30, estimated_cost_usd: 0, fallback_count: 0 }, retrieval: { average_candidates: 2, reranker_usage_rate: 0 } } });
    }
    if (method === 'GET' && path === 'api/v1/routing/policies') {
      return route.fulfill({ json: { policies: [{ name: 'static', description: 'Static policy' }], active_policy: 'static', provider_health: { groq: { healthy: true, consecutive_failures: 0 } } } });
    }
    if (method === 'GET' && path === 'api/v1/documents') return route.fulfill({ json: { items: docs, next_cursor: null } });
    if (method === 'POST' && path === 'api/v1/documents') {
      docs.push(document('uploaded-runbook.md', uploadedDocumentId));
      return route.fulfill({ status: 202, json: { job_id: jobId, status: 'queued' } });
    }
    if (method === 'DELETE' && path.startsWith('api/v1/documents/')) {
      const id = path.split('/').at(-1);
      const index = docs.findIndex(item => item.document_id === id);
      if (index >= 0) docs.splice(index, 1);
      return route.fulfill({ status: 204, body: '' });
    }
    if (method === 'GET' && path === 'api/v1/incidents') return route.fulfill({ json: { items: incidents, next_cursor: null } });
    if (method === 'POST' && path === 'api/v1/incidents/analyze') {
      incidents.unshift(incident(incidentId));
      return route.fulfill({ json: analysis });
    }
    if (method === 'GET' && path === `api/v1/incidents/${incidentId}`) return route.fulfill({ json: { ...incident(incidentId), latest_result: analysis } });
    if (method === 'GET' && path === `api/v1/incidents/${incidentId}/runs`) {
      return route.fulfill({ json: { items: [{ run_id: 'run-1', status: 'completed', created_at: now }] } });
    }
    if (method === 'POST' && path === 'api/v1/search') {
      return route.fulfill({ json: { query: 'pool timeouts', results: [{ document_id: documentId, chunk_id: 'chunk-1', source: 'pool-runbook.md', source_type: 'runbook', excerpt: 'Pool exhaustion causes request timeouts.', score: 0.91, rank: 1, service: 'payments-api', environment: 'test' }], retrieval: { mode: 'hybrid', reranker_used: false, candidate_count: 1 }, latency_ms: 12 } });
    }
    if (method === 'GET' && path === 'api/v1/evaluations') return route.fulfill({ json: { items: evaluations, next_cursor: null } });
    if (method === 'POST' && path === 'api/v1/evaluations') {
      evaluations.unshift(evaluation('browser-evaluation', createdEvaluationId));
      return route.fulfill({ status: 202, json: { evaluation_run_id: createdEvaluationId, job_id: jobId, status: 'queued' } });
    }
    if (method === 'GET' && path === 'api/v1/jobs/' + jobId) {
      return route.fulfill({ json: { job_id: jobId, job_type: 'evaluation', status: 'completed', progress: { completed: 1, total: 1 }, error: null, created_at: now, finished_at: now } });
    }
    if (method === 'GET' && path === `api/v1/evaluations/${createdEvaluationId}`) {
      return route.fulfill({ json: { ...evaluation('browser-evaluation', createdEvaluationId), config: { retrieval_mode: 'keyword' }, metrics: { recall_at_5: 1, citation_precision: 1 }, error: null } });
    }
    if (method === 'GET' && path === `api/v1/evaluations/${createdEvaluationId}/cases`) {
      return route.fulfill({ json: { evaluation_run_id: createdEvaluationId, items: [{ case_id: 'case-1', passed: true, retrieval_recall: 1 }] } });
    }
    if (method === 'POST' && path === 'api/v1/routing/simulate') {
      return route.fulfill({ json: { policy: 'static', eligible_models: [{ provider: 'groq', model: 'test-model' }], selected: { provider: 'groq', model: 'test-model', reason: 'eligible' }, excluded: [] } });
    }
    return route.fulfill({ status: 404, json: { error: `Unmocked test API request: ${method} ${path}` } });
  });

  return requests;
}

test('overview shows readiness, recent investigations, and navigation', async ({ page }) => {
  await installApiMocks(page);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'System readiness' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Recent investigations' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Knowledge base' })).toBeVisible();
});

test('knowledge upload tracks its job and delete refreshes the list', async ({ page }) => {
  const requests = await installApiMocks(page);
  page.on('dialog', dialog => dialog.accept());
  await page.goto('/knowledge');
  await expect(page.getByText('pool-runbook.md')).toBeVisible();
  await page.getByLabel('File').setInputFiles({ name: 'new-runbook.md', mimeType: 'text/markdown', buffer: Buffer.from('# Test runbook') });
  await page.getByLabel('Service (optional)').fill('payments-api');
  await page.getByRole('button', { name: 'Upload document' }).click();
  await expect(page.getByText(jobId)).toBeVisible();
  await expect(page.getByText('uploaded-runbook.md')).toBeVisible();
  await page.getByRole('button', { name: 'Delete uploaded-runbook.md' }).click();
  await expect(page.getByText('uploaded-runbook.md')).toHaveCount(0);
  await expect(page.getByText('pool-runbook.md')).toBeVisible();
  expect(requests.some(item => item.method === 'POST' && item.path === 'api/v1/documents')).toBe(true);
  expect(requests.some(item => item.method === 'DELETE' && item.path === `api/v1/documents/${uploadedDocumentId}`)).toBe(true);
});

test('search submits selected retrieval mode and service filters', async ({ page }) => {
  const requests = await installApiMocks(page);
  await page.goto('/search');
  await page.getByLabel('Query').fill('pool timeouts');
  await page.getByLabel('Retrieval mode').selectOption('hybrid');
  await page.getByLabel('Service filter').fill('payments-api');
  await page.getByLabel('Environment filter').fill('test');
  await page.getByRole('button', { name: 'Search evidence' }).click();
  await expect(page.getByText('Pool exhaustion causes request timeouts.')).toBeVisible();
  const search = requests.find(item => item.method === 'POST' && item.path === 'api/v1/search');
  expect(search?.body).toMatchObject({ query: 'pool timeouts', mode: 'hybrid', use_hybrid_search: true, filters: { service: 'payments-api', environment: 'test' } });
});

test('incident creation shows analysis, citations, read-only steps, and persisted detail', async ({ page }) => {
  const requests = await installApiMocks(page);
  await page.goto('/investigations/new');
  await page.getByLabel('Incident title').fill('Payment timeouts');
  await page.getByLabel('What happened?').fill('Requests time out under load.');
  await page.getByLabel('Service').fill('payments-api');
  await page.getByLabel('Environment').fill('test');
  await page.getByLabel('Severity').selectOption('SEV-2');
  await page.getByLabel('Symptoms (one per line)').fill('Connection timeouts');
  await page.getByRole('button', { name: 'Analyze incident' }).click();
  await expect(page).toHaveURL(new RegExp(`/investigations/${incidentId}$`));
  await expect(page.getByText(analysis.summary)).toBeVisible();
  await expect(page.getByRole('heading', { name: 'H1 · Connection pool saturation' })).toBeVisible();
  await expect(page.getByText('Retrieved citations')).toBeVisible();
  await expect(page.getByText('Inspect pool utilization metrics.')).toBeVisible();
  const request = requests.find(item => item.method === 'POST' && item.path === 'api/v1/incidents/analyze');
  expect(request?.body).toMatchObject({ title: 'Payment timeouts', service: 'payments-api', severity: 'SEV-2', symptoms: ['Connection timeouts'] });
  expect(requests.some(item => item.method === 'GET' && item.path === `api/v1/incidents/${incidentId}`)).toBe(true);
  expect(requests.some(item => item.method === 'GET' && item.path === `api/v1/incidents/${incidentId}/runs`)).toBe(true);
});

test('evaluation creation reports job completion and opens run details', async ({ page }) => {
  const requests = await installApiMocks(page);
  await page.goto('/evaluations');
  await expect(page.getByText('baseline-run')).toBeVisible();
  await page.getByLabel('Experiment name').fill('browser-evaluation');
  await page.getByLabel('Dataset split').selectOption('validation');
  await page.getByLabel('Retrieval mode').selectOption('keyword');
  await page.getByRole('button', { name: 'Start evaluation' }).click();
  await expect(page.getByText('completed', { exact: true })).toBeVisible();
  await page.getByRole('link', { name: /browser-evaluation/ }).click();
  await expect(page).toHaveURL(new RegExp(`/evaluations/${createdEvaluationId}$`));
  await expect(page.getByRole('heading', { name: 'browser-evaluation' })).toBeVisible();
  await expect(page.getByText('Case results')).toBeVisible();
  await expect(page.getByText('case-1', { exact: true })).toBeVisible();
  expect(requests.some(item => item.method === 'POST' && item.path === 'api/v1/evaluations')).toBe(true);
  expect(requests.some(item => item.method === 'GET' && item.path === `api/v1/jobs/${jobId}`)).toBe(true);
  expect(requests.some(item => item.method === 'GET' && item.path === `api/v1/evaluations/${createdEvaluationId}`)).toBe(true);
  expect(requests.some(item => item.method === 'GET' && item.path === `api/v1/evaluations/${createdEvaluationId}/cases`)).toBe(true);
});

test('operations changes metric windows and simulates routing without generation', async ({ page }) => {
  const requests = await installApiMocks(page);
  const initialResponses = [
    page.waitForResponse(response => response.url().includes('/api/backend/health/ready')),
    page.waitForResponse(response => response.url().includes('/api/backend/api/v1/routing/policies')),
    page.waitForResponse(response => response.url().includes('/api/backend/api/v1/metrics/summary?window=24h')),
  ];
  await page.goto('/operations');
  await Promise.all(initialResponses);
  await expect(page.getByText('LLM provider health')).toBeVisible();
  await page.getByLabel('Metrics time window').selectOption('1h');
  await expect(page.getByLabel('Metrics time window')).toHaveValue('1h');
  await expect(page.getByRole('heading', { name: 'Request metrics' })).toBeVisible();
  await page.getByLabel('Input token estimate').fill('1200');
  await page.getByLabel('Output token budget').fill('1200');
  await page.getByLabel('Latency budget (ms)').fill('20000');
  await page.getByLabel('Cost budget (USD)').fill('0.01');
  await page.getByLabel('Allowed providers (comma-separated)').fill('groq,gemini');
  await page.getByLabel('Policy').selectOption('static');
  const simulationResponse = page.waitForResponse(response => response.url().includes('/api/backend/api/v1/routing/simulate') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Simulate routing' }).click();
  expect((await simulationResponse).status()).toBe(200);
  await expect(page.getByText('test-model').first()).toBeVisible();
  expect(requests.some(item => item.method === 'GET' && item.path === 'api/v1/metrics/summary?window=1h')).toBe(true);
  expect(requests.some(item => item.method === 'POST' && item.path === 'api/v1/routing/simulate')).toBe(true);
  expect(requests.find(item => item.method === 'POST' && item.path === 'api/v1/routing/simulate')?.body).toMatchObject({ task_type: 'incident_analysis', policy: 'static', permitted_providers: ['groq', 'gemini'] });
  expect(requests.some(item => item.method === 'POST' && item.path === 'api/v1/incidents/analyze')).toBe(false);
});
