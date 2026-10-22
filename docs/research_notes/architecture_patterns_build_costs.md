# Architecture Patterns, Open-Source Building Blocks, and Unit Economics for (1) a Doctor's WhatsApp Patient-Reply Agent and (2) an LLM Mental-Health Counsellor Bot — as of 20 October 2026

Method note: WebSearch/WebFetch quota was exhausted early in this session, so most sources below were pulled directly with `curl` (official pricing pages, Meta/Anthropic/OpenAI/Google docs, GitHub READMEs, Hugging Face model cards) on 2026-10-20. Every price is dated. Anything computed by me is explicitly labelled **ESTIMATE** with its assumptions. INR figures are given where the vendor publishes INR; USD→INR conversions are not sourced and are flagged.

---

## Key Question 1 — Reference architectures: how production WhatsApp AI agents are built in 2025–2026

### Takeaway
The standard 2026 stack is: Meta WhatsApp Cloud API (or a BSP such as Twilio) → signed webhook into a thin FastAPI/Flask/Node receiver that returns 200 immediately → Redis/BullMQ/Celery queue → orchestrator (LangGraph / OpenAI Agents SDK / Pydantic AI / Claude Agent SDK, or n8n for low-code) → LLM with tools (RAG over clinic FAQs, appointment APIs, STT for voice notes, vision for prescriptions) → Messages API reply inside the 24-hour customer-service window, with a shared inbox (Chatwoot, Botpress) or LangGraph-style "interrupt" for doctor takeover/draft-approval. Meta now also sells its own hosted "Meta Business Agent" at $2/1M tokens, which is the benchmark a custom build must beat.

### Cited Findings

