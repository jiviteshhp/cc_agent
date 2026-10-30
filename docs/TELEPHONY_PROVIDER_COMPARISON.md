# Telephony providers for an Indian voice-agent MVP

**Recommendation:** Trial Plivo India first if the business meets its onboarding requirements. Obtain one-number streaming quotes from KooKoo/Ozonetel and TeleCMI PIOPIY as alternatives. Keep the working Vobiz connection during evaluation. Tata Smartflo becomes interesting with sustained usage; FreJun's published minimums are poorly matched to a small pilot.

This comparison assumes one Indian number, mainly inbound domestic calls, one simultaneous call initially, and a separately operated Python voice agent. Prices were checked on 14 September 2026. Costs exclude speech recognition, LLM, speech synthesis, application hosting, taxes and migration work. Quote-only does not mean expensive: affordability remains unresolved. No provider was live-tested for this assessment.

**What the phone provider must supply**

The application needs caller audio delivered continuously to its own server, generated audio sent back during the same call, and a playback cancellation mechanism for interruptions. A bidirectional audio WebSocket is a direct integration path. A SIP trunk can also work, but this application would need an additional SIP/media bridge. Call-status webhooks, post-call recordings and a human-agent softphone alone do not meet these requirements.

The local implementation returns Vobiz Stream XML in `main.py:71`, validates incoming audio in `main.py:138`, and sends `playAudio` and `clearAudio` in `agent.py:111–120`. It uses mono 16-bit PCM at 8 kHz. These observations make protocol compatibility and reliable playback cancellation meaningful criteria alongside price.

**Provider comparison**

| Provider / product | Pricing evidence | Advantages for this MVP | Disadvantages / unresolved items | Assessment |
|---|---|---|---|---|
| Plivo Voice API, India | ₹200/number/month; ₹0.38/min inbound or outbound; streaming included.[^1] | Low fixed cost; documented custom audio transport; close match to existing protocol. | Business onboarding required; call quality needs a trial. | Best first trial. |
| Vobiz | Current India selector leads to sales; an official article states ₹0.65/min both ways.[^6][^7] | Existing integration; no migration effort; control of own agent. | Account rental, streaming and call charges need the actual bill/quote. | Baseline; renegotiate before moving. |
| KooKoo / Ozonetel developer platform | Legacy IVR page: ₹500/month plus ₹0.50/min inbound.[^9] | Low advertised entry point; current site describes bidirectional WebSockets and own-model use.[^8] | Old tariff may exclude current streaming or a dedicated dialable number; codec conversion likely needed. | Worth a developer-plan quote. |
| TeleCMI PIOPIY | Complete India streaming tariff not verified.[^13] | Documented audio input, playback and interrupt actions.[^10][^11][^12] | Streaming entitlement and price require confirmation; interruption semantics need testing. | Good technical backup to price. |
| Exotel AgentStream | Streaming priced separately; ordinary phone plans exclude it.[^14] | Two-way audio, handoff options and developer examples.[^15][^16] | Custom quote; different integration from Vobiz. | Suitable if a small-pilot quote is competitive. |
| Tata Smartflo Voice Streaming | ₹20,000 setup; ₹1,100/month per concurrency; domestic calling advertised as unlimited with an asterisk.[^17] | Predictable recurring cost; DID per concurrency; own WebSocket integration.[^18] | Upfront expense; fair-use limits, minimum order and commitment unresolved. | Consider after volume is proven. |
| FreJun Teler Voice Apps | Support tariff: ₹800/channel/month, minimum 10; inbound ₹0.10 + streaming ₹0.15/min.[^19] | Model-independent WebSocket transport and suitable raw-audio format.[^21] | ₹8,000 recurring floor on that tariff; another official page quotes ₹600/channel.[^20] | Poor small-pilot economics unless minimum waived. |
| MyOperator | API page advertises ₹5,000/month Sedan; FAQ describes annual upfront billing.[^23][^24] | Business number, IVR and human-team workflows. | Raw bidirectional audio access not established in reviewed API pages; annual commitment. | Ordinary phone plan is not a verified bot solution. |
| Knowlarity | Virtual-number plan ₹16,800/year; inbound contact center ₹1,999/agent/month.[^25] | Indian business-phone options and routing. | Tariffs do not establish streaming access; some separate softphone plans have annual terms. | Request streaming/SIP quote first. |
| Twilio | India mobile outbound $0.0496/min; landline $0.0699/min; Media Streams $0.0044/min extra.[^26] | Programmable call control and streaming. | Domestic local-number route does not match this need; India outbound uses international caller IDs.[^27] | Poor fit for cheap Indian domestic telephony. |
| Telnyx | Voice API $0.002/min plus SIP route; WebSocket streaming $0.0035/min.[^28] | Separate telephony and media services support custom agents. | Suitable Indian local-number inventory and domestic route price not established. | Revisit for international expansion. |
| Airtel Business SIP trunk | Quote required.[^29] | Direct business SIP offering and DID support. | Additional SIP bridge and setup; no verified small-pilot tariff. | Consider when carrier connectivity is a larger requirement. |
| Sarvam rented numbers | Number-specific wallet pricing; managed Vobiz connection.[^30] | Convenient rental in Sarvam's platform. | Standalone routing to this custom agent not documented. | Not yet a qualified telephony-only replacement. |

