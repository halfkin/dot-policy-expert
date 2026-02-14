# Cost Analysis

Estimated per-query costs for Dot in LLM mode (OpenRouter + GPT-4o-mini).

## Per-Query Cost Breakdown

| Component | Cost per Query | When It Runs | Notes |
|---|---|---|---|
| Retrieval (keyword + embedding) | ~$0.000 | Every query | Local computation only — cosine similarity on pre-computed vectors |
| Ravelin Tier 0 (length + entropy + regex) | ~$0.000 | Every query | No API call — pure string checks |
| Ravelin Tier 1+ (Lakera + OpenRouter classifier) | ~$0.003 | Suspicious inputs only (~5-10% of traffic) | Two API calls for consensus |
| Query reformulation (GPT-4o-mini) | ~$0.001 | Vague queries in LLM mode (~30% of traffic) | Skipped for queries >15 words |
| Answer generation (GPT-4o-mini) | ~$0.002 | Every LLM-mode query | ~500 token prompt + ~200 token response |
| Conflict detection | ~$0.000 | Every query | Local numeric extraction — no API call |
| Language detection | ~$0.000 | Every query | Local `langdetect` library |

## Cost Per Query Type

| Query Type | Estimated Cost | Breakdown |
|---|---|---|
| Normal question (specific) | ~$0.002 | Retrieval + generation |
| Normal question (vague) | ~$0.003 | Retrieval + reformulation + generation |
| Suspicious input | ~$0.006 | Retrieval + Ravelin Tier 1 + generation |
| Blocked injection | ~$0.003 | Ravelin Tier 1 only (no generation) |
| Out-of-scope question | ~$0.002 | Retrieval + generation (LLM decides "Not in sources") |
| Offline mode (any query) | ~$0.000 | All local computation |

## Monthly Cost Estimates

| Daily Volume | Monthly API Cost | Notes |
|---|---|---|
| 50 queries/day | ~$4 | Small team, single client |
| 200 queries/day | ~$15 | Mid-size team or multiple departments |
| 1,000 queries/day | ~$60 | Large org or multi-tenant deployment |
| 5,000 queries/day | ~$300 | High-volume, consider caching |

## Infrastructure Costs

| Component | Monthly Cost | Notes |
|---|---|---|
| VPS (basic) | $5-15 | Hostinger, DigitalOcean, or Hetzner; 2GB RAM sufficient |
| VPS (with GPU for local embeddings) | $20-50 | Only needed if running larger embedding models |
| Domain + SSL | $0-1 | Caddy provides free Let's Encrypt SSL |
| Docker hosting | $0 | Included in VPS |

## Cost Optimization Strategies

**Already implemented:**
- Tiered security: normal queries skip expensive LLM classifier (~90% of traffic stays in Tier 0)
- Query reformulation gating: only runs on short/vague queries
- Offline fallback: zero API cost when LLM providers are unavailable

**Would implement at scale:**
- Response caching: 40%+ of support queries are duplicates — cache top 100 answers, cut generation costs by half
- Smaller model for reformulation: DeepSeek or a local model instead of GPT-4o-mini
- Batch embedding updates: re-index KB on schedule instead of at every startup
- Per-tenant usage caps tied to pricing tier

## Unit Economics (Service Model)

| | Per Client/Month |
|---|---|
| Client pays | $200-500 |
| API costs (200 queries/day) | ~$15 |
| VPS share (multi-tenant) | ~$5 |
| **Gross margin** | **~$180-480** |

At 5 clients: ~$1,000-2,500/month revenue, ~$100 costs. At 20 clients: ~$4,000-10,000/month revenue, ~$300 costs.