**Meta Cloud API mechanics (official)**
- The platform "relies heavily on webhooks": all inbound user messages and all outbound delivery-status updates arrive as JSON webhook payloads to your server — [Meta Cloud API overview](https://developers.facebook.com/docs/whatsapp/cloud-api/overview)
- If a webhook request receives a non-200 status (or can't be delivered), "Meta retries delivery with decreasing frequency until the request succeeds, for up to 7 days", and retries go to every subscribed app, which "can result in duplicate webhook notifications" — [Meta webhooks docs](https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/) (implication: your receiver must be idempotent on message id)
- Community guides state Meta expects a 200 within ~5 seconds and that slow handlers cause redelivery/duplicate replies; recommended pattern is "enqueue the job, return 200, then call the LLM and send the reply", with FastAPI `BackgroundTasks` as the simple option and Redis (24-h TTL) for conversation state plus Postgres for long-term storage — WebSearch summary of [groovyweb 2026 guide](https://www.groovyweb.co/blog/whatsapp-business-bot-development-2026), [dev.to production write-up](https://dev.to/richard_sakaguchi_5809b6b/whatsapp-ai-bot-in-production-3-months-50k-messages-zero-downtime-3bn3), [whapi.cloud 2026 integration guide](https://whapi.cloud/blog/whatsapp-api-integration-2026) (community sources, not Meta docs; the 5-second figure was not found in the official page I fetched)
- A 24-hour "customer service window" starts when a user messages (or calls) you and resets on each new user message; "Businesses can only send non-template messages to users when this window is open. If it is not open, businesses can only send template messages" — [Meta pricing docs, updated Sep 30 2026](https://developers.facebook.com/docs/whatsapp/pricing/)
- Service (free-form) messages can be text, image, audio, document, contacts, interactive CTA/URL, and Interactive Flow messages; "WhatsApp Flows [let you] book appointments, browse products, collect…" structured data — [Meta: Service messages](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-messages); [WhatsApp Flows](https://developers.facebook.com/docs/whatsapp/flows)
- Voice messages require ".ogg files encoded with the OPUS codec"; since March 17 2026 voice messages receive a "played" status webhook; if the *user* has transcripts set to Automatic "the message includes a text transcription" (client-side, not guaranteed) — [Meta: Audio messages](https://developers.facebook.com/docs/whatsapp/cloud-api/messages/audio-messages)
- You may only message users who have opted in; businesses are "solely responsible for determining the method of opt-in" and for notices/consents; Meta's policy also says "Don't use WhatsApp for telemedicine or to send or request any health related information, if applicable regulations prohibit distribution of such information to systems that do not meet heightened requirements" — [WhatsApp Business Messaging Policy](https://www.whatsapp.com/legal/business-policy)
- Meta's dev test environment provides 1,000 free service conversations/month (community claim) — [groovyweb](https://www.groovyweb.co/blog/whatsapp-business-bot-development-2026); official: "For each business phone number, Meta provides 1,000 free service messages per month" — [Meta pricing](https://developers.facebook.com/docs/whatsapp/pricing/)

**Meta's own hosted agent (new competitor/benchmark)**
- "Meta Business Agent" became a 5th message category on July 1 2026, billed at "One global rate of $2.00 USD per 1 million (M) tokens. One message typically consumes 20,000–25,000 tokens, which translates to approximately 4–5 cents (USD) per message"; Meta's comparison table estimates 3rd-party AI at "~9 ¢ per message" vs its own "~4-5 ¢" — [Meta pricing, Sep 30 2026](https://developers.facebook.com/docs/whatsapp/pricing/)

**BSP path (Twilio)**
- "Twilio's per-message fee for WhatsApp is $0.005, inbound or outbound", plus Meta's per-template fees passed through; failed-message fee $0.001; Twilio's India calculator shows "$0.0034/message Meta fee outside the customer service window, no charge for messages during the customer service window" — [Twilio WhatsApp pricing](https://www.twilio.com/en-us/messaging/channels/whatsapp/pricing) (note: Twilio's India Meta rate differs from Meta's own Oct-2026 card below; Twilio page may be stale)
- Twilio's March 11 2026 tutorial "Build a WhatsApp AI Agent with Node.js, Twilio Messaging, and OpenAI's GPT-5" uses the Twilio WhatsApp Sandbox + ngrok, with routing/decision logic and business functions behind a webhook — [Twilio blog](https://www.twilio.com/en-us/blog/developers/tutorials/integrations/whatsapp-ai-agent-twilio-openai)

**Concrete open-source examples / tutorials (URLs)**
- `daveebbelaar/python-whatsapp-bot`: Meta Cloud API + Flask + OpenAI, with a step on "Understanding Webhook Security" (signature verification) and ngrok setup — [GitHub](https://github.com/daveebbelaar/python-whatsapp-bot)
- `ArielSmoliar/wa-chatbot`: "A WhatsApp bot built with Python, Flask, Twilio, and Claude (claude-sonnet-4-6)… maintains per-conversation history in memory" — [GitHub](https://github.com/ArielSmoliar/wa-chatbot)
- Claude + Twilio + FastAPI + SQLite walkthrough (built with Claude Code and a Twilio MCP server) — [ggomez.dev](https://ggomez.dev/blog/ai-whatsapp-agent-with-claude-and-twilio-no-code-build-walkthrough)
- `Mahmoud-Ossama/WhatsApp-Clinic-AI-Agent`: "Flask-based WhatsApp assistant for a clinic, integrating Dialogflow CX for Arabic, custom Hebrew NLP flows, and an admin dashboard for managing patients and follow-ups" — [GitHub](https://github.com/Mahmoud-Ossama/WhatsApp-Clinic-AI-Agent)
- n8n template #3694 "Multi-Agent AI Clinic Management with WhatsApp, Telegram, and Google Calendar" — [n8n](https://n8n.io/workflows/3694-multi-agent-ai-clinic-management-with-whatsapp-telegram-and-google-calendar/)
- RAG variant: "webhook receives the request, the AI agent understands the user's intent, retrieves relevant information using RAG, and generates an accurate response" with FastAPI — [dev.to (vmodal)](https://dev.to/vmodal_ai/building-a-whatsapp-ai-agent-with-rag-for-automated-customer-support-22bj)
- Production write-up: bot/human "HYBRID_MODE", routing "complex cases… to humans with full context", a queue in front of the WhatsApp send step — [dev.to (Sakaguchi)](https://dev.to/richard_sakaguchi_5809b6b/whatsapp-ai-bot-in-production-3-months-50k-messages-zero-downtime-3bn3)
- Whapi 2026 guide shows "REDIS / BULLMQ (Reliable Queue)" between webhook and Node app — [whapi.cloud](https://whapi.cloud/blog/whatsapp-api-integration-2026)
- `lharries/whatsapp-mcp` (MIT): Go bridge on `whatsmeow` (WhatsApp Web multi-device API) + Python MCP server; messages stored in local SQLite; QR-code login; "After approximately 20 days, you… might need to re-authenticate"; README warns it is "subject to the lethal trifecta" (prompt-injection → data exfiltration) — [GitHub README](https://github.com/lharries/whatsapp-mcp); a third-party article reports 6,346 stars as of Oct 1 2026 — [pasqualepillitteri.it](https://pasqualepillitteri.it/en/news/19773/whatsapp-mcp-server-claude-en) (uses a *personal* account via unofficial API — not suitable for a clinic)
- Sarvam's docs list integration guides for "Twilio, Exotel, Vobiz, Vapi, n8n, Vercel AI SDK, LangChain, LiveKit, Pipecat" and a "WhatsApp Bot" cookbook — [Sarvam docs nav](https://docs.sarvam.ai/api-reference-docs/pricing)

**Orchestration frameworks and human-in-the-loop primitives**
- Claude Agent SDK (Python/TypeScript): "the same tools, agent loop, and context management that power Claude Code"; built-in hooks, subagents, MCP, permissions ("Control which tools run automatically, which need approval"), sessions; alternative "Managed Agents" hosted by Anthropic — [Agent SDK overview](https://platform.claude.com/docs/en/agent-sdk/overview)
- OpenAI Agents SDK: Agents, Handoffs, Guardrails ("Run input validation and safety checks in parallel with agent execution, and fail fast"), Sessions, MCP tools, "Human in the loop: Built-in mechanisms for involving humans during agent runs", realtime voice agents on `gpt-realtime-2.1` — [openai.github.io](https://openai.github.io/openai-agents-python/)
- Pydantic AI: typed agent loop, "every model a string swap away" (OpenAI, Anthropic, Google, Bedrock, Azure, Groq, Mistral, Ollama…), OpenTelemetry instrumentation, durable execution on Temporal/DBOS/Prefect/Restate/AWS Lambda — [ai.pydantic.dev](https://ai.pydantic.dev/)
- LangGraph interrupts: "Interrupts allow you to pause graph execution at specific points and wait for external input"; state is checkpointed and you resume with `Command` keyed by `thread_id` — the canonical "draft-for-approval / doctor takes over" primitive — [LangChain docs](https://docs.langchain.com/oss/python/langgraph/interrupts)
- NeMo Guardrails: input/dialog/retrieval/execution/output rails, Colang flows, LlamaGuard integration, heuristic + LLM self-check jailbreak detection — [NVIDIA docs](https://docs.nvidia.com/nemo/guardrails/latest/index.html); [GitHub](https://github.com/NVIDIA-NeMo/Guardrails)

**Shared-inbox / low-code platforms for handoff**
- Chatwoot: "open-source, and self-hosted customer support platform", with "Captain" AI agent; cloud add-on credits "$20/ 1,000 credits" — [GitHub](https://github.com/chatwoot/chatwoot); [pricing](https://www.chatwoot.com/pricing)
- Botpress: Plus $150/mo (includes $25 AI usage; conversation packs "100 for $65 ($0.65/convo)"), Team $750/mo ($150 AI usage; $0.50/convo) — [Botpress pricing](https://botpress.com/pricing)

**Indian-language components**
- Sarvam model line-up (docs dated Oct 19 2026): Saaras v4 STT (23 languages = 22 Indian + English; modes transcribe/translate/verbatim/translit/codemix), Bulbul v3 TTS (11 languages), Sarvam-105B chat LLM (11 languages; `sarvam-105b-conversations` for voice/dialogue), Mayura (11-lang translation), Sarvam-Translate (23 languages), Sarvam Vision (document OCR, 23 languages); **Saarika, Sarvam-M and Sarvam 30B are marked Deprecated**; open-weight GLM-5.3, Gemma 4 31B, DeepSeek V4.1 Flash served in beta — [Sarvam models](https://docs.sarvam.ai/api-reference-docs/getting-started/models)
- `sarvamai/sarvam-m` (open weights on HF): hybrid-reasoning model "built on Mistral-Small", "+20% average improvement on Indian language benchmarks", supports Indic scripts and romanised Indic — [HF card](https://huggingface.co/sarvamai/sarvam-m)
- AI4Bharat IndicTrans2: "first open-source transformer-based multilingual NMT model that supports high-quality translations across all the 22 scheduled Indic languages"; 1B base and ~200M distilled checkpoints on HF; BPCC corpus ≈230M bitext pairs; IN22 benchmark — [GitHub](https://github.com/AI4Bharat/IndicTrans2); [arXiv 2305.16307](https://arxiv.org/abs/2305.16307)
- AI4Bharat IndicConformer-600M (hybrid CTC+RNNT, 22 languages); its card now recommends successor "Indic-Transcribe (bodhan-ai) … supports 25 Indian languages and has better transcription quality" — [HF card](https://huggingface.co/ai4bharat/indic-conformer-600m-multilingual); AI4Bharat also lists IndicWav2Vec and IndicWhisper ASR models — [ai4bharat.iitm.ac.in](https://ai4bharat.iitm.ac.in/)
- Saaras V4 (Sarvam blog): LLM-WER on Vistaar (10 Indian languages) 11.12 vs ElevenLabs Scribe v2 14.44, Deepgram Nova3 23.33, GPT-4o Transcribe 25.89; per-language LLM-WER Hindi 5.80 (Scribe 11.53, Nova3 23.35, GPT-4o-Transcribe 8.63), Bengali 8.64, Marathi 9.64, Tamil 18.72, Malayalam 19.12; language-ID error 2.9% across top-10 languages — [Sarvam blog](https://www.sarvam.ai/blogs/introducing-saaras-v4) (vendor-run benchmark)
- Third-party summary: Saaras v3 "19.31% WER on the IndicVoices benchmark across the 10 most common Indian languages"; recommends Saaras for code-mixed/telephony Indian audio and Whisper or Google Chirp 3 for global English — [anuragwagh.com](https://anuragwagh.com/blog/sarvam-saaras-v3-vs-whisper-vs-google-stt-benchmark) (blog)
- Gemini 3.5 Transcribe exists as a dedicated STT model ($0.003/min audio in) — [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing)
- Google Cloud Speech-to-Text v2 includes Chirp models — [GCP STT pricing](https://cloud.google.com/speech-to-text/pricing)
- Krutrim / Gemma Indic variants: not retrievable in this session (see Gaps)

### Inferences
- The "doctor takes over" pattern is cheapest to implement as a conversation-level state flag (bot / hybrid / human) in Redis plus an inbox UI (Chatwoot self-hosted is the zero-licence option); LangGraph `interrupt()` or OpenAI Agents SDK HITL gives the same semantics inside the agent loop for "draft-for-approval" (agent drafts → doctor approves via a WhatsApp interactive button or the inbox → send).
- Because Meta retries for 7 days and duplicates are explicit in the docs, dedupe on `message.id` in Redis is mandatory, and the LLM call must never run inside the webhook request.
- Voice notes arrive as OGG/Opus; Sarvam Saaras v4 is the strongest documented option for Hindi/Indic voice notes on vendor benchmarks, with Gemini 3.5 Transcribe / Deepgram Nova-3 multilingual as fallbacks; WhatsApp's own client-side transcript is not reliable for backend use.
- Meta Business Agent at ~4–5¢/message sets a price ceiling: a custom agent on Haiku-class models is roughly 100x cheaper per turn (see Q4), so the custom build's value is in doctor-specific protocols, EHR/appointment tools and handoff, not raw chat.

### Gaps
- I could not fetch Meta's "Conversation types"/"Get started" pages (blocked) — numbers like the exact webhook timeout are from community sources only.
- No official doc fetched for Krutrim or Google Gemma-Indic; Gemma 4 pricing on Gemini API shows "Not available" (free tier only) — [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing).
- Star counts / maintenance status of the GitHub examples were not verified from GitHub itself (only README content).

---

## Key Question 2 — Mental-health chatbot architecture patterns (Wysa, Limbic, Woebot, Therabot, Ash) and safety tooling

### Takeaway
Every evidenced system layers a deterministic/classifier safety path *ahead of* generation (crisis detection → scripted SOS/safety plan/hotline), keeps the generative layer narrowly trained or prompted to CBT protocols, and has clinician review of flagged sessions; the open tooling to replicate this is Llama Guard 4 (S11 self-harm, S6 specialized advice), NeMo Guardrails rails, free OpenAI moderation, small HF suicide classifiers (Reddit-trained, 94–98% self-reported accuracy, unvalidated clinically), and promptfoo/DeepTeam/Inspect for red-teaming.

### Cited Findings

**Vendor architectures and evidence**
- Therabot (Dartmouth): first RCT of a generative-AI therapy chatbot, NEJM AI, March 27 2025; 106 people with MDD, GAD or eating-disorder risk in the treatment arm; "51% average reduction in symptoms" for depression, 31% for GAD, 19% for body-image/weight concerns; therapeutic alliance "comparable to working with a mental health professional"; avg 6 hours of use; built on "an original training set the researchers developed from current, evidence-based best practices for psychotherapy and cognitive behavioral therapy"; "If Therabot detects high-risk content such as suicidal ideation… it will provide a prompt to call 911, or contact a suicide prevention or crisis hotline, with the press of an onscreen button"; earlier evals found ">90% of responses were consistent with therapeutic best-practices"; in development since 2019 — [Dartmouth news](https://home.dartmouth.edu/news/2025/03/first-therapy-chatbot-trial-yields-mental-health-benefits); paper [NEJM AI](https://ai.nejm.org/doi/full/10.1056/AIoa2400802) (paywalled, not fetched); lead author: "no generative AI agent is ready to operate fully autonomously in mental health" — WebSearch summary of [ScienceDaily](https://www.sciencedaily.com/releases/2025/03/250327141529.htm)
- Wysa SOS data (Apr 15 2024; 19,000 users, 99 countries): "82% of these instances were detected by Wysa's AI and confirmed by the user that they were having thoughts of self harm or suicide… escalated the user to Wysa's SOS interventions"; 18% self-selected via the SOS button; "1 in 20 users trigger SOS mode every year"; SOS = helplines, personal safety plan, grounding exercises; 31% of SOS triggers 6pm–midnight — [Wysa blog](https://blogs.wysa.io/blog/wysa-news/ai-detects-82-of-mental-health-app-users-in-crisis-finds-wysas-global-study-released-on-the-role-of-ai-to-detect-and-manage-distress)
- Wysa: FDA Breakthrough Device Designation (following a JMIR chronic-pain/depression/anxiety trial); "more than 36 peer-reviewed publications" — [Wysa clinical evidence](https://www.wysa.com/clinical-evidence); Wysa says clinical safety is applied to "its rules engine and content library" and each AI model is "validated on at least 10,000 manually tagged records" — WebSearch summary of [wysa.com/ai-support](https://www.wysa.com/ai-support) (not directly fetched); a secondary source describes Wysa as using "a deterministic Safety Layer that intercepts crisis signals upstream of any generation" — [Neurals case study](https://neurals.ca/case-studies/healthcare/mental-health-support/) (not Wysa's own wording)
- Limbic: Nature Medicine 2024 multisite study of 129,400 NHS patients: self-referral chatbot services saw "15% increase versus 6% increase in control services" in referrals, "nonbinary (179% increase) and ethnic minority individuals (29% increase)" — [Habicht et al., Nat Med 30:595–602](https://www.nature.com/articles/s41591-023-02766-x); Limbic Access achieved Class IIa UKCA certification, auditors "reviewed clinical evidence generated from more than 60,000 referrals", with the e-triage chatbot "able to predict mental health disorders with an accuracy rate of 93%"; 130,000 NHS patients at that time — [HIT Consultant, Jan 23 2023](https://hitconsultant.net/2023/01/23/ai-mental-health-chatbot-diagnoses-disorders-with-93-accuracy/); product now split into Intake Agent, Triage Agent ("Proprietary clinical AI assesses needs, predicts diagnoses") and Therapy Agent ("Delivers CBT through generative chat while managing clear escalation pathways to clinical staff") — [limbic.ai](https://limbic.ai/)
- Slingshot "Ash": launched July 22 2025 with $93M funding; training = pre-training on behavioural-health data → clinical-team fine-tuning (when to challenge a user / end a conversation) → reinforcement learning; "Every flagged session is reviewed by a clinician to confirm that the AI gave appropriate information, like emergency contacts" — [Nebius case study](https://nebius.com/customer-stories/slingshot-ai); [BusinessWire launch](https://www.businesswire.com/news/home/20250722566346/en/Slingshot-Launches-Ash-the-First-AI-Designed-for-Therapy); STAT (Nov 24 2025): company preprint claims a 300-participant study and that guardrails "worked 100% of the time", disclaimers say "Ash is not intended for people facing a mental health crisis", and Slingshot argued to FDA that Ash is a low-risk "general wellness" app — [STAT](https://www.statnews.com/2025/11/24/slingshot-ai-mental-health-chatbot-safety-study-results/) (company claims, not independent)
- Woebot Health discontinued its consumer app in June 2025 — [bestaitherapy.ai guide](https://bestaitherapy.ai/guides/woebot-shutdown-explained/) (secondary; Woebot's own notice page exists at [woebothealth.com/woebot-health-to-close-consumer-app](https://woebothealth.com/woebot-health-to-close-consumer-app/) but its body did not render in my fetch); Woebot founded 2017 by clinical psychologist Alison Darcy — [woebothealth.com](https://woebothealth.com/)

**Guardrail frameworks**
- Llama Guard 4 (12B): "natively multimodal safety classifier… trained jointly on text and multiple images", aligned to the MLCommons hazards taxonomy, categories S1–S14 including **S6 Specialized Advice** ("financial, medical, or legal advice"), **S11 Self-Harm** ("Suicide, Self-injury (ex: cutting), Disordered eating") and S14 Code Interpreter Abuse; "can be run on a single GPU"; drop-in replacement for Llama Guard 3 8B/11B; outputs `safe` / `unsafe S1,S2` — [Meta model card](https://www.llama.com/docs/model-cards-and-prompt-formats/llama-guard-4/); [HF card](https://huggingface.co/meta-llama/Llama-Guard-4-12B)
- NeMo Guardrails: "Input rails… can reject the input… or alter the input (e.g., to mask potentially sensitive data)"; output rails can reject/alter; supports LlamaGuard, Fiddler, NemoGuard Jailbreak-Detection and Topic-Control NIMs; evaluation + vulnerability-scanning tooling — [docs](https://docs.nvidia.com/nemo/guardrails/latest/index.html); [GitHub](https://github.com/NVIDIA-NeMo/Guardrails)
- Guardrails AI: "[July 6, 2026] Guardrails validators are moving to standard PyPI packages… and Guardrails is discontinuing its hosted remote inferencing"; "Guardrails Index" benchmarks 24 guardrails across 6 categories — [GitHub](https://github.com/guardrails-ai/guardrails)
- Anthropic Constitutional Classifiers (Feb 2025): 183 red-teamers spent ">3,000 hours" with no universal jailbreak found; refusal rate up only 0.38% (not significant); compute cost "+23.7%" — [Anthropic research](https://www.anthropic.com/research/constitutional-classifiers)
- OpenAI Moderation: "The moderation endpoint is free to use", `omni-moderation-latest` accepts text and image inputs; categories include self-harm — [OpenAI moderation guide](https://developers.openai.com/api/docs/guides/moderation)

**Open crisis-detection classifiers (Hugging Face)**
- `sentinet/suicidality` (ELECTRA; CC0): Accuracy 0.9394, Recall 0.9372, Precision 0.9282, trained on Kaggle/Reddit/Twitter/suicide-note datasets — [HF card](https://huggingface.co/sentinet/suicidality)
- `gooohjy/suicidal-electra` (MIT): Accuracy 0.9792, Recall 0.9788, Precision 0.9677; Reddit dataset "232,074 rows equally distributed between 2 classes" — [HF card](https://huggingface.co/gooohjy/suicidal-electra)
- `vibhorag101/roberta-base-suicide-prediction-phr` (MIT): test Accuracy 0.9653 / F1 0.9652 (val 0.9707); dataset derived from Reddit (r/SuicideWatch-style posts) — [HF card](https://huggingface.co/vibhorag101/roberta-base-suicide-prediction-phr); [dataset](https://huggingface.co/datasets/vibhorag101/suicide_prediction_dataset_phr)
- PsyGUARD (RoBERTa, Chinese, EMNLP 2024) for suicidal-ideation detection in text counselling — WebSearch result [HF dataset README](https://huggingface.co/datasets/qiuhuachuan/PsySUICIDE/raw/main/README.md)
- Caveat stated in search synthesis: these numbers are self-reported on random splits of social-media text; no independent clinical validation found

**Evaluation / red-team harnesses**
- promptfoo: open-source; "breaks down LLM failure modes into adversarial testers known as plugins"; plugin catalogue includes `harmful:*` (e.g., misinformation, illegal drugs), `hallucination`, `overreliance`, `excessive-agency`, and OWASP LLM Top-10 / API Top-10 mappings — [promptfoo red-team docs](https://www.promptfoo.dev/docs/red-team/); [plugins](https://www.promptfoo.dev/docs/red-team/plugins/)
- DeepTeam (DeepEval): "Vulnerabilities… Adversarial Attacks… Target LLM System… Metrics" loop; `red_team(model_callback=…, vulnerabilities=[Bias(...)], attacks=[PromptInjection()])` — [deepeval docs](https://deepeval.com/docs/red-teaming-introduction)
- Inspect (UK AI Security Institute): "over 200 pre-built evaluations", agent evals, Docker/K8s sandboxing, MCP tools — [inspect.aisi.org.uk](https://inspect.aisi.org.uk/)
- A 2026 arXiv paper on "Retrieval-Augmented Generation in LLMs for Mental Health" exists — [arXiv 2607.24817](https://arxiv.org/pdf/2607.24817) (surfaced via search; not read)

### Inferences
- A defensible open stack for a counsellor bot: (1) pre-generation: regex/keyword list + fine-tuned small classifier (e.g., the RoBERTa/ELECTRA models above, re-validated on your own Hinglish data) + Llama Guard 4 or OpenAI moderation on *both* user input and model output; (2) constrained generation: system prompt pinned to CBT/psychoeducation scope, refusal of diagnosis/medication advice (Llama Guard S6 catches "specialized advice"); (3) scripted SOS path (safety plan, Indian helplines e.g., Tele-MANAS — not verified here) that bypasses the LLM; (4) clinician review queue for every flagged session (the Ash and Wysa pattern); (5) long-term memory = structured mood log + summarised history rather than raw transcript replay.
- Woebot's consumer shutdown and Slingshot's FDA "general wellness" positioning show the regulatory boundary: a product that claims to *treat* a condition is a device; wellness/coaching framing is what shipping consumer products use.
- The 94–98% accuracies of HF suicide classifiers are optimistic for WhatsApp/Hinglish chat; expect to re-label and re-evaluate (Wysa's "10,000 manually tagged records" is the order of magnitude of validation set a serious team uses).

### Gaps
- No primary Wysa technical paper separating rules vs. model in the SOS pipeline was found.
- Slingshot's preprint (methods for the "100% guardrails" claim) was not retrieved.
- Woebot's own closure announcement text was not retrievable; date "June 2025" is from secondary sources.
- No Indian-language (Hindi/Hinglish) crisis-detection model card was found.

---

## Key Question 3 — Model options and prices as of October 2026

### Takeaway
Frontier pricing has collapsed and re-tiered since 2025: Anthropic's line-up is Fable 5.1 ($10/$50), Opus 5.5 ($4/$20), Sonnet 5.5 ($2/$10) and Haiku 5.5 ($0.10/$0.50 for ≤100k-token prompts); OpenAI's is gpt-6-astra ($10/$50), gpt-6.1-sol ($2/$10), gpt-6-luna ($0.10/$0.50); Google's is Gemini 4 Argon ($2/$10 promo → $4/$20 from Dec 1 2026) and Gemini 3.8 Flash ($0.75/$3.75 promo → $1.50/$7.50 from Jan 1 2027). Indian-language STT is ₹30/hour (₹0.50/min) at Sarvam vs ~$0.003–0.006/min for Gemini/OpenAI/Deepgram.

### Cited Findings

**Anthropic (Claude API; page fetched 2026-10-20, prices USD per million tokens)** — [platform.claude.com pricing](https://platform.claude.com/docs/en/about-claude/pricing); [models overview](https://platform.claude.com/docs/en/about-claude/models/overview)
| Model (API id) | Input | 5m cache write | Cache read | Output |
|---|---|---|---|---|
| Claude Fable 5.1 (`claude-fable-5-1`) | $10 | $12.50 | $0.25 | $50 |
| Claude Opus 5.5 (`claude-opus-5-5`) | $4 | $5 | $0.20 | $20 |
| Claude Opus 5 / 4.8 / 4.7 / 4.6 / 4.5 | $5 | $6.25 | $0.50 | $25 |
| Claude Sonnet 5.5 (`claude-sonnet-5-5`) | $2 | $2.50 | $0.10 | $10 |
| Claude Sonnet 5 | $2 | $2.50 | $0.20 | $10 |
| Claude Sonnet 4.6 / 4.5 | $3 | $3.75 | $0.30 | $15 |
| Claude Haiku 5.5 (`claude-haiku-5-5`), prompts ≤100k tokens | $0.10 | $0.125 | $0.01 | $0.50 |
| Claude Haiku 5.5, prompts >100k tokens | $0.50 | $0.625 | $0.05 | $2.50 |
| Claude Haiku 4.5 | $1 | $1.25 | $0.10 | $5 |
- "Batch API requests are 50% off"; all current models have a 1M-token context window; "Claude 4.7 and later models… use a newer tokenizer… produces approximately 30% more tokens for the same text" — [models overview](https://platform.claude.com/docs/en/about-claude/models/overview)
- Sonnet 5's $2/$10 "introductory pricing… is now the standard price" (planned Sept 1 2026 increase cancelled) — [pricing page footnote](https://platform.claude.com/docs/en/about-claude/pricing)
- Haiku 5.5: 1M context, 128k max output, adaptive thinking, knowledge cutoff Jun 2026, "Fastest" latency tier — [Haiku 5.5 overview](https://platform.claude.com/docs/en/models/haiku-5-5/overview)
- US-only inference (`inference_geo: "us"`) costs 1.1x; Bedrock/Vertex regional endpoints carry a 10% premium over global — [pricing](https://platform.claude.com/docs/en/about-claude/pricing); [data residency](https://platform.claude.com/docs/en/manage-claude/data-residency)
- Bedrock: "Starting October 7, 2026, cache read pricing for Claude Sonnet 5.5 is reduced by 50%" — [AWS Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)

**OpenAI (fetched 2026-10-20; USD per 1M tokens, Standard tier, short context)** — [OpenAI pricing](https://developers.openai.com/api/docs/pricing)
| Model | Input | Cached input | Output | Long-context (input/output) |
|---|---|---|---|---|
| gpt-6-astra | $10.00 | $1.00 | $50.00 | $20 / $75 |
| gpt-6.1-sol | $2.00 | $0.10 | $10.00 | $4 / $15 |
| gpt-6-luna | $0.10 | $0.01 | $0.50 | $0.20 / $0.75 |
| gpt-5.6-sol (promo "at least through November 21, 2026") | $4.00 | $0.40 | $20.00 | $8 / $30 |
- Batch and Flex tiers are 50% of Standard; "Fast" is 2x; "Ultrafast" is 6x (e.g., gpt-6.1-sol Fast $4/$20); "Priority processing was renamed Fast mode on July 30, 2026"; "Regional processing (data residency) endpoints are charged a 10% uplift for models released on or after March 5, 2026" — same page
- Audio: `gpt-transcribe` $0.0045/min; `gpt-4o-transcribe` $0.006/min ($2.50/$10 per 1M tokens); `gpt-4o-mini-transcribe` $0.003/min; `gpt-live-transcribe` and `gpt-realtime-whisper` $0.017/min; `gpt-realtime-2.1` audio $32 in / $64 out per 1M, `-mini` $10/$20; `gpt-live-1` voice sessions $0.05/min — same page (legacy `whisper-1` no longer listed)
- Tools: file search $2.50/1k calls + $0.10/GB-day storage; web search $10/1k calls — same page

**Google Gemini API (fetched 2026-10-20; paid tier, USD per 1M tokens)** — [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing)
| Model | Input | Output | Notes |
|---|---|---|---|
| Gemini 4 Argon | $2.00 → $4.00 from Dec 1 2026 | $10.00 → $20.00 | flagship; no free tier |
| Gemini 3.8 Flash | $0.75 → $1.50 from Jan 1 2027 | $3.75 → $7.50 | free tier; batch $0.375/$1.875 |
| Gemini 3.6 Flash | $0.75 → $1.50 | $3.75 → $7.50 | free tier |
| Gemini 3.5 Flash-Lite | $0.30 | $2.50 | batch $0.15/$1.25 |
| Gemini 3.1 Flash-Lite | $0.25 (audio $0.50) | $1.50 | batch $0.125/$0.75 |
| Gemini 3.1 Pro Preview | $2.00 (≤200k) / $4.00 | $12.00 / $18.00 | |
| Gemini 3 Flash Preview ("legacy Flash") | $0.50 (audio $1.00) | $3.00 | |
| Gemini 2.5 Pro | $1.25 (≤200k) | $10.00 | |
| Gemini 2.5 Flash | $0.30 (audio $1.00) | $2.50 | |
| Gemini 2.5 Flash-Lite | $0.10 (audio $0.30) | $0.40 | |
| Gemini 3.5 Transcribe | $2.00/1M audio tokens ≈ $0.003/min | text ≈ $0.002/min | dedicated STT |
| Gemini 3.5 Transcribe Live | ≈ $0.005/min audio | ≈ $0.004/min text | streaming |
| Gemini 3.8 Live (voice) | $0.75 text / $3.00 audio (≈$0.005/min) | $4.50 text / $12 audio (≈$0.018/min) | |
- Grounding with Google Search: 5,000 free requests/month then $14 per 1,000 — same page

**Sarvam AI (official, INR; page fetched 2026-10-20)** — [Sarvam pricing](https://docs.sarvam.ai/api-reference-docs/pricing)
- LLMs (₹ per 1M tokens): Sarvam 105B / 105B-conversations ₹15 in, ₹5 cached, ₹60 out; Gemma 4 31B ₹35/₹10/₹90 (beta); GLM-5.3 ₹126/₹20/₹390 (beta); DeepSeek V4.1 Flash ₹25/₹0.5/₹105 (beta)
- Speech-to-Text ₹30/hour (= ₹0.50/min), with diarization ₹45/hour; "Priced per hour, billed per second"
- Translation/transliteration ₹20 per 10K characters; language ID ₹3.5/10K chars; Bulbul v3 TTS ₹30 per 10K characters; Document Digitization ₹0.5/page, Extraction ₹1/page; Dubbing from ₹36–40/min
- "Every new user receives ₹100 in credits"

**Deepgram (fetched 2026-10-20)** — [Deepgram pricing](https://deepgram.com/pricing)
- Pre-recorded: Nova-3 Monolingual $0.0043/min, Nova-3 Multilingual $0.0052/min, Whisper Large $0.0048/min; streaming Nova-3 $0.0048/min (promo; regular $0.0077), Multilingual $0.0058/min (regular $0.0092); $200 free credit; "45+ languages"; HIPAA BAA "for Enterprise customers"

**Google Cloud Speech-to-Text v2** — [GCP pricing](https://cloud.google.com/speech-to-text/pricing)
- Standard models (incl. Chirp): $0.016/min with data logging, $0.024/min without (first 60 min/month free); dynamic batch $0.003/min; Medical models $0.078/min

**Open-weight hosting (Together AI serverless, USD per 1M in/out; fetched 2026-10-20)** — [Together pricing](https://www.together.ai/pricing)
- Gemma 4 31B $0.39/$0.97; gpt-oss-120B $0.15/$0.60; Qwen3.8 Flash $0.15/$0.47; Qwen3.5 9B $0.17/$0.25; Qwen3.7-Plus $0.32/$1.28; DeepSeek V4.1 Flash $0.30 (input); Qwen3.8-2.4T-A95B $2.00 (input)
- Sarvam also serves Gemma 4 31B at ₹35/₹90 per 1M (beta) — [Sarvam pricing](https://docs.sarvam.ai/api-reference-docs/pricing)

**Indian-language quality comparisons**
- Saaras V4 vs others on Vistaar (10 Indic languages, LLM-WER, lower is better): Saaras V4 11.12, ElevenLabs Scribe v2 14.44, Deepgram Nova3 23.33, GPT-4o Transcribe 25.89; Hindi: 5.80 / 11.53 / 23.35 / 8.63 — [Sarvam blog](https://www.sarvam.ai/blogs/introducing-saaras-v4) (vendor benchmark)
- English (7 suites incl. Svarah Indian-English): AssemblyAI 4.66, Deepgram Nova 3 5.57 average WER (Saaras's own English number not captured) — same blog

### Inferences
- For a WhatsApp doctor agent, the economic sweet spot is Haiku 5.5 / gpt-6-luna / Gemini 3.1 Flash-Lite (≈$0.10–0.25 input) for routing, classification, extraction and FAQ replies, escalating to Sonnet 5.5 / gpt-6.1-sol / Gemini 3.8 Flash for clinical-nuance replies; with prompt caching, the per-turn cost is dominated by uncached conversation history, not the system prompt.
- Sarvam STT at ₹0.50/min is roughly 6–10x the per-minute price of Gemini 3.5 Transcribe ($0.003/min) or Deepgram Nova-3 ($0.0043–0.0052/min); the justification is the vendor-reported 2–4x lower Hindi/Indic WER and 8 kHz/code-mix handling — worth A/B testing on your own voice notes.
- Note Google's and OpenAI's current promo pricing expires on stated dates (Gemini Nov 30/Dec 31 2026; gpt-5.6-sol Nov 21 2026): budget at the post-promo numbers.

### Gaps
- Llama 4 was not on the Together price list I captured; no official Llama 4 hosting price obtained.
- `whisper-1` is absent from OpenAI's current pricing page; self-hosted Whisper GPU cost not sourced.
- Azure OpenAI per-token prices in Central India not fetched.
- No INR/USD rate sourced; Meta's own rate card implies ≈₹73–82 per USD depending on category (rounded) — [INR vs USD cards](https://developers.facebook.com/docs/whatsapp/pricing/).

---

## Key Question 4 — Unit economics: tokens per turn, cost per conversation, per-doctor monthly cost, WhatsApp/BSP fees, hosting, and a 10k-MAU counselling app

### Takeaway
With cached system prompts, an LLM turn on Haiku 5.5 / gpt-6-luna costs ≈$0.0004 (≈₹0.03–0.04) and on Sonnet 5.5 / gpt-6.1-sol ≈$0.008 (≈₹0.6–0.7); the WhatsApp delivery fee in India (₹0.115 per service/utility message after 1,000 free service messages per number per month, Oct 1 2026 card) and any BSP fee ($0.005/message at Twilio) are therefore comparable to or larger than the Haiku-class LLM cost. A doctor at 1,000 patient messages/day runs ≈$12/month on Haiku 5.5 or ≈$237/month on Sonnet 5.5 for the LLM, plus ≈₹3,300/month to Meta, plus hosting of roughly $20–60/month. A 10k-MAU counsellor app at 20 turns/day is dominated by LLM choice: ≈$1k/month on Haiku-class vs ≈$19k/month on Sonnet-class at 2M turns/month (all ESTIMATES; assumptions below).

### Cited Findings (rates used)

**WhatsApp (Meta) India rate card, effective October 1 2026** — INR and USD list-rate spreadsheets linked from [Meta pricing docs (updated Sep 30 2026)](https://developers.facebook.com/docs/whatsapp/pricing/):
| Category (India) | INR / message | USD / message |
|---|---|---|
| Marketing | ₹0.8631 | $0.0118 |
| Utility | ₹0.115 | $0.0014 |
| Authentication | ₹0.115 | $0.0014 |
| Authentication-International | ₹2.4971 | $0.0304 |
| Service | ₹0.115 | $0.0014 |
| Meta Business Agent | $2.00 USD / 1M tokens (global) | same |
- Rules: "Effective July 1, 2025 – Meta charges on a per-message basis… only for messages from businesses to users"; "For each business phone number, Meta provides 1,000 free service messages per month… Meta only charges as of the 1,001st service message"; all categories are free inside a Free Entry Point window (ad click-to-WhatsApp, up to 7 days); Meta changes prices only on Jan 1 / Apr 1 / Jul 1 / Oct 1 — [Meta pricing](https://developers.facebook.com/docs/whatsapp/pricing/)
- **Conflict to note:** Meta's marketing site still says "we do not charge for service messages, or for utility messages businesses send in response to users" — [business.whatsapp.com platform pricing](https://whatsappbusiness.com/products/platform-pricing/) — whereas the developer rate card dated Sep 30 2026 lists a Service rate of ₹0.115 beyond the free tier. Treat the developer docs/rate card as authoritative and budget ₹0.115 per reply beyond 1,000/month.
- Volume tiers exist "for utility and authentication messages only" — same page
- Twilio adds "$0.005 per message… inbound or outbound" on top of Meta fees — [Twilio](https://www.twilio.com/en-us/messaging/channels/whatsapp/pricing)
- Meta's own hosted agent benchmark: 20–25k tokens/message → "approximately 4–5 cents (USD) per message"; Meta estimates third-party AI at ~9¢/message — [Meta pricing](https://developers.facebook.com/docs/whatsapp/pricing/)

**LLM rates** (see Q3 tables): Haiku 5.5 $0.10/$0.50 (cache read $0.01); Sonnet 5.5 $2/$10 (cache read $0.10); Opus 5.5 $4/$20 (cache read $0.20); gpt-6-luna $0.10/$0.50 (cached $0.01); gpt-6.1-sol $2/$10 (cached $0.10); Gemini 3.8 Flash $0.75/$3.75 (through Dec 31 2026; implicit cache $0.075); Sarvam 105B ₹15/₹5 cached/₹60 — [Anthropic](https://platform.claude.com/docs/en/about-claude/pricing), [OpenAI](https://developers.openai.com/api/docs/pricing), [Google](https://ai.google.dev/gemini-api/docs/pricing), [Sarvam](https://docs.sarvam.ai/api-reference-docs/pricing)

**STT rates**: Sarvam ₹30/hr (₹0.50/min) — [Sarvam](https://docs.sarvam.ai/api-reference-docs/pricing); Deepgram Nova-3 multilingual $0.0052/min — [Deepgram](https://deepgram.com/pricing); OpenAI gpt-transcribe $0.0045/min — [OpenAI](https://developers.openai.com/api/docs/pricing); Gemini 3.5 Transcribe ≈$0.003/min — [Google](https://ai.google.dev/gemini-api/docs/pricing)

**Hosting rates**
- AWS Mumbai (ap-south-1) Linux on-demand, from AWS's pricing data feed (fetched 2026-10-20): t4g.small $0.0112/hr, **t4g.medium (2 vCPU, 4 GiB) $0.0224/hr**, t4g.large $0.0448/hr, t3.medium $0.0448/hr, m6g.large $0.0506/hr — [AWS EC2 on-demand price feed, Asia Pacific (Mumbai)](https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/ec2/USD/current/ec2-ondemand-without-sec-sel/Asia%20Pacific%20(Mumbai)/Linux/index.json) (same data as [aws.amazon.com/ec2/pricing/on-demand](https://aws.amazon.com/ec2/pricing/on-demand/))
- Render (fetched 2026-10-20): web services free (512 MB) / $7/mo (512 MB) / $25/mo (2 GB, 1 CPU); Postgres free (256 MB) / $6/mo (256 MB) / $19/mo (1 GB) / $55/mo (4 GB); key-value (Redis-compatible) free (25 MB) / $10/mo (256 MB) — [Render pricing](https://render.com/pricing)
- Railway: free trial = one-time $5 credit; Hobby "includes $5 of usage per month"; Pro "$20 minimum usage… Includes $20 of monthly usage"; usage billed by the second — [Railway pricing](https://railway.com/pricing)

### Inferences — the arithmetic (all ESTIMATES; assumptions stated)

**A. Tokens per WhatsApp reply turn (assumption)**
- System prompt + doctor protocol + tool schemas: 2,000 tokens, prompt-cached (cache read).
- RAG chunks (clinic FAQ/protocol): 1,500 tokens, uncached.
- Recent conversation history: 1,500 tokens, uncached (history could also be cached with the 5-minute cache if turns are rapid).
- Patient message: 100 tokens; reply: 150 tokens (WhatsApp replies are short).
- Total ≈ 5,100 input (2,000 cached + 3,100 uncached) + 150 output. Add ~30% if moving from Claude 4.6-era to 4.7+ tokenizer (already reflected because these are 2026-tokenizer-era estimates; the 30% note is from Anthropic's docs).

**B. LLM cost per turn (USD)**
| Model | Uncached in (3,100) | Cached in (2,000) | Out (150) | ≈ per turn |
|---|---|---|---|---|
| Haiku 5.5 | 3,100×$0.10/M = $0.00031 | 2,000×$0.01/M = $0.00002 | 150×$0.50/M = $0.000075 | **$0.0004** |
| gpt-6-luna | same rates as Haiku 5.5 | | | **$0.0004** |
| Gemini 3.1 Flash-Lite | 3,100×$0.25/M = $0.00078 | (implicit cache ~$0.025/M) $0.00005 | 150×$1.50/M = $0.00023 | **$0.0011** |
| Gemini 3.8 Flash (promo) | 3,100×$0.75/M = $0.0023 | 2,000×$0.075/M = $0.00015 | 150×$3.75/M = $0.00056 | **$0.0030** |
| Sonnet 5.5 / gpt-6.1-sol | 3,100×$2/M = $0.0062 | 2,000×$0.10/M = $0.0002 | 150×$10/M = $0.0015 | **$0.0079** |
| Opus 5.5 | 3,100×$4/M = $0.0124 | 2,000×$0.20/M = $0.0004 | 150×$20/M = $0.0030 | **$0.0158** |
| Sarvam 105B (INR) | 3,100×₹15/M = ₹0.047 | 2,000×₹5/M = ₹0.010 | 150×₹60/M = ₹0.009 | **≈₹0.066** |
- A 6-turn patient conversation therefore costs ≈$0.0024 on Haiku 5.5, ≈$0.047 on Sonnet 5.5, ≈$0.095 on Opus 5.5 — versus Meta Business Agent's ~4–5¢ *per message* (so ≈$0.27 for 6 messages).

**C. Per-doctor monthly LLM cost (30 days; 1 LLM call per patient message)**
| Patient msgs/day | Turns/month | Haiku 5.5 | Sonnet 5.5 | Opus 5.5 |
|---|---|---|---|---|
| 50 | 1,500 | $0.60 | $11.85 | $23.70 |
| 200 | 6,000 | $2.40 | $47.40 | $94.80 |
| 1,000 | 30,000 | $12.00 | $237 | $474 |
- Add a safety/intent pre-classifier on Haiku 5.5 (~1,500 in / 10 out ≈ $0.00016/turn): +$0.24 / +$0.96 / +$4.80 per month.
- Voice notes (assume 20% of messages are voice, 30 s each → 0.5 min): at 1,000 msgs/day → 100 min/day → 3,000 min/month → Sarvam ₹1,500/month; Deepgram Nova-3 multilingual $15.60/month; gpt-transcribe $13.50/month; Gemini 3.5 Transcribe ≈$9/month. At 50 msgs/day scale these are ₹75 / <$1.
- Images (prescriptions/lab reports): billed as input tokens on vision models; not costed here because the per-image token formula was not fetched (see Gaps) — at Sonnet-class rates a ~1,500-token image is ≈$0.003.

**D. WhatsApp delivery cost per doctor (India, Oct 2026 card; replies inside the 24-h window = Service)**
| Msgs/day | Replies/month | Billable (after 1,000 free) | Meta cost | + Twilio ($0.005 × in+out) |
|---|---|---|---|---|
| 50 | 1,500 | 500 | ₹57.5 (≈$0.70) | $15 |
| 200 | 6,000 | 5,000 | ₹575 (≈$7) | $60 |
| 1,000 | 30,000 | 29,000 | ₹3,335 (≈$40.6) | $300 |
- Appointment reminders outside the window are Utility templates at ₹0.115 each (e.g., 500 reminders/month = ₹57.5).
- Observation: at Twilio, the BSP fee ($0.005) is ≈3.6x Meta's India utility/service fee ($0.0014); direct Cloud API (or a cheaper Indian BSP) avoids it.

**E. Hosting for a small FastAPI + Postgres + Redis stack**
- AWS Mumbai minimal: t4g.medium app box $0.0224×730 h ≈ $16.35/month (+ RDS db.t4g.micro and ElastiCache/Valkey — Mumbai prices not fetched; see Gaps) → ESTIMATE $35–60/month all-in.
- Render: $25 (2 GB web) + $19 (1 GB Postgres) + $10 (256 MB key-value) = **$54/month**; a dev stack can run on free tiers.
- Railway: Hobby $5/month includes $5 usage; a small 3-service stack typically lands in the $5–20/month band (ESTIMATE based on included usage).

**F. Mental-health app at 10k MAU, ~20 turns/day**
- Assumptions: counselling turn = 3,000-token system prompt (cached) + 1,000-token memory/mood summary + 2,500-token history + 80-token user message = 6,580 input (3,000 cached) + 200-token reply; plus one Haiku 5.5 safety-classifier call per turn (~$0.0002). "10k MAU × 20 turns/day" is read as 20 turns on each *active* day; I assume 10 active days/month → **2M turns/month** (if every MAU chatted 20 turns every day it would be 6M — upper bound).
- Per-turn: Haiku 5.5 ≈ 3,580×$0.10/M + 3,000×$0.01/M + 200×$0.50/M = $0.00049 (+$0.0002 classifier ≈ **$0.0007**); Gemini 3.8 Flash ≈ $0.0027+0.0002+0.00075 ≈ **$0.0039**; Sonnet 5.5 / gpt-6.1-sol ≈ $0.00716+0.0003+0.002 ≈ **$0.0097**; self-hosted-style Gemma 4 31B on Together (no cache) ≈ 6,580×$0.39/M + 200×$0.97/M ≈ **$0.0028**.
- Monthly at 2M turns: Haiku-class ≈ **$1,400**; Gemini 3.8 Flash ≈ **$7,800**; Gemma 4 31B (Together) ≈ **$5,600**; Sonnet-class ≈ **$19,400**. At the 6M upper bound multiply by 3.
- Per MAU per month: ≈$0.14 (Haiku-class) to ≈$1.94 (Sonnet-class) at 200 turns/MAU/month.
- Adding Llama Guard 4 self-hosted on one GPU instead of a Haiku classifier: GPU hourly cost not sourced here (Gap).

### Gaps
- No sourced INR/USD exchange rate; ₹→$ conversions above use ≈₹82/USD implied by Meta's utility card and are approximate.
- RDS/ElastiCache Mumbai on-demand prices were not retrieved (the AWS feed path for RDS returned NoSuchKey); the vantage.sh page quotes db.t4g.micro "from $0.016/hour" but the region of that headline figure is unclear — [instances.vantage.sh](https://instances.vantage.sh/aws/rds/db.t4g.micro?region=ap-south-1).
- Anthropic's image-token formula page was not fetched; image costs are unpriced.
- Actual token counts per WhatsApp turn are my assumptions; no published per-turn telemetry from a production clinic bot was found.

---

## Key Question 5 — Compliance-oriented infrastructure: India data residency, HIPAA-eligible LLM APIs, ZDR, consent/audit patterns, DPDP on WhatsApp

### Takeaway
In-country LLM inference in India is available via Amazon Bedrock's India geographic cross-region profile (Mumbai + Hyderabad; Claude Opus 5 / Sonnet 5 / Haiku 4.5 since Sept 2026) and OpenAI's "India" storage-residency option (processing residency is US/EU only); Anthropic's first-party API offers HIPAA-ready access and ZDR but only US or global inference geos, no India. DPDP Rules were notified on 14 Nov 2025 with an 18-month phase-in, requiring a separate clear consent notice, so a WhatsApp doctor bot needs an explicit opt-in + DPDP notice step before any PHI exchange.

### Cited Findings

**Anthropic**
- Two arrangements: ZDR ("does not store customer prompts or responses at rest after the API response is returned") and HIPAA readiness ("With a signed BAA and a HIPAA-enabled organization, you can use supported API features to process PHI"); "If your organization handles PHI, HIPAA readiness is the arrangement to use; you do not also need ZDR"; eligible orgs "can review and execute the BAA and enable HIPAA readiness directly from the Claude Console" — [API and data retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention)
- Not covered: Claude Console PHI processing, "Claude Platform on AWS and Microsoft Foundry", Claude Code, beta features; the API returns a 400 if a HIPAA org uses an ineligible feature; "Do not include PHI in JSON schema definitions" (structured-output schemas are cached separately) — same page
- "Claude Fable 5.1, Claude Mythos 5.1, Claude Fable 5, and Claude Mythos 5: These models require 30-day data retention and are not available under ZDR unless expressly authorized" — same page
- Data residency: `inference_geo` is `"global"` or `"us"` only (Claude 4.6+); "Currently, `"us"` is the only available workspace geo"; US-only inference is 1.1x price — [Data residency](https://platform.claude.com/docs/en/manage-claude/data-residency)
- Consumer/Team plans "can't enable HIPAA" — WebSearch summary citing Anthropic help center (not directly fetched)

**AWS / Bedrock (India in-country)**
- "Amazon Bedrock expands Claude model availability to in-country inferencing in India" (Sept 29 2026): Claude Opus 5, Claude Sonnet 5 and Claude Haiku 4.5 via an India geographic cross-Region inference profile; "The India geographic profile keeps inference within India. Requests route only between ap-south-1 and ap-south-2" (Mumbai, Hyderabad) — [AWS ML blog](https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-expands-claude-model-availability-to-india-cross-region-inference/); [AWS What's New](https://aws.amazon.com/about-aws/whats-new/2026/09/claude-region-expansion-in-sk/)
- Amazon Bedrock, Bedrock AgentCore and Amazon Transcribe (incl. HealthScribe) are on AWS's HIPAA Eligible Services list — [AWS HIPAA eligible services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)
- Third-party tracker lists, for ap-south-1, Claude Haiku 5.5 / Sonnet 5.5 / Opus 5.5 / Fable 5.1 and OpenAI GPT-6 Sol/Luna/Astra via cross-region inference profiles (Global/US/EU/AU…) — [modelavailability.com](https://modelavailability.com/platforms/aws/regions/ap-south-1) (unofficial; verify in the Bedrock console)
- Bedrock regional (vs global) endpoints carry a 10% premium for Claude 4.5+ models — [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing)

**OpenAI**
- "To use the OpenAI API with protected health information (PHI), your organization must first enter into a Business Associate Agreement (BAA) with OpenAI. Eligible organizations can accept the standard BAA in the API Platform… An enterprise agreement is not required… Self-serve enrollment requires an established history of API usage" — [OpenAI Help: BAA](https://help.openai.com/en/articles/8660679-getting-a-business-associate-agreement-for-the-openai-api)
- Abuse-monitoring logs retained up to 30 days by default; ZDR or Modified Abuse Monitoring available to eligible customers; under ZDR `store` is always treated as false; "Regional processing is supported in the United States and Europe (EEA + Switzerland)"; a storage-residency table lists India (`in.`) among regions for `/v1/chat/completions`, `/v1/audio/transcriptions`, `/v1/batches` etc.; data-residency endpoints carry a 10% uplift; "Web Search with live internet access is not HIPAA eligible" — [OpenAI: Your data](https://developers.openai.com/api/docs/guides/your-data)
- Customers with a BAA provisioned with "Private Retention with Private Safety Processing" can use BAA-eligible endpoints for PHI even with retention — same page

**Azure / GCP**
- Azure Foundry offers "global, data zone, or regional deployment types based on your compliance requirements"; an Azure model-availability table shows "South India" rows with some models ✅; I did not find Central India rows in the fetched table — [Azure region availability](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability); [Azure OpenAI models](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/models)
- Google Vertex AI publishes Claude "Models with regional pricing" (e.g., asia-southeast1) and regional endpoints for Sonnet 4.6 and earlier — [Vertex pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing); Mumbai (asia-south1) Claude availability not confirmed in this session

**Other vendors**
- Deepgram: "We sign Business Associate Agreements (BAA) for Enterprise customers"; EU data-residency endpoint exists (no India endpoint listed) — [Deepgram pricing](https://deepgram.com/pricing)
- Sarvam offers "Self-Hosted Deployments… AWS SageMaker" for STT/TTS/Vision — [Sarvam docs nav](https://docs.sarvam.ai/api-reference-docs/pricing)

**India DPDP**
- DPDP Act 2023: processing only for a lawful purpose with consent or legitimate uses (s.4); every consent request must be preceded/accompanied by a notice describing the personal data, purpose, how to exercise rights and complain (s.5); consent "shall be free, specific, informed, unconditional and unambiguous with a clear affirmative action" (s.6); verifiable parental consent for children (s.9); rights to access, correction/erasure, grievance redressal, nomination (ss.11–14); the Act's own illustration uses a telemedicine app's consent request — [DPDP Act 2023 (MeitY PDF)](https://www.meity.gov.in/static/uploads/2024/06/2bf1f0e9f04e6fb4f8fef35e82c42aa5.pdf)
- "The Government of India notified the Digital Personal Data Protection (DPDP) Rules, 2025 on 14 November 2025"; "The Rules introduce an eighteen-month period for phased compliance"; "Every Data Fiduciary must issue a separate consent notice that is clear and easy to understand"; Consent Managers must be India-based companies; breach-notification/children violations "can each attract penalties of up to ₹200 crore"; Data Protection Board oversees — [PIB summary PDF](https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf)
- WhatsApp policy: opt-in required and "You are responsible for and must secure all necessary notices, permissions, and consents… including maintaining a published privacy policy"; best practice is "separate opt-in by specific message category" and clear opt-out — [WhatsApp Business Messaging Policy](https://www.whatsapp.com/legal/business-policy)

### Inferences
- Lowest-friction India-resident design today: Bedrock in ap-south-1 with the India inference profile (Claude Sonnet 5 / Haiku 4.5), Postgres/Redis in Mumbai, Sarvam STT (Indian vendor) or self-hosted Sarvam/AI4Bharat models on SageMaker Mumbai; sign the AWS BAA if you also serve US patients. If using Anthropic's or OpenAI's first-party API, PHI leaves India (global/US inference) — acceptable under DPDP only with notice/consent and a cross-border transfer assessment (DPDP permits transfers except to blacklisted countries; verify in the Rules).
- DPDP-friendly consent on WhatsApp: first-contact interactive message with a short notice (purpose: triage/appointments; data: messages, voice notes, images; retention; rights; grievance contact) + explicit "I agree" button or WhatsApp Flow screen; log the consent event (message id, timestamp, template version) in an append-only audit table; separate opt-in for utility reminders; a keyword (STOP/रोकें) opt-out. Keep the consent template versioned so re-consent can be triggered when the notice changes (the Act requires re-notice for pre-existing consent).
- Audit/encryption pattern: store raw WhatsApp media encrypted at rest in Mumbai S3 with short TTL, keep transcripts/extractions in Postgres with row-level patient id, log every LLM call (model, prompt hash, tool calls, cost) and every human takeover; do not put PHI in tool/JSON schema names (Anthropic's HIPAA rule).

### Gaps
- Azure Central India model availability and GCP asia-south1 Claude/Gemini availability were not confirmed.
- DPDP Rules' exact cross-border and breach-notification mechanics (72-hour windows etc.) were not read from the Rules text itself (only the PIB summary).
- No source found on Meta's own data-residency for WhatsApp Cloud API message metadata (Meta hosts the Cloud API; messages transit Meta infrastructure outside India).

---

## Key Question 6 — Team and time estimates: MVP scope and timeline for each product

### Takeaway
Published 2026 benchmarks put an AI MVP at 4–16 weeks (4–6 for a single-LLM integration, 12–16 for multi-agent systems with evals/guardrails); mental-health chatbot agencies quote $40k–$80k for a basic MVP rising to $80k–$180k once safety logic and escalation are added, with timelines of ~2 months (simple) to 3–6 months (with safety/compliance). WhatsApp-specific overhead is Meta business verification and template approval (hours to two weeks). A solo developer can ship a doctor-reply bot MVP in 4–8 weeks on the open-source stacks above; a safe counselling bot is a 12-week+ small-team effort because of the safety evaluation loop.

### Cited Findings
- "Most AI MVPs launch in 4 to 16 weeks… Simple integrations — adding an LLM feature to an existing product — commonly ship in 4 to 6 weeks. Full products with custom workflows take 6 to 12 weeks, and complex multi-agent systems with evaluations and guardrails take 12 to 16 weeks" — [HyperNeuron, AI MVP benchmarks 2026](https://www.hyperneuron.io/insights/ai-mvp-development-cost-and-timeline-2026) (agency data)
- Mental-health chatbot development: "Basic MVP $40,000 – $80,000 (simple chatbot… basic check-ins, guided exercises, limited AI)"; "Mid-Level Product $80,000 – $180,000 (structured conversations, safety logic, escalation paths, analytics)"; "Enterprise-Grade $180,000 – $400,000 (governance, compliance readiness, monitoring… human-in-the-loop)"; "A simple mental health chatbot can come together in a couple of months. Once you add safety checks, escalation paths, and compliance review, the timeline usually stretches closer to three to six months" — [Appinventiv](https://appinventiv.com/blog/mental-health-chatbot-development/) (agency quote, USD)
- WhatsApp: "Meta Business Manager verification… can take anywhere from a few hours to two weeks"; "Budget a full week for both approvals [business verification + templates] before you commit to a launch date"; Meta's free test environment allows building and staging "without incurring API costs" — [groovyweb 2026](https://www.groovyweb.co/blog/whatsapp-business-bot-development-2026)
- Comparable builds documented as small/solo efforts: Claude+Twilio+FastAPI+SQLite agent "orchestrated almost entirely by Claude Code" — [ggomez.dev](https://ggomez.dev/blog/ai-whatsapp-agent-with-claude-and-twilio-no-code-build-walkthrough); Flask+Twilio+Claude bot — [ArielSmoliar/wa-chatbot](https://github.com/ArielSmoliar/wa-chatbot); clinic bot with Dialogflow + admin dashboard + follow-ups — [WhatsApp-Clinic-AI-Agent](https://github.com/Mahmoud-Ossama/WhatsApp-Clinic-AI-Agent); n8n multi-agent clinic template — [n8n #3694](https://n8n.io/workflows/3694-multi-agent-ai-clinic-management-with-whatsapp-telegram-and-google-calendar/)
- Clinical-grade comparators took years: Therabot "in development… since 2019" before its 2025 RCT — [Dartmouth](https://home.dartmouth.edu/news/2025/03/first-therapy-chatbot-trial-yields-mental-health-benefits); Limbic's certification rested on >60,000 referrals of evidence — [HIT Consultant](https://hitconsultant.net/2023/01/23/ai-mental-health-chatbot-diagnoses-disorders-with-93-accuracy/); Wysa's safety claims rest on ≥10,000 manually tagged validation records per model (WebSearch summary of wysa.com) and 36+ publications — [Wysa](https://www.wysa.com/clinical-evidence)
- Low-code alternative costs: Botpress Plus $150/mo, Team $750/mo — [Botpress](https://botpress.com/pricing); Chatwoot self-hosted open source — [GitHub](https://github.com/chatwoot/chatwoot)

### Inferences
- **Doctor WhatsApp agent MVP (solo dev, 4–8 weeks):** week 1 Meta app + business verification + webhook skeleton (FastAPI, signature check, Redis dedupe/queue); week 2 LLM reply loop with cached system prompt + clinic FAQ RAG (pgvector) + Haiku/Sonnet routing; week 3 voice-note STT (Sarvam/Gemini) + image intake (vision model → structured extraction) + appointment tool (Google Calendar/clinic API) + utility reminder templates; week 4 shared inbox (Chatwoot) with bot/hybrid/human state, doctor "draft-approve" buttons, DPDP consent flow, audit logging; weeks 5–8 promptfoo regression suite, red-team of medical-advice boundaries, pilot with one clinic. Comparable to HyperNeuron's "4–6 weeks simple integration / 6–12 weeks full product" band.
- **Mental-health counsellor MVP (2–3 people, 12 weeks minimum):** the chat loop is a week; the remaining time is the safety stack (classifier + Llama Guard/moderation + scripted SOS + clinician review queue), memory/mood-tracking design, and the evaluation harness (promptfoo/DeepTeam suites for self-harm, medication, eating-disorder, abuse disclosures, plus Hinglish variants) — matching Appinventiv's "3–6 months once you add safety checks, escalation paths, and compliance review" and HyperNeuron's "12–16 weeks… with evaluations and guardrails".
- Budget reality for India: agency USD quotes above are 5–10x what a solo Indian developer's opportunity cost would be, but the *calendar* time for safety validation does not compress; plan the clinician-review loop and a labelled Hindi/English crisis test set from day one.

### Gaps
- No India-specific (INR) agency quotes for WhatsApp healthcare bots or counselling bots were retrieved.
- No published post-mortem with engineering headcount from Wysa/Limbic/Therabot teams was found.