**Why Plivo leads the first trial**

Plivo's India Professional plan is pay-as-you-go and supports voice and SIP. Its Enterprise minimum belongs to a different plan; it should not be mistaken for a mandatory entry price for all Indian voice users.[^2] Low rental and a documented transport fit uncertain demand better than buying idle channels.

The current KYC guide accepts any one of GST registration, Certificate of Incorporation, or Udyam registration, with a signed and sealed first application. Older support material and the number-pricing page describe narrower requirements. Use the current guide, but confirm eligibility in the actual onboarding flow. Business email and an India-region organization are relevant prerequisites.[^3][^4]

Plivo supports `audio/x-l16;rate=8000`, bidirectional Stream XML, and `playAudio`/`clearAudio` messages.[^5] That is close to the project's Vobiz integration. Relatively low migration effort is an engineering inference, not proof that a URL change is sufficient. Start-event fields, track selection, authentication and disconnect/retry behavior still need checking.

**Where alternatives can win**

KooKoo is the developer offering to ask Ozonetel about. A full contact-center quote answers a different purchasing question. The current site describes PCMU/8 kHz bidirectional streaming, while the legacy IVR tariff has a 2015 footer and does not explicitly price modern streaming.[^8][^9] Treat ₹500 as a negotiation lead, not a validated all-in price. Confirm a dedicated number that callers can reach without entering an extension.

TeleCMI PIOPIY establishes both sides of audio exchange. However, its interrupt page describes stopping the WebSocket streaming connection while keeping the call connected.[^10][^11][^12] This may differ from clearing queued playback while maintaining caller audio. Request an example showing interruption followed by resumed listening and playback. Public PIOPIY pricing pages contain unresolved placeholders; zero-looking values are not reliable prices.[^13]

Exotel's Voicebot path supports an external agent over WebSocket, including media output and playback clearing.[^15][^16] Its potential advantage is a richer phone journey, such as bot-to-human handoff. Ask for one number and one AgentStream concurrency. The advertised ordinary business-phone packages do not establish that budget.[^14]

Smartflo is a utilization decision. Its Voice Streaming plan differs from the Lite human-phone plan. The setup fee makes a brief pilot expensive even if recurring rental is attractive.[^17] Dynamic WebSocket endpoints and authentication headers support keeping the custom backend.[^18] Confirm minimum concurrency, commitment, fair-use terms and permission for the intended automated-call workload before treating the plan as unlimited.

FreJun's call rate is only one bill component. Its support tariff gives ₹0.25/min for inbound plus streaming before optional recording, but the ten-channel commitment dominates a small account. A vendor blog quotes ₹600/channel while the dedicated support tariff says ₹800; the scenarios conservatively use the latter.[^19][^20] Its separate SIP product has a fifty-channel minimum at ₹600/channel before number rental and usage, making that offer even less suitable for entry.[^22]

MyOperator and Knowlarity may suit human calling, IVR and team administration. The reviewed pages do not confirm that advertised entry plans let an external server run the live conversation.[^23][^25] They could offer access privately. They rank lower because both technical eligibility and total cost must first be resolved.

Twilio and Telnyx cannot be ranked using US local-number prices for an Indian requirement. Twilio distinguishes international outbound reach from domestic service in its India guidelines.[^27] Telnyx's API and media prices are only part of the bill; a suitable local Indian number and route remain unverified.[^28] Airtel SIP is architecturally possible but needs a bridge, so a material cost or service advantage is needed to justify the work.[^29]

**Illustrative monthly costs**

These are telephony-only calculations before tax. They assume one PSTN call leg and full-call streaming, without transfers, paid provider recording, discounts, trial credits, or optional noise cancellation. Minutes mean billable minutes after provider rounding. Plivo's India page publishes a 30-second pulse, so elapsed conversation time can be lower than billed time.[^1]

