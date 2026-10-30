# Return incoming calls to cascaded with single-word Hindi fillers

Native phone calls were dropping after playback acknowledgement timeouts. The
production phone engine is now set back to cascaded; the number and Vobiz Answer
URL stay the same, while the website's browser engine choice remains independent.

On cascaded phone turns, the fixed opening is unchanged. Three single-word Hindi
acknowledgements (जी, अच्छा, ठीक) are prepared once with the existing Sarvam
voice, cached as 8 kHz PCM, and rotated only if reply audio has not arrived after
850 ms. Gemini and TTS keep working while the word plays. The phone-only prompt
asks Gemini to start directly with its question, and a streaming filter removes
an accidental leading acknowledgement to avoid two in a row. The answer follows
in order; the filler is audible in the mixed recording but excluded from clinical
history and extraction. If clips are unavailable, the normal reply plays without
a filler. The browser's editable prompt is unchanged.

Validation: 359 offline tests pass, including delayed/fast replies, split-token
acknowledgement removal, cache reuse, rotation, missing clips and interruption
cleanup. The candidate real-provider preflight prepared all three 8 kHz words.
After rollout, both services are healthy; all 30 runtime hashes match, the
Answer XML selects 8 kHz, private routes remain protected, and 49 prior call
rows and 119 saved artifacts were preserved. Rollback:
`/home/ubuntu/cc-agent-backups/phone-20260929T195554Z`. A disposable
real-provider probe sent one filler word at 852 ms, followed by the reply with
no repeated opening acknowledgement and a matched simulated playback check.
One earlier probe failed with Sarvam TTS HTTP 422 before answer audio; two later
probes passed. A real carrier call is still needed to assess audible quality,
STT and actual Vobiz playback acknowledgements.
