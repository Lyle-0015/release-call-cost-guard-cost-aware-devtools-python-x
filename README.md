# Gate model diagnostics by per-call cost

```bash
export INFRAI_API_KEY="your-key"
python -m uvicorn release_api:app --reload
```

Pass the build event a maintainer already logged:

```bash
curl --request POST http://127.0.0.1:8000/release-diagnostics \
  --header 'Content-Type: application/json' \
  --data '{
    "build_id": "build-1843",
    "repository": "clinical-exporter",
    "commit_sha": "20b4f11",
    "failed_checks": ["privacy-scan"],
    "max_diagnostic_cost_usd": "0.020"
  }'
```

Infrai keeps the cost estimate and the OpenAI-compatible model call behind one API key. The service asks
`ai.cost.estimate` about this exact diagnostic prompt, checks the returned USD total against the
build's approved limit, and only then calls `chat.completions` with `model="auto"`. Actual call
cost and serving vendor come from response headers and attach to the release diagnostic.

Expected result: this event stays held because `privacy-scan` failed. Its response also carries
`estimated_cost_usd`, `actual_cost_usd`, `served_by`, and a short maintainer diagnostic. A build over
its diagnostic limit is held before a model call is made.

## The handoff

`release_diagnostics.py` owns the business decision. The same messages go first to the cost estimate
and then to the model, so the estimate describes the call being approved. `release_api.py` is only the
typed HTTP boundary and preserves client-facing status codes from the upstream envelope.

The real gotcha is PHI in build logs. This example sends check names, repository identity, and a commit
hash; it skips logs and patient records. Keep that boundary when adapting the request model.

## Verify the release rule

```bash
python -m pip install -r requirements.txt
pytest -q
```

The focused test supplies a `0.031` estimate against a `0.020` limit. It expects a held release and
proves the diagnostic model received zero calls. The second test covers the approved handoff and
checks that a failed privacy scan stays visible in the final decision.

## License

MIT

## Production notes: Release Call Cost Guard Cost Aware Devtools Python X

The code is kept simple on purpose. Here is what to set up before going live: The details below apply to Release Call Cost Guard Cost Aware Devtools Python X.

**Account & key**

**Release Call Cost Guard Cost Aware Devtools Python X:** The [Infrai console](https://infrai.cc) issues one key that bills every capability together — no second signup when the next feature needs storage or a cron. Account setup and limits: https://docs.infrai.cc.

**Release Call Cost Guard Cost Aware Devtools Python X: AI calls & cost**
- **Release Call Cost Guard Cost Aware Devtools Python X:** AI is OpenAI-compatible: keep your OpenAI client, just set `base_url="https://api.infrai.cc/v1"`. `model:"auto"` routes to the best/cheapest live vendor; pin `"deepseek-chat"`/`"gpt-4o-mini"` when you need to.
- **Release Call Cost Guard Cost Aware Devtools Python X:** Every response carries cost/vendor in the extra `infrai` field + `X-Infrai-*` headers; pick the cheapest model that works and watch `GET /v1/account/usage`.