| Monthly billable minutes | Plivo, one number | FreJun Teler, minimum ten channels | Smartflo, one concurrency, conditional |
|---:|---:|---:|---:|
| 500 | ₹390 | ₹8,125 | ₹1,100 recurring + ₹20,000 setup |
| 2,000 | ₹960 | ₹8,500 | ₹1,100 recurring + ₹20,000 setup |
| 10,000 | ₹4,000 | ₹10,500 | ₹1,100 recurring + ₹20,000 setup |

Formulas: Plivo = `200 + 0.38 × M`; FreJun = `800 × 10 + (0.10 + 0.15) × M`. Smartflo is a conditional illustration, not a confirmed one-channel quote. Setup is paid once, not every month. Rate sources are the respective cards.[^1][^17][^19]

Spreading Smartflo setup over twelve months gives approximately ₹2,767/month. Under these assumptions, that becomes cheaper than the Plivo illustration at about 6,755 billable minutes/month over a full year. With setup already sunk, the recurring-cost crossing is about 2,369 minutes/month. These calculated thresholds change with minimum channels, usage restrictions and project lifetime.

At 500 minutes, saving ₹0.20/min saves only ₹100/month. A ₹1,000 higher recurring commitment needs 5,000 minutes merely to offset that rate advantage. Rental and minimums should drive the initial shortlist before small differences in per-minute price.

Vobiz is deliberately absent from the numeric table. Its current India selector routes to sales, while explanatory articles publish a rate without establishing the full streamed-call account bill.[^6][^7] Calculate savings from the actual fixed charges and effective streamed-call rate. A wallet recharge is not an additional recurring expense if the same usage already counted consumes it.

**How to judge service in a pilot**

No comparable independent quality benchmark was established for these exact Indian routes, plans and custom-agent workloads. Provider claims about uptime, very low latency and fast onboarding are not measured results for this application. The ranking emphasizes pricing evidence, integration documentation and operational fit.

Run 20–30 synthetic calls across Airtel, Jio and Vi callers at different times. Keep the AI models and prompts constant so the transport is the principal variable. Record connection success, missing initial audio, one-way audio, audible gaps, disconnect behavior and caller-heard interruption delay. Include slow Hindi/Hinglish speech, silence and interruption during the greeting.

Match the call-detail record and wallet debit for a short and a long call. That exposes rounding, streaming fees and extra legs. Ask support one concrete integration question and note whether the answer resolves it. Do not substitute brand familiarity or a star rating for route-specific service evidence.

Mixed local recordings help debugging but do not prove exactly when the caller heard audio stop. Use caller-side observation for that check. A laptop or tunnel outage can also resemble a carrier issue; compare application logs and provider events before attributing failures.

**Quote request**

> Please quote one standard Indian inbound number, one simultaneous call, and bidirectional WebSocket audio to our own Python server. We provide our own STT, LLM, TTS and agent logic. Give total recurring costs at 500, 2,000 and 10,000 minutes/month, setup fees, minimum channels, wallet recharge, credit expiry, contract and cancellation terms. Separate call, streaming and optional recording charges. Confirm billing pulse, fair-use limits, number series, business KYC, audio format, playback-clear behavior and technical support. Does the trial include this exact transport?

For KooKoo, ask whether the legacy tariff includes modern streaming and a directly dialable number. For PIOPIY, request an interruption/resume example. For Exotel, explicitly request AgentStream. For FreJun, ask for a one-channel pilot and reconcile the channel-price discrepancy. For Sarvam, require confirmation of standalone routing first.

**Decision path**

Establish eligibility and trial Plivo. If the real bill matches the advertised tariff and call behavior passes, it is the strongest supported low-cost starting point here. If onboarding or performance blocks it, compare current KooKoo, PIOPIY and Exotel quotes. Retain Vobiz until an alternative passes the same scenarios. Revisit Smartflo when sustained volume can justify setup. Model replacement is a separate decision and is unnecessary for this evaluation.

**Sources and evidence notes**

All sources accessed 14 September 2026. Most pages do not provide a reliable update date. Published prices are not negotiated quotes. Legacy and conflicting material is identified above. Evidence does not establish independent service-quality rankings.

