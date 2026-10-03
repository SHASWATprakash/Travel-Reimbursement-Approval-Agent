import { z } from 'zod'

const amount = z.coerce.number().finite().nonnegative()
export const decisionSchema = z.enum(['APPROVE', 'PARTIAL_APPROVE', 'REJECT', 'MANUAL_REVIEW'])
const claimSchema = z.object({
  claim_id: z.string(), employee: z.string(), purpose: z.string(),
  trip_start: z.string(), trip_end: z.string(), submitted: z.string(),
  total_claimed: amount, currency: z.literal('USD'), business_documented: z.boolean(),
  items: z.array(z.object({ item_id: z.string(), category: z.string(), description: z.string(), amount,
    receipt_attached: z.boolean(), receipt_itemized: z.boolean().default(true), units: z.number().nullable().optional() })),
})
const resultSchema = z.object({
  claim_id: z.string(), decision: decisionSchema,
  approved_amount: amount, deducted_amount: amount,
  missing_docs: z.array(z.string()), policy_refs: z.array(z.string()),
  confidence: z.number().min(0).max(1), explanation: z.string(), tools_used: z.array(z.string()),
}).strict()
const findingSchema = z.object({code: z.string(), message: z.string(), policy_refs: z.array(z.string()), item_ids: z.array(z.string()), review: z.boolean()})
const eventSchema = z.object({name: z.string(), arguments: z.record(z.string(), z.unknown()), output: z.unknown(), duration_ms: z.number(), call_id: z.string().optional(), transport: z.string().optional()})
export const envelopeSchema = z.object({
  claim: claimSchema, result: resultSchema,
  audit: z.object({mode: z.string(), model: z.string(), provider: z.string(), duration_ms: z.number(),
    policy_version: z.string(), reason_codes: z.array(z.string()), findings: z.array(findingSchema),
    pending_amount: amount, lines: z.array(z.object({item_id: z.string(), category: z.string(), claimed: amount,
      provisional_allowed: amount, provisional_deducted: amount, policy_refs: z.array(z.string())})),
    events: z.array(eventSchema), model_turns: z.array(z.record(z.string(), z.unknown())),
    model_proposal: z.unknown(), validation_errors: z.array(z.string()), validator: z.string(),
    mcp: z.object({server: z.string(), transport: z.string(), discovered_tools: z.array(z.string()), methods: z.array(z.string()), requests: z.array(z.unknown())}),
  }),
})
const snapshotSchema = z.object({evaluations: z.array(envelopeSchema), policy_version: z.string()})
const policiesSchema = z.object({rules: z.record(z.string(), z.string()), policy_version: z.string(), tools: z.array(z.string())})
const healthSchema = z.object({status: z.string(), live_available: z.boolean(), ollama_available: z.boolean(), model: z.string(), queue_depth: z.number(), deadline_seconds: z.number().default(120)})
const jobSchema = z.object({job_id: z.string(), mode: z.enum(['rules', 'replay', 'live']), status: z.enum(['queued', 'running', 'completed', 'failed']), claim_ids: z.array(z.string()),
  completed_count: z.number(), evaluations: z.array(envelopeSchema), error: z.string().nullable(), created_at: z.string(), finished_at: z.string().nullable()})

export type Evaluation = z.infer<typeof envelopeSchema>
export type Result = z.infer<typeof resultSchema>
export type Decision = z.infer<typeof decisionSchema>
export type Mode = 'rules' | 'replay' | 'live'
export type Job = z.infer<typeof jobSchema>
export type Policies = z.infer<typeof policiesSchema>

async function request<T>(path: string, schema: z.ZodType<T>, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1/${path}`, {...init, signal: AbortSignal.timeout(8000)})
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status}).`)
  }
  try { return schema.parse(await response.json()) }
  catch { throw new Error('The server returned an unexpected response. Existing results have been preserved.') }
}

export const api = {
  latest: () => request('evaluations/latest', snapshotSchema),
  policies: () => request('policies', policiesSchema),
  health: () => request('health', healthSchema),
  job: (id: string) => request(`evaluations/${encodeURIComponent(id)}?include_results=false`, jobSchema),
  evaluate: (mode: Mode, claimIds?: string[]) => request('evaluations', jobSchema, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({mode, ...(claimIds ? {claim_ids: claimIds} : {})})}),
}

export function downloadResults(results: Result[], filename = 'reimbursement-results.json') {
  const url = URL.createObjectURL(new Blob([JSON.stringify(results, null, 2)], {type: 'application/json'}))
  const link = document.createElement('a'); link.href = url; link.download = filename; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