[^1]: Plivo, [India Voice API Pricing](https://www.plivo.com/voice/pricing/in/). Call, rental, streaming and pulse rates.
[^2]: Plivo, [Plans and Pricing](https://www.plivo.com/docs/faq/account/plans). India Professional versus Enterprise scope.
[^3]: Plivo, [India Number KYC](https://docs.plivo.com/docs/numbers/rent-india-numbers); compare narrower [number-pricing requirements](https://www.plivo.com/phone-numbers/pricing/in/).
[^4]: Plivo, [Account Management](https://www.plivo.com/docs/faq/account/account-management). Email, region and payment prerequisites.
[^5]: Plivo, [Audio Streaming Guide](https://www.plivo.com/docs/voice-agents/audio-streaming/concepts/audio-streaming-guide) and [Audio Stream reference](https://support.plivo.com/hc/en-us/sections/32252450281369-Audio-Stream).
[^6]: Vobiz, [Pricing](https://www.vobiz.ai/pricing/). Public [rate-table asset](https://www.vobiz.ai/assets/channelPricing-CtQjHCEP.js) marks India contact-sales-only; versioned asset can change.
[^7]: Vobiz, [What is a DID number?](https://www.vobiz.ai/resources/blogs/telephony-infrastructure/what-is-a-did-number/). ₹0.65/min in an explanatory article, not a full account quote.
[^8]: Ozonetel/KooKoo, [Developer platform](https://www.kookoo.in/). Current search-indexed text describes own models, PCMU/8 kHz two-way streaming and barge-in. Direct page extraction was limited.
[^9]: Ozonetel/KooKoo, [Legacy IVR pricing](https://kookoo.cxone.ozonetel.com/index.php/pricing). Page footer says 2015; modern streaming inclusion unverified.
[^10]: TeleCMI PIOPIY, [AI Streaming](https://doc.telecmi.com/piopiy/docs/ai-streaming/).
[^11]: TeleCMI PIOPIY, [Play Streaming](https://doc.telecmi.com/piopiy/docs/stream-action-play-stream/).
[^12]: TeleCMI PIOPIY, [Interrupt](https://doc.telecmi.com/piopiy/docs/streaming-action-interrupt/).
[^13]: PIOPIY, [Pricing](https://www.piopiy.com/pricing) and [Voice API pricing](https://www.piopiy.com/pricing/voice-call). Stale indexed pages with unresolved values; not used numerically.
[^14]: Exotel, [Business Phone System pricing](https://exotel.com/pricing/business-phone-system/). Explicit AgentStream exclusion.
[^15]: Exotel, [Developer documentation](https://developer.exotel.com/) and [AgentStream integration paths](https://cdnweb.exotel.com/build/agentstream-integration-paths-connect-voice-ai-flow-exoml/).
[^16]: Exotel, [AgentStream and Pipecat](https://exotel.com/blog/exotel-pipecat-agentstream-guide/), 7 August 2025. PCM and clear-event examples.
[^17]: Tata Tele Business Services, [Smartflo Call Center Solutions](https://www.tatatelebusiness.com/features/smartflo-call-center-solutions/). Voice Streaming plan.
[^18]: Tata Smartflo, [November 2025](https://docs.smartflo.tatatelebusiness.com/changelog/november-2025) and [February 2026](https://docs.smartflo.tatatelebusiness.com/changelog/february-2026) changelogs.
[^19]: FreJun, [Teler Pricing for India and UAE](https://knowledge.frejun.com/frejun-teler-pricing-for-india-and-uae-). ₹800/channel and ten-channel minimum.
[^20]: FreJun, [Knowlarity alternative for developers in India](https://frejun.com/teler-blog/knowlarity-alternative-india/). Conflicting ₹600/channel claim; competitor judgments not adopted.
[^21]: FreJun, [Teler](https://frejun.com/teler/). Model-independent transport. Latency claims not independently verified.
[^22]: FreJun, [SIP Trunking Pricing for India](https://knowledge.frejun.com/sip-trunking-pricing-for-india). Fifty-channel minimum; legal summaries on that page not relied on.
[^23]: MyOperator, [APIs and Webhooks](https://myoperator.com/integrations/api-webhooks).
[^24]: MyOperator, [Plans and payment terms](https://support.myoperator.com/portal/en/kb/articles/how-can-i-know-the-call-rates-and-plans-of-myoperator-24-8-2025).
[^25]: Knowlarity, [Voice pricing](https://www.knowlarity.com/pricing/voice) and [Small-business plans](https://www.knowlarity.com/small-business).
[^26]: Twilio, [India Voice Pricing](https://www.twilio.com/en-us/voice/pricing/in).
[^27]: Twilio, [India Voice Guidelines](https://www.twilio.com/en-us/guidelines/in/voice). Provider-specific reachability; not a general legal interpretation.
[^28]: Telnyx, [Voice API Pricing](https://telnyx.com/pricing/voice-api). Indian local-number quote not established.
[^29]: Airtel Business, [SIP trunk](https://www.airtel.in/b2b/sip-trunk).
[^30]: Sarvam, [Rent from Sarvam](https://docs.sarvam.ai/conversations/deploy/telephony/rent-from-sarvam).
